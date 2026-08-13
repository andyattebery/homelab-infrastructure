#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $(basename "$0") [-n|--dry-run] [-r|--reboot] <hostname>"
    echo
    echo "Deploy a NixOS host via deploy-rs."
    echo
    echo "Options:"
    echo "  -n, --dry-run   Show what would change, then exit without activating"
    echo "  -r, --reboot    Reboot the host after deploy if the system closure changed"
    echo
    echo "Examples:"
    echo "  $(basename "$0") network-01"
    echo "  $(basename "$0") --dry-run network-01"
    echo "  $(basename "$0") --reboot network-01"
    exit 1
}

REBOOT=false
DRY_RUN=false
HOSTNAME=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -r|--reboot)
            REBOOT=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            echo "Unknown option: $1"
            usage
            ;;
        *)
            if [[ -n "$HOSTNAME" ]]; then
                echo "Error: multiple hostnames specified"
                usage
            fi
            HOSTNAME="$1"
            shift
            ;;
    esac
done

if [[ -z "$HOSTNAME" ]]; then
    echo "Error: no hostname specified"
    usage
fi

DOMAIN=$(grep 'domainName' "$SCRIPT_DIR/../secrets/vars.nix" | sed 's/.*= *"\(.*\)".*/\1/')
FQDN="${HOSTNAME}.${DOMAIN}"

# Preview first, ALWAYS -- with or without --dry-run. `nh os build` returns before
# activation, so this only builds and diffs.
#
# Deliberately NOT `deploy --dry-activate`, which would also produce the closure but
# additionally runs the dry-activation script -- and that is not a simulation: snippets
# declaring supportsDryActivation execute for real. sops-nix does, printing
# "Imported ... as age key" on every single run. A plain build produces the closure the
# diff needs and nothing else.
#
# --build-host and --target-host MUST both be set and identical. With --target-host
# omitted nh diffs against the LOCAL /run/current-system and copies the built closure
# back; with both set it diffs on the host and leaves the closure there, which is also
# what the subsequent deploy-rs deploy needs. Dropping --target-host does not error --
# it silently diffs the wrong machine.
#
# services@ matches deploy.nodes.<host>.sshUser in flake.nix.
#
# -R because nh refuses to run as root and the nix-shell.sh container is root.
# --diff always because `auto` silently skips when it cannot find a local profile.
# --no-nom keeps output predictable; drop it for nix-output-monitor's progress display.
#
# nh is pinned to the flake's own nixpkgs so the diff tool cannot drift from what is
# being deployed. Flags verified against nh 4.4.2; re-check after a nixpkgs bump.
#
# Follow root.inputs.nixpkgs to its node rather than hardcoding a node name -- the node
# is currently "nixpkgs_2" (the one named "nixpkgs" belongs to nixos-raspberrypi) and
# those suffixes get renumbered when inputs are added or removed.
NIXPKGS_REV=$(jq -r '.nodes[.nodes.root.inputs.nixpkgs].locked.rev' "$SCRIPT_DIR/../flake.lock")

echo "Building $HOSTNAME without activating..."
"$SCRIPT_DIR/nix-shell.sh" --ssh run "github:NixOS/nixpkgs/$NIXPKGS_REV#nh" -- \
    os build . \
    -H "$HOSTNAME" \
    --build-host  "services@$FQDN" \
    --target-host "services@$FQDN" \
    --diff always --no-nom -R
echo

if [[ "$DRY_RUN" == "true" ]]; then
    echo "Dry run only — nothing was activated. Re-run without --dry-run to deploy."
    exit 0
fi

echo "Deploying $HOSTNAME..."
"$SCRIPT_DIR/nix-shell.sh" --ssh run .#deploy-rs -- ".#$HOSTNAME"
echo "Deploy complete."

# Compare only the boot-relevant parts, which is what actually requires a reboot --
# a userspace-only change does not.
#
# The previous check compared `readlink /run/booted-system` against
# `readlink /nix/var/nix/profiles/system` and ALWAYS reported "reboot required",
# for two independent reasons:
#   1. readlink resolves one level, so the first yields a store path while the
#      second yields "system-NN-link".
#   2. Even fully resolved they differ, because deploy-rs points the profile at its
#      `activatable-nixos-system-...` wrapper while /run/booted-system points at the
#      plain toplevel. Those are different store paths by construction.
# Verified on network-03: this version reports "no reboot needed" on a host already
# booted into the deployed kernel, where the old one said reboot required.
NEEDS_REBOOT=$(ssh "$FQDN" 'bash -c "
    booted=\$(readlink -f /run/booted-system/{initrd,kernel,kernel-modules} 2>/dev/null)
    current=\$(readlink -f /run/current-system/{initrd,kernel,kernel-modules} 2>/dev/null)
    if [ \"\$booted\" != \"\$current\" ]; then echo yes; else echo no; fi
"')

if [[ "$NEEDS_REBOOT" == "yes" ]]; then
    if [[ "$REBOOT" == "true" ]]; then
        echo "System closure changed — rebooting $HOSTNAME..."
        ssh "$FQDN" 'sudo reboot' || true
        echo "Waiting for $HOSTNAME to come back..."
        sleep 10
        timeout=300
        elapsed=0
        until ssh -o ConnectTimeout=5 -o BatchMode=yes "$FQDN" true 2>/dev/null; do
            sleep 5
            elapsed=$((elapsed + 5))
            if [[ $elapsed -ge $timeout ]]; then
                echo "Error: $HOSTNAME did not come back after ${timeout}s"
                exit 1
            fi
        done
        echo "$HOSTNAME is back online."
    else
        echo "Reboot required — booted system differs from current profile. Run with --reboot to reboot automatically."
    fi
else
    echo "No reboot needed — booted system matches current profile."
fi
