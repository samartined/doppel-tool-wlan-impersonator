# `doppel`

Terminal tool to **impersonate a WiFi client's identity** on the local network. It clones the
target's MAC address, injects a custom hostname via DHCP option 12, and holds the router's ARP table
with continuous gratuitous ARPs. Optionally it deauthenticates the real device first so there is no
MAC conflict.

> This is a **client-side identity takeover** tool (it runs as a normal managed-mode station via
> NetworkManager). It is **not** an evil-twin / rogue-AP: there is no `hostapd`, no DHCP/DNS server
> and no captive portal. Use only on networks you are authorised to test.

## Dependencies

- Python 3.10+ (standard library only)
- `nmcli` (NetworkManager) — always
- `arping` — always. Both **Thomas Habets `arping`** and **iputils-arping** are supported; the tool
  detects which one is installed and builds the correct command for it.
- `aireplay-ng` (aircrack-ng), `iw`, `ip` — only when using `-b/--router-bssid` (deauth)

## Quick start

```
sudo ./doppel <start|stop|status> [OPTIONS]
sudo ./doppel start ... --dry-run     # print the plan without changing anything
./doppel --version
```

## Subcommands

### `start` — Activate impersonation

Applies the spoofed identity, reconnects the WiFi connection, and holds the router's ARP table.
If anything fails mid-way, `doppel` **automatically rolls back** (reverts the connection and clears
state) instead of leaving a half-spoofed profile behind.

**Spoof only** (no deauth, omit `-b`):

```bash
sudo ./doppel start \
  -c "MyWiFi" \
  -i wlan0 \
  -m aa:bb:cc:dd:ee:f0 \
  -n "TARGET-PC" \
  -a 192.168.1.42
```

**Full flow** (deauth + spoof + arping):

```bash
sudo ./doppel start \
  -c "MyWiFi" -i wlan0 \
  -m aa:bb:cc:dd:ee:f0 -n "TARGET-PC" -a 192.168.1.42 \
  -b 00:11:22:33:44:55
```

| Short | Long | Description |
|---|---|---|
| `-c` | `--connection` | NetworkManager connection name (required) |
| `-i` | `--iface` | Wireless interface, e.g. `wlan0` (required) |
| `-m` | `--target-mac` | **Unicast** MAC address to impersonate (required) |
| `-n` | `--target-hostname` | Hostname to inject via DHCP option 12 (required, DNS-valid) |
| `-a` | `--target-ip` | **IPv4** address for gratuitous ARP (required) |
| `-b` | `--router-bssid` | AP BSSID — enables an initial deauth burst (optional) |
| | `--monitor-iface` | Separate monitor-capable adapter for the deauth (optional) |
| | `--deauth-count` | Deauth **bursts** (1–1000, default 10). Each burst ≈ 128 frames |
| | `--deauth-delay` | Seconds to wait after deauth (0–60, default 3) |
| | `--dry-run` | Show the planned actions and exit without executing |

### `stop` — Revert impersonation

Stops the `arping` process (verifying the PID is really `arping` before killing it), clears the cloned
MAC and DHCP hostname, and reconnects with the original identity.

```bash
sudo ./doppel stop -c "MyWiFi"
```

### `status` — Show current state

Displays the spoofing values configured on the connection and the tracked `arping` process state.
Run it with `sudo` if `start` was run with `sudo` (runtime state lives in root-owned `/run/doppel`).

```bash
sudo ./doppel status -c "MyWiFi"
```

## Deauth: monitor mode

`aireplay-ng` needs the adapter in **monitor mode** on the AP's channel. `doppel` handles this for you:

- **Single card** (default): the given `--iface` is briefly switched to monitor mode (released from
  NetworkManager, channel set from the AP's BSSID), the deauth is sent, and the card is restored to
  managed mode before connecting. There is a short window where the card is not associated.
- **Two cards** (`--monitor-iface`): the deauth runs on the dedicated monitor adapter while `--iface`
  stays managed. Preferred when you have a second adapter.

If injection cannot be verified (adapter without monitor/injection support, wrong channel, etc.), the
deauth **fails loudly and rolls back** — it no longer silently pretends to have kicked the target.

## When to use each flag

**`-b` / `--router-bssid`** depends on whether the target is connected *right now*:

- **Target IS connected**: use `-b`. It deauthenticates the target before you take its identity,
  avoiding a MAC conflict.
- **Target is NOT connected** (off / out of range): you don't need `-b`.

**`--deauth-count`** / **`--deauth-delay`** only matter with `-b`. Note `--deauth-count` counts
*bursts* (each burst sends 64 frames to the client and 64 to the AP), not individual frames.

## Notes on `--target-ip`

The gratuitous ARP announces `--target-ip → your (cloned) MAC` to poison the router's ARP cache. Your
station still gets its own address from DHCP; if that address differs from `--target-ip`, `doppel`
warns you (the announce is only fully effective when DHCP hands you the target's lease).

## Global installation

### Option 1 — Symlink in `/usr/local/bin` (recommended)

```bash
sudo ln -s "$(pwd)/doppel" /usr/local/bin/doppel
```

The symlink points to the real script, so edits are reflected immediately.

### Option 2 — Add the folder to PATH

Add to `~/.zshrc` (or `~/.bashrc`):

```bash
export PATH="/path/to/doppel-tool-wlan-impersonator:$PATH"
```

Runtime state is stored in `/run/doppel/` (tmpfs, cleared on reboot), **not** in the tool directory,
so a read-only install works fine and no target identifiers ever land next to the source.

## How it works

1. **Deauth** (optional): switches an adapter to monitor mode on the AP channel and sends deauth
   bursts to the target, then restores managed mode.
2. **Spoofing**: sets `wifi.cloned-mac-address` and `ipv4.dhcp-hostname` on the NM connection.
3. **Reconnection**: brings the connection down/up so NM applies the fake MAC and negotiates DHCP with
   the injected hostname.
4. **Gratuitous ARP**: launches `arping -U` in the background (flavor-aware) to keep the router's ARP
   table pointing at this machine. Startup is verified — a dead arping is reported, not hidden.
5. **State**: saves the PID and metadata to `/run/doppel/state.json` (0600) so `stop`/`status` work.

## Development

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q            # unit tests for the pure logic
ruff check doppel tests/        # lint
python3 -m py_compile doppel    # syntax check
```

## Warnings

- If the target device is connected simultaneously, a MAC conflict occurs. Use `-b` to disconnect it.
- The deauth is a one-shot burst; a resistant target can re-associate. Raise `--deauth-count` or use a
  dedicated monitor adapter for sustained pressure.
- Always run `stop` to revert the identity when finished.
