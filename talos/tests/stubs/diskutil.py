#!/usr/bin/env python3
"""Stand-in for macOS diskutil, scoped to info -plist / unmountDisk / eject.

`info -plist` prints $STUB_DISKUTIL_PLIST, a plist captured from a real card (fixtures/). Every
call is appended to $STUB_LOG as a JSON argv list.
"""

import json
import os
import sys


def main(argv):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    if argv[1:3] == ["info", "-plist"]:
        with open(os.environ["STUB_DISKUTIL_PLIST"]) as f:
            sys.stdout.write(f.read())
        return 0
    if argv[1] in ("unmountDisk", "eject"):
        return 0
    sys.stderr.write("stub-diskutil: unsupported %r\n" % argv)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
