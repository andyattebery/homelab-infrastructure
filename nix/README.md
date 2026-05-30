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
        vars.nix                # eval-time values (placeholders in git, real values via populate + sync-vars.sh)
        vars.nix.tpl            # 1Password references for eval-time values
      scripts/
        populate-secrets-from-op.sh  # generates secrets.yaml, vars.nix, ssh-keys.nix from 1Password
        install-proxmox-template.sh  # unattended NixOS install for Proxmox template VM
        add-host.sh                  # run on Mac: generates host config + flake entry (called by provision-host.sh)
        provision-host.sh            # end-to-end: template clone → running host in one command
        sync-vars.sh                 # scps vars.nix to a host (real values, not placeholders)
        nix-shell.sh                 # runs Nix commands via Docker (no Nix install needed)

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
- **`vars.nix`**: Committed with placeholder values. Flakes require tracked files, so it can't be gitignored. After populating with real values locally, use `git update-index --assume-unchanged nix/secrets/vars.nix` to hide the diff. Transfer real values to hosts via `scripts/sync-vars.sh <hostname>`.
- **`ssh-keys.nix`**: Committed with real values. Hosts get these via `git pull`.

The age private key for sops encryption is stored in 1Password. The populate script uses `op run` to inject it at runtime -- no key file on disk.

To push `vars.nix` (with real values) to a host before rebuild:

```sh
nix/scripts/sync-vars.sh <hostname>
```

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
```

## Day-to-day workflow

```sh
# Mac: edit config, commit, push
vim nix/hosts/network-03/default.nix
git commit && git push

# Mac: deploy
nix/scripts/deploy-host.sh network-03 network-03
```
