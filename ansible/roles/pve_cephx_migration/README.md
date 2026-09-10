# pve_cephx_migration

Proxmox's cephx key migration — `aes` → `aes256k`, the remedy for the `AUTH_INSECURE_*` health
checks Ceph 20.2.4 / 19.2.6 added for CVE-2025-30156 — as a playbook with gates. The rotation
itself is done by Proxmox's own helper, `pve-cephx-rotate-service-keys`; this role supplies the
preflight, the health allow-list, the post-conditions, and the client refresh, and
`playbook-prod-proxmox-cluster-cephx-migration.yaml` sequences them one phase per run.

## Status: Production — ran 2026-09-10, all four phases, prod cluster HEALTH_ERR → aes256k-only

Completed in ~25 minutes of wall clock across four separate invocations. Every gate held and no
client lost access. Two defects surfaced on the live runs and were fixed in the role afterwards:

- **Stage 1** failed its last task on `'pve_cephx_migration_apply' is undefined` — a dynamic
  `include_role` does not put role defaults in scope for a playbook-level `when:`. The gate moved
  into `assert_checks_cleared.yaml`. (An include's `vars:` do *not* have this problem; they are
  templated inside the include.)
- **Stage 3** failed on `FAIL: '--confirm-all-clients-refreshed' ... needs '--apply'` —
  `run_helper.yaml` dry-ran every selection first, and the helper refuses to evaluate the confirm
  flags without `--apply`. Hence `pve_cephx_migration_dry_run_first`. The fixture stub had been
  more permissive than the real helper, so the suite was green while the role could not run its
  own last phase; the stub now enforces the rule.

Both are covered by fixture cases with positive controls. The suite is green: 175 assertions,
13 positive controls.

## What it encodes

[Migrate Cephx Keys from `aes` to `aes256k`](https://pve.proxmox.com/pve-docs/chapter-pveceph.html#pveceph_cephx_migration)
(read 2026-09-10). The helper is stateful, drives the whole cluster over SSH from one node, and
journals to `/etc/pve/priv/cephx-key-migration.json`. So this role does not re-implement any of
it — the value added is everything around the invocation.

| Tag | Role task file | Helper options | Gate afterwards |
|---|---|---|---|
| `always` | `preflight_node.yaml` (all nodes), `preflight_cluster.yaml` (runner) | — | versions, kernel, helper present; quorate; one Ceph release; health allow-list |
| `status` | `status.yaml` | *(none — the state report)* | — |
| `stage1` | `run_helper.yaml`, `assert_checks_cleared.yaml` | `--rotate-cluster-keys` | `AUTH_INSECURE_SERVICE_KEY_TYPE` and `AUTH_INSECURE_SERVICE_TICKETS` absent |
| `stage2` | `run_helper.yaml` | `--rotate-all-storage-keys --rotate-admin-key` | — (keys are *staged*; both remain valid) |
| `refresh` | `refresh_clients.yaml` → `refresh_ha_node.yaml`, `refresh_migrate_guest.yaml`, then `status.yaml` | *(none)* | helper reports no session on an old key |
| `stage3` | `confirm_and_restrict.yaml`, `assert_checks_cleared.yaml` | `--confirm-all-clients-refreshed --restrict-ciphers` | `AUTH_INSECURE_CLIENT_KEY_TYPE`, `..._KEYS_ALLOWED`, `..._KEYS_CREATABLE` absent |

## Required inputs

### `pve_ceph_release`

The cluster's Ceph release, from `group_vars/prod_proxmox_cluster/vars.yaml` — the same variable
`pve_node_ceph` installs and guards on. `preflight_node` refuses a node whose `ceph -v` codename
differs, which is how this playbook avoids being pointed at a cluster the repo does not manage.
Wrong value: every node fails preflight naming both strings.

### `pve_cluster_designated_runner`

The single node the helper runs on. The helper drives the whole cluster over SSH and its own
`--help` says "run it once"; a second concurrent run waits on the cluster lock and then gives up.

## Optional inputs

### `pve_cephx_migration_apply`

Default `false` — **the safety catch**. False means every phase prints its plan and changes
nothing. Pass `-e pve_cephx_migration_apply=true` on the run that is meant to act. There is no
way to make a phase act by accident, and the dry run happens on the apply run too, so the log
always contains the plan that was carried out.

### `pve_cephx_migration_min_pve_manager`, `..._min_ceph_package`, `..._min_kernel`

Defaults `9.2.17`, `20.2.4-pve3`, `7.0`. Two distinct Ceph minimums exist and the docs keep them
apart: `-pve3` is what staging a client key with both credentials valid needs; `-pve4` adds
per-session key fingerprints, which is what lets a rollback confirm without disconnecting every
client of a shared user first. The role requires `-pve3` and the prod cluster runs `-pve4`.
Too-low values are refused per node, naming the version found and the minimum.

### `pve_cephx_migration_allowed_health_checks`, `..._allowed_error_checks`

Default: the six `AUTH_*` checks, of which two may be `HEALTH_ERR`. This is the one place the
role deliberately differs from `pve_ceph_upgrade`'s health gate — that one refuses `HEALTH_ERR`
outright, and this migration *starts* from it. A third ERR check stops the run naming it.

### `pve_cephx_migration_blocker_patterns`

Default `[]`, and the check is skipped while it is empty. See the comment on the variable: a
pattern list invented from the helper's `--help` is theater — `"blocker"` matches
`"No blockers found"`. The helper's own refusals are the real gate. Calibrate this from a dry
run that was actually read.

### `pve_cephx_migration_stage1_args`

Default `['--rotate-cluster-keys']`. See "The one thing the docs do not settle" below.

### Wait budgets and command paths

`..._wait_retries` × `..._wait_delay` (60 × 5 s) for health checks; `..._migrate_retries` ×
`..._migrate_delay` (120 × 10 s) for guest migrations; `..._command_timeout` (3600 s) for the
helper itself. `..._ceph_command`, `..._pveversion_command`, `..._pvecm_command`,
`..._pvesh_command`, `..._rbd_command`, `..._ha_manager_command`, `..._qm_command`,
`..._helper_command` and `..._kernel` are overridable for the stubs in `tests/test.yml`.

## Example

```sh
cd ansible
# read the plan
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-cephx-migration.yaml --tags stage1
# carry it out
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-cephx-migration.yaml --tags stage1 \
  -e pve_cephx_migration_apply=true
```

with `watch ceph -s` open on a node. Then `stage2`, `refresh`, `stage3` the same way.

## One phase per run, and no tag that runs them all

`--tags` is required: a run that names no phase, or more than one, is refused by the first task
in the playbook. This is structural, not advice — `stage3` is irreversible, and `stage2` stages a
key that every client must be refreshed onto before `stage3` retires the old one. A pipeline that
could reach `stage3` from a cold start would be the wrong shape for this work.

## `--force` is unreachable

The helper's `--force` overrides the blockers that stop `--restrict-ciphers` cutting off a live
client and locking administration out. The role constructs no such flag, has no variable for it,
and `run_helper.yaml` refuses a caller that puts one in `pve_cephx_migration_args`. If a blocker
is genuinely wrong, the dry run names it and the cause gets fixed instead.

## `--apply` always carries `--assume-yes`

From the helper's own `--help`: "`--apply` needs this when standard input is not a terminal."
Ansible's `command` module has no TTY. `run_helper.yaml` appends both together, always — a
fixture case asserts it and goes red if the pair is split.

## The one thing the docs do not settle

The docs say `--rotate-cluster-keys` rotates "the manager, metadata server, OSD, monitor,
bootstrap, crash, and encrypted OSD lockbox keys". `--help` also lists a separate
`--rotate-client-keys` for "the `client.bootstrap-*` keys and `client.crash`". Whether the first
subsumes the second is not answerable from either text.

**The stage-1 dry run answers it.** If its plan does not name all six `client.bootstrap-*` keys
and `client.crash`, re-run stage 1 with both:

```sh
-e '{"pve_cephx_migration_stage1_args": ["--rotate-cluster-keys", "--rotate-client-keys"]}'
```

Nothing is lost by finding out this way: a dry run changes nothing, and rotating an
already-rotated key is a no-op ("Reruns do not rotate completed keys again").

## The refresh derives its plan; it is not given one

`refresh_clients.yaml` reads three live sources and writes down no VM ids of its own:

- `pvesh get /storage` — which storages are local Ceph, and which RBD pools. Storages of an
  *external* cluster are excluded on their `monhost` key; the helper never rotates that
  cluster's keys, so their consumers need nothing.
- `rbd -p <pool> ls` — which guests have an image there (`vm-<id>-*`, `base-<id>-*`).
- `pvesh get /nodes/<node>/qemu/<id>/migrate` — whether PVE will actually move that guest.

That last one is why this does **not** grep `qm config` for `hostpci`: PVE's own answer covers
passthrough, unshared local disks and every other check it makes, and its output carries no
guest credentials. A guest PVE will not migrate, and HA does not manage, is **reported and never
touched** — its refresh is a stop and start, which is downtime somebody has to schedule.

HA-managed guests are refreshed by draining their node, not by migrating each one: they have
`failback: true` and a node-affinity rule, so `qm migrate` is refused ("Cannot migrate VM,
because HA resource vm:NNN is not allowed on the selected target node"). The documented route is
`ha-manager crm-command node-maintenance enable <node>` — see `pve_cluster_ha/README.md` and
`pve_node_rebuild/tasks/evacuate.yaml`, whose pattern this follows.

CephFS mounts are not in the plan at all: the helper refreshes idle ones itself and leaves busy
ones alone. If it reports outstanding mounts, re-run the refresh once nothing is using them.

## Two traps that cost a debugging session each

- **A dynamic include's untagged children are filtered out unless `apply:` restates the tag.**
  Verified 2026-09-10 against ansible-core 2.21.3: with `--tags stage1`, an `include_role` tagged
  `stage1` *appears in the output* and its children never run. Every include in the playbook
  therefore carries `apply: {tags: <same>}`. Nesting is fine — the tag propagates from there.
- **`template` is always present in `/cluster/resources`**, `0` for an ordinary guest. So
  `rejectattr('template', 'defined')` rejects every guest and yields an empty refresh plan,
  silently. It must be `rejectattr('template', 'eq', 1)`.

## If it goes wrong

The journal at `/etc/pve/priv/cephx-key-migration.json` is what resumes an interrupted run and
it holds the old keys — **do not delete it** until the migration is finished and every client
refreshed. Run `--tags status` to see where things are and what the helper says to do next.

A staged `client.admin` rolls back with `--abort-staged-key client.admin --apply`, then refresh
the clients back, then `--confirm-abort-clients-refreshed client.admin --apply`. That path is not
wrapped by this role — it is rare, it is per-user, and the helper prints exactly what to run.

If a wrong restriction locks administration out, `mon_auth_emergency_allowed_ciphers` in
`/etc/pve/ceph.conf` plus a monitor restart restores access; SSH does not depend on cephx, so a
root shell is enough. Remove it and restart every monitor before the final dry run, or the helper
refuses to restrict (changing the MonMap would not take effect while it is set).

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_cephx_migration/tests/inventory \
  roles/pve_cephx_migration/tests/test.yml
```

Stub `ceph` / `pveversion` / `pvecm` / `pvesh` / `rbd` / helper answering with output captured
from the real cluster on 2026-09-10 — the six `AUTH_*` checks, the 12-daemon `ceph versions`, the
`/cluster/resources` and `/cluster/ha/status/current` shapes, and both answers PVE gives to the
migrate-feasibility query. 160 assertions, 12 positive controls.

Covered: node preflight (passes; refuses an old `pve-manager`, `ceph 20.2.4-pve2`, a 6.x kernel,
a missing helper, a non-executable helper); the health gate (today's `HEALTH_ERR` accepted, a
third ERR check refused, the post-stage-1 `HEALTH_WARN` accepted); the version gate (one release
passes, a straggler refused, a silent daemon type refused rather than passing vacuously);
`assert_checks_cleared` (cleared passes, still-present refused); `run_helper` (a dry run never
emits `--apply`; an apply always pairs it with `--assume-yes`; `--force` refused; an empty
selection refused); the refresh derivation (pools, guest ids, HA vs non-HA vs unmigratable, and
that a dry run issues nothing but `pvesh get`); and `confirm_and_restrict` (refused while the
helper is not offering the command, and the exact documented command when it is).

**Not covered, on purpose:** what the helper itself does, and the live migrations in
`refresh_ha_node.yaml` / `refresh_migrate_guest.yaml`. Those are verified only against the real
cluster, with `ceph -s` open.
