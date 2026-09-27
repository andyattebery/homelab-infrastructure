#!/usr/bin/env python3
"""Stand-in for the 1Password CLI, scoped to item get / item edit / inject.

- `item get ... --format json` prints $STUB_OP_ITEM.
- `item edit` reads the item template from stdin, saves it to $STUB_OP_CAPTURE, and echoes it to
  stdout -- the real op prints the edited item, so a script that passes op's output on would
  leak it. Exits $STUB_OP_EDIT_EXIT (default 0).
- `inject -i <tpl> -o <out>` copies $STUB_OP_INJECT_SOURCE to <out>.
Every call is appended to $STUB_LOG as a JSON argv list.
"""

import json
import os
import shutil
import sys


def main(argv):
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(argv[0])] + argv[1:]) + "\n")
    args = argv[1:]
    if args[:2] == ["item", "get"]:
        with open(os.environ["STUB_OP_ITEM"]) as f:
            sys.stdout.write(f.read())
        return 0
    if args[:2] == ["item", "edit"]:
        template = sys.stdin.read()
        with open(os.environ["STUB_OP_CAPTURE"], "w") as f:
            f.write(template)
        sys.stdout.write(template)
        return int(os.environ.get("STUB_OP_EDIT_EXIT", "0"))
    if args[:1] == ["inject"]:
        shutil.copy(os.environ["STUB_OP_INJECT_SOURCE"], args[args.index("-o") + 1])
        return 0
    sys.stderr.write("stub-op: unsupported %r\n" % argv)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
