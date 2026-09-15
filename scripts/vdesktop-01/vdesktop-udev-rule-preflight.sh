#!/usr/bin/env bash
#
# Prove that installing the `lxc-input` udev rule changes NOTHING about the input devices a
# hypervisor already has.
#
# Usage:
#   scripts/vdesktop-01/vdesktop-udev-rule-preflight.sh <host> baseline   # before the rule exists
#   scripts/vdesktop-01/vdesktop-udev-rule-preflight.sh <host> compare    # after it is installed
#
#   scripts/vdesktop-01/vdesktop-udev-rule-preflight.sh vm-host-01 baseline
#   scripts/vdesktop-01/vdesktop-udev-rule-preflight.sh vm-host-01 compare
#
# WHY THIS EXISTS. Writing a udev rules file IS activating it -- udevd notices the change and
# reloads on its own (systemd v257 src/udev/udev-manager.c:590 calls manager_reload() from
# event_queue_start(); :268 reloads when udev_rules_should_reload()). There is no
# installed-but-inert window on the node in which to check anything. So the only honest sequence
# is: record what the host looks like first, install, then prove nothing moved.
#
# The rule is a no-op on current hardware BY CONSTRUCTION -- it matches vendor 1209, which is
# Sunshine's virtual keyboard and mouse and which no physical device carries. This exists to
# PROVE that, not to discover it.
#
# BOTH MODES ARE READ-ONLY. This script never writes to the host, never installs the rule, and
# never runs `udevadm control`, `trigger` or `settle`. Installing the rule is a separate,
# deliberate step: `ansible-playbook playbook-vdesktop-01.yaml --tags udev-input --limit <host>`.
#
# WHY A SCRIPT AND NOT A HANDFUL OF SSH COMMANDS. The host has ~100 input devices. Comparing
# two runs of that by eye is precisely how a false pass gets produced -- and the comparison is
# the entire point of the exercise. This captures a normalised, diffable record instead.
#
# Baselines land in tasks/, which is gitignored: they carry real device names.

set -euo pipefail

HOST=""
MODE=""
BASELINE=""

while [ $# -gt 0 ]; do
    case "$1" in
        baseline|compare) MODE="$1" ;;
        --baseline)       BASELINE="${2:?--baseline needs a path}"; shift ;;
        -h|--help)        sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)               echo "unknown option: $1" >&2; exit 2 ;;
        *)                [ -n "$HOST" ] && { echo "unexpected argument: $1" >&2; exit 2; }
                          HOST="$1" ;;
    esac
    shift
done

[ -n "$HOST" ] || { echo "error: no host given" >&2; exit 2; }
[ -n "$MODE" ] || { echo "error: give 'baseline' or 'compare'" >&2; exit 2; }

# The repo root, two levels up from scripts/vdesktop-01/. Written as one assignment so moving
# this file again is a single edit rather than a hunt for `..` counts scattered through the file.
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
: "${BASELINE:=$ROOT/tasks/udev-preflight-$HOST.txt}"

# The capture, run on the far side. `bash -s` over stdin rather than `bash -lc '...'`: these
# hosts log in to fish, and -- more importantly -- a pattern inside a long -c string can match
# the ssh session's own command line, which has already killed one of these sessions.
capture() {
    ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" 'bash -s' <<'REMOTE'
set -uo pipefail

# THE CASE SET, FIRST. A glob that matches nothing reports itself as a perfect result: every
# later "no device changed" assertion is trivially true over an empty set.
shopt -s nullglob
devices=(/sys/class/input/event*)
echo "# devices ${#devices[@]}"
echo "# kernel $(uname -r)"

for d in "${devices[@]}"; do
    sysname=${d##*/}
    name=$(cat "$d/device/name" 2>/dev/null || echo '-')
    vendor=$(cat "$d/device/id/vendor" 2>/dev/null || echo '-')
    product=$(cat "$d/device/id/product" 2>/dev/null || echo '-')

    # `udevadm test` APPLIES NOTHING. src/udev/udevadm-test.c:107 prints "This program is for
    # debugging only, it does not run any program specified by a RUN key"; it calls
    # udev_event_execute_rules() and then only printf()s the result. Safe against production.
    #
    # 2>/dev/null is not cosmetic: --debug is implied for `udevadm test` (man/udevadm.xml,
    # Options) and floods stderr, while the report goes to stdout.
    #
    # The group is printed on the line AFTER the marker, indented:
    #     Device node group:
    #       input (gid=997)
    # so this takes the following line, not the marker's own. Grepping for `GROUP=` instead
    # would find nothing -- that is the rule's syntax, not the tool's output.
    group=$(sudo udevadm test "$d" 2>/dev/null \
            | awk '/^Device node group:/{getline; gsub(/^[ \t]+|[ \t]+$/,""); print; exit}')

    # An ABSENT group line means "not determined", NOT "unchanged". udevadm-test.c:169 reads
    # `if (!gid_is_valid(uid))` where it means `gid` -- a genuine upstream slip -- so when the
    # event sets no gid the fallback is skipped and nothing prints at all. Recording it as a
    # distinct token keeps that case from silently matching a real group on the other side of a
    # diff.
    [ -n "$group" ] || group='<none-printed>'

    printf '%s|%s|%s|%s|%s\n' "$sysname" "$vendor" "$product" "$group" "$name"
done | sort
REMOTE
}

case "$MODE" in
baseline)
    echo "== capturing baseline from $HOST (read-only)"
    mkdir -p "$(dirname "$BASELINE")"
    capture > "$BASELINE"
    count=$(awk '/^# devices/{print $3}' "$BASELINE")
    echo "-- wrote $BASELINE"
    echo "-- devices: $count"

    # Stop rather than report a vacuous pass. On a node with no input devices at all, `compare`
    # would find nothing changed and that would prove nothing whatsoever.
    if [ "${count:-0}" = "0" ]; then
        echo
        echo "RESULT: PROVED NOTHING -- this host has no input devices, so a later comparison"
        echo "        has an empty case set and cannot fail. Do not read a green 'compare' as"
        echo "        evidence the rule is harmless here."
        exit 3
    fi

    echo
    echo "-- group distribution across the case set:"
    awk -F'|' '!/^#/{print $4}' "$BASELINE" | sort | uniq -c | sort -rn | sed 's/^/     /'
    echo
    echo "-- does any EXISTING device already carry vendor 1209 (what the rule matches)?"
    if awk -F'|' '!/^#/ && $2 == "1209"' "$BASELINE" | grep -q .; then
        awk -F'|' '!/^#/ && $2 == "1209"' "$BASELINE" | sed 's/^/     /'
        echo "     ^^ THE RULE WOULD MATCH THESE. It is NOT a no-op on this host."
        exit 1
    fi
    echo "     none -- the rule matches no device that exists, which is why installing it is safe"
    echo
    echo "Next: install with"
    echo "  ansible-playbook playbook-vdesktop-01.yaml --tags udev-input --limit $HOST"
    echo "then re-run this script with 'compare'."
    ;;

compare)
    [ -r "$BASELINE" ] || {
        echo "error: no baseline at $BASELINE -- run 'baseline' BEFORE installing the rule." >&2
        echo "       There is no way to reconstruct it afterwards: the rule is live the moment" >&2
        echo "       its file lands, so a capture taken now is already post-change." >&2
        exit 2
    }
    echo "== re-capturing from $HOST and comparing against $BASELINE"
    now=$(mktemp)
    trap 'rm -f "$now"' EXIT
    capture > "$now"

    before=$(awk '/^# devices/{print $3}' "$BASELINE")
    after=$(awk '/^# devices/{print $3}' "$now")
    echo "-- devices: baseline $before, now $after"

    if diff -u "$BASELINE" "$now" > /dev/null; then
        echo
        echo "PASS -- every one of $after devices reports exactly what it did before."
        echo "        The rule is installed and changed nothing about existing hardware."
        echo
        echo "This is the NEGATIVE half only. That Sunshine's devices DO land in lxc-input has"
        echo "no target until Sunshine runs in the container, and is a build-time check"
        echo "(ls -ln /dev/input showing gid 996, not 65534)."
        exit 0
    fi

    echo
    echo "FAIL -- something moved. Full diff (baseline -> now):"
    diff -u "$BASELINE" "$now" | sed 's/^/     /'
    echo
    if diff "$BASELINE" "$now" | grep -qi 'lxc-input'; then
        echo "     At least one EXISTING device was moved into lxc-input. That is the failure"
        echo "     this preflight exists to catch: the rule is matching real hardware."
    fi
    exit 1
    ;;
esac
