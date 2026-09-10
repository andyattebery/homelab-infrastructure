# pve_node_rebuild

Rebuilding one node of a Proxmox VE + Ceph cluster — boot drive replaced, OSD disk kept or
replaced — as playbook phases. The role holds one task file per phase and the decisions they
rest on; `playbook-prod-proxmox-cluster-node-rebuild.yaml` sequences them by `--tags`, and the
main playbook (`playbook-prod-proxmox-cluster.yaml --limit <node>`) does the converge in the
middle. The runbook is `docs/proxmox_node_reinstall.md`.

## Status: Fixture-tested, not yet run live

Written 2026-09-08 from the vm-host-02 rebuild of 2026-09-07, which was done by hand and cost a
console outage, a cluster file edited by regex and a node on the wrong Ceph major. Every step
of that day is here, sequenced and asserted. The first live run is vm-host-01's rebuild.

| Phase | `--tags` | Runs on | Task files |
|---|---|---|---|
| 0 preflight | `preflight` | survivor | `state.yaml`, `preflight.yaml` |
| 1 teardown | `teardown` | localhost, node, survivor | + `backup.yaml`, `cluster_prepare.yaml`, `evacuate.yaml`, `remove_services.yaml`, `remove_node.yaml` |
| 2 physical swap, 3 installer | — | hands | — |
| 4 bootstrap | `bootstrap --ask-pass` | localhost, node as root | `bootstrap_known_hosts.yaml`, `bootstrap_node.yaml` |
| 5 converge | the main playbook | node | `pve_node_ceph` and the rest |
| 6 finish | `finish` | survivor, node | `state.yaml`, `finish.yaml` (+ `measure_recovery.yaml`), `load_plan.yaml`, `verify.yaml` |

The **survivor** — the node that runs cluster-side commands — is derived by the playbook as
the first other member of the cluster group, never assumed: `pve_cluster_designated_runner`
will be rebuilt one day too.

## Required inputs

Passed with `-e`; the playbook refuses to guess any of them.

### `rebuild_node`

Inventory hostname of the node being rebuilt. Not a member of
`pve_node_rebuild_cluster_group`: the playbook's first play fails.

### `rebuild_osd`

`preserve` — the OSD disk survives the rebuild: `noout` and `norebalance` are set, the OSD is
marked out and its unit stopped, and the finish clears the flags once `pve_node_ceph`'s
`activate_existing` has it up and in again. `replace` — the OSD is destroyed
(`pveceph osd destroy --cleanup 1`, which zaps the old disk) and the rebuilt node creates a new
one; neither flag is set, since `norebalance` would block the backfill this variant exists to
cause. Any other value: refused by preflight.

### `rebuild_evacuate_to`

Where the guests HA does not manage go — stopped VMs and templates included, which
`node-maintenance` never touches. Required only when the node carries any; preflight names
them and refuses otherwise. Must be another online member of the cluster group.

### Read from the inventory

`pve_ceph_release` (verify: every daemon on it), the node's `pve_pin_network_interface_pins`
(verify: each name carries its MAC), `install_realtek_r8125` and
`kernel_parameters_new_parameters` (verify: `dkms status`, `/proc/cmdline`), `vault_ansible_user`
(bootstrap: the user it creates — read directly, because that play runs as root and shadows
`ansible_user`), and `domain_name` from the node's hostvars (bootstrap: the FQDN whose stale
host key is forgotten).

## Optional inputs

### `rebuild_node_dead` (default `false`)

`true` acknowledges a node that no longer answers: the node-side plays are skipped and the
survivor removes its daemons raw — `ceph mon remove`, `ceph auth del` for the `mds.<node>` and
`mgr.<node>` entities (what `pveceph mds destroy` and `mgr destroy` end with,
`PVE::Ceph::Services` 354-359 and 429), `ceph osd out`, and `ceph osd purge` for `replace`;
the leftovers in ceph.conf are what `pve_node_ceph` forgets on the rebuilt node.
Guarded twice: preflight refuses the flag on a node that is online, and the teardown refuses a
node that answers the probe while the flag is set — a wrong flag against a merely slow node
would remove a live monitor. Guest configs left on a dead node are never moved by the play;
it refuses and names them (PVE's dead-node recovery, by hand, at the console).

### `rebuild_resume` (default `false`)

Acknowledges that this node's own teardown already ran part way, so preflight tolerates the
degradation that teardown caused — and nothing else.

A teardown that stops after `ceph osd out` leaves the cluster HEALTH_OK but with the node's OSD
out and its PGs `active+clean+remapped`. Preflight's health gate then refuses to re-run, because
it cannot tell damage it inflicted from damage that was already there. Without this flag the
teardown is not re-runnable after a partial failure, which is exactly when you need it to be.

With it, each clause widens by a measured amount and no more:

| clause | widened to | still fatal |
| --- | --- | --- |
| PGs `active+clean` | also `active+clean+remapped` | any PG not active, undersized, degraded, peering |
| no recovery | any, **because the row above already decides it** | a degraded or backfilling PG — no such state is in the allowed list |
| every OSD `in` | short by exactly this node's out-OSDs | an OSD out that belongs to another node |
| every OSD `up` | short by exactly this node's down-OSDs | a down OSD elsewhere |

The last two are the load-bearing ones: the shortfall must equal *this node's* count, so another
node's OSD going out while you resume is still refused. Pass it to resume a teardown you started.
Do not pass it to get past degradation you cannot account for — that is the failure the health
gate exists to prevent, and the flag does not disable it.

`ha-manager`'s monitor check is separate and needed no flag: "quorum survives one monitor fewer"
is now asserted only when the node still *has* a monitor to remove, since a teardown that removes
none cannot cost quorum.

### `rebuild_local_content` (default `keep`)

The pre-wipe backup copies `/etc/pve`, `/etc/ssh`, `/root/.ssh`, `/etc/network` and the apt
sources — not `/var/lib/vz`. Preflight lists what the node's `local` storage holds and refuses
while it is not empty unless this is `discard`. vm-host-01's `local` is empty (2026-09-08).

### `rebuild_measure_recovery` (default `false`), `rebuild_measure_minutes` (default `10`)

`replace` only. Before waiting for the backfill, sample `ceph -s` every
`pve_node_rebuild_measure_interval` seconds (30) for the given minutes under the current
mClock profile, switch to `high_recovery_ops`, sample again, and restore the profile in an
`always:` whatever happened. The rows land as CSV at `pve_node_rebuild_measure_csv_path`
(`tasks/<node>-recovery-<stamp>.csv`, gitignored) and both means are printed. Pass it for
vm-host-01: a full backfill is the one clean chance to measure that the profile, not the
network, sets the recovery rate.

### `rebuild_return_guests` (default `false`)

Finish: migrate the guests that left back from `rebuild_evacuate_to`. Off by default because
where a guest lives is a decision. Needs the plan the teardown's preflight recorded at
`pve_node_rebuild_plan_path` (`tasks/<node>-rebuild-plan.json`); without it the return is
refused rather than guessed.

### `rebuild_bootstrap_pubkey`, `rebuild_known_hosts_path`

The key the bootstrap authorizes for the automation user (default: the control node's
`~/.ssh/id_ed25519.pub`) and the known_hosts file whose stale entries it removes (default
`~/.ssh/known_hosts`; a non-default `UserKnownHostsFile` in the ssh config is yours to pass —
the role does not read that file).

### `rebuild_backup_root` (default `~/pve-backups`)

Where `scripts/pve-pre-wipe-backup.sh` writes. Outside the repo on purpose: the tarball holds
cluster keys and root's SSH keys.

### `pve_node_rebuild_allowed_health_checks` (default `[]`)

Health checks that may be present without blocking preflight or finish. Empty means only
`HEALTH_OK`. Extend with `-e '{"pve_node_rebuild_allowed_health_checks": ["..."]}'` for a
warning already judged benign; PGs that are not `active+clean` are refused regardless.

### Wait budgets

`pve_node_rebuild_wait_retries` × `pve_node_rebuild_wait_delay` (60 × 5 s) for the HA moves,
the node going offline, the guest directory emptying and HA bringing resources back;
`pve_node_rebuild_backfill_wait_minutes` (180) for every PG `active+clean` with no recovery.
A wait that runs out fails the play with the JSON it last read.

### `pve_node_rebuild_cluster_group` (default `prod_proxmox_cluster`)

The inventory group that is the cluster.

### Paths and commands

`pve_node_rebuild_pve_nodes_dir`, `…_ceph_conf_path`, `…_cmdline_path`, `…_sys_net_dir`,
`…_running_kernel`, `…_plan_path`, `…_measure_csv_path`, `…_backup_script`,
`…_migrate_delegate`, `…_return_delegate` and the `…_<cli>_command` variables exist so
`tests/test.yml` can run every decision against stubs and a tempdir. `qm`, `ha-manager`,
`pvecm`, `pvesh`, `systemctl` and `dkms` default to bare names — the plays run with become,
whose PATH has `/usr/sbin`; `ceph` and `pveceph` are the absolute paths `pve_node_ceph` uses.

## Example

vm-host-01, OSD replaced, non-HA guests to vm-host-02, with the measurement:

```sh
cd ansible
P=playbook-prod-proxmox-cluster-node-rebuild.yaml
V="-e rebuild_node=vm-host-01 -e rebuild_osd=replace -e rebuild_evacuate_to=vm-host-02"
.venv/bin/ansible-playbook $P $V --tags preflight
.venv/bin/ansible-playbook $P $V --tags teardown
# swap the drives; PVE installer with the pin names in its Options dialog
.venv/bin/ansible-playbook $P $V --tags bootstrap --ask-pass
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster.yaml --limit vm-host-01
.venv/bin/ansible-playbook $P $V --tags finish -e rebuild_measure_recovery=true
```

## What each phase asserts

**Preflight** (`preflight.yaml`, read-only): the inputs; quorate; node online or its death
acknowledged (and not both); `HEALTH_OK` or only allowed checks, every PG `active+clean`, no
recovery, every OSD up and in; at least three monitors (losing one keeps a majority); at most
one OSD on the node; every non-HA guest has a destination; no guest disk on a storage the node
does not share (`(ide|sata|scsi|virtio)N`, `efidisk0`, `tpmstate0`, `unusedN`; `none,media=cdrom`
is not a volume); `local` empty or its loss acknowledged. Then it prints what the teardown will
do and records the plan on the control node.

**Teardown**: the probe decides reachable or dead, and the acknowledgement must match. Reachable:
backup → flags (`preserve`) → `node-maintenance enable` and wait for HA to move everything →
`qm migrate <vmid> <target> --online` per non-HA guest in vmid order (`--online` is ignored
for a stopped guest, so it is always passed) → wait for the node's `qemu-server/` to empty →
on the node: `ceph mds fail` if its MDS is active (immediate standby takeover), `pveceph mds
destroy`, `pveceph mgr destroy`, `pveceph mon destroy` (from the node: destroymon takes the
address to drop from `mon_host` out of the monmap, which it can only do while the monitor is
in it), `ceph osd out`, then `preserve`: `systemctl stop`/`disable ceph-osd@<id>`; `replace`:
`ceph osd ok-to-stop`, `pveceph stop --service osd.<id>`, `pveceph osd destroy <id> --cleanup 1`;
`systemctl poweroff` → on the survivor: wait until offline, refuse if `qemu-server/` still holds
a config, `pvecm delnode`, assert quorate without the node, remove `/etc/pve/nodes/<node>`.
Dead: no backup, no evacuation, no node-side play; the survivor does `ceph mon remove`,
`ceph auth del` for the MDS and manager entities, `ceph osd out` (+ `purge` for `replace`)
before `delnode`. No `ceph osd crush rm`:
`pve_node_ceph`'s create gate ignores an empty bucket.

**Bootstrap**: the control node forgets the node's old host key under its short name, FQDN and
address; then as root on the node: `apt-get update` (allowed to fail on the enterprise
repository — the Debian lists it also fetched are all `sudo` needs), `sudo`, the automation
user in group `sudo`, the bootstrap key, `/etc/sudoers.d/90-ansible` validated with `visudo`.
The root password comes from `--ask-pass` through the builtin `ssh` connection: ansible-core
2.19+ defaults `password_mechanism` to `ssh_askpass`, so neither `sshpass` nor paramiko is
needed (ansible-core 2.21 ships no paramiko plugin). `StrictHostKeyChecking=accept-new`
records the new key and still refuses a changed one. Run it from a terminal: the prompt is
interactive.

**Finish**: assert the node is online with its OSD up and in (that is `pve_node_ceph`'s job;
the message says so), clear the flags (`preserve`), measure on request, wait for every PG
`active+clean` with no recovery, `node-maintenance disable`, wait for HA to bring back every
resource whose rule prefers the node (`pvesh get /cluster/ha/rules`: the node with the highest
priority in a `node-affinity` rule's `nodes`), migrate the recorded non-HA guests back on
request, final health. Then on the node, `verify.yaml`: V1 quorate with every node online, V2
health, V3 OSD up and in, V4 one active MDS and a standby per other node, V5 every daemon on
`pve_ceph_release`, V6 a `[mon.<node>]` section per node, V7 the r8125 DKMS line for the running
kernel, V8 `intel_iommu=on`, V9 every enabled storage active (`local-lvm` excepted: `maxvz 0`),
V10 the ACME certificate, V11 the rule-preferred HA resources started here, V12 the returned
guests present, V13 every pinned name carries its MAC.

## Live-only

Not exercised by the fixture suite: `wait_for_connection`, the pre-wipe script, the destroys and
migrations actually happening, `pvecm delnode`, the paramiko-free bootstrap, the backfill wait
and the measurement's timing. Each is asserted by what follows it — a destroy that did not
happen fails the offline wait or the delnode; a migration that did not happen fails the
`qemu-server/` wait; a bootstrap that did not take fails the main playbook's first task.

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_node_rebuild/tests/inventory roles/pve_node_rebuild/tests/test.yml
```

Localhost only; stub `ceph`, `pvesh`, `qm`, `ha-manager`, `pvecm`, `pveceph`, `systemctl`
and `dkms` answering with JSON captured from the cluster on 2026-09-08 (vm-host-01's real guest
set, HA resources and rule, storages, CRUSH tree, osdmap) and logging every argv. Covers:
preflight on vm-host-01 as it is and every refusal (no destination, offline without or with
the acknowledgement, two OSDs, a disk on `local-lvm`, content on `local`, `HEALTH_WARN` unless
allowed, a backfill in progress, two monitors); the flags only for `preserve` and only when
unset; evacuate's exact argv in vmid order and its HA wait failing before any migration; the
two teardown command sets on the node, and a standby MDS destroyed without a `fail`; the
node-removal guard, the reachable branch and both dead branches; finish for `preserve`, for
`replace` with the guest return, refused with the OSD out and refused without the recorded
plan; the sampler's argv, means and CSV, and the profile restored after a failing `ceph -s`;
verify green on the capture and one mutation per assertion. The constructed fixtures — a
backfill in progress, an offline node, the post-delnode membership — carry the key names Ceph
and PVE document; everything else is a capture.
