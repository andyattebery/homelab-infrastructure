# pve_ceph_upgrade

The Proxmox rolling Ceph major upgrade as a playbook with Ceph's own JSON as the gate between
steps. The role holds one task file per phase; `playbook-prod-proxmox-cluster-ceph-upgrade.yaml`
sequences them with `serial: 1` where the wiki says "one node at a time".

## Status: Production — ran 2026-09-08, squid → tentacle on the prod cluster

Completed in ~20 minutes; every gate held. Two defects surfaced on that run and were fixed in
the role afterwards: `restart_osd.yaml` now resets each OSD unit's start-limit counter before
restarting (a recent boot had spent osd.2's budget and the restart died with
`start-limit-hit`), and `finalize.yaml`'s last health check no longer defines its allow-list
in terms of itself (a template loop that failed the final task after every action had run).
The fixture suite covers both paths' decision logic now; the restart itself is still live-only.

## What it encodes

[Ceph Squid to Tentacle](https://pve.proxmox.com/wiki/Ceph_Squid_to_Tentacle) (read
2026-09-08), which this cluster violates in two ways the playbook accounts for: one node may
already be on the target release (vm-host-02 was installed on tentacle by mistake), and a node
may have no monitor in the monmap (that mon had been removed). Restarts skip what is not
there; version gates accept either release until the phase that finishes it.

| Play | Role task file | Gate |
|---|---|---|
| Preflight (all nodes) | `preflight_node.yaml` | `pve-manager` ≥ `pve_ceph_upgrade_min_pve_manager`; `ceph -v` is the source or the target |
| Preflight (runner) | `preflight_cluster.yaml` → `assert_min_mon_release.yaml`, `assert_versions.yaml`, `assert_health.yaml` | `min_mon_release_name` is the source (or already the target — a re-run); every daemon on source or target; `pvecm status` quorate; health allow-listed |
| noout | `osd_flag.yaml` | — |
| Packages (all nodes, parallel) | `packages.yaml` → `pve_node_ceph/tasks/repo.yaml` | `ceph -v` is the target afterwards |
| Monitors (`serial: 1`) | `restart_mon.yaml` | this mon back in `quorum_names`, quorum size = monmap size |
| Verify monitors (runner) | `assert_min_mon_release.yaml`, `assert_versions.yaml` | `min_mon_release_name` is the target; every mon on it |
| Managers (`serial: 1`) | `restart_mgr.yaml` | `mgr dump` `available`, this mgr listed |
| OSDs (`serial: 1`) | `restart_osd.yaml` | `num_up_osds == num_osds`; every PG `active+clean` |
| MDS | `mds_prepare.yaml`, `mds_wait_state.yaml`, `mds_restore.yaml` | one active per fs; standbys down; active back; standbys back; settings restored |
| Finalize (runner) | `finalize.yaml` | every daemon on the target; `require-osd-release`; `noout` unset; health |

## Required inputs

### `pve_ceph_upgrade_from`

The release every node runs today — `-e pve_ceph_upgrade_from=squid`. The playbook refuses to
guess the source. Wrong value: `preflight_cluster` fails on `min_mon_release`.

### `pve_ceph_release`

The target, from the cluster's `group_vars` — the same variable `pve_node_ceph` installs and
guards on. Flip it to the target in the same change as running this playbook; between the flip
and the end of the run the main playbook refuses every node at `pve_node_ceph`'s release guard,
which is intended.

### `pve_cluster_designated_runner`

The node that runs the cluster-wide checks and commands (the same convention as the main
playbook).

## Optional inputs

### `pve_ceph_upgrade_allowed_health_checks`

Default `[OSDMAP_FLAGS]` — the `noout` the upgrade itself sets. `HEALTH_OK`, or `HEALTH_WARN`
whose checks are all in this list, passes; anything else stops the run with
`ceph health detail` in the message. Extending it is a decision: pass
`-e '{"pve_ceph_upgrade_allowed_health_checks": ["OSDMAP_FLAGS", "BLUESTORE_SLOW_OP_ALERT"]}'`
only for a warning already judged benign (osd.0's slow ops on 2026-09-08 were the known-slow
960 PRO). The final health check drops `OSDMAP_FLAGS` from the list, since `noout` is unset by
then.

### `pve_ceph_upgrade_min_pve_manager`

Default `9.1.4`, the wiki's prerequisite for Tentacle. Edit for the next major.

### Wait budgets

`pve_ceph_upgrade_wait_retries` × `pve_ceph_upgrade_wait_delay` (60 × 5 s) for mon/mgr/mds;
`pve_ceph_upgrade_osd_wait_retries` × `pve_ceph_upgrade_osd_wait_delay` (120 × 10 s) for OSDs,
which re-peer after a restart. A wait that runs out fails the play with the task name saying
what did not happen.

### `pve_ceph_upgrade_ceph_command`, `…_pveversion_command`, `…_pvecm_command`

Overridable for the stubs in `tests/test.yml`.

## Example

```sh
cd ansible
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-ceph-upgrade.yaml \
  -e pve_ceph_upgrade_from=squid
```

with `pve_ceph_release: tentacle` in `group_vars/prod_proxmox_cluster/vars.yaml` and
`watch ceph -s` open on a node.

## Failure leaves `noout` set — on purpose

A failed step stops the run before the next node is touched, with `noout` still set so nothing
is marked out while you look. Fix the cause and re-run the whole playbook **with the same
arguments**: preflight accepts a cluster already past the monitor phase, every play re-reads
state, restarts are harmless to repeat one node at a time, and the last play clears the flag.
Do not `ceph osd unset noout` by hand mid-way.

## What is not this playbook's job

- **Recreating a monitor** that is missing from the monmap. Run
  `playbook-prod-proxmox-cluster.yaml --limit <node>` afterwards; `pve_node_ceph` forgets the
  stale state and creates it, now that `min_mon_release` allows the new release.
- **Rebooting** into a kernel that `apt full-upgrade` pulled in. `packages.yaml` reports
  `/var/run/reboot-required`; the main playbook reboots one node at a time on its next run.
- **Choosing the release.** That is `pve_ceph_release`.
- **Migrating cephx keys off the `aes` cipher.** Ceph 20.2.4 adds `AUTH_INSECURE_*` health
  checks that this playbook does not clear and is not affected by — two of them are
  `HEALTH_ERR`, so its own health gate would refuse to start a later upgrade until they are
  dealt with. That is `playbook-prod-proxmox-cluster-cephx-migration.yaml` and
  [pve_cephx_migration](../pve_cephx_migration/README.md).

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_ceph_upgrade/tests/inventory roles/pve_ceph_upgrade/tests/test.yml
```

Stub `ceph`/`pveversion`/`pvecm` answering with output captured from the real cluster on
2026-09-08 (the mixed squid/tentacle `ceph versions`, the `BLUESTORE_SLOW_OP_ALERT` health,
the `cephfs` mdsmap). Covers: node preflight (pass; old `pve-manager` refused; source equal to
target refused), the health gate (slow ops refused by default, allowed on purpose, `noout`
alone passes, `HEALTH_OK` passes), the version gate (mixed accepted mid-upgrade, stragglers
named with counts, a finished cluster passes, a silent daemon type refused rather than passed
vacuously), cluster preflight (pass; monitors already past the source refused), and the MDS
plan (settings recorded, active/standby found, the two `fs set` calls, restore puts back
exactly what was recorded). **Not covered, on purpose:** the restart and wait loops. They run
only against the real cluster, with `ceph -s` open.
