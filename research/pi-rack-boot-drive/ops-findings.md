# Operational findings from this investigation

Repo and tooling facts checked on 2026-09-25 that matter when pi-rack is rebuilt on new hardware.

## A new board means a new MAC, and NIM won't clean up the old one

- pi-rack's fixed IP comes from `network-inventory/network_hosts_inventory.yaml.tpl:29-31`: `ip:
  192.168.1.226`, `mac: {{ op://Home Lab/pi-rack/hardware/mac address }}`, no `skip_dhcp`.
- NIM runs on network-01. It reads that template **from GitHub**
  (`configRepo = "andyattebery/homelab-infrastructure"`) and resolves `op://` refs via a 1Password
  service account, every `syncInterval = 1800` s (`nix/hosts/network-01/default.nix:126-128`).
- NIM's UniFi output only **creates or updates** reservations keyed by MAC. It never deletes or
  unsets one (`network_inventory_manager/outputs/unifi.py:26-92`).
- **Procedure for a board swap:**
  1. In UniFi, clear the fixed IP on the old board's client.
  2. Set `op://Home Lab/pi-rack/hardware/mac address` to the new board's **Ethernet** MAC.
  3. Wait for NIM's next sync (≤ 30 min), or set the same fixed IP in the UI.
- A WiFi MAC and an Ethernet MAC on the same Pi differ, so reusing a board that was on WiFi
  doesn't collide with its old reservation.

## NUT clients need no change

All seven server accounts in `nix/modules/nut.nix` read `op://Home Lab/pi-rack/nut/<name>
password` (`nix/secrets/secrets.yaml.tpl:26-32`). The Ansible clients read the same fields:
`host_vars/{nas-host-01,vm-host-01,vm-host-02,backup-01}/vault.yaml.tpl` and
`group_vars/all/vault.yaml.tpl:199-201`. Usernames match.

## Secrets state

- `nix/secrets/.sops.yaml` anchors: `operator`, `network-01`, `network-03`. **pi-rack is not yet a
  recipient**; `secrets.yaml` has 3 recipient blocks.
- `age-keygen` is now installed on the Mac (`/opt/homebrew/bin/age-keygen`), so the old "blocked
  on brew install age" note is resolved.
- `tailscale-auth-key` is the same 1Password field as Ansible's `vault_tailscale_authkey`
  (`op://Personal/Tailscale/auth keys/ansible artis3n.tailscale.machine`). pikvm-hid used it
  successfully on 2026-09-25.
- `populate-secrets-from-op.sh` re-injects every value. If the Cloudflare token leaked in the
  pikvm task is rotated, `secrets.yaml` changes for network-01 and network-03 too, and they need a
  deploy to pick it up.

## `deploy-host.sh` specifics

- It uses `ssh-ng://services@<fqdn>`: `nix copy --derivation`, then `nix build --eval-store auto
  --store …`, then runs `nix run github:NixOS/nixpkgs/<nixpkgs-unstable rev>#dix` **on the host**,
  so the host needs flakes plus internet. Then deploy-rs with magic rollback.
- `nix-shell.sh --ssh` mounts `~/.ssh` **read-only** in the container, so it can't record a new
  host key. Run `ssh services@pi-rack.<domain_name> true` once from the Mac after a re-image.
- `host-age-key.sh --target` must use `services@…`, not `root@…` (`PermitRootLogin = "no"`).

## Tooling checks

- `nix store cat` exists in the pinned `nixos/nix:2.35.2` image. It can copy a built image out of
  the Docker-volume store: `nix-shell.sh store cat <out>/sd-image/<name>.img.zst </dev/null > file`.
- `zstd` is on the Mac (`/opt/homebrew/bin/zstd`). `smartctl` is not.
- The Ansible inventory has no `groups['network']` / `groups['homelab']` consumers in templates or
  playbooks, so dropping pi-rack / network-02 from those groups affects nothing else.
- Prometheus keeps pi-rack series only from 2026-09-10. Anything older must come from Scrutiny or
  the host's own journal.

## Monitoring gaps this failure exposed

- Nothing alerted when Scrutiny flagged SMART 199 (status 2 by 2026-08-28).
- Nothing alerted when `scrutiny-collector.service` started failing on every run (from
  2026-09-16).
- Both went unnoticed for weeks.
