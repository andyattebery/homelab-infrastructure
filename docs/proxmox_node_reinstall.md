# Proxmox Node Reinstall

End-to-end runbook for replacing a node in the homelab Proxmox/Ceph cluster: failed boot drive, full hardware swap, OS rebuild via Ansible.

Assumes the OSD lives on a separate disk (not the boot drive) and is intact, so its data is preserved through the rebuild.

Throughout this doc, fill in `<host>` (e.g. `vm-host-02`), `<id>` (the OSD ID), `<fqdn>` (e.g. `vm-host-02.<domain_name>`), etc. for the node being reinstalled.

## Prerequisites

- Cluster healthy, other nodes up.
- Replacement boot disk on hand. OSD disk is intact and won't be touched.
- Console / PiKVM access to the target.

## Phase 0 — Gather info from existing cluster

On a surviving node:

```
pveversion                 # confirm cluster's PVE major (PVE 9.x for trixie)
ceph -v                    # confirm ceph version (squid as of writing)
ceph osd tree              # note OSD id for <host>
ceph mon dump              # note mon address for <host>
ceph fs status             # is <host> running an MDS standby?
ceph -s
```

On `<host>` itself, while still bootable:

```
sudo ceph-volume lvm list  # capture OSD id, fsid, LV path — needed for activate_existing mode
ip a                       # capture MACs of the management NIC and cluster NIC
```

## Phase 1 — Pre-wipe backup

From the control node:

```
scripts/pve-pre-wipe-backup.sh <host>
```

Pulls `/etc/pve`, `/etc/ssh`, `/root/.ssh`, `/etc/network`, apt sources, and a snapshot of cluster state into a tarball. Treat the tarball as a credentials dump.

## Phase 2 — Cluster prep

On a surviving node:

```
sudo ceph osd set noout
sudo ceph osd set norebalance
sudo ceph -s
```

These pause rebalancing so the cluster doesn't shuffle data while one node is offline.

## Phase 3 — Drain & remove the node

On `<host>`:

```
sudo systemctl stop ceph-osd@<id>.service ceph-mon@<host>.service ceph-mgr@<host>.service ceph-mds@<host>.service
sudo systemctl disable ceph-osd@<id>.service ceph-mon@<host>.service ceph-mgr@<host>.service ceph-mds@<host>.service
```

On a surviving node:

```
sudo ceph osd out <id>            # do NOT purge — preserve the OSD ID and on-disk data
sudo ceph mon remove <host>
sudo ceph mds fail <host>         # only if <host> ran an MDS
```

**Clean up `/etc/pve/ceph.conf`** on a surviving node — `ceph mon remove` only updates the live monmap, not the conf file:

```
sudo ${EDITOR:-nano} /etc/pve/ceph.conf
```

- Remove the entire `[mon.<host>]` section.
- Remove `<host>'s mon IP` from the `mon_host = ...` line in `[global]`.

(Skipping this causes `pveceph mon create` to fail with "address already in use" later.)

Power off `<host>`. Then on a surviving node:

```
sudo pvecm delnode <host>
sudo rm -rf /etc/pve/nodes/<host>/   # clears stale per-node state
sudo pvecm expected <remaining>      # e.g. 2 if going from 3 → 2 nodes
sudo pvecm status
```

## Phase 4 — Physical swap

Replace the failed boot drive. Leave the OSD drive alone. Boot to BIOS, confirm both drives are detected.

## Phase 5 — PVE installer

Boot the PVE installer USB. Match the cluster's PVE major version (e.g. PVE 9.x).

**Hard Disk** — Advanced LVM options:

| Field | Value |
|---|---|
| Disk | new boot drive only (do **not** include the OSD drive) |
| Filesystem | `ext4` |
| `hdsize` | full |
| `swapsize` | `8` |
| `maxroot` | `80` |
| `maxvz` | leave blank (installer takes the rest minus minfree) |
| `minfree` | default |

**Network**: pick the management NIC — typically the Dell onboard (MAC OUI `a4:bb:6d`). The cluster NIC (Realtek `1c:fd:08` etc.) is configured later by the playbook.

**Interface pinning**: accept it. The installer pins names to MACs as `nic0`, `nic1`. Our playbook resolves the cluster NIC by MAC, so the chosen names don't matter — but pinning prevents future hardware-detection drift.

Hostname / IP / gateway / DNS: match the existing host_vars / DNS records.

## Phase 7 — Run the playbook

From the control node:

```
ansible-playbook ansible/playbook-<host>.yaml --ask-become-pass
```

Single end-to-end run. Things the playbook handles automatically that previously required manual intervention:

- Reboots once if a newer kernel was installed via `pve-headers` (so DKMS modules load against the running kernel).
- Swaps r8169 → r8125 driver via udev re-trigger so the 2.5GbE NIC negotiates above 1Gb.
- Joins the cluster idempotently (gated on `/etc/pve/corosync.conf` existing).
- Polls for the ACME cert to actually appear (the order is async — the role waits for `pveproxy-ssl.pem` to land or fails clearly).
- After OSD activate-existing, resets-failed and starts `ceph-osd@<id>` so the daemon is up persistently.
- Force-clears any stale cephfs mounts that went zombie during the rebuild.

## Phase 8 — Bring OSD back in and monitor recovery

```
sudo ceph osd in <id>
sudo watch -n 5 'ceph -s'
```

Watch for:

- `objects degraded` count dropping toward 0
- `pgs:` transitioning from `active+undersized+degraded+remapped+backfill_wait` / `+backfilling` / `+recovering` back to all `active+clean`
- `recovery:` rate climbing, then the line disappearing entirely

Recovery rate ceiling is the cluster network speed. On 2.5GbE expect ~50–150 MB/s sustained, ~280 MB/s theoretical max.

When all PGs show `active+clean` and there's no `recovery:` line:

```
sudo ceph osd unset noout
sudo ceph osd unset norebalance
sudo ceph -s                        # HEALTH_OK
```

## Phase 9 — Verify

```
sudo pvecm status                                              # 3 nodes quorate
sudo ceph -s                                                   # HEALTH_OK
sudo ceph osd tree                                             # original OSD id preserved on <host>
sudo ceph fs status                                            # MDS standby restored if applicable
sudo dkms status                                               # r8125, r8168 built for running kernel
cat /proc/cmdline | grep intel_iommu                           # intel_iommu=on present
sudo pvesm status                                              # all storages active (cephfs + cifs + pbs etc.)
ls /etc/pve/nodes/<host>/pveproxy-ssl.pem                      # ACME cert present
```

Browse `https://<fqdn>:8006` — should show a valid Let's Encrypt cert.

## Gotchas

The runbook and roles auto-handle most issues that came up during the original rebuild. These are the ones that remain manual:

### 2.5GbE link falling back to 100Mb / 1Gb

Hardware: bad cable, bad keystone jack, bad switch port. Check:

```
sudo ethtool nic1 | grep -E 'Speed|Duplex|Link detected'
sudo ethtool -S nic1 | grep -iE 'err|drop|crc'
```

Climbing `rx_errors` / `align_errors` → bad physical layer. Replace cable, replace keystone, try a different switch port.

### `pvecm add` "hostname verification failed" (manual join)

Use the FQDN (`pvecm add <main-fqdn>`) not the IP. The cluster's main node serves a Let's Encrypt cert for the FQDN; IP connections fail SAN verification. The playbook's pvesh-based join doesn't hit this — only relevant if you bypass the playbook.

### Sensitive output in `pvesh get /cluster/acme/plugins`

That command returns the Cloudflare API token in cleartext. Mind where the transcript ends up if you paste it.

## Reference

- [`ansible/scripts/pve-pre-wipe-backup.sh`](../ansible/scripts/pve-pre-wipe-backup.sh) — pre-wipe state capture (run from control node).
- [`ansible/roles/pve_config`](../ansible/roles/pve_config) — apt sources management, content-based deb822/.list auto-detect.
- [`ansible/roles/pve_cluster_add_node`](../ansible/roles/pve_cluster_add_node) — cluster join, idempotent via `/etc/pve/corosync.conf` stat check.
- [`ansible/roles/pve_cluster_acme`](../ansible/roles/pve_cluster_acme) / [`ansible/roles/pve_node_acme`](../ansible/roles/pve_node_acme) — ACME account + per-node cert order, polls until cert lands.
- [`ansible/roles/pve_node_ceph`](../ansible/roles/pve_node_ceph) — ceph install + mon/mgr/MDS create + OSD create-or-activate (`pve_node_ceph_osd_mode`).
- [`ansible/roles/pve_storage_add_nas_01_proxmox`](../ansible/roles/pve_storage_add_nas_01_proxmox) — CIFS storage attach.
- [`ansible/roles/pve_backup_job_script`](../ansible/roles/pve_backup_job_script) — wrapper script attach to backup jobs.
- [`ansible/playbook-vm-host-02.yaml`](../ansible/playbook-vm-host-02.yaml) — canonical playbook shape for a node rebuild.
