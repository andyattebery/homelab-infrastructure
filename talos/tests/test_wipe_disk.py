"""wipe-disk.sh: it wipes exactly the one NVMe drive the serial names, on the named node, or nothing.

The disks are fixtures/talos-disks.json, `talosctl get disks -o json` captured from pi-cluster-01
(README.md, "Tests"): the SD card and the PM991 as Talos really reports them. The duplicate and
SD-card cases are built from that capture. talosctl's stub serves it and swallows `wipe disk`.
"""

import copy
import json

import pytest

from support import DISKS, calls, captured_disks, make_env, only, run

needs_disks = pytest.mark.skipif(
    not DISKS.exists(), reason="fixtures/talos-disks.json is captured from pi-cluster-01 (README.md, Tests)"
)


def wipe(tmp_path, talos, resources, *args):
    stream = tmp_path / "disks.json"
    stream.write_text("".join(json.dumps(r, indent=4) + "\n" for r in resources))
    env = make_env(tmp_path, STUB_TALOS_DISKS=stream)
    return env, run(talos, "wipe-disk.sh", *args, env=env)


def wipes(env):
    return [c for c in calls(env, "talosctl") if "wipe" in c]


# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["pi-cluster-01"],
        ["pi-cluster-07", "S1"],
        ["pi-cluster-1", "S1"],
        ["nas-01", "S1"],
        ["pi-cluster-01", "S1", "--force"],
        ["pi-cluster-01", "S1", "--yes", "extra"],
        ["pi-cluster-01", "S1", "--insecure", "--yes", "extra"],
    ],
)
def test_refuses_bad_arguments_before_asking_the_node(tmp_path, talos, args):
    env = make_env(tmp_path)
    result = run(talos, "wipe-disk.sh", *args, env=env)
    assert result.returncode == 1
    assert calls(env) == []


@needs_disks
def test_without_yes_it_only_shows_the_match(tmp_path, talos):
    resources = captured_disks()
    env, result = wipe(tmp_path, talos, resources, "pi-cluster-01", only(resources, "nvme")["spec"]["serial"])
    assert result.returncode == 1
    assert only(resources, "nvme")["metadata"]["id"] in result.stdout
    assert len(calls(env, "talosctl")) == 1
    assert wipes(env) == []


@needs_disks
def test_refuses_an_unknown_serial(tmp_path, talos):
    env, result = wipe(tmp_path, talos, captured_disks(), "pi-cluster-01", "NO-SUCH-SERIAL", "--yes")
    assert result.returncode == 1
    assert wipes(env) == []


@needs_disks
def test_refuses_a_serial_two_disks_share(tmp_path, talos):
    resources = captured_disks()
    twin = copy.deepcopy(only(resources, "nvme"))
    twin["metadata"]["id"] = "nvme1n1"
    twin["spec"]["dev_path"] = "/dev/nvme1n1"
    env, result = wipe(tmp_path, talos, resources + [twin], "pi-cluster-01", twin["spec"]["serial"], "--yes")
    assert result.returncode == 1
    assert wipes(env) == []


@needs_disks
def test_never_wipes_the_sd_card(tmp_path, talos):
    resources = captured_disks()
    sd = only(resources, "mmc")
    # Some cards report no serial; give it one so the serial really selects the SD card.
    sd["spec"]["serial"] = sd["spec"].get("serial") or "0xdeadbeef"
    env, result = wipe(tmp_path, talos, resources, "pi-cluster-01", sd["spec"]["serial"], "--yes")
    assert result.returncode == 1
    assert wipes(env) == []


@needs_disks
@pytest.mark.parametrize("host, node", [("pi-cluster-01", "192.168.1.181"), ("pi-cluster-06", "192.168.1.186")])
def test_wipes_the_matched_drive_on_that_node(tmp_path, talos, host, node):
    resources = captured_disks()
    nvme = only(resources, "nvme")
    env, result = wipe(tmp_path, talos, resources, host, nvme["spec"]["serial"], "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert wipes(env) == [
        ["talosctl", "--talosconfig", "generated/talosconfig", "-e", node, "-n", node,
         "wipe", "disk", "--insecure=false", nvme["metadata"]["id"]],
    ]


@needs_disks
@pytest.mark.parametrize("flags", [["--insecure", "--yes"], ["--yes", "--insecure"]])
def test_insecure_reaches_a_node_in_maintenance_mode(tmp_path, talos, flags):
    resources = captured_disks()
    nvme = only(resources, "nvme")
    env, result = wipe(tmp_path, talos, resources, "pi-cluster-04", nvme["spec"]["serial"], *flags)
    assert result.returncode == 0, result.stdout + result.stderr
    node = "192.168.1.184"
    assert calls(env, "talosctl") == [
        ["talosctl", "--talosconfig", "generated/talosconfig", "-e", node, "-n", node,
         "get", "disks", "--insecure=true", "-o", "json"],
        ["talosctl", "--talosconfig", "generated/talosconfig", "-e", node, "-n", node,
         "wipe", "disk", "--insecure=true", nvme["metadata"]["id"]],
    ]
