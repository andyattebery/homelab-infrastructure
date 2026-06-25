# NixOS Configuration

NixOS host management for the homelab, running alongside the existing Ansible setup.

## Directory structure

    nix/
      flake.nix                 # entry point -- inputs, host definitions
      flake.lock                # pinned dependency versions
      modules/
        base.nix                # common config for all hosts (users, SSH, packages)
        docker-host.nix         # services.docker-compose module for Docker Compose stacks
        network.nix             # network host role (AdGuard Home, keepalived, WireGuard, etc.)
        proxmox-guest.nix       # QEMU guest agent + auto disk resize + serial console
        tailscale.nix           # Tailscale with IP forwarding
        monitoring.nix          # Prometheus node_exporter
        ssh-keys.nix            # shared SSH public keys (generated from ssh-keys.nix.tpl)
        ssh-keys.nix.tpl        # 1Password references for SSH keys
        compose/                # Docker Compose files and templates used by modules
      hosts/
        proxmox-vm-hardware.nix # shared hardware config for Proxmox VMs
        proxmox-template/       # minimal bootstrap config for the Proxmox template
        network-03/             # network-03 host config
      secrets/
        .sops.yaml              # age key list + sops creation rules
        secrets.yaml            # sops-encrypted secrets (commit this)
        secrets.yaml.tpl        # 1Password references for secrets
        vars.nix                # eval-time values (placeholders in git, real values via populate-secrets-from-op.sh)
        vars.nix.tpl            # 1Password references for eval-time values
      scripts/
        deploy-host.sh                   # deploy a host via deploy-rs, with optional reboot
        nix-shell.sh                     # runs Nix commands via Docker (no Nix install needed)
        populate-secrets-from-op.sh      # generates secrets.yaml, vars.nix, ssh-keys.nix from 1Password
        install-proxmox-template.sh      # unattended NixOS install for Proxmox template VM
        add-host.sh                      # run on Mac: generates host config + flake entry
        update-packages.sh               # updates custom Nix packages to latest GitHub releases
        legacy/                          # pre-deploy-rs scripts (SSH + git pull + nixos-rebuild)

## How the flake works

`flake.nix` defines a `mkHost` helper that wires up shared config for each host:

```nix
mkHost = hostname: extraModules: nixpkgs.lib.nixosSystem {
  system = "x86_64-linux";
  specialArgs = { inherit sops-nix; vars = import ./secrets/vars.nix; };
  modules = [
    sops-nix.nixosModules.sops
    ./modules/base.nix
    ./modules/monitoring.nix
    ./hosts/${hostname}
  ] ++ extraModules;
};
```

Each host gets `base.nix` and `monitoring.nix` automatically. Role modules (`tailscale.nix`, `docker-host.nix`, `network.nix`) are added per-host via `extraModules`. Host-specific config lives in `hosts/<hostname>/default.nix`.

`vars` (from `secrets/vars.nix`) provides infrastructure values at Nix eval time -- domain name, subnet CIDR, DNS VIP, ACME email. These are available in any module via `{ vars, ... }:` in the function args.

## Secrets

Three categories, all populated by `scripts/populate-secrets-from-op.sh`:

| File | What | How it's used |
|---|---|---|
| `secrets.yaml` | Credentials (API tokens, passwords, WireGuard config) | sops-encrypted. Decrypted at boot by sops-nix to `/run/secrets/`. |
| `vars.nix` | Infrastructure values (domain, subnet, VIP, email) | Plain Nix. Read at eval time via `specialArgs`. Committed with placeholders, overwritten locally by the populate script. |
| `ssh-keys.nix` | SSH public keys | Plain Nix. Imported by `base.nix` and `proxmox-template`. Committed with real values (public keys aren't secret). |

After running `populate-secrets-from-op.sh`:

- **`secrets.yaml`**: Commit the sops-encrypted file. It's safe for public repos -- only age key holders can decrypt.
- **`vars.nix`**: Committed with placeholder values. Flakes require tracked files, so it can't be gitignored. After populating with real values locally, use `git update-index --assume-unchanged nix/secrets/vars.nix` to hide the diff. deploy-rs bakes these values into the derivation at eval time -- no need to transfer them to hosts.
- **`ssh-keys.nix`**: Committed with real values.

The age private key for sops encryption is stored in 1Password. The populate script uses `op run` to inject it at runtime -- no key file on disk.

## Docker Compose

The `services.docker-compose` module (defined in `docker-host.nix`) manages Docker Compose stacks as systemd services. Each stack is its own compose project with its own working directory.

```nix
services.docker-compose.immich = {
  composeFile = ./compose/docker-compose-immich.yaml;
  environmentFiles = [ config.sops.secrets."immich-env".path ];
};
```

Default environment variables (`PUID`, `PGID`, `DOCKER_GID`, `TZ`, `DOMAIN_NAME`, `DOCKER_DATA_DIRECTORY`) are injected into every stack automatically.

Compose files are referenced from the Ansible roles where possible (no duplication):

```nix
composeFile = ../../ansible/roles/docker_compose_wireguard/files/docker-compose-wireguard.yaml;
```

`dcup` is generated per-host: pulls all images one service at a time, restarts each stack, prunes. Run with `sudo dcup`.

## Running Nix from Mac

Nix is not installed on the Mac. All Nix commands run in Docker via `scripts/nix-shell.sh`:

```sh
nix/scripts/nix-shell.sh flake check       # validate
nix/scripts/nix-shell.sh flake update      # update dependencies
nix/scripts/nix-shell.sh flake show        # show outputs
nix/scripts/nix-shell.sh --x86 build ...   # x86 build (slow, QEMU emulation)
nix/scripts/nix-shell.sh --ssh run ...     # run with SSH agent forwarding (for deploy-rs)
```

## Deploying with deploy-rs

Deployments use [deploy-rs](https://github.com/serokell/deploy-rs) via the Docker wrapper. deploy-rs evaluates the flake locally, sends the derivation to the host, the host builds it natively, and deploy-rs activates the new configuration. If activation breaks SSH connectivity, deploy-rs automatically reverts to the previous generation (magic rollback).

### Deploy a single host

```sh
nix/scripts/deploy-host.sh network-03
```

### Deploy with reboot (kernel upgrades, dbus-broker binary changes, etc.)

```sh
nix/scripts/deploy-host.sh --reboot network-03
```

After activation succeeds, `--reboot` compares `/run/booted-system` to `/nix/var/nix/profiles/system`. If they differ, the host is rebooted and the script waits for SSH to come back.

### Deploy all hosts

```sh
nix/scripts/deploy-host.sh network-01
nix/scripts/deploy-host.sh network-03
nix/scripts/deploy-host.sh pi-rack
```

### How it works

1. `nix-shell.sh --ssh` starts a Docker container with the repo mounted and SSH agent forwarded
2. deploy-rs evaluates the flake inside the container, reading `vars.nix` (with real values) at eval time
3. The derivation is sent to the target host via SSH
4. The host builds the derivation natively (`remoteBuild = true`), fetching from cache.nixos.org as needed
5. deploy-rs activates the new configuration and verifies SSH connectivity
6. If SSH fails post-activation, the previous generation is automatically restored

No git repo, `vars.nix` SCP, or `git pull` needed on the host.

## Provisioning a new host

1. Clone the Proxmox template VM
2. Generate an age key and scaffold the host config:

```sh
nix/scripts/legacy/provision-host.sh [--proxmox] [--tailscale] root@<ip> <hostname>
```

3. The script generates the age key, adds it to `.sops.yaml`, scaffolds host config via `add-host.sh`, populates secrets, commits and pushes
4. Deploy the new host:

```sh
nix/scripts/deploy-host.sh <hostname>
```

## Upgrading hosts

### Update flake inputs (routine)

Updates nixpkgs, sops-nix, dsm, nim, nixos-hardware, deploy-rs, and custom packages to their latest versions within the current NixOS release.

```sh
# Update all flake inputs
nix/scripts/nix-shell.sh flake update

# Update custom packages (keepalived-exporter, adguardhome-sync)
nix/scripts/update-packages.sh

# Validate
nix/scripts/nix-shell.sh flake check

# Commit
git add nix/flake.lock nix/pkgs/
git commit -m "nix: update flake inputs"
```

Then deploy to each host:

```sh
nix/scripts/deploy-host.sh network-01
nix/scripts/deploy-host.sh network-03
nix/scripts/deploy-host.sh pi-rack
```

### NixOS release upgrade (e.g. 26.05 → 26.11)

1. Edit `flake.nix` — change `nixpkgs.url` to the new branch (e.g. `github:NixOS/nixpkgs/nixos-26.11`)
2. Update lock: `nix/scripts/nix-shell.sh flake update`
3. Check release notes for breaking changes relevant to your modules
4. Validate: `nix/scripts/nix-shell.sh flake check`
5. Commit, then deploy one host at a time starting with the least critical
6. Verify each host's services after deploy (check logs, not just status)

### Secrets refresh (if needed before deploy)

If 1Password secrets changed, regenerate before deploying:

```sh
nix/scripts/populate-secrets-from-op.sh
# Commit secrets.yaml / ssh-keys.nix if they changed
```

`vars.nix` values are baked into the derivation at eval time — no manual sync to hosts needed.

## Legacy scripts

Pre-deploy-rs scripts in `scripts/legacy/`. These SSH into hosts, run `git pull`, SCP `vars.nix`, and run `nixos-rebuild switch` on-host. They require the repo to be cloned on each host at `/root/homelab-infrastructure`.

```sh
nix/scripts/legacy/deploy-host.sh <ssh-target> <hostname>    # deploy via SSH + nixos-rebuild
nix/scripts/legacy/sync-vars.sh <user@host> [repo-path]      # SCP vars.nix to a host
nix/scripts/legacy/provision-host.sh [--proxmox] [--tailscale] <ssh-target> <hostname>  # full provisioning
```
