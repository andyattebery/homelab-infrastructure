# pve_node_ceph

Per-node Ceph for a Proxmox VE node: owns the Ceph apt source, installs the release the
cluster runs, refuses to go further if the node or the cluster disagrees with that release,
initialises the cluster's Ceph config on the designated runner, then creates this node's
monitor, manager, metadata server and OSD — and waits for each to show up in Ceph's own view.

## Status: Production

The 2026-09-08 additions — the OSD gate on the CRUSH bucket, the device inventory and
`pve_node_ceph_osd_zap`, `ceph osd in` on activation, the up/in wait, and forgetting a stale
`[mds.<id>]` section — went through vm-host-01's rebuild on 2026-09-09
(`docs/proxmox_node_reinstall.md`): the zap cleared a disk that still carried ZFS labels,
`Create ceph OSD` went `changed`, and osd.0 came back up and in. Both the three-step zap and
`pve_node_ceph_manage_mon` came out of that run — see their entries below.

Cluster-wide Ceph objects — the RBD pool and the CephFS filesystem — are `pve_cluster_ceph`,
which runs once per cluster. This role runs on every node, and must run **first**: a pool
cannot be created before there are OSDs to place its PGs on.

Upgrading the cluster from one release to the next is **not** this role's job; that is
`playbook-prod-proxmox-cluster-ceph-upgrade.yaml` (role `pve_ceph_upgrade`), which includes
this role's `repo.yaml` to switch the apt source.

## Required inputs

### `pve_ceph_release`

The Ceph release codename this cluster runs — `squid`, `tentacle`. Read three times: passed to
`pveceph install --version` on a fresh node, written into
`/etc/apt/sources.list.d/ceph.sources`, and compared against both the installed binaries and
the cluster's `min_mon_release` before any daemon is created. The values PVE accepts are in
`/usr/share/perl5/PVE/Ceph/Releases.pm` (on PVE 9: `squid`, `tentacle`).

**No default, on purpose.** Without a value `pveceph install` picks the release PVE currently
ships. On 2026-09-07 that put a rebuilt vm-host-02 on tentacle against a squid cluster; see
"The release guard". Belongs in the cluster's `group_vars`, next to `pve_ceph_network`, and is
changed only together with running the upgrade playbook.

Undefined: the role fails at its first task. Wrong: the guard fails with a message saying
which side disagrees.

### `pve_cluster_designated_runner`

Inventory hostname of the single node that performs cluster-wide writes. Only that node runs
`pveceph init`. Conventionally derived from the inventory rather than set per host, so exactly
one node matches.

If it names a host that is not in the play, `pveceph init` never runs and every node fails
later at `pveceph mon create` with "Could not connect to ceph cluster despite configured
monitors". If it matches more than one host, they race for the cluster lock.

### `pve_ceph_network`

CIDR of the Ceph cluster network, e.g. `10.0.0.0/24`. Passed to `pveceph init --network`.
Read only on the designated runner, and only on a fresh cluster.

Wrong value: the mons bind on a network the other nodes cannot reach, and every subsequent
run fails the "cluster is configured but mons are unreachable" check.

### `ceph_mon_address`

This node's address on the Ceph cluster network — a bare IP, no prefix length. Passed to
`pveceph mon create --mon-address`, and used to recognise this node's entry in `mon_host`.
Derive it from whatever variable already defines the node's cluster-NIC address so the two
cannot drift apart.

If the address does not exist on any local interface when the role runs, `pveceph mon create`
fails. If it exists but the interface has no carrier, the mon is created and then cannot form
quorum — which the join wait reports.

### `pve_ceph_osd_device`

Block device for this node's OSD. **Required when `pve_node_ceph_osd_mode` is `create`**;
unused otherwise.

Use a stable `/dev/disk/by-id/` path, never `/dev/sdX` or `/dev/nvmeXn1` — kernel device names
are not stable across boots, and pointing this at the wrong disk destroys it. The path can be
written before the drive is fitted: `ata-<model>_<serial>` for SATA, `nvme-<model>_<serial>`
for NVMe, with the serial from `hardware/ssd-inventory.md`. The device must be empty;
`ceph-volume inventory` decides, and a disk that is not (a filesystem, LVM, an old OSD) is
refused with its reasons unless `pve_node_ceph_osd_zap` is set — see below.

## Optional inputs

### `pve_node_ceph_osd_mode`

Default `create`. Two values, and picking the wrong one fails silently rather than loudly:

| Value | Behaviour | Use when |
|---|---|---|
| `create` | `pveceph osd create {{ pve_ceph_osd_device }}` | the OSD does not exist yet — a new node, or a node whose OSD disk is being replaced |
| `activate_existing` | `ceph-volume lvm activate --all`, then enable and start each `ceph-osd@N` found under `/var/lib/ceph/osd/`; fails if there is none; `ceph osd in` for any of this node's OSDs the osdmap says is out | reinstalling the host OS while keeping the OSD disk intact — a rebuild's teardown marks the OSD out first |

`activate_existing` needs no per-host OSD id or fsid — it discovers both from the disk. Both
modes end by waiting for every OSD in this node's CRUSH bucket to be up and in (24 × 5 s);
`systemctl` is not consulted.

**Steady state for a provisioned cluster is `activate_existing`.** A host left on `create`
will not activate its OSD on the next reinstall: the OSD is still in the node's CRUSH bucket,
so the gate below skips the create, nothing activates, and the play fails a minute later at
the up/in wait. `ansible/tests/test-ceph-osd-config.yml` fails while any node says `create`.

### `pve_node_ceph_osd_zap`

Default `false`. Read only in `create` mode, after the gate has decided an OSD is to be
created, and only when `ceph-volume inventory` reports `pve_ceph_osd_device` as not available.
`false` fails the play there, naming the inventory's reasons and the LVs on the disk.

`true` runs three steps unconditionally, in this order, on exactly that device:

1. `ceph-volume lvm zap --destroy` — an LVM teardown, and the right thing for a repurposed
   former OSD whose LVM sits on the bare device. It has to run first, or wiping a signature
   orphans the volume group. **Best-effort, and its exit status is ignored**: pointed at a disk
   that still has a partition table it refuses outright — *"RuntimeError: Device … has
   partitions."* — which is exactly what stopped the vm-host-01 rebuild on 2026-09-09.
2. `lsblk -nrpo NAME` on the device, then `wipefs -a` on **each partition first and the whole
   device last**. This is the step that actually clears the disk. The order is not cosmetic:
   ZFS labels live *inside* the partitions (four of them, two at each end), so clearing the
   partition table first would strand them at absolute offsets where nothing looks for them;
   the device itself carries the GPT and the protective MBR.
3. `udevadm settle`, so udev drops the stale partition device nodes before the disk is re-read.

The device is then inventoried again and the play fails if it is still not available. That
assert — not a branch on `rejected_reasons` — is what reacts if this sequence turns out not to
be enough for some future disk.

A one-run switch for a disk that arrives with something on it (vm-host-01's replacement S3610
still carried ZFS labels), removed once the OSD exists;
`ansible/tests/test-ceph-osd-config.yml` fails while it is set on any node. A wrong serial in
`pve_ceph_osd_device` is the only way this reaches the wrong disk.

### `pve_node_ceph_manage_mon`

Default `true`. Set `false` to leave this node's monitor entirely alone for a run: no forget,
no `pveceph mon create`, no enable/start, no quorum wait. The node's manager, metadata server
and OSD are unaffected and still converge on the same run — that separation is the whole point
of the flag.

It exists for quarantining a monitor that is known bad while the node's other daemons are
still wanted. On 2026-09-09 a freshly created 20.2.4 monitor syncing against 20.2.2 peers drove
hundreds of MB/s of memory growth on the other two monitors. The node's OSD was still needed,
so neither stopping the play nor letting the monitor come back on the next run was acceptable.

**Wrong in either direction is quiet.** Left at `false`, a rebuilt node silently never gets its
monitor back and the cluster runs one short — nothing fails, because a node without a monitor
is an ordinary thing for Ceph. Set back to `true` while the monitor is still the problem and
the next run recreates it. This is a per-host, per-incident switch; it does not belong in
`group_vars` and it does not stay in `host_vars` after the incident.

The gate is four `when:` clauses in `tasks/create_ceph_services.yaml` — forget, create,
enable/start, quorum wait. `tests/test.yml` asserts it covers exactly those four and no mgr,
mds or OSD task, and that the default is `true`.

### `pve_node_ceph_repository`

Default `no-subscription`. The component for `pveceph install --repository` and for
`ceph.sources`. `enterprise` needs a subscription; without one apt fails with 401.

### `pve_node_ceph_service_id`

Default `ansible_facts['hostname']` — the id PVE gives this node's mon, mgr and mds, which is
PVE's own default too. Exists for the fixture test; do not set it on a real node.

### `pve_node_ceph_conf_path`, `pve_node_ceph_mon_data_root`, `pve_node_ceph_mds_data_root`, `pve_node_ceph_osd_data_root`, `pve_node_ceph_ceph_command`, `pve_node_ceph_pveceph_command`, `pve_node_ceph_ceph_volume_command`, `pve_node_ceph_lsblk_command`, `pve_node_ceph_wipefs_command`, `pve_node_ceph_udevadm_command`

Defaults `/etc/ceph/ceph.conf`, `/var/lib/ceph/mon`, `/var/lib/ceph/mds`, `/var/lib/ceph/osd`,
`/usr/bin/ceph`, `/usr/bin/pveceph`, `ceph-volume`, `lsblk`, `wipefs`, `udevadm`. Overridable
so the decision tasks run against stubs and a tempdir in `tests/test.yml`.

The last three are the zap's tools, and they are bare names rather than absolute paths on
purpose: the play runs with `become`, whose `PATH` includes `/usr/sbin`, where `wipefs` and
`udevadm` live. A stripped `PATH` breaks the zap with "No such file or directory" rather than
with anything that mentions a disk.

## Example

From the calling playbook — the role takes no inline vars, reading everything from
`group_vars` and `host_vars`:

```yaml
- name: Configure per-node Ceph (install, init on designated runner, services)
  ansible.builtin.import_role:
    name: pve_node_ceph
```

```yaml
# group_vars/<cluster group>/vars.yaml
pve_ceph_network: 10.0.0.0/24
pve_ceph_release: squid
ceph_mon_address: "{{ ceph_cluster_nic_address_cidr.split('/')[0] }}"
pve_cluster_designated_runner: "{{ groups['<cluster group>'] | sort | first }}"

# host_vars/<node>/vars.yaml
pve_ceph_osd_device: /dev/disk/by-id/nvme-<model>_<serial>
pve_node_ceph_osd_mode: activate_existing

# host_vars/<node>/vars.yaml — for the one run that provisions a replacement disk
pve_ceph_osd_device: /dev/disk/by-id/ata-<model>_<serial>   # the new drive, from its serial
pve_node_ceph_osd_mode: create
pve_node_ceph_osd_zap: true                                  # only if the disk is not empty
```

## The release guard

`tasks/check_release.yaml` runs after install and before anything else — the apt source is
converged only on a node that passes it, so this role never switches a disagreeing node's repo:

1. `ceph -v` must name `pve_ceph_release`. Otherwise: *"Installed Ceph is 'X' … but
   pve_ceph_release is 'Y'"* — either the cluster is being upgraded (run the upgrade playbook
   first) or `pveceph` installed something else.
2. `ceph mon dump -f json` → `min_mon_release_name` must equal `pve_ceph_release`. Otherwise:
   *"The cluster's min_mon_release is 'X' … Refusing to create daemons that cannot join."*
   Skipped when there is no monmap yet (the designated runner before `pveceph init`).
3. `ceph versions -f json` → every running daemon must report the **exact x.y.z** this node has
   installed. Otherwise: *"This node runs Ceph 20.2.4 but the cluster's running daemons report
   20.2.2."* Skipped when there is no cluster to answer, like check 2.

Why this exists: on 2026-09-07 `install_ceph.yaml` ran `pveceph install` with no `--version`
and a rebuilt node got tentacle against a squid cluster. A monitor one major ahead of
`min_mon_release` cannot join; it sat `probing` for an hour while its unit reported `active`,
the election churn OOM-killed another node's monitor until systemd's start limiter gave up,
and the cluster lost quorum. Check 2 is what would have stopped that run before
`pveceph mon create`.

Why check 3 exists: checks 1 and 2 compare release *names*, and on 2026-09-09 that was not
enough. A reinstalled node got 20.2.4 while the cluster ran 20.2.2 — both `tentacle`, so both
passed — and the new monitor store-syncing against its older peers drove hundreds of MB/s of
memory growth on the other two monitors until it was stopped by hand. Check 3 is the version
axis of the same guard.

It asserts **equality**, not "this node is not newer". The harm observed came from a newer
node, but the 2026-09-07 failure was a node one major *behind* what the cluster would accept,
and the remedy for both is the same playbook — so an ordering test would silently readmit half
of what this guard exists to stop. `overall` is dropped from the comparison: it is Ceph's own
rollup of the other keys and can never carry a version they do not.

None of this blocks a rolling upgrade: `pve_ceph_upgrade` includes this role with
`tasks_from: repo` only, so the upgrade playbook never reaches these assertions and a cluster
that is legitimately mid-upgrade is free to be mixed. The main playbook is a different matter —
run it against a node while the cluster is half-upgraded and check 3 refuses, naming every
version in play. That is intended: a mixed cluster is a fine thing to be *upgrading* and a bad
thing to be *building a new node into*.

## Forgetting a stale monitor

`tasks/mon_state.yaml` decides from the monmap, not from `pveceph status` text. A monitor is
*stale* when the cluster is reachable, this node is not in the monmap, and something of it is
left behind: a `[mon.<id>]` section in ceph.conf, its address in `mon_host`, or
`/var/lib/ceph/mon/ceph-<id>`. That is what a raw `ceph mon remove` leaves — the only option
from a survivor when the node is down, and what the 2026-09-08 quorum recovery used — and
`pveceph mon create` refuses each leftover ("monitor '<id>' already exists", "monitor address
… already in use", "monitor filesystem … already exist").

`pveceph mon destroy` cannot clean it either: it takes the address to drop from `mon_host`
from the monmap, where the mon no longer is (`MON.pm` `destroymon`, pve-manager 9.2.11). So
`tasks/forget_mon.yaml` does what destroy does when it can: `files/ceph_conf_forget_mon.pl`
drops the section and the `mon_host` entry under PVE's cluster lock and through PVE's own
ceph.conf parser, then the store is removed, the unit disabled, and the node's service list
re-broadcast into the cluster KV (`broadcast_ceph_services`, as destroymon does) so the create
that follows cannot see the ghost. ceph.conf is pmxcfs —
that edit is replicated to every node, which is exactly why it goes through PVE's lock and
writer rather than a text substitution. The helper refuses a vector-form `mon_host`
(`[v2:…,v1:…]`) rather than guess at it.

A monitor that **is** in the monmap is never touched, whatever else exists.

## Forgetting a stale metadata server

`tasks/mds_state.yaml` decides from `ceph mds metadata`, the `[mds.<id>]` section in ceph.conf
and `/var/lib/ceph/mds/ceph-<id>`. The section is *stale* when it exists, the data dir does
not, and Ceph does not list the daemon — a reinstall, or a dead node's raw cleanup. `pveceph
mds create` dies on it: *"MDS '<id>' already referenced in ceph config, abort!"* (`MDS.pm`
187, pve-manager 9.2.11). `tasks/forget_mds.yaml` does what `pveceph mds destroy` does first
(`MDS.pm` 256-261): `files/ceph_conf_forget_mds.pl` drops the section under PVE's cluster lock
and through PVE's own parser, then the unit is stopped. A daemon Ceph still lists is never
touched, whatever is missing locally.

A reachable teardown runs `pveceph mds destroy`, which removes the section and the daemon's
auth entity together (`PVE::Ceph::Services::destroy_mds`, 354-359). After a raw cleanup the
`mds.<id>` entity would survive; `create_mds` (301-313) runs `auth get-or-create` with fixed
caps, which hands back the existing key when the caps match — and `pve_node_rebuild`'s
dead-node branch deletes the entity anyway, so the create starts clean either way. Should the
create still fail, `createmds` removes the section it wrote (`MDS.pm` 201-211) and the play
stops there. Not exercised live yet.

## A green create means joined

`changed` on the mon/mgr/mds create tasks means the command exited 0, and then the role waits
for Ceph to list the daemon: `quorum_status.quorum_names` for the mon, `mgr dump` for the
mgr, `mds metadata` for the mds — 12 × 5 s each. A daemon that never shows up fails the play
with the task name saying what to check. `systemctl is-active` is not consulted anywhere: an
MDS with no address on the cluster network starts, registers nothing and reports `active`,
and a refused monitor does the same while probing.

## The OSD gate on `create`

`tasks/osd_state.yaml` reads `ceph osd tree -f json` and takes the children of this node's
`host` bucket. The create runs only when there are none: a node with an OSD never gets a
second one, and an empty bucket — what `pveceph osd destroy` leaves behind (seen 2026-09-07)
— no longer blocks it, because `pveceph osd create` reuses the bucket. Until 2026-09-08 the
gate was a substring test on the decompiled CRUSH map, which an empty bucket also matched; the
play then finished green with no OSD on the node, and the fix was a hand-run `ceph osd crush
rm`. No hand step remains.

Before the create, `tasks/osd_prepare_device.yaml` runs `ceph-volume inventory` on
`pve_ceph_osd_device` and refuses a disk that is not available, naming the reasons and the LVs
on it; `pve_node_ceph_osd_zap` is the only way past that.

There is deliberately **no** gate on `activate_existing`: a reinstalled host keeps its CRUSH
entry (the OSD was never removed, only down), so a "skip if this node has an OSD" check would
skip the exact case that branch exists to handle. The inner tasks gate themselves instead, so
they do not report `changed` on an already-provisioned host — and the block fails when nothing
exists to activate, rather than finishing green with no OSD.

## Stale CephFS mounts

The role ends by force-unmounting any `/mnt/pve/*` CephFS mount that has gone stale — the
mountpoint stats as missing while still appearing in `/proc/self/mountinfo` — and bouncing
`pvestatd` so it remounts cleanly. This happens when the cluster network flaps mid-mount, and
shows up as `d?????????` from `ls` and an inactive storage in `pvesm status`.

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_node_ceph/tests/inventory roles/pve_node_ceph/tests/test.yml
```

Localhost only, stub `ceph` and `ceph-volume`, tempdir; nothing contacted. Covers the release
guard (agreeing, installed-ahead, cluster-ahead, point releases agreeing, a node one point
release ahead of the daemons, the same skew the other way, a half-upgraded cluster where only
some daemons match, a cluster naming no daemons at all, and no cluster yet), every `mon_state`
decision
(stale, member, unreachable, clean, and the `10.1.40.12` vs `10.1.40.120` boundary),
`forget_mon()`'s editing, that `ceph.sources` renders byte-identical to the file `pveceph
install` writes, every `osd_state` decision against the real CRUSH tree (an OSD present, the
empty bucket, no bucket, a preserved OSD out and down), the device preparation with the stub
logging its argv (an empty disk untouched, with or without the flag; a disk in use refused
without the flag; with the flag zapped once, on that device, then re-checked; a zap that
changes nothing failing), every
`mds_state` decision (stale, member, clean with the `vm-host-020` boundary, listed and so
never stale), and `forget_mds()`'s editing. One case is structural rather than behavioural:
that `pve_node_ceph_manage_mon` gates exactly the four monitor tasks and no mgr, mds or OSD
task, asserted from the parsed `create_ceph_services.yaml` because that file cannot be driven
on the control node at all — three of its tasks are `ansible.builtin.systemd_service`, two
shell out to a bare `systemctl` that is not behind a command variable, and one reads
`/proc/self/mountinfo`. Each new case was shown to go red under a code mutation before it
counted (2026-09-08; the mon-gate case on 2026-09-10, once per gate and once for the default;
the six daemon-version cases on 2026-09-10, six mutations — stray check disabled, empty report
allowed, codename read instead of the version, the clusterless skip removed, the `overall` rollup
left in, and only the first daemon type compared — each killing a different case).

Not covered, on purpose: `pveceph` itself, the join and up/in waits, OSD activation, and the
`forget_*.yaml` actions — those are verified live by the waits failing when a daemon does not
join.
