#!/usr/bin/env python3
"""Resolve PCI topology strings to the device currently at that position in the PCIe tree.

A topology string is "<domain>:<rootbus>/<dev.fn>/<dev.fn>/...": the root bus, then the
device.function of each hop from the root port down to the endpoint, with the bus numbers
left out. Bus numbers are what shifts when a device appears or disappears upstream (the
onboard NIC that a BIOS setting hides on some boots); root-port and downstream-port device.function numbers are
fixed by the silicon and the card, so this string names a physical position.

Usage:
    resolve_pci_topology.py [--sysfs-root /sys] TOPOLOGY [TOPOLOGY ...]

Prints a JSON array with one object per topology, in argument order:
    {"topology": ..., "path": "0000:46:00.0", "id": "8086:2525",
     "subsystem_id": "8086:380a" | null, "iommugroup": 74, "driver": "vfio-pci" | null}
or, when a topology cannot be resolved,
    {"topology": ..., "error": "..."}
Exit status is 0 only when every topology resolved. Stdlib only.
"""

import argparse
import json
import os
import re
import sys

TOPOLOGY_RE = re.compile(r"^([0-9a-f]{4}):([0-9a-f]{2})((?:/[0-9a-f]{2}\.[0-7])+)$")
ADDRESS_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:([0-9a-f]{2}\.[0-7])$")


def _read_hex(path):
    """Read a sysfs hex attribute ("0x8086\\n") and return it without the 0x prefix."""
    with open(path) as f:
        return f.read().strip().lower().removeprefix("0x")


def _link_basename(path):
    if not os.path.islink(path):
        return None
    return os.path.basename(os.readlink(path).rstrip("/"))


def resolve_one(sysfs_root, topology):
    m = TOPOLOGY_RE.match(topology)
    if not m:
        return {"topology": topology, "error": "malformed topology %r; expected <dddd>:<bb>/<dd.f>/..." % topology}
    domain, root_bus, hops = m.group(1), m.group(2), m.group(3).strip("/").split("/")
    root = "%s:%s" % (domain, root_bus)
    current = os.path.join(sysfs_root, "devices", "pci" + root)
    if not os.path.isdir(current):
        return {"topology": topology, "error": "root bus %s not present under %s" % (root, sysfs_root)}
    for hop in hops:
        candidates = []
        for name in os.listdir(current):
            am = ADDRESS_RE.match(name)
            if am and am.group(1) == hop and os.path.isdir(os.path.join(current, name)):
                candidates.append(name)
        if len(candidates) != 1:
            return {
                "topology": topology,
                "error": "hop %s under %s matched %d devices %s, expected exactly 1"
                % (hop, os.path.basename(current), len(candidates), sorted(candidates)),
            }
        current = os.path.join(current, candidates[0])
    path = os.path.basename(current)
    result = {
        "topology": topology,
        "path": path,
        "id": "%s:%s" % (_read_hex(os.path.join(current, "vendor")), _read_hex(os.path.join(current, "device"))),
        "subsystem_id": None,
        "iommugroup": None,
        "driver": _link_basename(os.path.join(current, "driver")),
    }
    sv, sd = os.path.join(current, "subsystem_vendor"), os.path.join(current, "subsystem_device")
    if os.path.exists(sv) and os.path.exists(sd):
        result["subsystem_id"] = "%s:%s" % (_read_hex(sv), _read_hex(sd))
    group = _link_basename(os.path.join(current, "iommu_group"))
    if group is not None:
        result["iommugroup"] = int(group)
    return result


def resolve(sysfs_root, topologies):
    return [resolve_one(sysfs_root, t) for t in topologies]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sysfs-root", default="/sys")
    parser.add_argument("topology", nargs="+")
    args = parser.parse_args(argv)
    results = resolve(args.sysfs_root, args.topology)
    json.dump(results, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0 if all("error" not in r for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
