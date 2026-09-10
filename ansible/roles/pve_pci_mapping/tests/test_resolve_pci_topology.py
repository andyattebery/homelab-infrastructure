"""Guards for the vendored PCI topology resolver.

    cd ansible && .venv/bin/pytest roles/pve_pci_mapping/tests/ -q

Hermetic: the resolver reads a sysfs tree given by --sysfs-root, so every case runs against a
fake tree built in a tempdir. Two trees are used, both recorded from a real node's kernel log
rather than invented:

- "lan_off": the 2026-08-31 enumeration (Onboard LAN hidden). Optanes at 46/47, groups 74/75.
- "lan_on":  the 2026-08-28 enumeration. Root port 40:01.3 present with the X550 at bus 42,
  everything below bus 40 shifted by two, IOMMU groups by three. Optanes at 48/49, groups 77/78,
  ASPEED VGA sitting at 46:00.0 where intel_p1600x_1 used to be.

The point of the resolver is that the same topology string resolves to the right device in both.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_sysfs import LAN_OFF, LAN_ON, MAPPINGS, EXPECTED_LAN_OFF, EXPECTED_LAN_ON, build_tree  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "resolve_pci_topology.py"


def _load():
    assert SCRIPT.exists(), "script missing at %s" % SCRIPT
    spec = importlib.util.spec_from_file_location("_resolve_pci_topology_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture
def lan_off(tmp_path):
    root = tmp_path / "lan_off"
    build_tree(root, LAN_OFF)
    return root


@pytest.fixture
def lan_on(tmp_path):
    root = tmp_path / "lan_on"
    build_tree(root, LAN_ON)
    return root


def _by_topology(results):
    return {r["topology"]: r for r in results}


def test_lan_off_tree_resolves_all_eleven_mappings(lan_off):
    m = _load()
    got = _by_topology(m.resolve(str(lan_off), list(MAPPINGS.values())))
    assert len(got) == 11
    for name, topo in MAPPINGS.items():
        path, pci_id, subsystem_id, group = EXPECTED_LAN_OFF[name]
        r = got[topo]
        assert "error" not in r, (name, r)
        assert (r["path"], r["id"], r["subsystem_id"], r["iommugroup"]) == (path, pci_id, subsystem_id, group), name


def test_lan_on_tree_resolves_the_same_strings_to_the_shifted_devices(lan_on):
    m = _load()
    got = _by_topology(m.resolve(str(lan_on), list(MAPPINGS.values())))
    assert len(got) == 11
    for name, topo in MAPPINGS.items():
        path, pci_id, subsystem_id, group = EXPECTED_LAN_ON[name]
        r = got[topo]
        assert "error" not in r, (name, r)
        assert (r["path"], r["id"], r["subsystem_id"], r["iommugroup"]) == (path, pci_id, subsystem_id, group), name


def test_optane_topology_never_lands_on_the_aspeed_vga(lan_on):
    # 46:00.0 is the ASPEED BMC VGA in the LAN-on layout — the device the stale mapping was
    # aimed at on 2026-08-28. The topology string must not resolve there.
    m = _load()
    (r,) = m.resolve(str(lan_on), ["0000:40/03.3/00.0"])
    assert r["path"] == "0000:48:00.0"
    assert r["id"] == "8086:2525"
    assert r["id"] != "1a03:2000"


def test_driver_is_reported_and_null_when_unbound(lan_off):
    m = _load()
    got = _by_topology(m.resolve(str(lan_off), ["0000:40/03.3/00.0", "0000:40/01.1/00.0", "0000:40/01.5/00.0/00.0"]))
    assert got["0000:40/03.3/00.0"]["driver"] == "vfio-pci"
    assert got["0000:40/01.1/00.0"]["driver"] == "nvme"
    assert got["0000:40/01.5/00.0/00.0"]["driver"] is None


def test_subsystem_id_is_null_when_the_device_has_none(tmp_path):
    root = tmp_path / "nosub"
    build_tree(root, [("0000:00/0000:00:01.1/0000:01:00.0", "10de:24b0", None, 97, None)])
    m = _load()
    (r,) = m.resolve(str(root), ["0000:00/01.1/00.0"])
    assert r["id"] == "10de:24b0"
    assert r["subsystem_id"] is None


def test_missing_hop_is_an_error_naming_the_hop(lan_off):
    m = _load()
    (r,) = m.resolve(str(lan_off), ["0000:40/01.3/00.0"])
    assert "error" in r
    assert "01.3" in r["error"]
    assert "path" not in r


def test_missing_root_bus_is_an_error(lan_off):
    m = _load()
    (r,) = m.resolve(str(lan_off), ["0000:e0/01.1/00.0"])
    assert "error" in r
    assert "0000:e0" in r["error"]


def test_ambiguous_hop_is_an_error_not_a_guess(tmp_path):
    # Two children under one bridge with the same dev.fn but different bus numbers cannot occur
    # on real hardware; if the tree is ever that malformed the resolver must not pick one.
    root = tmp_path / "ambig"
    build_tree(
        root,
        [
            ("0000:40/0000:40:03.3/0000:46:00.0", "8086:2525", "8086:380a", 74, None),
            ("0000:40/0000:40:03.3/0000:47:00.0", "8086:2525", "8086:380a", 75, None),
        ],
    )
    m = _load()
    (r,) = m.resolve(str(root), ["0000:40/03.3/00.0"])
    assert "error" in r
    assert "2" in r["error"]  # the count of candidates


def test_malformed_topology_string_is_an_error(lan_off):
    m = _load()
    (r,) = m.resolve(str(lan_off), ["40/03.3/00.0"])
    assert "error" in r


def test_cli_prints_json_and_exits_zero_when_all_resolve(lan_off):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--sysfs-root", str(lan_off), "0000:40/03.3/00.0", "0000:80/03.1/00.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert [r["path"] for r in out] == ["0000:46:00.0", "0000:84:00.0"]


def test_cli_exits_nonzero_when_any_topology_fails_but_still_prints_all(lan_off):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--sysfs-root", str(lan_off), "0000:40/03.3/00.0", "0000:40/01.3/00.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    out = json.loads(proc.stdout)
    assert out[0]["path"] == "0000:46:00.0"
    assert "error" in out[1]
