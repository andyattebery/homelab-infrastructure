# Homelab specifics for the Turing Pi cluster

Researched 2026-09-26 from this repo, `network-inventory-manager`, and the owner's answers.

## Fixed IPs

- The UniFi dynamic pool is `192.168.1.10–.159` (owner). Everything from `.160` up is outside it.
- `network-inventory/network_hosts_inventory.yaml.tpl` already has a Turing Pi block. None of these entries has a `mac:`.

| IP | Entry | Now |
|---|---|---|
| .215 | `turingpi` | the BMC |
| .216 | `turingpi-rk1-01` | RK1; last ran Ubuntu, per the commented-out `[turingpi]` inventory group |
| .217 | `turingpi-rk1-02` | RK1 |
| .218 | `turingpi-cm4-01` | CM4 |
| .219 | `turingpi-cm4-02` | stale [I]: the owner now has one Turing Pi CM4, and pi-rack moved to a CM4 on 2026-09-25 |

- `.220–.223` have no entry, and `.224` is network-01. `.220` is the proposed API VIP.
- `.160–.170` is the other free block outside the pool.

## How NIM applies the inventory

- **Reservations go to UniFi**, only for entries with a `mac` and no `skip_dhcp` (`network-inventory-manager/network_inventory_manager/sync.py:92-96`). The user guide (`docs/user-guide.md:48`): "A DHCP reservation in UniFi (if `mac` is present and `skip_dhcp` is not `true`)".
- **MAC-less entries** get a DNS rewrite and an AdGuard client entry only.
- **NIM runs on network-01** and reads the `.tpl` from GitHub (`nix/hosts/network-01/default.nix:127`) every 1800 s. A change applies only after it is pushed.
- **Reservations are never deleted.** The UniFi output "only creates and updates reservations and never deletes" (user guide).
- **Stale README.** `ansible/roles/docker_compose_network_inventory_manager/README.md` says reservations go to AdGuard and that UniFi is read-only. That is stale.
- **Adding a MAC.** `network-inventory/add_host.sh <host> <ip> <mac>` writes the MAC to a 1Password item (`hardware/mac address`) and to the `.tpl`. It needs `OP_SERVICE_ACCOUNT_TOKEN`.

## Vaulted values that shape the design

- **The DNS VIP is vaulted:** `nix/secrets/vars.nix.tpl:4` (`op://Home Lab/Home Lab/dns/vip`) and `ansible/group_vars/all/vars.yaml:82` (`vault_dns_server_vip`). MACs live in 1Password.
- A Talos static-address patch needs nameservers, so it can't be committed. Nodes run DHCP with UniFi reservations instead.
- The internal domain is secret too, so the Kubernetes endpoint is the VIP's IP, not a name under the domain.

## jetson-01 today

- `ansible/playbook-jetson-01.yaml` runs `node_exporter` and a compose stack from `ansible/files/jetson-01/docker-compose-home-assistant-wyoming.yml`: Wyoming faster-whisper (:10300) and piper (:10200) for Home Assistant (`hardware/host-inventory.md`).
- It is in the inventory at 192.168.1.193, with a MAC reservation.
- It did not answer the 2026-09-06 audit.
- Moving the Orin into the cluster in any form ends those two services unless they move. media-01 already runs a Whisper, per `hardware/host-inventory.md`.

## Earlier attempts in the repo

- A commented-out `[turingpi]` inventory group (rk1-01/02 with `ansible_user=ubuntu`, cm4-01/02) and `ansible/playbook-turingpi.yaml` (`configure_server`, `system_upgrade`).
- `ansible/playbook-pi-cluster.yaml`: k3s on six Pis (`pi-cluster-0[1:6]`, legacy, group commented out).
- `talos/` from 2026-02-15 (`talos/pi-cluster/` and a 1.8.0 Raspberry Pi image). The owner wants it wiped.

## Local tooling (2026-09-26)

- `kubectl` 1.33.9 at `/usr/local/bin`, outside the skew for Kubernetes 1.37.
- `talosctl`, `helm` and `tpi` are not installed. `mise` and `op` are.
- The mise precedent is `ansible/mise.toml`: a directory-scoped config that pins tools and creates its own venv.
