#!/usr/bin/env bash
set -euo pipefail

TALOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TALOS_DIR"

usage() {
    echo "Usage: $(basename "$0") [<node>[,<node>...]]"
    echo
    echo "Show every sensor on each node, read from sysfs through the Talos API: each hwmon"
    echo "temperature with its max and critical limits, and each alarm (0 = clear, 1 = raised)."
    echo "Nodes default to \$TALOS_NODES, which mise.toml sets to all six. They are read in"
    echo "parallel. A node that doesn't answer shows 'no answer' after about 20 s, and the exit"
    echo "status is then 1."
    echo
    echo "Example:"
    echo "  $(basename "$0") 192.168.1.181"
    exit 1
}

[[ $# -le 1 ]] || usage
NODE_LIST="${1:-${TALOS_NODES:-}}"
[[ -n "$NODE_LIST" && "$NODE_LIST" != -* ]] || usage
IFS=, read -r -a NODES <<<"$NODE_LIST"

TAB="$(printf '\t')"

# Millidegrees to degrees, rounded to a tenth: 55991 -> 56.0C. Empty, or a value a sensor uses
# for "no limit" (0 K, or the 65535 K on the PM991's second sensor), prints "-".
celsius() {
    awk -v m="$1" 'BEGIN {
        if (m == "" || m <= -273000 || m >= 1000000) { print "-"; exit }
        t = int((m + 50) / 100); printf "%d.%dC\n", t / 10, t % 10
    }'
}

# talosctl against $NODE alone, endpoint and node both: it answers even when the control planes
# don't. A file or directory that isn't there prints nothing.
tc() { talosctl --talosconfig generated/talosconfig -e "$NODE" -n "$NODE" "$@" 2>/dev/null || true; }
entries() { tc list "$1" | grep -v -x -F . || true; }
has() { grep -q -x -F "$1" <<<"$FILES"; }
read_or_dash() { local value; value="$(tc read "$1")"; echo "${value:--}"; }

# $NODE's sensors, one tab-separated row each: node, device, sensor, temp, max, crit, alarm.
node_rows() {
    NODE=$1
    local host zone hw trip trips="" dir name input n label temp max crit alarm entry
    if ! host="$(talosctl --talosconfig generated/talosconfig -e "$NODE" -n "$NODE" read /proc/sys/kernel/hostname 2>/dev/null)"; then
        printf '%s\tno answer\n' "$NODE"
        return
    fi

    # A thermal zone's critical trip is where the kernel shuts the node down. It is the only
    # limit cpu_thermal has, so it fills the crit column of the hwmon device the zone links to.
    for zone in $(entries /sys/class/thermal | grep '^thermal_zone' || true); do
        hw="$(entries "/sys/class/thermal/$zone" | grep '^hwmon' || true)"
        [[ -n "$hw" ]] || continue
        for trip in $(entries "/sys/class/thermal/$zone" | grep -E '^trip_point_[0-9]+_type$' || true); do
            if [[ "$(tc read "/sys/class/thermal/$zone/$trip")" == critical ]]; then
                trips="$trips $hw=$(tc read "/sys/class/thermal/$zone/${trip%_type}_temp")"
            fi
        done
    done

    for hw in $(entries /sys/class/hwmon | grep '^hwmon' || true); do
        dir=/sys/class/hwmon/$hw
        FILES="$(entries "$dir")"
        name="$(read_or_dash "$dir/name")"
        for input in $(grep -E '^temp[0-9]+_input$' <<<"$FILES" || true); do
            n=${input%_input}
            label=$n max=- crit=- alarm=-
            if has "${n}_label"; then label="$(read_or_dash "$dir/${n}_label")"; fi
            temp="$(celsius "$(tc read "$dir/$input")")"
            if has "${n}_max"; then max="$(celsius "$(tc read "$dir/${n}_max")")"; fi
            if has "${n}_crit"; then crit="$(celsius "$(tc read "$dir/${n}_crit")")"; fi
            if [[ "$crit" == - ]]; then
                for entry in $trips; do
                    if [[ "${entry%%=*}" == "$hw" ]]; then crit="$(celsius "${entry#*=}")"; fi
                done
            fi
            if has "${n}_alarm"; then alarm="$(read_or_dash "$dir/${n}_alarm")"; fi
            printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$host" "$name" "$label" "$temp" "$max" "$crit" "$alarm"
        done
        # Alarms that belong to no temperature. rpi_volt's in0_lcrit_alarm is the firmware's
        # under-voltage alarm.
        for input in $(grep -E '_alarm$' <<<"$FILES" | grep -v '^temp' || true); do
            printf '%s\t%s\t%s\t-\t-\t-\t%s\n' "$host" "$name" "${input%_alarm}" "$(read_or_dash "$dir/$input")"
        done
    done
}

# Each node in the background; the rows are tagged with the node's position and sorted back
# into the order given, whichever node answers first.
ROWS="$(
    {
        i=0
        for node in "${NODES[@]}"; do
            node_rows "$node" | sed "s/^/$i$TAB/" &
            i=$((i + 1))
        done
        wait
    } | sort -s -n -k1,1 | cut -f2-
)"

{
    printf 'NODE\tDEVICE\tSENSOR\tTEMP\tMAX\tCRIT\tALARM\n'
    printf '%s\n' "$ROWS"
} | column -t -s "$TAB"

if grep -q "${TAB}no answer\$" <<<"$ROWS"; then
    exit 1
fi
