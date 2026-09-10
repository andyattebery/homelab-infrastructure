#!/usr/bin/env python3
"""Stand-in for qm, scoped to config / pending / set.

$STUB_QM_DIR holds one <vmid>.conf per VM (the current config, PVE's format) and, when the VM
is "running", a <vmid>.running marker. Writes are logged to $STUB_QM_LOG and applied:
- stopped VM: straight into <vmid>.conf, as PVE does;
- running VM: into <vmid>.pending (JSON {key: value | null}), as PVE queues a hostpci change
  for the next stop/start.
`qm config` prints the pending-applied view (PVE's default); `qm pending` prints cur/new/del
lines the way PVE::GuestHelpers::format_pending does.
"""

import json
import os
import sys


def paths(vmid):
    d = os.environ["STUB_QM_DIR"]
    return os.path.join(d, vmid + ".conf"), os.path.join(d, vmid + ".pending"), os.path.join(d, vmid + ".running")


def read_conf(p):
    out = {}
    with open(p) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("["):
                break  # only the main section is the current config
            k, v = line.split(":", 1)
            out[k] = v.strip()
    return out


def write_conf(p, conf):
    with open(p, "w") as f:
        for k in sorted(conf):
            f.write("%s: %s\n" % (k, conf[k]))


def read_pending(p):
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def main(argv):
    verb, vmid, rest = argv[1], argv[2], argv[3:]
    conf_p, pend_p, run_p = paths(vmid)
    conf = read_conf(conf_p)
    pending = read_pending(pend_p)
    if verb == "config":
        view = dict(conf)
        for k, v in pending.items():
            if v is None:
                view.pop(k, None)
            else:
                view[k] = v
        for k in sorted(view):
            print("%s: %s" % (k, view[k]))
        return 0
    if verb == "pending":
        for k in sorted(set(conf) | set(pending)):
            if k in pending and pending[k] is None:
                print("del %s: %s" % (k, conf.get(k, "")))
            elif k in pending and k in conf:
                print("cur %s: %s" % (k, conf[k]))
                print("new %s: %s" % (k, pending[k]))
            elif k in pending:
                print("new %s: %s" % (k, pending[k]))
            else:
                print("cur %s: %s" % (k, conf[k]))
        return 0
    if verb == "set":
        with open(os.environ["STUB_QM_LOG"], "a") as f:
            f.write(" ".join(argv[1:]) + "\n")
        changes = {}
        i = 0
        while i < len(rest):
            if rest[i] == "--delete":
                for k in rest[i + 1].split(","):
                    changes[k] = None
                i += 2
            elif rest[i].startswith("--"):
                changes[rest[i][2:]] = rest[i + 1]
                i += 2
            else:
                return 2
        if os.path.exists(run_p):
            pending.update(changes)
            with open(pend_p, "w") as f:
                json.dump(pending, f)
        else:
            for k, v in changes.items():
                if v is None:
                    conf.pop(k, None)
                else:
                    conf[k] = v
            write_conf(conf_p, conf)
        return 0
    sys.stderr.write("stub-qm: unsupported %r\n" % argv)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
