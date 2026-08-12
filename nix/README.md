# NixOS Configuration

NixOS host management for the homelab, running alongside the existing Ansible setup.

## Directory structure

    nix/
      flake.nix                 # entry point -- inputs, mkHost, derived nixosConfigurations + deploy.nodes
      flake.lock                # pinned dependency versions
      modules/
        base.nix                # foundation: everything every host gets (users, SSH, sops, node_exporter, beszel)
        tailscale.nix           # capability: Tailscale with routing features
        nut.nix                 # capability: NUT UPS server + its Prometheus exporter
        docker-host.nix         # capability: services.docker-compose + Diun (no host imports it yet)
        network.nix             # stack bundle: AdGuard Home + keepalived + ACME (+ nginx)
        proxmox-guest.nix       # hardware: QEMU guest agent, grub, growPartition
        rpi4.nix                # hardware: Raspberry Pi 4 on-disk layout
        ssh-keys.nix            # shared SSH public keys (generated from ssh-keys.nix.tpl)
        ssh-keys.nix.tpl        # 1Password references for SSH keys
        compose/                # empty; kept for Compose files referenced by docker-host.nix
      hosts/                    # one directory per host -- this listing IS the host list
        proxmox-vm-hardware.nix # shared hardware config for Proxmox VMs (a file, not a host)
        proxmox-template/       # minimal bootstrap config for the Proxmox template
        network-01/             # AdGuard primary, adguardhome-sync, network-inventory-manager
        network-03/             # AdGuard replica
        pi-rack/                # Raspberry Pi 4: AdGuard replica + NUT server
      pkgs/                     # custom packages (adguardhome-sync, keepalived-exporter)
      docs/                     # raspberry-pi.md, proxmox-workflow.md
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
        add-host.sh                      # run on Mac: scaffolds a host config, key and sops recipient
        host-age-key.sh                  # create/install a host's age key, stored in 1Password
        add-sops-recipient.sh            # add an age key to .sops.yaml and re-encrypt
        update.sh                        # bump the Nix image pin + all flake inputs, then check
        update-packages.sh               # updates custom Nix packages to latest GitHub releases
        legacy/                          # pre-deploy-rs scripts (SSH + git pull + nixos-rebuild)

## How the flake works

**The host list is the `hosts/` directory.** `flake.nix` does not name hosts; it reads them:

```nix
hostDirs     = lib.filterAttrs (_: type: type == "directory") (builtins.readDir ./hosts);
managedHosts = builtins.removeAttrs hostDirs [ "proxmox-template" ];

mkHost = hostname: lib.nixosSystem {
  specialArgs = { inherit sops-nix nixpkgs-unstable vars nixos-raspberrypi dsm nim; };
  modules = [ ./modules/base.nix ./hosts/${hostname} ];
};

nixosConfigurations = (builtins.mapAttrs (hostname: _: mkHost hostname) managedHosts) // { … };
deploy.nodes        = builtins.mapAttrs (hostname: _: { … }) managedHosts;
```

So **adding a host means adding a directory under `hosts/`** — there is no list to keep in sync,
and no marker comment for a script to `sed` against. `deploy.nodes` is derived the same way, taking
each host's architecture from its own evaluated `nixpkgs.hostPlatform`. `mapAttrs` is lazy per
attribute and deploy-rs narrows `nodes` to the one node being deployed before serialising it, so
`deploy .#some-host` never forces the others.

`proxmox-template` is the one exception, defined by hand: it is a bare bootstrap image with root SSH
and deliberately no `base.nix`, no sops and no `services` user. Excluding it from `managedHosts` also
keeps it out of `deploy.nodes`, so it can never become a deploy target.

### Where a module goes

Four kinds, each with one home. Put a new module in the wrong one and it either gets forced on hosts
that do not want it, or silently missing from hosts that do.

| Kind | Examples | Chosen by | Lives in |
|---|---|---|---|
| **Foundation** — every host, no opting out | `base.nix` | nobody | `mkHost`'s module list |
| **Capability** — any host could opt in | `tailscale.nix`, `nut.nix`, `docker-host.nix`, `dsm-provider` | the host | the host file's `imports` |
| **Hardware** | `rpi4.nix`, `proxmox-guest.nix`, `proxmox-vm-hardware.nix` | the machine | the host file's `imports` |
| **Stack bundle** — capabilities as one unit | `network.nix` | the host, as one unit | the host file's `imports` |

If a host could reasonably decline it, it is a capability and does not belong in `base.nix`.

Modules from flake inputs (`dsm`, `nim`, `nixos-raspberrypi`) arrive through `specialArgs`, which
reaches a module before evaluation and so may be used in that module's own `imports` — by a host file
or by another module.

**A stack bundle imports its own dependencies.** `network.nix` configures `tailscale.nix` and
`dsm-provider` unconditionally, so it imports both, and a host gets them by importing `network.nix`
without having to know they are involved. `docker-host.nix` imports `dsm-provider` for the same
reason. Both stay opt-in capabilities in their own right: a host wanting Tailscale or dashboard
entries without the AdGuard stack imports them directly.

Importing `dsm-provider` from two places at once is safe because its exported module carries an
explicit `key`. That is not automatic — a flake module exported as a bare function gets a fresh dedup
key per import site, so a second import re-declares its options and evaluation fails. Only a path, or
an explicit `key`, dedups. Worth knowing before importing any flake's module from more than one place.

`tailscale.nix` still needs `base.nix` for `pkgs-unstable`, which `mkHost` always supplies.

`vars` (from `secrets/vars.nix`) provides infrastructure values at Nix eval time -- domain name, subnet CIDR, DNS VIP, ACME email. These are available in any module via `{ vars, ... }:` in the function args.

## Secrets

Three categories, all populated by `scripts/populate-secrets-from-op.sh`:

| File | What | How it's used |
|---|---|---|
| `secrets.yaml` | Credentials — the services user's password hash, Tailscale auth key, Cloudflare token, AdGuard/NIM/beszel/Pushover/NUT passwords | sops-encrypted. Decrypted at boot by sops-nix to `/run/secrets/`. |
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

Nix is not installed on the Mac. Docker (OrbStack) must be running. Three CLI tools come from
Homebrew and the scripts check for them: `op` and `sops` (`populate-secrets-from-op.sh`) and `age`
(`host-age-key.sh`, `brew install age`).

A host's age key lives in 1Password as a `nix` section on the host's own item, beside whatever else
that item already holds, in **two single-line fields**:

    op://Home Lab/<hostname>/nix/age key           AGE-SECRET-KEY-...
    op://Home Lab/<hostname>/nix/age public key    age1...

Split rather than storing `age-keygen`'s three-line output verbatim because those fields flatten
newlines — and a flattened key file is one line starting with `#`, which age reads as a comment, so
it would contain no identity at all and sops-nix would fail to decrypt on that host. Keeping the
public half as its own field also means it never has to be derived back out of the secret.
`host-age-key.sh` rebuilds a proper two-line file when it installs the key.

All Nix commands run in Docker via `scripts/nix-shell.sh`:

```sh
nix/scripts/nix-shell.sh flake check       # validate
nix/scripts/nix-shell.sh flake update      # update dependencies
nix/scripts/nix-shell.sh flake show        # show outputs
nix/scripts/nix-shell.sh --x86 build ...   # x86 build (slow, QEMU emulation)
nix/scripts/nix-shell.sh --ssh run ...     # run with SSH agent forwarding (for deploy-rs)
```

The `nixos/nix` image is **pinned** in `scripts/nix-image` (tracked in git, so the Nix version
shows up in `git diff` next to `flake.lock`). `update.sh` bumps this pin to the current release
alongside the flake inputs. The wrapper caches the Nix store in a per-image Docker volume
(`nix-store`, `nix-store-amd64`) labelled with the pin; when the pin changes it recreates the
volume automatically (re-downloading the cached store once). No manual volume management.

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

1. Get the machine booted and reachable over SSH with passwordless sudo — clone the Proxmox template
   VM, or flash an image for bare metal.
2. Scaffold it:

```sh
nix/scripts/add-host.sh --proxmox --tailscale --target root@<ip> <hostname>
```

   This creates `hosts/<hostname>/default.nix`, generates the host's age key locally, stores it in
   1Password, installs it at `/var/lib/sops-nix/key.txt`, adds it to `.sops.yaml` in both required
   places, and re-encrypts `secrets.yaml`. It does **not** touch `flake.nix` — creating the directory
   is what registers the host. It runs no git commands; staging and committing are yours.

   If the machine does not exist yet, `nix/scripts/host-age-key.sh <hostname>` creates and stores the
   key on its own, and prints the public half to pass to `add-host.sh` positionally. Install it later
   with `host-age-key.sh --target <ssh-target> <hostname>`.

3. Add capability modules to `hosts/<hostname>/default.nix` — see "Where a module goes" above.
4. Validate and deploy:

```sh
nix/scripts/nix-shell.sh flake check
nix/scripts/deploy-host.sh <hostname>
```

**If `add-host.sh` fails partway** — most likely `populate-secrets-from-op.sh` without 1Password auth
— it prints what to clean up. The host directory and the `.sops.yaml` edit both survive the failure,
and re-running refuses until they are removed, which is deliberate.

### Re-imaging an existing host

`add-host.sh` refuses when `hosts/<name>/` exists, and it should — the config is already right. Only
the key needs restoring, and because it is in 1Password it is the *same* key, so `.sops.yaml` and
`secrets.yaml` do not change at all:

```sh
nix/scripts/host-age-key.sh --target root@<ip> <hostname>
```

## Upgrading hosts

### Update flake inputs (routine)

Updates nixpkgs, nixpkgs-unstable, sops-nix, dsm, nim, nixos-hardware, deploy-rs, nixos-raspberrypi
and the custom packages to their latest versions within the current NixOS release.

`update.sh` does all of it, including bumping the pinned Nix image in `scripts/nix-image`:

```sh
nix/scripts/update.sh
```

Or step by step:

```sh
nix/scripts/nix-shell.sh flake update      # all inputs
nix/scripts/update-packages.sh             # keepalived-exporter, adguardhome-sync
nix/scripts/nix-shell.sh flake check       # validate
git add nix/flake.lock nix/pkgs/ nix/scripts/nix-image
```

Stage only — committing is done by hand, never by a script here.

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

`provision-host.sh` is superseded by `add-host.sh --target`. It still contains its own inline
`age-keygen` block, which generates the key **on the host** — so the key exists only on that disk and
is lost on a re-image. It also commits and pushes, which this repo does not do. Do not use it for new
hosts; it is kept only as a record of the pre-deploy-rs flow.
