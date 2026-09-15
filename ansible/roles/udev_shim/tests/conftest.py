"""Make the role's vendored sender importable, and keep pytest out of the roles symlink.

`collect_ignore` is required, not tidiness: `tests/roles/udev_shim` is a symlink to `../../`, so
without it pytest recurses through the link and collects this same file dozens of times. Same
reason roles/pve_pci_mapping/tests/conftest.py has one -- see ansible/tests/README.md,
"Role resolution".
"""

import os
import sys

collect_ignore = ["roles"]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files"))
