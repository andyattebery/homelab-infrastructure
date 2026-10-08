#!/usr/bin/env python3
"""Stand-in for kubectl, which would reach the cluster.

- Every call is appended to $STUB_LOG as a JSON argv list, and succeeds.
- $STUB_KUBECTL_FAIL="<substring>:<n>" fails the first n `apply` calls whose arguments contain the
  substring, as a webhook that is not ready yet refuses them. The count is kept in a file next to
  $STUB_LOG.
"""

import json
import os
import sys


def main(argv):
    log = os.environ["STUB_LOG"]
    with open(log, "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    args = argv[1:]
    fail = os.environ.get("STUB_KUBECTL_FAIL")
    if fail and "apply" in args:
        substring, limit = fail.rsplit(":", 1)
        if any(substring in arg for arg in args):
            counter = os.path.join(os.path.dirname(log), "kubectl-failures")
            failed = int(open(counter).read()) if os.path.exists(counter) else 0
            if failed < int(limit):
                with open(counter, "w") as f:
                    f.write(str(failed + 1))
                sys.stderr.write("stub-kubectl: apply refused ($STUB_KUBECTL_FAIL)\n")
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
