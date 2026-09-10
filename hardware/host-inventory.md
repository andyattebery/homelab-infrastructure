# Homelab host inventory

Last verified: 2026-09-06, over read-only ssh to every reachable host.
See [Refresh commands](#refresh-commands) at the bottom to re-derive all of it.

[inventory.ini](../ansible/inventory.ini) now holds **21 names — 20 distinct machines**,
since `network-02` is an alias for `pi-rack`. **16 of the 21 answered** on the audit date.
`pi-camera`, `jetson-01`, `offsite-nas` and `wsl-01` did not answer, and `ideapad3` was not
probed; all five are marked *not verified 2026-09-06* where they appear and carry forward what
was there before.

(It was 23 names during the audit. `pi-01` and `pi-octoprint` were removed on 2026-09-07 —
see [Retired / not managed](#retired--not-managed).)

## What the "roles" column does and does not tell you

Each row points at the playbook that owns the host. **That is the set of roles Ansible
applies — it is not the set of services running.** The two have drifted apart on purpose:
`playbook-nas-01.yaml` has **23 commented-out roles whose stacks are still deployed and
running**, and `playbook-docker-01.yaml` has **8**. Commenting a role out stops Ansible
managing the stack; it does not remove it.

So: for "what is Ansible responsible for", read the playbook. For "what is actually running",
run the refresh command. Do not infer either from the other.

## Proxmox cluster — physical nodes

Three nodes, one cluster (`pve_cluster_name: homelab`), on **PVE 9.2.x**, kernel `7.0.14-16-pve`
(nas-host-01 still on `-15`, reboot pending), Ceph **20.2.4 tentacle** (`pve_ceph_release`).
Release changes go through
[playbook-prod-proxmox-cluster-ceph-upgrade.yaml](../ansible/playbook-prod-proxmox-cluster-ceph-upgrade.yaml). Dedicated Ceph cluster network, CIDR set per-host via
`ceph_cluster_nic_address_cidr` ([group_vars/prod_proxmox_cluster/vars.yaml](../ansible/group_vars/prod_proxmox_cluster/vars.yaml)).
Inventory group `prod_proxmox_cluster`; all three managed by
[playbook-prod-proxmox-cluster.yaml](../ansible/playbook-prod-proxmox-cluster.yaml).

| Host | Chassis | CPU | RAM | Ceph OSD | Guests |
| --- | --- | --- | --- | --- | --- |
| `vm-host-01` | Dell OptiPlex Micro 5070 | Intel i5-9500T, 6C/6T | 62 GB | Intel DC S3610 1.6T `BTHC637404T21P6PGN` (osd.0, class `ssd`) on an Optane P1600X 58G boot | `docker-01` (102), `network-01` (103), `homeassistant` (110), `vdesktop-01` (120) |
| `vm-host-02` | Dell OptiPlex Micro 3070 | Intel i3-9100T, 4C/4T | 38 GB | Intel DC S3610 1.6T (osd.1, class `ssd`) on an Optane P1600X 58G boot | none. **HA failover target for vm-host-01's VMs** |
| `nas-host-01` | Innovision S45624 4U, Asrock Rack ROMED8-2T ([nas-host-01.md](nas-host-01.md)) | AMD EPYC 7282, 16C/32T | 192 GB | Intel Optane 905P 960G (osd.2) | `nas-01` (200, HBA + bulk storage), `media-01` (201, RTX A4000 + Arc B580), `network-03` (203), templates `1000`/`1001` |

All three OSDs `up`, one per node.

`pve_cluster_designated_runner` is the alphabetically-first node → currently `nas-host-01`. It
owns cluster-wide writes (ACME, storage defs, Ceph init). It is also the current CRM master,
which is a separate thing and can move.

**vm-host-02 is idle by design** — it exists as the HA failover target. `vdesktop-01` (120, an
experiment) runs on vm-host-01; the two templates, `1000` ubuntu-2404-cloudinit and `1001`
nixos-2511, live on nas-host-01. None of the three is HA-managed, so a rebuild of their host moves
them with `qm migrate` (`rebuild_evacuate_to`) rather than by failover.

### Network interface names

Pinned to MACs by the [pve_pin_network_interface](../ansible/roles/pve_pin_network_interface/README.md)
role, so moving a card between PCIe slots cannot rename a NIC out from under `vmbr0`'s
`bridge-ports`. Names are chip-family based, management port first.

| Host | vmbr0 uplink | Ceph cluster net |
| --- | --- | --- |
| `vm-host-01` | `i219p0` (Intel I219-V, onboard) | `rtl8125p0` (Realtek RTL8125 2.5G) |
| `vm-host-02` | `rtl8168p0` (Realtek RTL8168 1G) | `rtl8125p0` (Realtek RTL8125 2.5G) |
| `nas-host-01` | `cx4p0` (Mellanox ConnectX-4 Lx p1) | `cx4p1` (Mellanox ConnectX-4 Lx p2) |

Pins live in `/usr/local/lib/systemd/network/50-pmx-<name>.link` on each node and take effect
at boot. nas-host-01's BMC USB gadget is deliberately unpinned — its `enx<mac>` name is already
slot-independent.

### HA rules

Being **HA-managed** and being in a **node-affinity rule** are two different things — check
`ha-manager status` for the former, `/etc/pve/ha/rules.cfg` for the latter.

Declared in `group_vars/prod_proxmox_cluster/vars.yaml` and converged by
[pve_cluster_ha](../ansible/roles/pve_cluster_ha/README.md). Adding an HA resource or rule in the
web UI now fails the next cluster run until it is declared there too — the role never deletes, it
refuses.

HA-managed resources: `vm:102`, `vm:103`, `vm:110`.

One node-affinity rule (`ha-group-main`) covers all three:

| Resource | VM | Preferred (prio) | Failover (prio) | Last resort (prio) | strict | failback |
| --- | --- | --- | --- | --- | --- | --- |
| `vm:102` | docker-01 | vm-host-01 (3) | vm-host-02 (2) | nas-host-01 (1) | 0 | 1 |
| `vm:103` | network-01 | vm-host-01 (3) | vm-host-02 (2) | nas-host-01 (1) | 0 | 1 (default) |
| `vm:110` | homeassistant | vm-host-01 (3) | vm-host-02 (2) | nas-host-01 (1) | 0 | 1 |

Neither `strict` nor `vm:103`'s `failback` is written in `/etc/pve/ha/rules.cfg`; both are absent
keys taking PVE's documented default, which is not the same as being unset.

**Consequence for maintenance:** because the rule is priority-ordered and `failback` is on, PVE 9.2
**refuses** a hand migration of any of the three off vm-host-01 —

    Cannot migrate VM, because HA resource vm:102 is not allowed on the selected target node.

A resource may only be moved among the nodes tied at the highest priority, and vm-host-01 holds
priority 3 alone. This is the rule working as declared. Use
`ha-manager crm-command node-maintenance enable <node>` instead — it evacuates all HA resources,
survives a reboot, and moves them back only when maintenance is disabled.

`strict 0` = non-strict: if all preferred nodes are down, HA will start the VM on any remaining
online node. nas-host-01's passthrough VMs (`nas-01`, `media-01`) are **not** HA-managed —
they are pinned to that node by hardware passthrough and would not survive failover.
`network-03` is likewise not HA-managed.

## Virtual machines

Nine guests across the cluster: **seven running, two stopped templates**.

| VM | Parent | VMID | vCPU | RAM | Disks | OS | Playbook | Purpose |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `docker-01` | vm-host-01 | 102 | 4 | 16 GB | 2× 128 GB (Ceph) | Ubuntu 24.04.4 | [playbook-docker-01.yaml](../ansible/playbook-docker-01.yaml) | Apps + observability. Traefik, the Prometheus/Grafana stack and its exporters, dashboards, and the small self-hosted utilities. |
| `network-01` | vm-host-01 | 103 | 2 | 4 GB | 64 GB (Ceph) | NixOS 26.05 | _(not Ansible-managed)_ [nix/hosts/network-01/](../nix/hosts/network-01/) | DNS primary. AdGuardHome (keepalived MASTER, prio 200), AdGuardHome-sync, network-inventory-manager, nginx, Tailscale. |
| `homeassistant` | vm-host-01 | 110 | 4 | 12 GB | 128 GB (Ceph) | HAOS 18.2 (HA 2026.9.1, supervisor 2026.08.0) | _(none)_ | Home automation. |
| `vdesktop-01` | vm-host-01 | 120 | 4 | 8 GB | 64 GB (Ceph) | — | _(none)_ | Virtual desktop **experiment**. On vm-host-01 by decision (2026-09-08). |
| `ubuntu-2404-cloudinit-template` | vm-host-01 | 1000 | 2 | 8 GB | 64 GB (Ceph) | Ubuntu 24.04 | — | Template, stopped. |
| `nixos-2511-template` | vm-host-01 | 1001 | 2 | 4 GB | 64 GB (Ceph) | NixOS 25.11 | — | Template, stopped. |
| `nas-01` | nas-host-01 | 200 | 14 | 48 GB **(88 GB staged)** | 128 + 32 + 64 GB on `pve-optane-01`, plus all passed-through storage | Ubuntu 22.04.5 | [playbook-nas-01.yaml](../ansible/playbook-nas-01.yaml) | NAS + heavy data services. Owns every bulk disk via HBA passthrough; runs the ZFS pools, snapraid/mergerfs, and syncoid to backup-01 and offsite-nas. |
| `media-01` | nas-host-01 | 201 | 24 | 56 GB | 192 + 640 GB on `pve-optane-01` | Ubuntu 26.04.1 | [playbook-media-01.yaml](../ansible/playbook-media-01.yaml) | Media + AI inference. RTX A4000 + Intel Arc B580 passthrough; media servers, Tdarr **server and an A4000 node**, Immich ML, Whisper. |
| `network-03` | nas-host-01 | 203 | 2 | 4 GB | 64 GB (Ceph) | NixOS 26.05 | _(not Ansible-managed)_ [nix/hosts/network-03/](../nix/hosts/network-03/) | DNS tertiary. AdGuardHome (keepalived BACKUP, prio 100), Tailscale. |

`docker-01`, `network-01`, `nas-01`, `media-01` and `network-03` each run `beszel-agent`
plus a node exporter — see [Monitoring coverage](#monitoring-coverage). `homeassistant` is an
appliance OS and was not checked for either; `vdesktop-01` and the two templates were not
checked.

**nas-01's 88 GB is staged, not applied.** `/etc/pve/qemu-server/200.conf` carries a
`[PENDING] memory: 90112`. It lands on the next stop/start. This is intended.

**media-01 is temporarily wide.** 14 + 24 + 2 = **40 vCPU allocated against nas-host-01's 32
threads**, and 108 GB of 192. The overcommit is deliberate and temporary — media-01 was widened
for a one-time job and will be narrowed again. media-01 also carries a `pre-26-04` snapshot from
the Ubuntu 26.04 upgrade.

`network-02` is **not** a separate VM — it is an inventory alias for the bare-metal `pi-rack`
(see below). The three `network-XX` names share the AdGuardHome VRRP cluster behind the
`dns_server_vip`, and are split across two config systems: `network-01` and `network-03` are
NixOS deployed from `nix/hosts/`; `pi-rack` (= `network-02`) is still Ubuntu and is the only
member [playbook-network.yaml](../ansible/playbook-network.yaml) targets. WireGuard runs on
`pi-rack` and `cloud-01` only — the two VM peers dropped it at the NixOS migration.

## Bare-metal services & pis

| Host | Hardware | Playbook | Purpose |
| --- | --- | --- | --- |
| `backup-01` | Intel N150 4C/4T, 32 GB DDR5-4800, whitebox board (DMI reports `Default string`). Boot on an Intel S3520 150 GB; `backups` zpool 20 TB = 2× 10 TB + 2× 12 TB mirrors | [playbook-backup-01.yaml](../ansible/playbook-backup-01.yaml) | **Proxmox Backup Server** (datastore `zfs_backups_pbs` at `/mnt/backups/pbs`) on Debian 13 trixie / PVE 7.0 kernel. Also ZFS replication target (syncoid from nas-01, forwards to offsite-nas), Samba Time Machine target, NUT client, `remote_power_control` target. |
| `pi-rack` / `network-02` | Raspberry Pi 4 Model B Rev 1.4, 8 GB, PoE+ HAT, boots from a 139.7 GB USB SSD | [playbook-pi-rack.yaml](../ansible/playbook-pi-rack.yaml) + [playbook-network.yaml](../ansible/playbook-network.yaml) (as `network-02`) | UPS server + DNS HA member + rack ops. NUT **server** for the APC SMT1500RM2U (via AP9630 SNMP) with `nas-host-01`, `vm-host-01`, `vm-host-02`, `backup-01` as `upsmon` secondaries and `homeassistant` polling via the HA NUT integration. AdGuardHome (keepalived BACKUP, prio 150), WireGuard, Diun, Certbot. `scrutiny-collector` is a **systemd timer**, not a container. |
| `pi-camera` | Raspberry Pi 5 Model B Rev 1.0 | [playbook-pi-camera.yaml](../ansible/playbook-pi-camera.yaml) | Camera streamer — `go2rtc` (rpi5 config), Certbot. No docker. **Not verified 2026-09-06** (unreachable). |
| `pi-turntable` | Raspberry Pi 4 Model B Rev 1.1, 4 GB, 58 GB SD | [playbook-pi-turntable.yaml](../ansible/playbook-pi-turntable.yaml) | Turntable audio streaming. Traefik, Owntone, `needledrop` (Last.fm scrobbling), icecast2, and `owntone-alsa-pipe.service` (ALSA → named pipe → Owntone). |
| `pikvm` | Raspberry Pi 4 Model B Rev 1.5, 2 GB, Arch Linux ARM, kvmd 4.212-1 | [playbook-pikvm.yaml](../ansible/playbook-pikvm.yaml) | Primary PiKVM. Tailscale exit node, esphome-api-cli outlet control (`backup_01`, `mac_mini_01`, `nas_host_01`, `vm_host_01`, `vm_host_02`), `remote_power_control` client to four servers, HID switching to `pikvm-hid`. |
| `pikvm-hid` | Raspberry Pi **Zero 2 W** Rev 1.0, 389 MB, Arch Linux ARM, kvmd 4.212-1 | [playbook-pikvm.yaml](../ansible/playbook-pikvm.yaml) | Secondary PiKVM (HID / USB-keyboard only), slaved to `pikvm`'s `pikvm_hid_kvm_switch_input`. |
| `jetson-01` | NVIDIA Jetson Orin Nano Dev Kit Super (Tegra R36) | [playbook-jetson-01.yaml](../ansible/playbook-jetson-01.yaml) | AI offload for Home Assistant — Wyoming `faster-whisper` (:10300) and Wyoming `piper-tts` (:10200). **That is all it runs**; it does not run Immich ML. **Not verified 2026-09-06** (unreachable). |

`playbook-pikvm.yaml` targets three hosts, not two — `pikvm`, `pikvm-hid` and `offsite-pikvm`.

## Workstations & clients

Group `workstations` in [inventory.ini](../ansible/inventory.ini). No `group_vars/workstations/`
exists, so only `group_vars/all/` and `group_vars/homelab/` apply.

| Host | Hardware | OS | Connection | Playbook | Purpose |
| --- | --- | --- | --- | --- | --- |
| `eta` | Gigabyte X570 AORUS MASTER, AMD Ryzen 9 5900X 12C/24T, 32 GB, **NVIDIA RTX 5060 Ti**, Intel Optane 900P 280 GB + a 4 TB Storage Space | Windows 11 Pro (10.0.26200) | **ssh with `ansible_shell_type: powershell`** — no WinRM. No `become`: the ssh login is already an elevated Administrator token, and `become: true` without `become_user` would enter the `runas` plugin and fail | [playbook-eta.yaml](../ansible/playbook-eta.yaml) | Windows workstation. Tdarr **Windows node** (NVENC) with a jellyfin-ffmpeg build; game streaming via `ApolloService`. The only Windows host in the estate. |
| `htpc-01` | AMD Ryzen 5 5600GE 6C/12T, 32 GB, **ASRock Steel Legend Radeon RX 9070 XT 16 GB** (`1002:7550` / `1849:5403`, gfx1201) + Cezanne iGPU, 4 drives (SK hynix P41 2 TB, Intel DC S3500 1.6 TB, Samsung 850 EVO 500 GB, BC711 256 GB) | Bazzite (Fedora 44 base, rpm-ostree) | ssh as `bazzite`, `become: true`, `-o SetEnv=TERM=dumb` | [playbook-htpc-01.yaml](../ansible/playbook-htpc-01.yaml) | HTPC + local AI. **Rootful Podman quadlets, not Docker.** Caddy, ComfyUI, llama-swap (the LLM backend for Onyx on media-01 and local-deep-research on docker-01), and a VAAPI Tdarr node. |
| `wsl-01` | eta's hardware — Ubuntu 24.04 under WSL2, same IP as `eta` | Ubuntu 24.04 (WSL2) | ssh to `eta` on **port 2222** (`ssh.socket` drop-in; `sshd_config`'s `Port` is ignored under socket activation) | [playbook-wsl-01.yaml](../ansible/playbook-wsl-01.yaml) | Docker host on eta's GPU — Traefik, a Tdarr node, TabbyAPI. Retirement is intended but it is still being maintained. **Not verified 2026-09-06** (did not answer). |
| `ideapad3` | Lenovo IdeaPad 3 laptop | — | ssh, `ansible_host=192.168.1.49` | [playbook-ideapad3.yaml](../ansible/playbook-ideapad3.yaml) | Spare laptop. Only `configure_server` — no services. Not probed 2026-09-06. |

## Offsite / cloud

| Host | Hardware / Provider | Purpose |
| --- | --- | --- |
| `cloud-01` | Ubuntu 24.04.4 VPS — 1 vCPU on an AMD EPYC 7713 KVM host, 961 MB RAM, 24.5 GB disk | Public ingress + RSS. Traefik, WireGuard (public-facing), FreshRSS with a `*/15` cron feed updater, Diun. |
| `offsite-nas` | Bare metal NAS at an offsite location; wakes on demand for syncoid pulls | Cold-storage backup target. ZFS, syncoid destination (from nas-01, backup-01, offsite-homeassistant), Samba (home-assistant backups share), sanoid, shutdown_tracker, Tailscale, an `offsite-last-awake` textfile collector. **Not verified 2026-09-06** (asleep). |
| `offsite-pikvm` | Raspberry Pi **Compute Module 4** Rev 1.1, Arch Linux ARM, kvmd 4.212-1 | PiKVM for `offsite-nas` remote power. Tailscale, ACME via Tailscale cert. |

For the `offsite` group, `domain_name` is the Tailscale tailnet, not the internal domain.

## Monitoring coverage

Checked host by host on 2026-09-06 rather than assumed. **12 of the 14 hosts checked run
`beszel-agent` plus exactly one node exporter**, and the unit name splits by OS family
(`network-01` and `network-03` are here as machines, though they are not `inventory.ini`
names):

| Unit | Hosts |
| --- | --- |
| `node_exporter` | backup-01, pi-rack, pi-turntable, cloud-01, docker-01, nas-01, media-01 |
| `prometheus-node-exporter` | network-01, network-03, pikvm, pikvm-hid, offsite-pikvm |
| **neither, and no beszel-agent** | **htpc-01, eta** |

htpc-01 has neither because `configure_server` dispatches to the Bazzite
`tasks/fedora_immutable.yaml` path, which installs no agent and no exporter. Consistent with
Prometheus, which does not scrape `htpc-01`, `eta`, `wsl-01`, `ideapad3`, `cloud-01` or
`mac-mini-01`.

Not checkable on the day: `pi-camera`, `jetson-01`, `offsite-nas`, `wsl-01`, `ideapad3`.

## Retired / not managed

Recorded so the next reader does not re-investigate them.

| Name | Status |
| --- | --- |
| `pi-01` | **Decommissioned.** Removed from `inventory.ini` on 2026-09-07. It had exactly one reference in the whole repo and never had a playbook. |
| `pi-octoprint` | **A finished experiment.** Removed from `inventory.ini` on 2026-09-07 along with `playbook-pi-octoprint.yaml`, which could not complete anyway — it templated a `go2rtc-rpi5.yaml.j2` that was never committed. **OctoPrint now runs as a container on docker-01.** |
| `vm-host-03` / `vm-host-04` | Never hosts here. Their stale `ansible/files/vm-host-0{3,4}/interfaces` were deleted 2026-09-07. **The PiKVM WoL and GPIO entries for `vm-host-03` remain** in `ansible/files/pikvm/override.yaml.j2` and the vault vars — deliberately untouched, a separate decision. |
| `mac-mini-01` | Real (192.168.1.201) but **not Ansible-managed**. Power only, via the `mac-mini-01-outlet.local` ESPHome outlet from `pikvm`; it has no `remote_power_control` ssh target. `ansible/files/macos/` is applied by hand. |
| `offsite-homeassistant` | Real but not Ansible-managed. Appears only as a syncoid source and a Samba share on `offsite-nas`. |

## Refresh commands

```sh
# --- Case set: what actually exists ---
ansible-inventory -i ansible/inventory.ini --list --yaml   # 21 names, 20 machines
for h in vm-host-01 vm-host-02 nas-host-01; do ssh $h 'sudo qm list'; done

# --- Cluster + HA ---
ssh nas-host-01 'sudo pvecm nodes && sudo ha-manager status && sudo cat /etc/pve/ha/rules.cfg'
ssh nas-host-01 'sudo pveversion && sudo ceph osd tree'

# --- VM sizing. TARGETED GREP, NEVER `cat`: 200.conf contains a cipassword. ---
# `ssh <host> bash -s` pipes the script to a known shell. Necessary: these hosts have
# fish as the login shell, so a bare `for ... do ... done` sent over ssh will not parse.
for h in vm-host-01 vm-host-02 nas-host-01; do
  echo "===== $h"
  ssh "$h" bash -s <<'EOF'
for f in /etc/pve/qemu-server/*.conf; do
  echo "[$f]"
  sudo grep -E "^(name|cores|memory|ostype|machine|bios|onboot|template|hostpci[0-9]|scsi[0-9]|net[0-9])" "$f"
done
EOF
done

# --- Per-host: OS, CPU/RAM, containers, and the monitoring pair ---
for h in backup-01 docker-01 nas-01 media-01 pi-rack pi-turntable cloud-01 \
         network-01 network-03 pikvm pikvm-hid offsite-pikvm htpc-01; do
  echo "== $h"
  ssh $h 'bash -c ". /etc/os-release; echo \$PRETTY_NAME; uname -r; nproc; free -g | head -2
    systemctl is-active beszel-agent node_exporter prometheus-node-exporter
    (sudo docker ps --format "{{.Names}}" 2>/dev/null || sudo podman ps --format "{{.Names}}" 2>/dev/null) | sort"'
done

# htpc-01 runs ROOTFUL podman — `podman ps` as the login user returns nothing.
ssh htpc-01 'bash -lc "sudo podman ps --format \"{{.Names}}\""'

# eta is Windows: ssh + powershell, no WinRM.
ssh eta 'powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Format-List Caption,Version"'
```
