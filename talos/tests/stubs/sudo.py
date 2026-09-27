#!/usr/bin/env python3
"""Stand-in for sudo: logs its argv to $STUB_LOG, then runs the command as the same user, found
on PATH (so `sudo dd` reaches the dd stub)."""

import json
import os
import sys


def main(argv):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    os.execvp(argv[1], argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
