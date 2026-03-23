# `doppel`

Terminal tool to impersonate a WiFi client's identity on the local network. Clones the MAC address, injects a custom hostname via DHCP option 12, and holds the router's ARP table with continuous gratuitous ARPs.

## Dependencies

- Python 3.10+
- `nmcli` (NetworkManager)
- `arping` (iputils-arping)
- `aireplay-ng` (aircrack-ng) — only needed when using `-b/--router-bssid` for deauth

## Quick start

```
sudo ./doppel <start|stop|status> [OPTIONS]
```

## Subcommands

### `start` — Activate impersonation

Applies the spoofed identity, reconnects the WiFi connection, and holds the router's ARP table.

**Full flow** (deauth + spoof + arping):

```bash
sudo ./doppel start \
  -c "MyWiFi" \
  -i wlo1 \
  -m aa:bb:cc:dd:ee:ff \
  -n "TARGET-PC" \
  -a 192.168.1.42 \
  -b 00:11:22:33:44:55
```

**Spoof only** (no deauth, omit `-b`):

```bash
sudo ./doppel start \
  -c "MyWiFi" \
  -i wlo1 \
  -m aa:bb:cc:dd:ee:ff \
  -n "TARGET-PC" \
  -a 192.168.1.42
```

| Short | Long | Description |
|---|---|---|
| `-c` | `--connection` | NetworkManager connection name (required) |
| `-i` | `--iface` | Wireless interface, e.g. `wlo1` (required) |
| `-m` | `--target-mac` | MAC address to impersonate (required) |
| `-n` | `--target-hostname` | Hostname to inject via DHCP option 12 (required) |
| `-a` | `--target-ip` | IP address for gratuitous ARP (required) |
| `-b` | `--router-bssid` | AP BSSID — enables initial deauth burst (optional) |
| | `--deauth-count` | Number of deauth frames (default: 10) |
| | `--deauth-delay` | Seconds to wait after deauth (default: 3) |

### `stop` — Revert impersonation

Stops the `arping` process, clears the cloned MAC and DHCP hostname, and reconnects with the original identity.

```bash
sudo ./doppel stop -c "MyWiFi"
```

### `status` — Show current state

Displays the spoofing values configured on the connection and the `arping` process state.

```bash
./doppel status -c "MyWiFi"
```

## When to use each flag

### Required flags (always needed)

| Flag | Why |
|---|---|
| `-c` | The script needs to know which NetworkManager WiFi connection to manipulate. This is the name shown by `nmcli connection show`, e.g. `"MyWiFi"`. |
| `-i` | The physical wireless interface you are connected through (`wlo1`, `wlan0`...). Needed to launch `arping` on that interface. |
| `-m` | The MAC address of the device you want to impersonate. Without this there is no spoofing. |
| `-n` | The hostname the router will show in its client table. This is what gets injected into DHCP option 12. |
| `-a` | The target device's IP address. Used for gratuitous ARPs that keep the router's ARP table pointing at you. |

### Optional flags (depends on the scenario)

**`-b` / `--router-bssid`** — Whether to use it depends on whether the target device is connected at the same time:

- **IF the target IS connected to the network**: you need `-b`. The script will send deauth frames to disconnect it before you connect with its identity. Without this, both devices would compete for the same MAC and connectivity would be unstable for both.
- **IF the target is NOT connected** (powered off, out of range, etc.): you don't need `-b`. There is no MAC conflict, so you can connect directly with the spoofed identity without a prior deauth.

**`--deauth-count`** and **`--deauth-delay`** — Only relevant when using `-b`:

- `--deauth-count` (default: 10): how many deauth frames to send. If the target doesn't disconnect with 10, increase the number. If you want to be more discreet, lower it.
- `--deauth-delay` (default: 3): seconds to wait between the deauth and the connection. Allow more time if the network is slow to release the target's MAC from its table.

### Examples by scenario

**Target disconnected (simple case):**

```bash
sudo doppel start -c "MyWiFi" -i wlo1 -m aa:bb:cc:dd:ee:ff -n "TARGET-PC" -a 192.168.1.42
```

**Target connected (need to kick it off first):**

```bash
sudo doppel start -c "MyWiFi" -i wlo1 -m aa:bb:cc:dd:ee:ff -n "TARGET-PC" -a 192.168.1.42 -b 00:11:22:33:44:55
```

**Target connected and resistant (more aggressive):**

```bash
sudo doppel start -c "MyWiFi" -i wlo1 -m aa:bb:cc:dd:ee:ff -n "TARGET-PC" -a 192.168.1.42 -b 00:11:22:33:44:55 --deauth-count 50 --deauth-delay 5
```

## Global installation

To use `doppel` from any directory without navigating to the script's folder:

### Option 1 — Symlink in `/usr/local/bin` (recommended)

```bash
sudo ln -s /path/to/wlan-impersonator/doppel /usr/local/bin/doppel
```

After this, from any terminal:

```bash
sudo doppel start -c "MyWiFi" ...
```

The symlink points to the real script, so edits are reflected immediately.

### Option 2 — Add the folder to PATH in `.zshrc`

Add this line to `~/.zshrc`:

```bash
export PATH="$HOME/Sync/wlan-impersonator:$PATH"
```

After reloading the shell (`source ~/.zshrc` or opening a new terminal), `doppel` will be available globally. The difference from option 1 is that this only applies to your user and to zsh, while the symlink in `/usr/local/bin` works for any user and any shell.

## How it works

1. **Deauth** (optional): sends deauthentication frames to the target device to disconnect it from the AP.
2. **Spoofing**: sets `wifi.cloned-mac-address` and `ipv4.dhcp-hostname` on the NetworkManager connection.
3. **Reconnection**: brings the connection down and back up so NetworkManager applies the fake MAC and negotiates DHCP with the injected hostname.
4. **Gratuitous ARP**: launches `arping -U` in the background to permanently keep the router's ARP table pointing at this machine.
5. **State**: saves the PID and metadata to `.state` so that `stop` and `status` work reliably.

## Warnings

- If the target device is connected simultaneously, a MAC conflict occurs. Use `-b` to disconnect it first.
- The continuous `arping -U` overwrites the router's ARP entry, but if the target reconnects there may be instability for both.
- Always run `stop` before closing the session to revert the identity.
