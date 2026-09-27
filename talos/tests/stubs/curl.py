#!/usr/bin/env python3
"""Stand-in for curl, scoped to the two Image Factory calls flash-sd.sh makes.

- POST .../schematics prints {"id": $STUB_SCHEMATIC_ID}.
- GET .../image/<id>/<version>/metal-arm64.raw.xz writes a small real .xz file to the -o path,
  so the script's `xz -dk` runs for real.
Every call is appended to $STUB_LOG as a JSON argv list.
"""

import json
import lzma
import os
import sys


def main(argv):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    args = argv[1:]
    if "https://factory.talos.dev/schematics" in args:
        print(json.dumps({"id": os.environ["STUB_SCHEMATIC_ID"]}))
        return 0
    if any(a.startswith("https://factory.talos.dev/image/") for a in args):
        with open(args[args.index("-o") + 1], "wb") as f:
            f.write(lzma.compress(b"stand-in for a Talos disk image\n", format=lzma.FORMAT_XZ))
        return 0
    sys.stderr.write("stub-curl: unsupported %r\n" % argv)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
