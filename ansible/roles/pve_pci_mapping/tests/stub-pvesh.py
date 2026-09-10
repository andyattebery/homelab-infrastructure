#!/usr/bin/env python3
"""Stand-in for pvesh, scoped to /cluster/mapping/pci.

State lives in $STUB_PVESH_STATE (a JSON array shaped like `pvesh get /cluster/mapping/pci
--output-format json`). Every write (create/set/delete) is appended to $STUB_PVESH_LOG and
applied to the state file, so a second role run sees its own earlier writes, as it would
against pmxcfs. `--check-node` reproduces PVE::Mapping::PCI::assert_valid against the fake sysfs
tree in $STUB_PVESH_SYSFS: id, subsystem-id and iommugroup must match the device at `path`.
"""

import json
import os
import sys


def load():
    with open(os.environ["STUB_PVESH_STATE"]) as f:
        return json.load(f)


def save(state):
    with open(os.environ["STUB_PVESH_STATE"], "w") as f:
        json.dump(state, f, indent=1)


def log(argv):
    with open(os.environ["STUB_PVESH_LOG"], "a") as f:
        f.write(" ".join(argv) + "\n")


def parse_map(s):
    return dict(kv.split("=", 1) for kv in s.split(","))


def read_hex(p):
    with open(p) as f:
        return f.read().strip().lower().removeprefix("0x")


def find_device(root, path):
    for dirpath, dirnames, _ in os.walk(os.path.join(root, "devices")):
        if os.path.basename(dirpath) == path:
            return dirpath
    return None


def checks_for(entry, node):
    out = []
    for m in entry["map"]:
        kv = parse_map(m)
        if kv.get("node") != node:
            continue
        dev = find_device(os.environ["STUB_PVESH_SYSFS"], kv["path"])
        if dev is None:
            out.append({"severity": "error", "message": "pci device '%s' not found\n" % kv["path"]})
            continue
        expected = {
            "id": "%s:%s" % (read_hex(os.path.join(dev, "vendor")), read_hex(os.path.join(dev, "device"))),
            "iommugroup": os.path.basename(os.readlink(os.path.join(dev, "iommu_group"))),
            "subsystem-id": "%s:%s" % (read_hex(os.path.join(dev, "subsystem_vendor")), read_hex(os.path.join(dev, "subsystem_device"))),
        }
        for prop in sorted(expected):
            if kv.get(prop) != expected[prop]:
                out.append({"severity": "error", "message": "Invalid configuration: '%s' does not match for '%s' (%s != %s)\n" % (prop, entry["id"], expected[prop], kv.get(prop))})
    return out


def main(argv):
    if len(argv) < 3:
        return 2
    verb, path, rest = argv[1], argv[2], argv[3:]
    opts = {}
    i = 0
    while i < len(rest):
        if rest[i].startswith("--"):
            opts[rest[i][2:]] = rest[i + 1] if i + 1 < len(rest) else None
            i += 2
        else:
            i += 1
    state = load()
    if verb == "get" and path == "/cluster/mapping/pci":
        node = opts.get("check-node")
        out = []
        for e in state:
            e = dict(e)
            if node:
                e["checks"] = checks_for(e, node)
            out.append(e)
        print(json.dumps(out))
        return 0
    if verb == "get" and path.startswith("/cluster/mapping/pci/"):
        wanted = path.rsplit("/", 1)[1]
        for e in state:
            if e["id"] == wanted:
                print(json.dumps(e))
                return 0
        sys.stderr.write("no such mapping '%s'\n" % wanted)
        return 2
    log(argv[1:])
    if verb == "create" and path == "/cluster/mapping/pci":
        if any(e["id"] == opts["id"] for e in state):
            sys.stderr.write("pci ID '%s' already defined\n" % opts["id"])
            return 2
        state.append({"id": opts["id"], "map": [opts["map"]], "type": "pci"})
    elif verb == "set" and path.startswith("/cluster/mapping/pci/"):
        wanted = path.rsplit("/", 1)[1]
        for e in state:
            if e["id"] == wanted:
                e["map"] = [opts["map"]]
                break
        else:
            sys.stderr.write("no such mapping '%s'\n" % wanted)
            return 2
    elif verb == "delete" and path.startswith("/cluster/mapping/pci/"):
        wanted = path.rsplit("/", 1)[1]
        state = [e for e in state if e["id"] != wanted]
    else:
        sys.stderr.write("stub-pvesh: unsupported %r\n" % argv)
        return 2
    save(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
