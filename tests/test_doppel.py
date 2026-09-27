"""Unit tests for the pure/testable logic of `doppel`.

The tool is a single executable script without a .py extension, so we load it as
a module by path. No privileged or network calls are exercised here.
"""

from __future__ import annotations

import importlib.util
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
# `doppel` has no .py extension, so give importlib an explicit source loader.
_loader = SourceFileLoader("doppel", str(_ROOT / "doppel"))
_spec = importlib.util.spec_from_loader("doppel", _loader)
doppel = importlib.util.module_from_spec(_spec)
_loader.exec_module(doppel)


# ── Command builders ──────────────────────────────────────────────────────────

def test_build_deauth_cmd():
    assert doppel.build_deauth_cmd("wlan0mon", "AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66", 10) == [
        "aireplay-ng", "--deauth", "10",
        "-a", "AA:BB:CC:DD:EE:FF", "-c", "11:22:33:44:55:66", "wlan0mon",
    ]


def test_build_arping_cmd_habets_drops_redundant_source():
    # Habets: interface is -i and the cloned MAC is already on the iface → no -s.
    assert doppel.build_arping_cmd("habets", "wlo1", "192.168.1.50") == [
        "arping", "-U", "-i", "wlo1", "192.168.1.50",
    ]


def test_build_arping_cmd_iputils_uses_capital_I():
    assert doppel.build_arping_cmd("iputils", "wlo1", "192.168.1.50") == [
        "arping", "-U", "-I", "wlo1", "192.168.1.50",
    ]


def test_build_arping_cmd_iputils_source_is_ip():
    # On iputils -s is a source IP (never a MAC).
    assert doppel.build_arping_cmd("iputils", "wlo1", "192.168.1.50", "192.168.1.50") == [
        "arping", "-U", "-I", "wlo1", "-s", "192.168.1.50", "192.168.1.50",
    ]


# ── MAC validation ────────────────────────────────────────────────────────────

def test_validate_mac_accepts_unicast():
    # First octet 0x02 → I/G bit clear (unicast), locally administered.
    doppel.validate_mac("02:11:22:33:44:55")  # no exception


@pytest.mark.parametrize("mac", [
    "ff:ff:ff:ff:ff:ff",          # broadcast
    "01:00:5e:00:00:01",          # multicast (LSB of first octet set)
    "00:00:00:00:00:00",          # all-zero
    "zz:zz:zz:zz:zz:zz",          # bad format
    "11:22:33:44:55",             # too short
])
def test_validate_mac_rejects_bad(mac):
    with pytest.raises(SystemExit):
        doppel.validate_mac(mac)


def test_validate_mac_allow_multicast_flag():
    doppel.validate_mac("01:00:5e:00:00:01", allow_multicast=True)  # no exception


# ── IPv4 validation ───────────────────────────────────────────────────────────

def test_validate_ipv4_accepts():
    doppel.validate_ipv4("10.0.0.1")


@pytest.mark.parametrize("ip", ["::1", "fe80::1", "999.1.1.1", "not-an-ip", ""])
def test_validate_ipv4_rejects(ip):
    with pytest.raises(SystemExit):
        doppel.validate_ipv4(ip)


# ── Hostname / connection / iface validation ──────────────────────────────────

@pytest.mark.parametrize("name", ["laptop", "host-01", "a.b.c", "PC1"])
def test_validate_hostname_ok(name):
    doppel.validate_hostname(name)


@pytest.mark.parametrize("name", ["-bad", "has space", "a/b", "x@y", "", "a" * 300])
def test_validate_hostname_bad(name):
    with pytest.raises(SystemExit):
        doppel.validate_hostname(name)


@pytest.mark.parametrize("name", ["-c", "", "\tx"])
def test_validate_connection_rejects_dash_and_control(name):
    with pytest.raises(SystemExit):
        doppel.validate_connection(name)


def test_validate_connection_allows_spaces():
    doppel.validate_connection("Wired connection 1")  # no exception


@pytest.mark.parametrize("iface,ok", [
    ("wlo1", True), ("wlan0", True), ("eth0.5", True),
    ("-wlan0", False), ("wlan space", False), ("verylonginterfacename", False),
])
def test_iface_regex(iface, ok):
    assert bool(doppel.IFACE_RE.match(iface)) is ok


# ── arping flavor / injection detection ───────────────────────────────────────

def test_arping_flavor_habets(monkeypatch):
    class _R:
        stdout = "ARPing 2.29, by Thomas Habets <thomas@habets.se>"
        stderr = ""
    monkeypatch.setattr(doppel.subprocess, "run", lambda *a, **k: _R())
    assert doppel._arping_flavor() == "habets"


def test_arping_flavor_iputils(monkeypatch):
    class _R:
        stdout = "Usage: arping [-fqbDUAV] [-c count] ... destination"
        stderr = ""
    monkeypatch.setattr(doppel.subprocess, "run", lambda *a, **k: _R())
    assert doppel._arping_flavor() == "iputils"


@pytest.mark.parametrize("out,failed", [
    ("wlan0 is on channel 6, but the AP uses channel 11", False),
    ("fixed channel wlan0: -1", True),
    ("Interface wlan0 doesn't support injection", True),
    ("wlan0 is not in monitor mode", True),
    ("Sending 64 directed DeAuth. STMAC: [..]", False),
])
def test_injection_failed(out, failed):
    assert doppel._injection_failed(out) is failed


# ── PID helpers ───────────────────────────────────────────────────────────────

def test_pid_alive_self_and_missing():
    assert doppel._pid_alive(os.getpid()) is True
    assert doppel._pid_alive(2 ** 31 - 1) is False  # implausible PID


def test_pid_is_arping_false_for_self():
    # This test process is python, not arping.
    assert doppel._pid_is_arping(os.getpid()) is False
    assert doppel._pid_is_arping(2 ** 31 - 1) is False


# ── State round-trip ──────────────────────────────────────────────────────────

def test_state_roundtrip_and_perms(tmp_path, monkeypatch):
    state_dir = tmp_path / "run-doppel"
    monkeypatch.setattr(doppel, "STATE_DIR", state_dir)
    monkeypatch.setattr(doppel, "STATE_FILE", state_dir / "state.json")

    data = {"connection": "c", "iface": "wlo1", "arping_pid": 1234}
    doppel.save_state(data)

    assert doppel.load_state() == data
    mode = (state_dir / "state.json").stat().st_mode & 0o777
    assert mode == 0o600

    doppel.clear_state()
    assert doppel.load_state() is None


def test_load_state_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(doppel, "STATE_FILE", tmp_path / "nope.json")
    assert doppel.load_state() is None


# ── Parser smoke ──────────────────────────────────────────────────────────────

def test_parser_start_requires_core_args():
    parser = doppel.build_parser()
    args = parser.parse_args([
        "start", "-c", "conn", "-i", "wlo1",
        "-m", "11:22:33:44:55:66", "-n", "host", "-a", "10.0.0.5",
    ])
    assert args.command == "start"
    assert args.deauth_count == 10
    assert args.monitor_iface is None
    assert args.dry_run is False
