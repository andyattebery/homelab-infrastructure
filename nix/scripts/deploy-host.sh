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

# Before reading domainName: a placeholder vars.nix yields "example.com", so every ssh
# and store URL below would silently target <host>.example.com and fail looking like DNS.
"$SCRIPT_DIR"/check-secrets.sh

DOMAIN=$(grep 'domainName' "$SCRIPT_DIR/../secrets/vars.nix" | sed 's/.*= *"\(.*\)".*/\1/')
FQDN="${HOSTNAME}.${DOMAIN}"

# Preview first, ALWAYS -- with or without --dry-run.
#
# Deliberately NOT `deploy --dry-activate`, which would also produce the closure but
# additionally runs the dry-activation script -- and that is not a simulation: snippets
# declaring supportsDryActivation execute for real. sops-nix does, printing
# "Imported ... as age key" on every single run. A plain build produces the closure the
# diff needs and nothing else.
#
# NOT `nh os build` either, though it was used here until 2026-09-10. nh 4.4.2 deadlocks
# on large diffs: nh-remote/src/remote.rs:1664-1690 gives ssh BOTH .stdout(Redirection::Pipe)
# and .stderr(Redirection::Pipe), then waits for the process to exit before reading either.
# Past 64 KiB of build output nothing drains the pipe and the deploy hangs forever -- 27
# minutes on network-03 and again on network-01, both times after the build had finished.
# The capture below reads continuously, so it cannot deadlock the same way.
#
# --eval-store auto evaluates HERE and --store ssh-ng://... builds THERE, the same split
# deploy-rs uses for remoteBuild. Evaluation has to be local: the host has neither the
# flake nor secrets/vars.nix, so it cannot evaluate its own configuration.
#
# The derivation must be copied first or the build fails with "don't know how to build
# these paths" -- verified on network-01. -s makes the host pull dependencies from
# substituters instead of having them pushed over ssh from here.
#
# Not wasted work: the activatable-* wrapper the real deploy builds references this
# toplevel directly, so only two small activate scripts remain to realise afterwards.
REF=".#nixosConfigurations.$HOSTNAME.config.system.build.toplevel"
# services@ matches deploy.nodes.<host>.sshUser in flake.nix. The other ssh calls here
# use a bare $FQDN and rely on ssh config; the store URL has to name the user.
STORE="ssh-ng://services@$FQDN"

echo "Building $HOSTNAME without activating..."
"$SCRIPT_DIR/nix-shell.sh" --ssh copy -s --to "$STORE" --derivation "$REF"

# --json rather than --print-out-paths: `nix build --help` documents it as "suitable for
# consumption by another program", and a corrupted stream makes jq fail loudly instead of
# returning a plausible-looking string. No line-position guessing either.
#
# </dev/null because nix-shell.sh adds `docker run -it` when stdin is a TTY
# (nix-shell.sh:51). A data capture should not vary with how the script was invoked.
#
# --no-link is deliberate: per the nix manual the result symlink is what registers a GC
# root, so omitting it means "only looking, do not pin this on the host". If the deploy
# follows, deploy-rs roots the system properly; if it does not, the closure stays
# reclaimable. The trade is that a GC in between costs a rebuild, never correctness.
NEW=$("$SCRIPT_DIR/nix-shell.sh" --ssh build "$REF" \
    --eval-store auto --store "$STORE" \
    --json --no-link </dev/null | jq -r '.[0].outputs.out')

# Anchored at BOTH ends. Start-anchored only would let a trailing ANSI escape through,
# and trailing is the real case -- a reset (\033[0m) is emitted at the end of coloured
# output, which is what produced a confusing remote shell parse error once.
if [[ ! "$NEW" =~ ^/nix/store/[a-z0-9]{32}-[a-zA-Z0-9.:_+?=-]+$ ]]; then
    echo "Error: could not determine the new system path for $HOSTNAME"
    echo "  got: $NEW"
    exit 1
fi

echo
# dix rather than `nix store diff-closures`: it drops size-only entries carrying no
# version, groups multiple outputs, aligns columns and prints closure totals.
#
# The two marker characters are independent (crates/dix/src/render.rs:190-223): the first
# is the diff status (U upgraded, D downgraded, C changed or mixed, A added, R removed),
# the second is SELECTION status (* selected, + newly selected, . unselected, - newly
# unselected). So [U*] means "upgraded and selected", i.e. a top-level package rather than
# a transitive dependency. It says nothing about how large the version jump is.
#
# --force-correctness because dix's default backend can fall back to opening nix's SQLite
# database with ?immutable=1, which its own help notes "can be inaccurate if the database
# is being written to at the same time". This runs immediately after a build on that host,
# which is exactly that case.
#
# Empty output means no package VERSIONS moved, which is not the same as "no change" --
# a config-only change shows up as a non-zero DIFF with no CHANGED section.
#
# Followed from nixpkgs-unstable, NOT the flake's own nixpkgs: dix there is 2.2.0 versus
# 1.4.2 in the pinned nixpkgs. 2.x is what prints exact closure path counts (the PATHS
# line) and per-package size deltas, and it is the same version nh vendored. Note the node
# is literally "nixpkgs-unstable" whereas plain nixpkgs is "nixpkgs_2", so the bracket
# lookup is required here too. nixpkgs-unstable is already a flake input (flake.nix:4), so
# no new input is added -- but the HOST does now fetch and evaluate that nixpkgs itself.
#
# This preview is a hard gate: under `set -e` a failed fetch or eval aborts before anything
# is deployed. That is deliberate -- a deploy whose diff could not be shown is the one you
# least want to wave through -- but it means a transient network failure on the host blocks
# deploying, and `nix run` registers no GC root, so nh-clean's weekly GC drops dix and the
# next run re-fetches it.
DIX_REV=$(jq -r '.nodes[.nodes.root.inputs["nixpkgs-unstable"]].locked.rev' "$SCRIPT_DIR/../flake.lock")
echo "Package changes:"
# The path goes over stdin and xargs appends it as the final argument, so no variable
# content is ever interpolated into a remote command string. The hosts' login shell is
# fish; this makes that irrelevant rather than something to quote around.
printf '%s\n' "$NEW" | ssh "$FQDN" \
    "xargs nix run github:NixOS/nixpkgs/$DIX_REV#dix -- --color=always --force-correctness /run/current-system"
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
        # `sudo reboot` tears the connection down, so a non-zero exit here is normal and
        # says nothing about whether the command ran. It cannot be the success signal.
        ssh "$FQDN" 'sudo reboot' || true

        # Wait for the host to actually GO DOWN before waiting for it to come back.
        # Without this, the "came back" loop cannot tell a completed reboot from one that
        # never happened. On 2026-09-12 DNS resolution failed for exactly this ssh, the
        # `|| true` swallowed it, the loop below then succeeded on its FIRST attempt
        # against a host that had never restarted, and the script printed "is back online"
        # while network-01 sat on the old kernel with booted != current.
        echo "Waiting for $HOSTNAME to go down..."
        down=false
        elapsed=0
        while [[ $elapsed -lt 120 ]]; do
            if ! ssh -o ConnectTimeout=3 -o BatchMode=yes "$FQDN" true 2>/dev/null; then
                down=true
                break
            fi
            sleep 5
            elapsed=$((elapsed + 5))
        done
        if [[ "$down" != "true" ]]; then
            echo "Error: $HOSTNAME never went down — the reboot did not take effect."
            echo "  The new configuration is active, but the host is still on the old kernel."
            exit 1
        fi

        echo "Waiting for $HOSTNAME to come back..."
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

        # sshd answering only proves the host booted, not that it booted into the new
        # system -- a failed boot that fell back to the previous generation also answers.
        BOOTED_OK=$(ssh "$FQDN" 'bash -c "
            b=\$(readlink -f /run/booted-system/{initrd,kernel,kernel-modules} 2>/dev/null)
            c=\$(readlink -f /run/current-system/{initrd,kernel,kernel-modules} 2>/dev/null)
            if [ \"\$b\" != \"\$c\" ]; then echo no; else echo yes; fi
        "')
        if [[ "$BOOTED_OK" != "yes" ]]; then
            echo "Error: $HOSTNAME came back, but its booted system still differs from current."
            exit 1
        fi
        echo "$HOSTNAME is back online, running the deployed kernel."
    else
        echo "Reboot required — booted system differs from current profile. Run with --reboot to reboot automatically."
    fi
else
    echo "No reboot needed — booted system matches current profile."
fi
