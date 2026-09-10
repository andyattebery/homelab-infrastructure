#!/usr/bin/env python3
"""Prometheus textfile metrics for a Proxmox node's PCI resource mappings.

    pve_pci_mapping_metrics.py --node <node> [--pvesh /usr/bin/pvesh] [--journalctl journalctl]

Prints, in node_exporter textfile format:

    pve_pci_mapping_check_ok{mapping="<id>"} 0|1
        one per mapping that has a map entry for this node; 1 when
        `pvesh get /cluster/mapping/pci --check-node <node>` reports no check for it.
        0 is what a VM start would fail on ("'id' does not match", "'iommugroup' does not
        match", "pci device not found").
    pve_pci_mapping_bmc_kcs_ok 0|1
        1 when the kernel's first IPMI exchange this boot succeeded (`ipmi_si … Found new BMC`
        appears before any `BMC returned incorrect response`). On the node this was written for, the boots that
        POSTed against a BMC that was still initialising were the ones whose PCI enumeration
        changed; this is the host-side marker for that condition.

Exits non-zero (printing nothing for the check gauges) if pvesh fails, so the wrapper never
writes a .prom file that looks healthy while the source is unreachable. Stdlib only.
"""

import argparse
import json
import re
import subprocess
import sys

FOUND_RE = re.compile(r"ipmi_si .*Found new BMC")
BAD_RE = re.compile(r"ipmi_si .*BMC returned incorrect response")


def check_gauges(pvesh, node):
    proc = subprocess.run(
        [pvesh, "get", "/cluster/mapping/pci", "--check-node", node, "--output-format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("pvesh failed (rc=%d): %s" % (proc.returncode, proc.stderr.strip()))
    node_re = re.compile(r"(^|,)node=%s(,|$)" % re.escape(node))
    out = {}
    for entry in json.loads(proc.stdout):
        if not any(node_re.search(m) for m in entry.get("map", [])):
            continue
        out[entry["id"]] = 0 if entry.get("checks") else 1
    return out


def bmc_kcs_ok(journalctl):
    proc = subprocess.run([journalctl, "-b", "0", "-k", "--no-pager", "-o", "cat"], capture_output=True, text=True, check=False)
    for line in proc.stdout.splitlines():
        if FOUND_RE.search(line):
            return 1
        if BAD_RE.search(line):
            return 0
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--node", required=True)
    parser.add_argument("--pvesh", default="/usr/bin/pvesh")
    parser.add_argument("--journalctl", default="journalctl")
    args = parser.parse_args(argv)
    try:
        gauges = check_gauges(args.pvesh, args.node)
    except (RuntimeError, ValueError) as e:
        sys.stderr.write("pve_pci_mapping_metrics: %s\n" % e)
        return 1
    lines = [
        "# HELP pve_pci_mapping_check_ok 1 when pvesh --check-node reports no problem for the mapping on this node.",
        "# TYPE pve_pci_mapping_check_ok gauge",
    ]
    for mapping in sorted(gauges):
        lines.append('pve_pci_mapping_check_ok{mapping="%s"} %d' % (mapping, gauges[mapping]))
    lines += [
        "# HELP pve_pci_mapping_bmc_kcs_ok 1 when the kernel's first IPMI exchange this boot found the BMC.",
        "# TYPE pve_pci_mapping_bmc_kcs_ok gauge",
        "pve_pci_mapping_bmc_kcs_ok %d" % bmc_kcs_ok(args.journalctl),
    ]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
