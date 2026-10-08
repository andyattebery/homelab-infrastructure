"""reset-node.sh: it resets the named node, wiping STATE and exactly the one NVMe drive the serial
names, or nothing.

The disks are fixtures/talos-disks.json, as in test_wipe_disk.py: the SD card and the PM991 as
Talos really reports them. talosctl's stub serves it and swallows `reset`.
"""

import copy
import json

import pytest

from support import DISKS, calls, captured_disks, make_env, only, run

needs_disks = pytest.mark.skipif(
    not DISKS.exists(), reason="fixtures/talos-disks.json is captured from pi-cluster-01 (README.md, Tests)"
)


def reset(tmp_path, talos, resources, *args):
    stream = tmp_path / "disks.json"
    stream.write_text("".join(json.dumps(r, indent=4) + "\n" for r in resources))
    env = make_env(tmp_path, STUB_TALOS_DISKS=stream)
    return env, run(talos, "reset-node.sh", *args, env=env)


def resets(env):
    return [c for c in calls(env, "talosctl") if "reset" in c]


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
    ],
)
def test_refuses_bad_arguments_before_asking_the_node(tmp_path, talos, args):
    env = make_env(tmp_path)
    result = run(talos, "reset-node.sh", *args, env=env)
    assert result.returncode == 1
    assert calls(env) == []


@needs_disks
def test_without_yes_it_only_shows_the_match(tmp_path, talos):
    resources = captured_disks()
    nvme = only(resources, "nvme")
    env, result = reset(tmp_path, talos, resources, "pi-cluster-01", nvme["spec"]["serial"])
    assert result.returncode == 1
    assert nvme["spec"]["dev_path"] in result.stdout
    assert len(calls(env, "talosctl")) == 1
    assert resets(env) == []


@needs_disks
def test_refuses_an_unknown_serial(tmp_path, talos):
    env, result = reset(tmp_path, talos, captured_disks(), "pi-cluster-01", "NO-SUCH-SERIAL", "--yes")
    assert result.returncode == 1
    assert resets(env) == []


@needs_disks
def test_refuses_a_serial_two_disks_share(tmp_path, talos):
    resources = captured_disks()
    twin = copy.deepcopy(only(resources, "nvme"))
    twin["metadata"]["id"] = "nvme1n1"
    twin["spec"]["dev_path"] = "/dev/nvme1n1"
    env, result = reset(tmp_path, talos, resources + [twin], "pi-cluster-01", twin["spec"]["serial"], "--yes")
    assert result.returncode == 1
    assert resets(env) == []


@needs_disks
def test_never_chooses_the_sd_card(tmp_path, talos):
    resources = captured_disks()
    sd = only(resources, "mmc")
    # Some cards report no serial; give it one so the serial really selects the SD card.
    sd["spec"]["serial"] = sd["spec"].get("serial") or "0xdeadbeef"
    env, result = reset(tmp_path, talos, resources, "pi-cluster-01", sd["spec"]["serial"], "--yes")
    assert result.returncode == 1
    assert resets(env) == []


@needs_disks
@pytest.mark.parametrize("host, node", [("pi-cluster-01", "192.168.1.181"), ("pi-cluster-06", "192.168.1.186")])
def test_resets_that_node_wiping_state_and_the_matched_drive(tmp_path, talos, host, node):
    resources = captured_disks()
    nvme = only(resources, "nvme")
    env, result = reset(tmp_path, talos, resources, host, nvme["spec"]["serial"], "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert resets(env) == [
        ["talosctl", "--talosconfig", "generated/talosconfig", "-e", node, "-n", node,
         "reset", "--graceful=false", "--reboot", "--system-labels-to-wipe", "STATE",
         "--user-disks-to-wipe", nvme["spec"]["dev_path"]],
    ]
