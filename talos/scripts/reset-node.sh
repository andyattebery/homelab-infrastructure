#!/usr/bin/env bash
set -euo pipefail

TALOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TALOS_DIR"

usage() {
    echo "Usage: $(basename "$0") <pi-cluster-0N> <serial> [--yes]"
    echo
    echo "Reset a node to maintenance mode for a rebuild: wipe STATE (its machine config) and the"
    echo "whole NVMe drive with this serial (EPHEMERAL and the Longhorn volume), keep the SD card's"
    echo "boot partitions, and reboot. Without --yes it only shows the match. Refuses unless exactly"
    echo "one disk has the serial and it is NVMe -- never the SD card."
    echo
    echo "Example:"
    echo "  $(basename "$0") pi-cluster-04 <serial from 'talosctl get disks'> --yes"
    exit 1
}

HOST="${1:-}"
SERIAL="${2:-}"
CONFIRM="${3:-}"
[[ "$HOST" =~ ^pi-cluster-0([1-6])$ ]] || usage
NODE="192.168.1.18${BASH_REMATCH[1]}"
[[ -n "$SERIAL" ]] || usage
[[ $# -le 3 && ( -z "$CONFIRM" || "$CONFIRM" == --yes ) ]] || usage

# Endpoint and node are both the node itself: partway through a teardown, the other control
# planes in the talosconfig are already in maintenance mode.
TALOSCTL=(talosctl --talosconfig generated/talosconfig -e "$NODE" -n "$NODE")

MATCHES="$("${TALOSCTL[@]}" get disks -o json | jq -s --arg serial "$SERIAL" '[.[] | select(.spec.serial == $serial)]')"
COUNT="$(jq length <<<"$MATCHES")"
if (( COUNT != 1 )); then
    echo "Error: $COUNT disks on $HOST have serial $SERIAL; expected exactly one"
    exit 1
fi
DEV_PATH="$(jq -r '.[0].spec.dev_path' <<<"$MATCHES")"
TRANSPORT="$(jq -r '.[0].spec.transport' <<<"$MATCHES")"
echo "$HOST: $DEV_PATH, $(jq -r '.[0].spec.model + ", " + .[0].spec.pretty_size' <<<"$MATCHES"), transport $TRANSPORT"
if [[ "$TRANSPORT" != nvme ]]; then
    echo "Error: $DEV_PATH on $HOST is not an NVMe drive"
    exit 1
fi
if [[ "$CONFIRM" != --yes ]]; then
    echo "Re-run with --yes to reset $HOST and wipe $DEV_PATH."
    exit 1
fi

# --graceful=false: a whole-cluster teardown has no etcd quorum to leave. --reboot: a node
# that shuts down here comes back only with a power cycle of the whole board.
"${TALOSCTL[@]}" reset --graceful=false --reboot --system-labels-to-wipe STATE --user-disks-to-wipe "$DEV_PATH"
# talosctl returns once the node answers in maintenance mode. That shows STATE is gone, not that
# the drive was wiped: a drive that hangs during the reset keeps its partitions, and the node
# comes back all the same (README, Traps).
echo "Reset $HOST; it answers in maintenance mode. Check that $DEV_PATH has no partitions:"
echo "  talosctl get discoveredvolumes --insecure -n $NODE"
