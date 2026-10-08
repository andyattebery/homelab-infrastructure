#!/usr/bin/env python3
"""Stand-in for helm, which would reach the cluster and the chart repositories.

Every call is appended to $STUB_LOG as a JSON argv list, and succeeds.
"""

import json
import os
import sys


def main(argv):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
