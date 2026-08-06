#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

GRACE_PERIOD="${GRACE_PERIOD:-300}"
POLL_INTERVAL="${POLL_INTERVAL:-30}"
CHECK_DIR="/etc/sleep-inhibitor.d"
INHIBITOR_PID=""

cleanup() { stop_inhibitor; exit 0; }
trap cleanup SIGTERM SIGINT EXIT

start_inhibitor() {
    if [[ -n "$INHIBITOR_PID" ]] && kill -0 "$INHIBITOR_PID" 2>/dev/null; then
        return
    fi
    local why="$1"
    systemd-inhibit --what=sleep --mode=block \
        --who=sleep-inhibitor --why="$why" \
        sleep infinity &
    INHIBITOR_PID=$!
    echo "inhibitor acquired ($why), pid=$INHIBITOR_PID"
}

stop_inhibitor() {
    if [[ -n "$INHIBITOR_PID" ]] && kill -0 "$INHIBITOR_PID" 2>/dev/null; then
        kill "$INHIBITOR_PID" 2>/dev/null || true
        wait "$INHIBITOR_PID" 2>/dev/null || true
        echo "inhibitor released"
    fi
    INHIBITOR_PID=""
}

idle_since=0

while true; do
    active_checks=()
    for f in "$CHECK_DIR"/*; do
        [[ -x "$f" ]] || continue
        if timeout 10 "$f"; then
            active_checks+=("$(basename "$f")")
        fi
    done

    if [[ ${#active_checks[@]} -gt 0 ]]; then
        idle_since=0
        why="active: $(IFS=,; echo "${active_checks[*]}")"
        if [[ -z "$INHIBITOR_PID" ]] || ! kill -0 "$INHIBITOR_PID" 2>/dev/null; then
            start_inhibitor "$why"
        fi
    else
        now=$(date +%s)
        if [[ "$idle_since" -eq 0 ]]; then
            idle_since=$now
        elif [[ $((now - idle_since)) -ge GRACE_PERIOD ]]; then
            stop_inhibitor
        fi
    fi

    sleep "$POLL_INTERVAL"
done
