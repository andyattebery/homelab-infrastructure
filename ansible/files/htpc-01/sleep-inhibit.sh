#!/usr/bin/env bash
set -euo pipefail

# Take or release a manual sleep inhibit.
#
# Writes a deadline to /run/sleep-inhibit-until, which sleep-inhibitor.d/manual.sh reads on its
# next poll. Nothing here talks to logind directly: the poll loop already owns the one
# inhibitor, and going around it would mean two mechanisms holding sleep with no single place
# to ask what is happening.
#
# The deadline is the point. A hold that never expires outlives the reason for it and the
# memory of setting it, and the host stops sleeping for good.

LOCK=/run/sleep-inhibit-until
POLL=30    # sleep-inhibitor.service POLL_INTERVAL
GRACE=300  # sleep-inhibitor.service GRACE_PERIOD

usage() {
    cat <<'USAGE'
Usage: sleep-inhibit <duration> | until <time> | run <duration> -- <command...> | status | off

  sleep-inhibit 2h            hold for a duration (30s, 90m, 2h, 1d)
  sleep-inhibit until 09:00   hold until a wall-clock time
  sleep-inhibit indefinite    hold with no expiry, until released
  sleep-inhibit status        show the current hold, if any
  sleep-inhibit off           release now
  sleep-inhibit run 2h -- <command...>
                              hold for one command, then put back the hold that was there
                              before it (what pqup uses)

Prefer a duration. `indefinite` never lapses, so it outlives both the reason for it and
your memory of setting it — only `off` or a reboot ends it. It exists because the
alternative people reach for, a hand-rolled `systemd-run … systemd-inhibit … sleep
infinity`, holds sleep just as hard while being invisible to `status`.

Timing, so it is not a surprise:
  - takes effect within 30s (the poll interval)
  - after it expires or is released, the inhibitor drops up to 300s later (the grace period)
Both lag towards staying awake, never towards sleeping early.

This is one voice among several. Other checks (ffmpeg, llama-swap, ...) hold the inhibitor
on their own, so `off` does not guarantee the host may sleep — only that you are no longer
the reason it cannot.

`run` never shortens a hold you already have: a longer or indefinite one is left alone, and
a shorter one is restored when the command finishes.
USAGE
}

need_root() {
    [[ $EUID -eq 0 ]] || { echo "sleep-inhibit: must run as root (try: sudo sleep-inhibit $*)" >&2; exit 1; }
}

show_status() {
    if [[ ! -f "$LOCK" ]]; then
        echo "manual hold: none"
    else
        local until_epoch remaining
        until_epoch=$(head -n1 "$LOCK" 2>/dev/null || echo "")
        if [[ "$until_epoch" == "indefinite" ]]; then
            echo "manual hold: INDEFINITE — no expiry. Release with: sudo sleep-inhibit off"
        elif [[ ! "$until_epoch" =~ ^[0-9]+$ ]]; then
            echo "manual hold: lock file is malformed, treated as no hold ($LOCK)"
        else
            remaining=$(( until_epoch - $(date +%s) ))
            if (( remaining > 0 )); then
                printf 'manual hold: until %s (%dh%02dm left)\n' \
                    "$(date -d "@$until_epoch" '+%Y-%m-%d %H:%M:%S')" \
                    $(( remaining / 3600 )) $(( (remaining % 3600) / 60 ))
            else
                echo "manual hold: expired $(date -d "@$until_epoch" '+%Y-%m-%d %H:%M:%S'), treated as no hold"
            fi
        fi
    fi

    # What the poll loop actually did with it. The lock is a request; this is the outcome.
    echo
    if systemd-inhibit --list 2>/dev/null | grep -q '^sleep-inhibitor'; then
        systemd-inhibit --list 2>/dev/null | awk 'NR==1 || /^sleep-inhibitor/'
    else
        echo "sleep-inhibitor is not currently holding an inhibitor"
    fi
}

set_until() {
    local when="$1" until_epoch
    until_epoch=$(date -d "$when" +%s 2>/dev/null) \
        || { echo "sleep-inhibit: cannot parse time '$when'" >&2; exit 1; }
    if (( until_epoch <= $(date +%s) )); then
        echo "sleep-inhibit: '$when' is in the past" >&2
        exit 1
    fi
    printf '%s\n' "$until_epoch" > "$LOCK"
    chmod 0644 "$LOCK"
    printf 'holding until %s (takes effect within %ss)\n' \
        "$(date -d "@$until_epoch" '+%Y-%m-%d %H:%M:%S')" "$POLL"
}

# 45s|90m|2h|1d -> "45 seconds" and so on. Anything else is rejected rather than guessed: a
# typo that silently became "now" would be a hold that never happened.
duration_spec() {
    local d="$1"
    [[ "$d" =~ ^([0-9]+)([smhd])$ ]] \
        || { echo "sleep-inhibit: bad duration '$d' (use 30s, 90m, 2h, 1d)" >&2; return 1; }
    case "${BASH_REMATCH[2]}" in
        s) echo "${BASH_REMATCH[1]} seconds" ;;
        m) echo "${BASH_REMATCH[1]} minutes" ;;
        h) echo "${BASH_REMATCH[1]} hours" ;;
        d) echo "${BASH_REMATCH[1]} days" ;;
    esac
}

# Run a command under a deadline hold without disturbing a hold an operator already has.
#
# The lock is one value, so a job that ran `sleep-inhibit 2h` would replace an indefinite or
# longer operator hold, and `off` at the end would delete it. So: take the hold only when
# the existing one is absent, expired, or ends before this one would; afterwards put back
# what was there — the operator's deadline if it is still in the future, nothing otherwise.
# Returns the command's exit status. A command that outlives its duration loses the hold, so
# size the duration for the worst case; one killed mid-way leaves the deadline, which expires.
run_under_hold() {
    local spec="$1"; shift
    local want prev="" took=0 rc=0
    want=$(date -d "+$spec" +%s)
    [[ -f "$LOCK" ]] && prev=$(head -n1 "$LOCK" 2>/dev/null || echo "")
    if [[ "$prev" == "indefinite" ]] || { [[ "$prev" =~ ^[0-9]+$ ]] && (( prev >= want )); }; then
        echo "sleep-inhibit: an existing hold already covers this run; leaving it as is"
    else
        printf '%s\n' "$want" > "$LOCK"
        chmod 0644 "$LOCK"
        took=1
        printf 'sleep-inhibit: holding until %s (takes effect within %ss) for: %s\n' \
            "$(date -d "@$want" '+%Y-%m-%d %H:%M:%S')" "$POLL" "$*"
    fi
    "$@" || rc=$?
    if (( took )); then
        if [[ "$prev" =~ ^[0-9]+$ ]] && (( prev > $(date +%s) )); then
            printf '%s\n' "$prev" > "$LOCK"
            printf 'sleep-inhibit: command finished (exit %s); earlier hold restored, until %s\n' \
                "$rc" "$(date -d "@$prev" '+%Y-%m-%d %H:%M:%S')"
        else
            rm -f "$LOCK"
            printf 'sleep-inhibit: command finished (exit %s); hold released (inhibitor drops within %ss if nothing else is busy)\n' \
                "$rc" "$GRACE"
        fi
    fi
    return "$rc"
}

case "${1-}" in
    ""|-h|--help|help)
        usage
        ;;
    status)
        show_status
        ;;
    off)
        need_root "$@"
        if [[ -f "$LOCK" ]]; then
            rm -f "$LOCK"
            printf 'manual hold released (inhibitor drops within %ss if nothing else is busy)\n' "$GRACE"
        else
            echo "manual hold: none to release"
        fi
        ;;
    indefinite|forever)
        need_root "$@"
        printf 'indefinite\n' > "$LOCK"
        chmod 0644 "$LOCK"
        printf 'holding indefinitely (takes effect within %ss). This will NOT expire —\n' "$POLL"
        printf 'release it with: sudo sleep-inhibit off\n'
        ;;
    until)
        need_root "$@"
        [[ $# -ge 2 ]] || { echo "sleep-inhibit: 'until' needs a time, e.g. until 09:00" >&2; exit 1; }
        shift
        set_until "$*"
        ;;
    # A bare duration: 45s, 90m, 2h, 1d. Rejected rather than guessed if it is not one of
    # those — a typo that silently became "now" would be a hold that never happened.
    *[0-9]s|*[0-9]m|*[0-9]h|*[0-9]d)
        need_root "$@"
        spec=$(duration_spec "$1") || exit 1
        set_until "+$spec"
        ;;
    # Hold for the length of one command, then put back whatever hold was there before.
    run)
        need_root "$@"
        [[ $# -ge 4 && "$3" == "--" ]] \
            || { echo "sleep-inhibit: usage: sleep-inhibit run <duration> -- <command...>" >&2; exit 1; }
        spec=$(duration_spec "$2") || exit 1
        shift 3
        run_under_hold "$spec" "$@"
        ;;
    *)
        echo "sleep-inhibit: unrecognised argument '$1'" >&2
        echo >&2
        usage >&2
        exit 1
        ;;
esac
