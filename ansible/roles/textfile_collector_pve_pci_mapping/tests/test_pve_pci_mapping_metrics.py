"""Guards for the vendored metrics script behind textfile_collector_pve_pci_mapping.

    cd ansible && .venv/bin/pytest roles/textfile_collector_pve_pci_mapping/tests/ -q

Hermetic: the script takes the two commands it runs (`pvesh`, `journalctl`) as arguments, so
each case injects a stub that prints canned output. Nothing else is touched.
"""

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "pve_pci_mapping_metrics.py"

CHECK_JSON = """[
 {"id": "intel_p1600x_1", "map": ["node=node-a,path=0000:46:00.0,id=8086:2525,subsystem-id=8086:380a,iommugroup=74"], "type": "pci",
  "checks": [{"severity": "error", "message": "Invalid configuration: 'id' does not match for 'intel_p1600x_1' (1a03:2000 != 8086:2525)\\n"}]},
 {"id": "samsung_980_pro_1", "map": ["node=node-a,path=0000:c7:00.0,id=144d:a80a,subsystem-id=144d:a801,iommugroup=21"], "type": "pci", "checks": []},
 {"id": "other_node_only", "map": ["node=node-b,path=0000:03:00.0,id=1000:00c4,subsystem-id=1000:31a0,iommugroup=9"], "type": "pci", "checks": []}
]"""

KMSG_OK = """[   13.9] ipmi_si IPI0001:00: IPMI message handler: Found new BMC (man_id: 0x00c1d6, prod_id: 0x1000, dev_id: 0x20)
[   13.9] ipmi_si IPI0001:00: IPMI kcs interface initialized
"""
# The 2026-08-28 boot, verbatim shape: the first exchange failed and there was no Found new BMC.
KMSG_BAD = """[   13.5] ipmi_si IPI0001:00: IPMI message handler: BMC returned incorrect response, expected netfn 7 cmd 8, got netfn 0 cmd 0
[   13.5] ipmi_si IPI0001:00: Unable to get the device id, falling back to hardcoded values
"""
# The 2026-08-31 13:47 boot: Found new BMC first, a milder complaint after. Counts as OK —
# the metric is about the first exchange.
KMSG_LATE_COMPLAINT = """[   13.8] ipmi_si IPI0001:00: IPMI message handler: Found new BMC (man_id: 0x00c1d6, prod_id: 0x1000, dev_id: 0x20)
[   13.9] ipmi_si IPI0001:00: IPMI message handler: BMC returned incorrect response, expected netfn 7 cmd 42, got netfn 0 cmd 0
"""


def _stub(tmp_path, name, body):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


def _run(tmp_path, pvesh_out, kmsg_out, node="node-a"):
    pvesh = _stub(tmp_path, "pvesh", "echo \"$@\" > %s/pvesh.args\ncat <<'JSON'\n%s\nJSON\n" % (tmp_path, pvesh_out))
    journalctl = _stub(tmp_path, "journalctl", "echo \"$@\" > %s/journalctl.args\ncat <<'TXT'\n%s\nTXT\n" % (tmp_path, kmsg_out))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--node", node, "--pvesh", pvesh, "--journalctl", journalctl],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc


def test_script_exists():
    assert SCRIPT.exists(), "script missing at %s" % SCRIPT


def test_one_gauge_per_mapping_on_this_node_and_none_for_other_nodes(tmp_path):
    proc = _run(tmp_path, CHECK_JSON, KMSG_OK)
    assert proc.returncode == 0, proc.stderr
    lines = [l for l in proc.stdout.splitlines() if l.startswith("pve_pci_mapping_check_ok{")]
    assert sorted(lines) == [
        'pve_pci_mapping_check_ok{mapping="intel_p1600x_1"} 0',
        'pve_pci_mapping_check_ok{mapping="samsung_980_pro_1"} 1',
    ]


def test_pvesh_is_asked_to_check_this_node(tmp_path):
    _run(tmp_path, CHECK_JSON, KMSG_OK, node="node-x")
    args = (tmp_path / "pvesh.args").read_text().split()
    assert args[:3] == ["get", "/cluster/mapping/pci"] + ["--check-node"][:1] or "--check-node" in args
    assert args[args.index("--check-node") + 1] == "node-x"
    assert "json" in args


def test_help_and_type_lines_present_once(tmp_path):
    proc = _run(tmp_path, CHECK_JSON, KMSG_OK)
    out = proc.stdout
    assert out.count("# TYPE pve_pci_mapping_check_ok gauge") == 1
    assert out.count("# TYPE pve_pci_mapping_bmc_kcs_ok gauge") == 1


def test_bmc_kcs_ok_is_1_when_first_exchange_found_the_bmc(tmp_path):
    proc = _run(tmp_path, CHECK_JSON, KMSG_OK)
    assert "pve_pci_mapping_bmc_kcs_ok 1" in proc.stdout.splitlines()


def test_bmc_kcs_ok_is_0_for_the_0828_shape(tmp_path):
    proc = _run(tmp_path, CHECK_JSON, KMSG_BAD)
    assert "pve_pci_mapping_bmc_kcs_ok 0" in proc.stdout.splitlines()


def test_a_complaint_after_found_new_bmc_still_counts_as_ok(tmp_path):
    proc = _run(tmp_path, CHECK_JSON, KMSG_LATE_COMPLAINT)
    assert "pve_pci_mapping_bmc_kcs_ok 1" in proc.stdout.splitlines()


def test_journalctl_reads_this_boot_kernel_messages_only(tmp_path):
    _run(tmp_path, CHECK_JSON, KMSG_OK)
    args = (tmp_path / "journalctl.args").read_text().split()
    assert "-k" in args
    assert "-b" in args and args[args.index("-b") + 1] == "0"


def test_no_ipmi_lines_at_all_reports_0(tmp_path):
    proc = _run(tmp_path, CHECK_JSON, "")
    assert "pve_pci_mapping_bmc_kcs_ok 0" in proc.stdout.splitlines()


def test_pvesh_failure_leaves_the_check_gauges_out_and_exits_nonzero(tmp_path):
    pvesh = _stub(tmp_path, "pvesh", "echo 'ipcc_send_rec[1] failed' >&2\nexit 2\n")
    journalctl = _stub(tmp_path, "journalctl", "cat <<'TXT'\n%s\nTXT\n" % KMSG_OK)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--node", "node-a", "--pvesh", pvesh, "--journalctl", journalctl],
        capture_output=True,
        text=True,
        check=False,
    )
    # The wrapper writes stdout to the .prom file only on success; a partial file with
    # stale-looking gauges would be worse than a missing one.
    assert proc.returncode != 0
    assert "pvesh" in proc.stderr
    assert "pve_pci_mapping_check_ok{" not in proc.stdout
