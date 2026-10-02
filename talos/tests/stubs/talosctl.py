#!/usr/bin/env python3
"""Stand-in for talosctl that answers only what would reach a node.

- `get disks` prints $STUB_TALOS_DISKS, output captured from a real node (fixtures/).
- `wipe disk` does nothing.
- `list <dir>` and `read <file>` print talosctl's output for that path from $STUB_TALOS_SYSFS,
  captured from a real node (fixtures/). A path it doesn't hold fails, as a missing file does.
  Both fail for a node named in $STUB_TALOS_DOWN (comma-separated), as an unreachable node does.
  For a node named in $STUB_TALOS_SLOW, the hostname read takes a second.
Everything else -- gen, machineconfig, config, validate, version -- is offline, and runs the real
binary at $STUB_REAL_TALOSCTL. Every call is appended to $STUB_LOG as a JSON argv list.
"""

import json
import os
import sys
import time


def has(args, *words):
    return any(tuple(args[i:i + len(words)]) == words for i in range(len(args)))


def named(variable, node):
    return node in os.environ.get(variable, "").split(",")


def sysfs(args):
    node = args[args.index("-n") + 1]
    if named("STUB_TALOS_DOWN", node):
        sys.stderr.write(
            f'error from node {node}: rpc error: code = Unavailable desc = connection error: desc = '
            f'"transport: Error while dialing: dial tcp {node}:50000: i/o timeout"\n'
        )
        return 1
    verb = "list" if "list" in args else "read"
    path = args[args.index(verb) + 1]
    if named("STUB_TALOS_SLOW", node) and path == "/proc/sys/kernel/hostname":
        time.sleep(1)
    with open(os.environ["STUB_TALOS_SYSFS"]) as f:
        output = json.load(f)[verb].get(path)
    if output is None:
        sys.stderr.write(f"error from node {node}: {path}: no such file or directory\n")
        return 1
    sys.stdout.write(output)
    return 0


def main(argv):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    args = argv[1:]
    if has(args, "get", "disks"):
        with open(os.environ["STUB_TALOS_DISKS"]) as f:
            sys.stdout.write(f.read())
        return 0
    if has(args, "wipe", "disk"):
        return 0
    if "list" in args or "read" in args:
        return sysfs(args)
    real = os.environ["STUB_REAL_TALOSCTL"]
    os.execv(real, [real] + args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
