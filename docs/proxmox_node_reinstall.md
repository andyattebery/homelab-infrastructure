# Proxmox Node Reinstall

Rebuilding one node of the homelab Proxmox/Ceph cluster — boot drive replaced, OSD disk kept
or replaced — with everything after the PVE installer done by playbooks. Two use cases, one
variable: `rebuild_osd=preserve` keeps the OSD disk and its data through the rebuild;
`rebuild_osd=replace` destroys the OSD and creates a new one on a new disk. Every mutation is a
phase of [playbook-prod-proxmox-cluster-node-rebuild.yaml](../ansible/playbook-prod-proxmox-cluster-node-rebuild.yaml)
or of the main playbook; the commands left in this doc are read-only checks or the console-only
recovery at the end.

Why it is shaped this way: vm-host-02 was rebuilt by hand from the previous version of this doc
on 2026-09-07, and every step it left to the operator between playbook runs went wrong — a
console outage from a `.link` file deleted by hand, a cluster-wide `ceph.conf` edited by regex,
an hour of guess-and-check on a monitor that could not join, and a node installed one Ceph
major ahead of its cluster. Each of those is now a task with an assertion.

Fill in `<node>` (the node being rebuilt, e.g. `vm-host-01`), `<survivor>` (any other node) and
`<target>` (where the guests HA does not manage go) below.

## The two use cases

| | `preserve` | `replace` |
|---|---|---|
| OSD disk | stays in the chassis | comes out with the boot drive |
| Teardown | `noout` + `norebalance` set; OSD marked out and its unit stopped | `ceph osd ok-to-stop`, `pveceph stop`, `pveceph osd destroy --cleanup 1` (zaps the old disk) |
| `host_vars` before Phase 5 | unchanged (`pve_node_ceph_osd_mode: activate_existing`) | `pve_ceph_osd_device` = the new disk, `pve_node_ceph_osd_mode: create`, `pve_node_ceph_osd_zap: true` if the disk is not empty |
| Phase 5 | `ceph-volume lvm activate --all`, the OSD marked in, up/in wait | inventory, zap on request, `pveceph osd create`, up/in wait |
| Finish | flags cleared, recovery from the PG logs | full backfill onto the new OSD (measurable) |
| Afterwards | nothing | flip the three `host_vars` back |

Neither flag is set for `replace`: `noout` would protect an OSD that is being destroyed anyway,
and `norebalance` blocks the backfill onto the new OSD — the one data movement the variant
exists to cause. Expect `HEALTH_WARN` with PGs `active+undersized+degraded` while the node is
gone: with `size 3` and three hosts, CRUSH has nowhere to put the third replica.

## Prerequisites

- Cluster `HEALTH_OK`, every PG `active+clean`, all three monitors in quorum. Phase 0 asserts
  every one of these and refuses otherwise.
- The replacement boot drive on hand; for `replace`, the new OSD disk and its **serial** from
  [ssd-inventory.md](../hardware/ssd-inventory.md) — the by-id path is
  `/dev/disk/by-id/ata-<model>_<serial>` (SATA) or `nvme-<model>_<serial>`, and it can be
  written into `host_vars` before the drive is fitted.
- Console / PiKVM access to the node, and the PVE installer USB matching the cluster's major.
- The control node's Ansible venv (`ansible-core` 2.21.3; the bootstrap needs OpenSSH ≥ 8.4,
  which macOS has), `op` for the vault.
- The node's `host_vars` already declare `pve_pin_network_interface_pins` with the names the
  installer's Options dialog will be given.

## Worked example: vm-host-01

Boot Intel DC S3520 150 GB → Intel Optane P1600X 58 GB; OSD `osd.0` on the Samsung 960 PRO →
Intel DC S3610 1.6 TB `BTHC637404T21P6PGN` (`/dev/disk/by-id/ata-INTEL_SSDSC2BX016T4_BTHC637404T21P6PGN`,
still carrying old ZFS labels, so the zap is needed). HA moves `vm:102`, `vm:103`, `vm:110`;
`120`, `1000`, `1001` are not HA-managed and go to vm-host-02. Pins `i219p0` (I219-V → vmbr0)
and `rtl8125p0` (RTL8125 → Ceph). `install_realtek_r8125: true`, so Phase 5 reboots once for
the r8125 module's kernel. Pass `-e rebuild_measure_recovery=true` in Phase 6: a full backfill
on a known network is the one clean chance to measure the mClock profiles.

Every command below spells itself out, so each one can be copied on its own without having
first run a setup block. Substitute:

| placeholder | for this rebuild |
|---|---|
| `<node>` | `vm-host-01` |
| `<target>` | `vm-host-02` |
| `<osd-mode>` | `replace` |

```sh
cd ansible
```

## Phase 0 — Preflight (read-only)

```sh
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-node-rebuild.yaml \
  -e rebuild_node=<node> -e rebuild_osd=<osd-mode> -e rebuild_evacuate_to=<target> \
  --tags preflight
```

Runs on a survivor and asserts, in this order: the inputs; the cluster is quorate; the node is
online (or its death is acknowledged with `-e rebuild_node_dead=true`, and never both); Ceph is
`HEALTH_OK` (or only warnings in `pve_node_rebuild_allowed_health_checks`), every PG
`active+clean`, no recovery, every OSD up and in; at least three monitors; at most one OSD on
the node; every guest HA does not manage has a destination (`rebuild_evacuate_to`, another
online member); no guest disk on a storage the node does not share; the node's `local` storage
is empty or its loss is acknowledged (`-e rebuild_local_content=discard` — the pre-wipe backup
does not copy `/var/lib/vz`). Then it prints what the teardown will do and writes the plan to
`tasks/<node>-rebuild-plan.json` on the control node.

| It refuses with | Do |
|---|---|
| "carries guests HA will not move: 120 …" | add `-e rebuild_evacuate_to=<target>` |
| "offline in the cluster" | bring the node up, or `-e rebuild_node_dead=true` if it is really gone |
| "Ceph is HEALTH_WARN … PGs clean: False" | wait for recovery, or allow a warning already judged benign with `-e '{"pve_node_rebuild_allowed_health_checks": ["…"]}'` |
| "disks on storages that are not shared" | move those disks to `pve_pool` first |
| "`local` storage holds …" | copy what matters off, or `-e rebuild_local_content=discard` |
| "holds [0, 3]" (two OSDs) | not this playbook's case |

## Phase 1 — Teardown

Your go, then:

```sh
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-node-rebuild.yaml \
  -e rebuild_node=<node> -e rebuild_osd=<osd-mode> -e rebuild_evacuate_to=<target> \
  --tags teardown
```

Add `-e rebuild_resume=true` if a previous teardown of this node stopped part way — preflight
otherwise refuses, on the degradation that teardown itself caused. See
[the role README](../ansible/roles/pve_node_rebuild/README.md#rebuild_resume-default-false).

In order — preflight again; the node is probed (30 s); the pre-wipe backup
(`scripts/pve-pre-wipe-backup.sh`) lands in `~/pve-backups/<node>-<stamp>/` — treat it as a
credentials dump; `preserve` only: `noout` and `norebalance`; `ha-manager crm-command
node-maintenance enable <node>` and a wait until no HA resource is on the node; `qm migrate
<vmid> <target> --online` for each non-HA guest, in vmid order, from the node (templates
migrate offline; `--online` is ignored for a stopped guest); a wait until
`/etc/pve/nodes/<node>/qemu-server/` is empty; then on the node: `ceph mds fail <node>` if its
MDS is active, `pveceph mds destroy`, `pveceph mgr destroy`, `pveceph mon destroy` (from the
node, the one place `destroymon` can also drop the address from `mon_host`), `ceph osd out`,
and `preserve`: `systemctl stop`/`disable ceph-osd@<id>`; `replace`: `ceph osd ok-to-stop`,
`pveceph stop --service osd.<id>`, `pveceph osd destroy <id> --cleanup 1`; `systemctl
poweroff`. Then from the survivor: wait until the node is offline, refuse if `qemu-server/`
still holds a config, `pvecm delnode <node>`, assert quorate, remove `/etc/pve/nodes/<node>`.

**Dead node** (`-e rebuild_node_dead=true`, and the probe must agree): no backup, no evacuation,
nothing node-side. HA has already fenced it and recovered its resources; the survivor does
`ceph mon remove`, `ceph auth del` for the MDS and manager entities (what the destroys would
have done), `ceph osd out` (and `ceph osd purge` for `replace`) before `delnode`. The
leftovers in ceph.conf — `[mon.<node>]`, its `mon_host` entry, `[mds.<node>]` — are forgotten by
`pve_node_ceph` on the rebuilt node; nothing is edited by hand. Guest configs a dead node still
owns are named and the play stops: moving a config is PVE's dead-node recovery, by hand, at
the console, and only for a node that is certainly off.

Read-only while it runs, on any node: `watch ceph -s`.

## Phase 2 — Physical swap

Replace the boot drive. `replace`: the OSD disk comes out too. `preserve`: leave it alone. Keep
every pulled drive on the shelf until Phase 6 passes — they are the rollback. Boot to BIOS and
confirm the drives are detected.

## Phase 3 — PVE installer

Boot the PVE installer USB matching the cluster's major (PVE 9.x).

**Hard Disk** — Advanced LVM options, for a 58 GB Optane boot drive (the values vm-host-02 was
installed with on 2026-09-07, and what they produced):

| Field | Value | Result on vm-host-02 |
|---|---|---|
| Disk | the new boot drive only — never the OSD disk | |
| Filesystem | `ext4` | |
| `hdsize` | full | |
| `swapsize` | `4` | 4 GB swap |
| `maxroot` | `40` | root **24.6 GB** — the installer caps it |
| `maxvz` | `0` | no `local-lvm` data volume (the guests live on Ceph); 25.8 GB left free in the VG |
| `minfree` | default | |

Growing root later is `lvextend` on that free space — a follow-up, not this doc's job. On a
larger boot drive `maxroot 80` fits as before.

**Network**: the management NIC — the Dell onboard (MAC OUI `a4:bb:6d`). The Ceph NIC is
configured by the playbook.

**Interface pinning**: keep it enabled and open **Options**: name each interface as the node's
`pve_pin_network_interface_pins` says, matched by MAC. Then nothing is renamed after install
and the playbook's pinning role is a no-op. If this ISO has no such dialog, leave the `nicN`
defaults — the playbook re-pins to the final names as its first task and reboots once for it.
**Never delete the installer's `.link` files by hand**; that is the console-only outage of
2026-09-07 (recovery at the end of this doc).

Hostname / IP / gateway / DNS: match the existing host_vars and DNS records.

## Phase 4 — Bootstrap

From a terminal — the prompt is interactive, and the root password never goes anywhere but ssh:

```sh
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-node-rebuild.yaml \
  -e rebuild_node=<node> -e rebuild_osd=<osd-mode> -e rebuild_evacuate_to=<target> \
  --tags bootstrap --ask-pass
```

The connection user is set to `root` by the play itself, so do not pass `-u`/`-e ansible_user`:
play vars outrank `group_vars/all`, and the override is already there.

The control node forgets the node's old host key under its short name, FQDN and address; then,
as root on the node: `sudo` is installed, the automation user (`vault_ansible_user`) is created
in group `sudo` with the control node's `~/.ssh/id_ed25519.pub` and passwordless sudo
(`/etc/sudoers.d/90-ansible`, validated). Nothing else. Mechanics, for when it does not work:
the password goes through the builtin `ssh` connection's `ssh_askpass` mechanism (ansible-core
2.19+; no `sshpass`, no paramiko — 2.21 ships none), and the new host key is recorded with
`StrictHostKeyChecking=accept-new`, which still refuses a *changed* key. A refusal there means
the known_hosts cleanup did not hit the name ssh actually uses; pass
`-e rebuild_known_hosts_path=…` if the ssh config keeps a non-default file.

## Phase 5 — Converge: the main playbook

`replace` only, **before** this run, in `host_vars/<node>/vars.yaml`:

```yaml
pve_ceph_osd_device: /dev/disk/by-id/ata-INTEL_SSDSC2BX016T4_<serial>   # the new drive
pve_node_ceph_osd_mode: create
pve_node_ceph_osd_zap: true   # only if the disk is not empty; vm-host-01's S3610 carries ZFS labels
```

`ansible/tests/test-ceph-osd-config.yml` is red from here until they are flipped back — that is
the reminder.

```sh
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster.yaml --limit <node>
```

One run. What it does that the old doc left to the operator: pins the NIC names first and
reboots once if any changed, before anything references a name; installs exactly the Ceph
release `pve_ceph_release` declares and refuses to create any daemon if the node or the cluster
disagrees; forgets the stale `[mon.<node>]`/`mon_host` and `[mds.<node>]` entries a raw removal
leaves, then recreates mon/mgr/mds and waits for each in Ceph's own view; creates the OSD only
when the node's CRUSH bucket is empty (an empty bucket left by a destroy no longer makes it
skip), after `ceph-volume inventory` — a disk in use is refused unless `pve_node_ceph_osd_zap`
asked for the zap; or activates the existing OSD, fails if there is none, marks it in again;
waits for the node's OSDs to be up and in; reboots once for a newer kernel so the r8125 module
loads; joins the cluster (gated on `/etc/pve/corosync.conf`); polls for the ACME certificate;
clears stale CephFS mounts.

`replace`, afterwards: `pve_node_ceph_osd_mode: activate_existing`, remove `pve_node_ceph_osd_zap`,
run the invariant test:

```sh
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i localhost, tests/test-ceph-osd-config.yml
```

## Phase 6 — Finish

```sh
# preserve
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-node-rebuild.yaml \
  -e rebuild_node=<node> -e rebuild_osd=<osd-mode> -e rebuild_evacuate_to=<target> \
  --tags finish

# replace, with the mClock measurement
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-node-rebuild.yaml \
  -e rebuild_node=<node> -e rebuild_osd=<osd-mode> -e rebuild_evacuate_to=<target> \
  --tags finish -e rebuild_measure_recovery=true
```

On the survivor: asserts the node is back with its OSD up and in (if not, the message points at
the main playbook — that is where the OSD is made); `preserve`: `ceph osd unset noout`,
`norebalance`; `replace` with the measurement: `ceph -s` sampled every 30 s for 10 minutes under
the current mClock profile, then under `high_recovery_ops`, the profile restored whatever
happens, both means printed and the samples written to `tasks/<node>-recovery-<stamp>.csv`;
then a wait for every PG `active+clean` with no recovery (budget 180 minutes — 253 GiB at the
~95 MiB/s seen in September 2026 is ~45); `ha-manager crm-command node-maintenance disable
<node>`; a wait until every HA resource whose rule prefers the node is started on it again
(`ha-group-main`: `vm:102`, `vm:103`, `vm:110` as of 2026-09-08 — the set is derived from the
live rule, not hard-coded); `-e rebuild_return_guests=true` migrates the recorded
non-HA guests back — off by default, because where they live is a decision (2026-09-08: they
stay on vm-host-01).

Why the measurement matters: 2.5GbE tops out near 280 MB/s, but recovery on this cluster runs
near a tenth of that, because mClock's `balanced` profile reserves most of each OSD's measured
capacity for client I/O. `osd_max_backfills` is inert under mClock; the profile is the lever.

Then on the node, as assertions — V1 quorate with every node online; V2 Ceph healthy; V3 the
node's OSD up and in; V4 one active MDS and a standby on every other node; V5 every daemon on
`pve_ceph_release`; V6 a `[mon.<node>]` section per node in `ceph.conf`; V7 the `r8125` DKMS
module built for the running kernel; V8 `intel_iommu=on` on the command line; V9 every enabled
storage active (`local-lvm` excepted); V10 `pveproxy-ssl.pem` present; V11 the rule-preferred HA
resources started here; V12 the returned guests present; V13 every pinned name carries its
MAC. A green finish is the rebuild done; browse `https://<node>.<domain_name>:8006` for the
Let's Encrypt certificate if you want to see it.

## If the node comes up with no management network

This happened on 2026-09-07 when the installer's `.link` files were deleted by hand before a
reboot. The playbook never does that, but the recovery is still console-only if it does happen:
`generate --interface X` rewrites references to `X`, the name the interface carries *right now*.
Once a `.link` file is gone the NIC reverts to a kernel name like `enp1s0`, while
`/etc/network/interfaces` still says `bridge-ports nic0` — an **orphaned reference the tool has
no way to match**, so it rewrites nothing and the bridge stays broken.

On console, fix both halves:

```
ip -br link                                    # real names, matched by MAC
pve-network-interface-pinning generate --interface <current> --target-name <final-name>
grep -n 'bridge-ports\|iface ' /etc/network/interfaces      # find orphaned names
${EDITOR:-nano} /etc/network/interfaces        # point bridge-ports at <final-name>
                                               # and check /etc/network/interfaces.new too
reboot
```

Verify after the reboot that `ip -br addr` shows the address on `vmbr0` **and** that
`/etc/network/interfaces` no longer mentions any name that `ip -br link` does not list. Then
continue with Phase 4.

## Gotchas

### 2.5GbE link falling back to 100Mb / 1Gb

Hardware: bad cable, bad keystone jack, bad switch port. Read-only checks:

```
sudo ethtool <cluster-nic> | grep -E 'Speed|Duplex|Link detected'
sudo ethtool -S <cluster-nic> | grep -iE 'err|drop|crc'
```

Climbing `rx_errors` / `align_errors` → bad physical layer. Replace cable, replace keystone, try
a different switch port. Check this before believing any recovery-rate number.

### `pvecm add` "hostname verification failed" (manual join only)

Use the FQDN (`pvecm add <main-fqdn>`) not the IP. The cluster's main node serves a Let's
Encrypt cert for the FQDN; IP connections fail SAN verification. The playbook's join
(`pve_cluster_add_node`, `--use_ssh`) does not hit this — only relevant if you bypass it.

### Sensitive output in `pvesh get /cluster/acme/plugins`

That command returns the Cloudflare API token in cleartext. Mind where the transcript ends up.

## Reference

- [`ansible/playbook-prod-proxmox-cluster-node-rebuild.yaml`](../ansible/playbook-prod-proxmox-cluster-node-rebuild.yaml) — the phases, by `--tags`.
- [`ansible/roles/pve_node_rebuild`](../ansible/roles/pve_node_rebuild) — the decisions and command sequences behind them, with the fixture suite that asserts every argv.
- [`ansible/playbook-prod-proxmox-cluster.yaml`](../ansible/playbook-prod-proxmox-cluster.yaml) — the converge; `--limit <node>` for a single rebuild.
- [`ansible/roles/pve_node_ceph`](../ansible/roles/pve_node_ceph) — ceph install, release guard, mon/mds forget + create, OSD create-or-activate (`pve_node_ceph_osd_mode`, `pve_node_ceph_osd_zap`).
- [`ansible/roles/pve_pin_network_interface`](../ansible/roles/pve_pin_network_interface) — NIC name pinning and re-pinning; the playbook reboots for it before anything uses a name.
- [`ansible/roles/pve_cluster_add_node`](../ansible/roles/pve_cluster_add_node) — cluster join, idempotent via `/etc/pve/corosync.conf`.
- [`ansible/roles/pve_cluster_acme`](../ansible/roles/pve_cluster_acme) / [`ansible/roles/pve_node_acme`](../ansible/roles/pve_node_acme) — ACME account + per-node cert order, polls until the cert lands.
- [`scripts/pve-pre-wipe-backup.sh`](../scripts/pve-pre-wipe-backup.sh) — pre-wipe state capture, run by the teardown from the control node.
- [`ansible/tests/test-ceph-osd-config.yml`](../ansible/tests/test-ceph-osd-config.yml) — every node's `pve_ceph_osd_device` is a by-id path, `pve_node_ceph_osd_mode` is back to `activate_existing`, no `pve_node_ceph_osd_zap` left behind.
- [`hardware/ssd-inventory.md`](../hardware/ssd-inventory.md) — the drives and their serials.
