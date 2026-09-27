#!/usr/bin/env python3
"""Stand-in for talosctl that answers only what would reach a node.

- `get disks` prints $STUB_TALOS_DISKS, output captured from a real node (fixtures/).
- `wipe disk` does nothing.
Everything else -- gen, machineconfig, config, validate, version -- is offline, and runs the real
binary at $STUB_REAL_TALOSCTL. Every call is appended to $STUB_LOG as a JSON argv list.
"""

import json
import os
import sys


def has(args, *words):
    return any(tuple(args[i:i + len(words)]) == words for i in range(len(args)))


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
    real = os.environ["STUB_REAL_TALOSCTL"]
    os.execv(real, [real] + args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
