#!/usr/bin/env bash
set -euo pipefail

TALOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TALOS_DIR"

usage() {
    echo "Usage: $(basename "$0") <pi-cluster-0N> <serial> [--insecure] [--yes]"
    echo
    echo "Wipe the NVMe drive with this serial on that node, through the Talos API, so Talos can"
    echo "lay out EPHEMERAL and the Longhorn volume on it. Without --yes it only shows the match."
    echo "Refuses unless exactly one disk has the serial and it is NVMe -- never the SD card."
    echo "--insecure is for a node in maintenance mode, before its config is applied: a rebuild"
    echo "whose reset left the drive's partitions behind."
    echo
    echo "Example:"
    echo "  $(basename "$0") pi-cluster-01 <serial from 'talosctl get disks'> --yes"
    exit 1
}

HOST="${1:-}"
SERIAL="${2:-}"
[[ "$HOST" =~ ^pi-cluster-0([1-6])$ ]] || usage
NODE="192.168.1.18${BASH_REMATCH[1]}"
[[ -n "$SERIAL" ]] || usage
shift 2
CONFIRM=""
# A node in maintenance mode has no certificates yet; it answers only the insecure maintenance
# service.
INSECURE=false
for ARG in "$@"; do
    case "$ARG" in
        --yes) CONFIRM=--yes ;;
        --insecure) INSECURE=true ;;
        *) usage ;;
    esac
done

# Endpoint and node are both the node itself: before bootstrap, the other endpoints in the
# talosconfig may still be in maintenance mode.
TALOSCTL=(talosctl --talosconfig generated/talosconfig -e "$NODE" -n "$NODE")

MATCHES="$("${TALOSCTL[@]}" get disks --insecure="$INSECURE" -o json | jq -s --arg serial "$SERIAL" '[.[] | select(.spec.serial == $serial)]')"
COUNT="$(jq length <<<"$MATCHES")"
if (( COUNT != 1 )); then
    echo "Error: $COUNT disks on $HOST have serial $SERIAL; expected exactly one"
    exit 1
fi
DEV="$(jq -r '.[0].metadata.id' <<<"$MATCHES")"
TRANSPORT="$(jq -r '.[0].spec.transport' <<<"$MATCHES")"
echo "$HOST: $DEV, $(jq -r '.[0].spec.model + ", " + .[0].spec.pretty_size' <<<"$MATCHES"), transport $TRANSPORT"
if [[ "$TRANSPORT" != nvme ]]; then
    echo "Error: $DEV on $HOST is not an NVMe drive"
    exit 1
fi
if [[ "$CONFIRM" != --yes ]]; then
    echo "Re-run with --yes to wipe $DEV on $HOST."
    exit 1
fi

"${TALOSCTL[@]}" wipe disk --insecure="$INSECURE" "$DEV"
echo "Wiped $DEV on $HOST."
