#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $(basename "$0") [-r|--reboot] <hostname>"
    echo
    echo "Deploy a NixOS host via deploy-rs."
    echo
    echo "Options:"
    echo "  -r, --reboot    Reboot the host after deploy if the system closure changed"
    echo
    echo "Examples:"
    echo "  $(basename "$0") network-01"
    echo "  $(basename "$0") --reboot network-01"
    exit 1
}

REBOOT=false
HOSTNAME=""

while [[ $# -gt 0 ]]; do
    case "$1" in
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

echo "Deploying $HOSTNAME..."
"$SCRIPT_DIR/nix-shell.sh" --ssh run .#deploy-rs -- ".#$HOSTNAME"
echo "Deploy complete."

NEEDS_REBOOT=$(ssh "$FQDN" 'bash -c "
    booted=\$(readlink /run/booted-system)
    current=\$(readlink /nix/var/nix/profiles/system)
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
