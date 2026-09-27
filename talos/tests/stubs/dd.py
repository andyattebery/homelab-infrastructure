#!/usr/bin/env python3
"""Stand-in for dd: logs its argv to $STUB_LOG and writes nothing. Fails, as dd does, when the
input file is missing."""

import json
import os
import sys


def main(argv):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    inputs = [a[3:] for a in argv[1:] if a.startswith("if=")]
    if not inputs or not os.path.isfile(inputs[0]):
        sys.stderr.write("stub-dd: no input file in %r\n" % argv)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
