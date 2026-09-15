# pve_lxc

Creates and converges an LXC container on a Proxmox VE cluster.

The role supplies the mechanism. **What the container is for is entirely the caller's** — it
installs nothing inside one beyond an optional login account, and knows nothing about what
will run there.

## Status: Production

Deployed against a real cluster on 2026-09-12: built a container on a PVE node from nothing, with
no typed arguments, and converges at `changed=0` on subsequent runs. Compare-and-set decisions
are proven by `tests/test.yml`.

The intended second consumer is a Tdarr node, and the role was written generic for that rather
than shaped around its first caller. Read "The `cmode` trap" below first — it is why a single
successful run proves less than it appears to.

## It uses the API for most things and `pct` for two

Everything the Proxmox API will accept from an **API token** goes through
`community.proxmox.proxmox`, which is idempotent and needs no ssh. Two option families cannot,
and this is not a privilege that can be granted — PVE checks for the literal `root@pam` user.
From `PVE::LXC::check_ct_modify_config_perm` in `/usr/share/perl5/PVE/LXC.pm` (PVE 9), which
short-circuits at line 1681 on `$authuser eq 'root@pam'` — a string comparison a
`root@pam!token` also fails:

| Option | Source | Consequence |
| --- | --- | --- |
| `dev[n]` | line 1709-1710, `"configuring device passthrough is only allowed for root@pam"` | unconditional; any GPU or device passthrough |
| `mp[n]` **bind** | line 1688-1693, `"mount point type ... is only allowed for root@pam" if $data->{type} ne 'volume'` | **volume**-backed mounts are fine through the token; a host path is not |

So `pve_lxc_devices` and `pve_lxc_bind_mounts` are applied with `pct` on the node, which needs
root there. Everything else — including `pve_lxc_mount_volumes` — goes through the token.
Do not "simplify" those two into the module: the result is a permission exception, not a
cleaner role.

Two more root-only cases the role does not hit but a caller might:
`features` other than `nesting` (line 1753-1755 — `nesting` alone needs only `VM.Allocate`),
and `hookscript` (line 1759-1760).

## `proxmoxer` is a controller-side dependency

The module talks to the API over HTTPS and imports `proxmoxer` (declared in
`ansible/requirements.txt`). The PVE nodes do not have it, so the module task runs
`delegate_to: localhost`. The `pct` tasks run on the node. A play calling this role therefore
targets the **node**, not the container — the container may not exist yet.

## Inputs

Required — all asserted, because a wrong value builds the wrong thing rather than failing:

- `pve_lxc_vmid` — 100 or greater. A wrong one converges over an existing guest.
- `pve_lxc_hostname`, `pve_lxc_node` — a guessed node builds the container in the wrong place.
- `pve_lxc_api_host`, `pve_lxc_api_user`, `pve_lxc_api_token_id`, `pve_lxc_api_token_secret` —
  the token needs `VM.Allocate`, `VM.Config.*`, `VM.PowerMgmt` and `Datastore.AllocateSpace`,
  granted to **both** the user and the token when the token has `privsep=1` (the default),
  because its effective rights are the *intersection* of the two.

Optional, passed straight through when set and omitted entirely when empty — so PVE's own
default applies rather than one this role would have to keep current:

`pve_lxc_ostemplate`, `_storage`, `_disk`, `_disk_volume`, `_mount_volumes`, `_cores`,
`_memory`, `_swap`, `_netif`, `_nameserver`, `_searchdomain`, `_timezone`, `_description`,
`_tags`, `_features`, `_unprivileged` (default `true`), `_onboot` (default `true`),
`_state` (default `present`), `_purge` (default `true`, used only with `state: absent`).

`pve_lxc_cmode` (default `tty`) is the one option deliberately **not** omittable. See
"The `cmode` trap" below; a caller may set `console` or `shell`, and `default` is refused.

Root-only, applied with `pct`:

- `pve_lxc_devices` — list of `{path, group|gid, uid, mode, deny_write, state}`. Position in
  the list is the N in `devN`. The rendered key is `deny-write` with a hyphen; the input uses
  an underscore because a hyphen is awkward as a YAML key, and the role translates.
- `pve_lxc_bind_mounts` — list of `{host_path, mount_point, options, state}`. Position is the
  N in `mpN`. `options` is a dict appended as `key=value`.
- `pve_lxc_raw_config` — list of `{key, value, match, state}` raw `lxc.*` lines. Not `pct` at
  all: a direct edit of the container config file, because there is no API property and no pct
  flag for these. See "Raw `lxc.*` lines are a file edit" below — every field there has a
  failure mode worth reading before using it.

Test seams:

- `pve_lxc_pct_command` — default `/usr/sbin/pct`, an input so a fixture test can point it at
  a stub that records its argv.
- `pve_lxc_conf_path` — default empty, meaning `/etc/pve/lxc/<vmid>.conf`. Exists so the
  fixture test can aim the raw-config edit at a tempfile. **Nothing else should set it.** The
  task it feeds replaces the whole file as root with `unsafe_writes`; pointed at the wrong
  path it destroys a container, which is why the role refuses to write a file with no
  `key: value` option line in its main section.

Optional bootstrap:

- `pve_lxc_bootstrap_user`, `_bootstrap_keys_url`, `_bootstrap_shell` (default `/bin/bash`),
  `_bootstrap_sudo` (default `true`). Unset user skips the whole file.

## Example

```yaml
- name: Create the container
  ansible.builtin.include_role:
    name: pve_lxc
  vars:
    pve_lxc_vmid: 120
    pve_lxc_hostname: example-01
    pve_lxc_node: node-a
    pve_lxc_api_host: node-a.example
    pve_lxc_api_user: rw-api@pam
    pve_lxc_api_token_id: ansible
    pve_lxc_api_token_secret: "{{ some_vaulted_secret }}"
    pve_lxc_ostemplate: local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst
    pve_lxc_storage: some_pool
    pve_lxc_disk: 32
    pve_lxc_netif:
      net0: "name=eth0,bridge=vmbr0,hwaddr={{ some_vaulted_mac }},ip=dhcp"
    pve_lxc_devices:
      - path: /dev/dri/renderD128
        group: render
```

## Raw `lxc.*` lines are a file edit, and the file has sections

`pve_lxc_raw_config` is the only part of this role that writes the container config directly.
It has to: `lxc` is not in PVE's `$confdesc`, so there is no API property and no `pct set` flag
for `lxc.cgroup2.devices.allow` or `lxc.mount.entry`. The file is the whole interface.

```yaml
pve_lxc_raw_config:
  - key: lxc.cgroup2.devices.allow
    value: "c 13:* rwm"
  - key: lxc.mount.entry
    value: "/dev/input dev/input none bind,optional,create=dir 0 0"
    match: '^lxc\.mount\.entry(:|\s*=)\s*/dev/input\b'
```

**The line goes above the first `[section]` header, and that is the entire difficulty.**
`PVE::LXC::Config::write_pct_config` emits, per section: the description as `#` comments, the
options sorted, then the raw `lxc.*` lines — and then `"\n[$name]\n"` plus a full copy of all
of that for `[pve:pending]` and for **every snapshot**. `parse_pct_config` reassigns `$conf` on
a `^\[...\]` line, so a line written after that header configures **the snapshot**, not the
container. Append at EOF on a container that has ever been snapshotted and the setting is
present in the file, absent from the container, and silently baked into the snapshot you would
roll back to.

`lineinfile` cannot express "before the first section header" — `insertbefore` and
`insertafter` both anchor on the *last* match — so the role splits the file at the first
header, edits only the part above it, and carries the rest through byte for byte.

**Written in the colon form.** `write_pct_config` re-emits every raw line as `"$k: $v"`, so an
`=`-form line would be rewritten behind the role and reported changed on every run. The role
reads both, because `parse_pct_config` matches `(lxc\.[a-z0-9_\-\.]+)(:|\s*=)` and a
hand-edited config legitimately contains either.

**`match` selects the line to replace**, defaulting to the key in both forms. It becomes
required the moment two entries share a key — two `lxc.mount.entry` lines, say — because
without it each would replace the other and the run would report success either way. That is
asserted, not left to chance. So is the converse: a `match` that does not also match the line
the role is about to write appends a duplicate on **every** run, forever, with both lines
taking effect in the container.

Folding an entry in deletes *every* line its `match` selects and appends one. That is what
collapses a duplicate an older `=`-form line or a hand edit left behind — and it is why a
`match` wider than intended deletes lines the caller meant to keep.

**Which keys are legal is PVE's decision, checked at container start.** The role only checks
the shape, using PVE's own character class `^lxc\.[a-z0-9_.-]+$` — deliberately not the
tidier-looking `^lxc\.[a-z0-9]+(\.[a-z0-9_]+)*$`, which rejects the real key
`lxc.hook.pre-start`. What the shape check is actually for is the caller error that corrupts
the file: a key that is not an `lxc` key at all (`rootfs`) renders as a plain option line and
clobbers a real one. A key PVE *parses* but does not *accept* leaves a container that will not
boot — `is_valid_lxc_conf_key` is where that is decided, at start, not at write time.

**Raw lines take effect only when the container starts.** The role reports that a restart is
owed and never performs one, the same rule every session-owning role here follows.

`/etc/pve` is pmxcfs, a FUSE filesystem that does not support the chmod Ansible's `atomic_move`
performs, so the write uses `unsafe_writes: true` and sets no `mode` — `copy` keeps the
destination's existing mode when none is given.

## A device's group is resolved *inside* the container

Give a device `group: render`, not `gid: 993`. The role runs `getent group` in the container
and uses what it answers.

This is not fastidiousness. On a PVE 9 node the `render` group is gid **993**; in a Debian 13
container it is **992**. Passing the host's gid produces a device node owned by a group that
means something else inside, and nothing reports an error — the application simply cannot open
it. `tests/test.yml` fixes the two numbers apart precisely so a regression here fails.

A group name requires the container to be **running**, since resolving it runs inside. The role
checks and refuses rather than guessing. Pass a literal `gid` if you need to configure a
stopped container — that path works, but it is the one where nothing can check your number
against the container, so it is the caller's problem if it is the host's gid.

## Bind mounts are often the wrong answer

They force the root-only path above, and in an **unprivileged** container the host uid/gid are
shifted by 100000, so a bind-mounted directory usually appears owned by `nobody` until the
ownership on the host is arranged to match.

If the goal is network storage — a media library, a share — mounting it *inside* the container
is usually simpler and avoids both problems. This repo already has `systemd_cifs_mount` for
exactly that. The role supports bind mounts because some callers genuinely need a host path;
reach for them second.

## `storage` cannot be combined with volume mounts

`community.proxmox` documents `storage` as mutually exclusive with `disk_volume` and
`mount_volumes`, `disk` with `disk_volume`, and `mounts` with `mount_volumes`. The role asserts
the incompatible pairs up front, so the failure names the two inputs in conflict instead of
surfacing from inside the module.

## The bootstrap account exists because there is no cloud-init

A VM built from a cloud image gets its login account from cloud-init. A container does not, and
`pct create` seeds only **root** — both `--password` and `--ssh-public-keys` are root-only. So
without `pve_lxc_bootstrap_user` the first playbook run against the new host has no account to
connect as.

It is done through `pct exec` from the node rather than over ssh, because at that moment the
container has no ssh account and possibly no address. The Debian LXC template also ships **no
sudo at all**, so `/etc/sudoers.d` does not exist; the role installs it before writing there.

## What the test proves, and what it does not

`tests/test.yml` proves the decisions. For the `pct` half: that a missing device is written
once with the container's gid, that an identical declaration a second time writes nothing,
that a bind mount renders in `mp` syntax rather than `dev` syntax and is likewise idempotent,
and that a group the container does not have is refused before anything is written.

For the raw-`lxc.*` half it seeds a config with the shape that matters — a `[pre-uinput]`
snapshot section and an `=`-form raw line — and compares the result **byte for byte**, because
"the line is in the file" is exactly what an EOF append also satisfies. On top of that:
idempotence proven on the raw bytes of two reads rather than on a `changed` flag alone; two
entries under one key kept apart by `match`; `state: absent` removing only its own line; a
`pct set` in the same run not costing the raw lines; and a `conf_path` that is not a container
config refused before the write.

`tests/stub-pct.py` mirrors `PVE::LXC::Config` where it matters for that: raw entries are a
list, not a dict, so duplicate keys survive; everything from the first `[name]` header on is
carried through untouched; and the section order on write is PVE's. A stub that reshaped the
file would hide the bugs this half can have.

Eight of the cases are controls that construct a broken **caller** — never a broken role — so
they stay runnable after the bug is fixed.

It proves **nothing** about the API half — no fixture can answer a Proxmox API — nor about
whether a container actually boots, nor whether PVE accepts a given `lxc.*` key, which it
decides at container start. Those need a cluster.

## The `cmode` trap, and why this role always sends it

`community.proxmox` 2.0.0 defines `cmode` with `default: default` — a sentinel meaning "do not
send this to the API". Only the create path honours it:

| path | behaviour |
| --- | --- |
| `create_lxc_instance()` (`proxmox.py:1169-1170`) | `if kwargs.get("cmode") == "default": kwargs.pop("cmode")` |
| `update_lxc_instance()` (`proxmox.py:969`, `:975`) | drops `None` values only — the sentinel is posted verbatim |

So a container **builds fine and then fails every converge afterwards**:

    400 Bad Request: Parameter verification failed.
    {'cmode': "value 'default' does not have a value in the enumeration 'shell, console, tty'"}

2.0.0 is the latest release, so there is nothing to upgrade to. This role therefore always
sends a real value. The default is `tty` because that is PVE's own documented default
(`pct.conf.5`: `cmode: <console | shell | tty> (default = tty)`), so sending it explicitly
changes nothing about the container — it only takes the decision away from the module.
`tasks/validate.yaml` rejects `default` outright so a caller cannot reintroduce it.

The general shape is worth keeping: a bug that only appears on the **second** run is invisible
to any amount of testing that creates something once and declares victory.

`docs/vdesktop-01.md` documents the first container built with this role, including the
root-only option families and the `cmode` converge bug as they appeared in practice.
