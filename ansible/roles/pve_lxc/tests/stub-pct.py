#!/usr/bin/env python3
"""Stand-in for pct, scoped to the four verbs pve_lxc uses.

$STUB_PCT_DIR holds, per container:
  <vmid>.conf     the current config in PVE's `key: value` format
  <vmid>.running  present when the container is "running"
  <vmid>.groups   `name:gid` per line, the container's own group database

Every `set` is appended to $STUB_PCT_LOG before being applied, so a test can assert the exact
argv rather than only the end state -- which is what catches a role that reaches the right
config by writing twice.

Deliberately fails on an unknown container the way pct does, so a test cannot pass by
accident against a container that was never created.

The config round-trip mirrors PVE::LXC::Config, because the role's raw-`lxc.*` half is a file
edit and a stub that reshapes the file would hide exactly the bugs that half can have:

  * everything from the first `[name]` header onwards belongs to a SNAPSHOT, not the container
    (parse_pct_config reassigns `$conf` there), so the tail is carried through untouched and
    never merged into the options;
  * raw `lxc.*` entries are a LIST, not a dict -- `push @{$conf->{lxc}}, [$key, $value]` -- so
    two `lxc.mount.entry` lines both survive, in order;
  * write_pct_config emits description comments, then options sorted, then the raw lines, then
    "\n[$name]\n" per snapshot. Same order here.
"""

import os
import re
import sys

# parse_pct_config's own patterns.
SECTION_RE = re.compile(r"^\[")
LXC_RE = re.compile(r"^(lxc\.[a-z0-9_\-.]+)(:|\s*=)\s*(.*?)\s*$")
OPT_RE = re.compile(r"^([a-z][a-z_]*\d*):\s*(.+?)\s*$")


def paths(vmid):
    d = os.environ["STUB_PCT_DIR"]
    return (
        os.path.join(d, vmid + ".conf"),
        os.path.join(d, vmid + ".running"),
        os.path.join(d, vmid + ".groups"),
    )


def read_conf(p):
    """-> (opts dict, lxc list of [k, v], comments list, tail list) or None."""
    if not os.path.exists(p):
        return None
    opts, lxc, comments, tail = {}, [], [], []
    with open(p) as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if SECTION_RE.match(line):
            tail = lines[i:]
            break
        if not line.strip():
            continue
        if line.startswith("#"):
            comments.append(line)
            continue
        m = LXC_RE.match(line)
        if m:
            lxc.append([m.group(1), m.group(3)])
            continue
        m = OPT_RE.match(line)
        if m:
            opts[m.group(1)] = m.group(2)
            continue
        sys.stderr.write("stub-pct: unable to parse config: %s\n" % line)
        sys.exit(2)
    return opts, lxc, comments, tail


def write_conf(p, conf):
    opts, lxc, comments, tail = conf
    out = list(comments)
    out += ["%s: %s" % (k, opts[k]) for k in sorted(opts)]
    out += ["%s: %s" % (k, v) for k, v in lxc]
    if tail:
        out += [""] + tail
    with open(p, "w") as f:
        f.write("\n".join(out) + "\n")


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("stub-pct: need a verb and a vmid\n")
        return 2
    verb, vmid, rest = argv[1], argv[2], argv[3:]
    conf_p, run_p, grp_p = paths(vmid)
    conf = read_conf(conf_p)

    if conf is None:
        sys.stderr.write("Configuration file 'nodes/stub/lxc/%s.conf' does not exist\n" % vmid)
        return 2

    opts, lxc, _comments, _tail = conf

    if verb == "config":
        for k in sorted(opts):
            print("%s: %s" % (k, opts[k]))
        for k, v in lxc:
            print("%s: %s" % (k, v))
        return 0

    if verb == "status":
        print("status: %s" % ("running" if os.path.exists(run_p) else "stopped"))
        return 0

    if verb == "exec":
        # pct exec <vmid> -- getent group <name>
        if rest[:1] == ["--"]:
            rest = rest[1:]
        if rest[:2] == ["getent", "group"]:
            name = rest[2]
            if os.path.exists(grp_p):
                with open(grp_p) as f:
                    for line in f:
                        n, _, gid = line.strip().partition(":")
                        if n == name:
                            print("%s:x:%s:" % (n, gid))
                            return 0
            return 2  # getent exits non-zero when the group is unknown
        sys.stderr.write("stub-pct: unsupported exec %r\n" % rest)
        return 2

    if verb == "set":
        with open(os.environ["STUB_PCT_LOG"], "a") as f:
            f.write(" ".join(argv[1:]) + "\n")
        i = 0
        while i < len(rest):
            if rest[i] == "--delete":
                for k in rest[i + 1].split(","):
                    opts.pop(k, None)
                i += 2
            elif rest[i].startswith("--"):
                opts[rest[i][2:]] = rest[i + 1]
                i += 2
            else:
                return 2
        write_conf(conf_p, conf)
        return 0

    sys.stderr.write("stub-pct: unsupported %r\n" % argv)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
