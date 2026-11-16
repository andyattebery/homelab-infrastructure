#!/usr/bin/env bash
set -euo pipefail

# What stock firmware v2.1.0 ships. The latch patch that keeps a v2.5 board's nodes running through a
# restart is newer than v2.0.5, and a v2.4 board has no latch: bmcd driving its enable lines is real.
EXPECTED_BMCD_VERSION="2.3.4"
EXPECTED_BOARD_REVISION="2.5"
EXPECTED_CERTIFICATE="/etc/ssl/certs/bmcd_cert.pem"
EXPECTED_PRIVATE_KEY="/etc/ssl/certs/bmcd_key.pem"

NODES=(turingpi-rk1-01 turingpi-rk1-02 turingpi-cm4-01 turingpi-jetson-01)
# bmcd skips authentication on loopback, so these need no API login.
API="https://127.0.0.1/api/bmc?opt=get"

usage() {
    echo "Usage: $(basename "$0") <bmc-ssh-target> [--yes]"
    echo
    echo "Measure whether restarting bmcd touches the Turing Pi 2 nodes. Prints the BMC's versions,"
    echo "node power and TLS paths, and each node's boot_id and uptime. Without --yes it stops there."
    echo "With it, the BMC's daemon is restarted and all of that is read again: any changed boot_id,"
    echo "unreachable node, changed power state, or a bmcd pid that did not change is a failure, exit"
    echo "1. If restarting bmcd does reset the nodes, --yes hard-resets all four, and the cached tpi"
    echo "login is dropped either way."
    echo
    echo "Example:"
    echo "  $(basename "$0") turingpi --yes"
    exit 1
}

BMC="${1:-}"
CONFIRM="${2:-}"
[[ -n "$BMC" && "$BMC" != -* && $# -le 2 && ( -z "$CONFIRM" || "$CONFIRM" == --yes ) ]] || usage

# One line per node, so two snapshots compare with a plain string test.
node_boot_ids() {
    local node
    for node in "${NODES[@]}"; do
        echo "$node $(ssh -o BatchMode=yes -o ConnectTimeout=10 "$node" cat /proc/sys/kernel/random/boot_id || echo unreachable)"
    done
}

node_uptimes() {
    local node
    for node in "${NODES[@]}"; do
        echo "$node $(ssh -o BatchMode=yes -o ConnectTimeout=10 "$node" uptime || echo unreachable)"
    done
}

# One ssh call, because each is a password prompt on a BMC with no key installed.
BMC_STATE="$(ssh "$BMC" "curl -sk '$API&type=about'; echo; curl -sk '$API&type=power'; echo; cat /var/run/bmcd.pid; grep -E '^[[:space:]]*(certificate|private_key):' /etc/bmcd/config.yaml; true")"
ABOUT="$(sed -n 1p <<<"$BMC_STATE")"
POWER_BEFORE="$(sed -n 2p <<<"$BMC_STATE")"
BMCD_PID_BEFORE="$(sed -n 3p <<<"$BMC_STATE")"
TLS_PATHS="$(sed -n '4,$p' <<<"$BMC_STATE")"
BOOT_IDS_BEFORE="$(node_boot_ids)"

echo "About: $ABOUT"
echo "Power: $POWER_BEFORE"
echo "bmcd pid: $BMCD_PID_BEFORE"
echo "TLS:"
echo "$TLS_PATHS"
echo "Nodes:"
echo "$BOOT_IDS_BEFORE"
node_uptimes

BLOCKED=false
if [[ "$ABOUT" != *"\"version\":\"$EXPECTED_BMCD_VERSION\""* ]]; then
    echo "Not safe to restart: bmcd is not $EXPECTED_BMCD_VERSION"
    BLOCKED=true
fi
# A prefix, so that v2.5.1 matches: its device tree includes the v2.5 one.
if [[ "$ABOUT" != *"\"board_revision\":\"$EXPECTED_BOARD_REVISION"* ]]; then
    echo "Not safe to restart: the board is not v$EXPECTED_BOARD_REVISION"
    BLOCKED=true
fi
if [[ "$TLS_PATHS" != *"$EXPECTED_CERTIFICATE"* || "$TLS_PATHS" != *"$EXPECTED_PRIVATE_KEY"* ]]; then
    echo "Not safe to restart: config.yaml does not use the default certificate paths"
    BLOCKED=true
fi
if [[ "$BOOT_IDS_BEFORE" == *unreachable* ]]; then
    echo "Not safe to restart: a node did not answer, so its boot_id cannot be compared"
    BLOCKED=true
fi
if [[ "$BLOCKED" == true ]]; then
    exit 1
fi

if [[ "$CONFIRM" != --yes ]]; then
    echo "Re-run with --yes to restart bmcd and compare."
    exit 0
fi

# Redirected because S94bmcd starts bmcd with --no-close: it would otherwise inherit this ssh
# channel's stdout and stderr, so ssh would never return.
BMC_STATE_AFTER="$(ssh "$BMC" "/etc/init.d/S94bmcd restart </dev/null >/dev/null 2>&1; curl -sk --retry 30 --retry-delay 2 --retry-connrefused --max-time 5 '$API&type=power'; echo; cat /var/run/bmcd.pid")"
POWER_AFTER="$(sed -n 1p <<<"$BMC_STATE_AFTER")"
BMCD_PID_AFTER="$(sed -n 2p <<<"$BMC_STATE_AFTER")"
# A reset node takes longer than this to come back, so it reads as unreachable or as a new boot_id.
sleep 10
BOOT_IDS_AFTER="$(node_boot_ids)"

echo "After restart:"
echo "Power: $POWER_AFTER"
echo "bmcd pid: $BMCD_PID_AFTER"
echo "$BOOT_IDS_AFTER"
node_uptimes

# Without this, an S94bmcd that did nothing would read as a pass: the API answers either way.
if [[ -z "$BMCD_PID_AFTER" || "$BMCD_PID_AFTER" == "$BMCD_PID_BEFORE" ]]; then
    echo "NOT TESTED: bmcd's pid did not change, so it never restarted."
    exit 1
fi
if [[ "$BOOT_IDS_AFTER" != "$BOOT_IDS_BEFORE" || "$POWER_AFTER" != "$POWER_BEFORE" ]]; then
    echo "CHANGED: restarting bmcd touched the nodes."
    exit 1
fi
echo "Unchanged: every node kept its boot_id and power state."
