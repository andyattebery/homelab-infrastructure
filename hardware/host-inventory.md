# Homelab host inventory

Last verified: 2026-05-13.
Sources: `ansible/inventory.ini`, playbooks under `ansible/`, `qm list` on each
Proxmox node, and `docker ps` on each Docker host.

Service descriptions reflect what is **actually running** on the host today,
which in places differs from what the playbook applies (many `docker_compose_*`
role lines are commented but the underlying stacks remain deployed).

## Proxmox cluster — physical nodes

The three nodes form one Proxmox cluster (`pve_cluster_name: homelab`) with a
dedicated Ceph cluster network (CIDR set per-host via `ceph_cluster_nic_address_cidr`,
range in [group_vars/prod_proxmox_cluster/vars.yaml](../ansible/group_vars/prod_proxmox_cluster/vars.yaml)).
Inventory group: `prod_proxmox_cluster`. See
[playbook-prod-proxmox-cluster.yaml](../ansible/playbook-prod-proxmox-cluster.yaml).

All three nodes are managed by [playbook-prod-proxmox-cluster.yaml](../ansible/playbook-prod-proxmox-cluster.yaml) (targets the `prod_proxmox_cluster` group).

| Host | Hardware | Role | Hosts VMs |
| --- | --- | --- | --- |
| `vm-host-01` | Intel + Realtek r8125/r8152 NICs ([host_vars/vm-host-01/vars.yaml](../ansible/host_vars/vm-host-01/vars.yaml)) | PVE node, Ceph OSD on Samsung 960 PRO 512G | `network-01` (101), `docker-01` (102), `homeassistant` (110) |
| `vm-host-02` | Intel + r8125 + r8168 NICs ([host_vars/vm-host-02/vars.yaml](../ansible/host_vars/vm-host-02/vars.yaml)) | PVE node, Ceph OSD on Samsung 970 EVO 500G. **HA failover target for vm-host-01's VMs** (see HA rules below) | (idle by design — only an Ubuntu 24.04 cloud-init template, stopped) |
| `nas-host-01` | AMD EPYC 7282 / Asrock Rack ROMED8-2T ([hardware/nas-host-01.md](nas-host-01.md)) | PVE node, Ceph OSD on Intel Optane 905P 960G, designated cluster runner | `nas-01` (200, HBA + bulk-storage passthrough), `media-01` (201, RTX A4000 passthrough), `network-03` (202) |

`pve_cluster_designated_runner` is computed as the alphabetically-first node →
currently `nas-host-01`. It owns cluster-wide writes (ACME, storage defs, Ceph
init).

### HA rules

One node-affinity rule (`ha-group-main`, from `/etc/pve/ha/rules.cfg`) covers all three HA-managed VMs:

| Resource | VM | Preferred (prio) | Failover (prio) | Last resort (prio) | strict |
| --- | --- | --- | --- | --- | --- |
| `vm:101` | network-01 | vm-host-01 (3) | vm-host-02 (2) | nas-host-01 (1) | 0 |
| `vm:102` | docker-01 | vm-host-01 (3) | vm-host-02 (2) | nas-host-01 (1) | 0 |
| `vm:110` | homeassistant | vm-host-01 (3) | vm-host-02 (2) | nas-host-01 (1) | 0 |

`strict 0` = non-strict: if all preferred nodes are down, HA will start the VM on any remaining online node. `nas-host-01`'s passthrough VMs (`nas-01`, `media-01`, `network-03`) are **not** HA-managed — they're pinned to that node by hardware passthrough and would not survive failover.

## Virtual machines

| VM | Parent | VMID | OS | Playbook | Purpose | Key services |
| --- | --- | --- | --- | --- | --- | --- |
| `network-01` | vm-host-01 | 101 | NixOS | _(not Ansible-managed)_ [nix/hosts/network-01/](../nix/hosts/network-01/) | DNS primary | AdGuardHome (keepalived MASTER, prio 200), AdGuardHome-sync, network-inventory-manager, Keepalived (+keepalived-exporter), dashboard-services-manager-provider, nginx reverse proxy, Tailscale |
| `docker-01` | vm-host-01 | 102 | Linux VM | [playbook-docker-01.yaml](../ansible/playbook-docker-01.yaml) | Main app/observability docker host | Traefik, tsdproxy, Beszel (hub+agent), Homepage, Dashy, Grafana, Prometheus, InfluxDB v2, Healthchecks, Uptime-Kuma, Dockwatch, Diun, Cup, dashboard-services-manager (+provider), Calibre, Changedetection.io (+playwright), Wallos, SearXNG (+redis), Vaultwarden, Jellystat, Tautulli, Octoprint, Spoolman, Cert-bot (ASRock IPMI cert updater) |
| `homeassistant` | vm-host-01 | 110 | Home Assistant OS (HAOS, x86_64) | _(none — not Ansible-managed)_ | Home automation | Home Assistant supervised stack |
| `nas-01` | nas-host-01 | 200 | Linux VM (HBA passthrough → all bulk storage) | [playbook-nas-01.yaml](../ansible/playbook-nas-01.yaml) | NAS + heavy data services | Traefik, tsdproxy, Diun, Frigate (NVR), Immich (server/redis/postgres), Nextcloud (+mariadb/redis), Paperless-ngx (+postgres/redis/tika/gotenberg), Forgejo, Manyfold, Linkwarden (+postgres), Linkding, Minio, Syncthing, Resilio-sync, Scrutiny-web (+influxdb). Also runs snapraid/mergerfs/ZFS, syncoid → backup-01 and offsite-nas. |
| `media-01` | nas-host-01 | 201 | Linux VM (RTX A4000 passthrough) | [playbook-media-01.yaml](../ansible/playbook-media-01.yaml) | Media + AI inference | Traefik, Plex, Jellyfin, Audiobookshelf, Tdarr, Ollama, Open-WebUI, Immich machine-learning (CUDA), Diun |
| `network-03` | nas-host-01 | 202 | NixOS | _(not Ansible-managed)_ [nix/hosts/network-03/](../nix/hosts/network-03/) | DNS tertiary | AdGuardHome (keepalived BACKUP, prio 100), Keepalived (+keepalived-exporter), dashboard-services-manager-provider, Tailscale |

`network-02` is **not** a separate VM — it is an inventory alias for the bare-metal `pi-rack` (see Pis below). The three `network-XX` names share the AdGuardHome VRRP cluster behind the `dns_server_vip`.

The three are split across two config systems: `network-01` and `network-03` are NixOS, deployed from `nix/hosts/`; `pi-rack` (= `network-02`) is still Ubuntu and is the only member `ansible/playbook-network.yaml` targets. WireGuard runs on `pi-rack` and `cloud-01` only — the two VM peers dropped it at the NixOS migration.

## Bare-metal services & pis

| Host | Hardware | Playbook | Purpose | Key services |
| --- | --- | --- | --- | --- |
| `backup-01` | x86 server, ZFS, PMX 7.0 kernel | [playbook-backup-01.yaml](../ansible/playbook-backup-01.yaml) | Proxmox Backup Server + ZFS replication target + Time Machine target | PBS (`pbs_config`, ACME), Samba (Time Machine share), syncoid destination (from nas-01) → forwards to offsite-nas, sanoid, shutdown_tracker, NUT client, Tailscale, remote_power_control target |
| `pi-rack` / `network-02` | Raspberry Pi 4 Model B Rev 1.4 (rack-mounted, PoE+ HAT) | [playbook-pi-rack.yaml](../ansible/playbook-pi-rack.yaml) + [playbook-network.yaml](../ansible/playbook-network.yaml) (as `network-02`) | UPS server + DNS HA member + rack ops | NUT server (APC SMT1500RM2U via AP9630 SNMP; `admin` + `monitor-primary` + 5 secondary accounts — `nas-host-01`, `vm-host-01`, `vm-host-02`, `backup-01` run `upsmon`, `homeassistant` polls via the HA NUT integration), nut-exporter, scrutiny_collector, AdGuardHome (keepalived BACKUP, prio 150), WireGuard, Keepalived, dashboard-services-manager-provider, Diun, Certbot. Two inventory aliases (`pi-rack`, `network-02`) point at this same Pi, and it is the only host `playbook-network.yaml` targets. |
| `pi-camera` | Raspberry Pi 5 Model B Rev 1.0 | [playbook-pi-camera.yaml](../ansible/playbook-pi-camera.yaml) | Camera streamer | `go2rtc` (rpi5 config), Certbot. No docker. |
| `pi-turntable` | Raspberry Pi 4 Model B Rev 1.1 | [playbook-pi-turntable.yaml](../ansible/playbook-pi-turntable.yaml) | Turntable audio streaming | Traefik + Owntone + `turntable-pipe.service` (ALSA → named pipe → Owntone) |
| `pikvm` | Pi (armv7l, 6.12 rpi kernel) | [playbook-pikvm.yaml](../ansible/playbook-pikvm.yaml) | Primary PiKVM | PiKVM OS stack, Tailscale exit node, esphome-api-cli outlet control (backup_01, mac_mini_01, nas_host_01, vm_host_01, vm_host_02), remote_power_control client to all four servers, HID switching to `pikvm-hid` |
| `pikvm-hid` | Pi (armv7l, 6.12 rpi kernel) | [playbook-pikvm.yaml](../ansible/playbook-pikvm.yaml) | Secondary PiKVM (HID/USB-keyboard-only) | PiKVM stack, slaved to `pikvm`'s `pikvm_hid_kvm_switch_input` |
| `jetson-01` | NVIDIA Jetson Orin Nano Dev Kit Super (Tegra R36) | [playbook-jetson-01.yaml](../ansible/playbook-jetson-01.yaml) | AI offload for HA + Immich | Wyoming `faster-whisper`, Wyoming `piper-tts`, Immich machine-learning (jetson build) |
| `ideapad3` | Lenovo IdeaPad 3 laptop | [playbook-ideapad3.yaml](../ansible/playbook-ideapad3.yaml) | Workstation (powered off during audit) | Only `configure_server` — no services to document |

## Offsite / cloud

| Host | Hardware / Provider | Purpose | Key services |
| --- | --- | --- | --- |
| `cloud-01` | Ubuntu 24.04 VPS (public hostname in `~/.ssh/conf.d`) | Public ingress + RSS | Traefik, WireGuard (public-facing), FreshRSS (with cron feed updater), Diun |
| `offsite-nas` | Bare metal NAS at offsite location (unreachable during audit — wakes on demand for syncoid pulls) | Cold-storage backup target | ZFS, syncoid destination (from nas-01 + backup-01 + offsite-homeassistant), Samba (home-assistant backups share), sanoid, shutdown_tracker, Tailscale |
| `offsite-pikvm` | Pi (armv7l, 6.12 rpi kernel) | PiKVM for `offsite-nas` remote power | PiKVM stack, Tailscale, ACME via Tailscale cert |
