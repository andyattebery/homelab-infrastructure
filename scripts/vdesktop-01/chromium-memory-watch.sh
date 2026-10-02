#!/usr/bin/env bash
#
# Find out where a leaking Chromium renderer's memory is going, on a remote headless host.
#
#   scripts/vdesktop-01/chromium-memory-watch.sh <host> start   # begin sampling, detached
#   scripts/vdesktop-01/chromium-memory-watch.sh <host> status  # is it running, how many samples
#   scripts/vdesktop-01/chromium-memory-watch.sh <host> report  # verdict from what it collected
#   scripts/vdesktop-01/chromium-memory-watch.sh <host> stop    # stop sampling, keep the CSV
#
# WHY THIS EXISTS. On 2026-10-02 one renderer on vdesktop-01 reached 6.86 GB of an 8 GB container
# playing a Canvas 2D game. The container does not die when that happens -- PVE sets
# `memory.high` just under `memory.max`, so the cgroup is THROTTLED into reclaim (34,494 events,
# zero OOM kills) and the host goes sluggish and then unreachable, recoverable only from the
# hypervisor. More RAM does not fix a leak; 4 GB bought minutes and 8 GB bought hours.
#
# The one decision worth evidence is WHERE the memory is, because it decides whether any flag can
# bound it:
#   JS heap        -> `--js-flags=--max-old-space-size=N` makes the page OOM instead of the box
#   detached DOM   -> no flag; a heap snapshot names the retainer
#   canvas/GPU     -> no flag; only the unit's MemoryMax contains it
#
# REQUIRES `--remote-debugging-port=9222` on the browser, which playbook-vdesktop-01.yaml adds to
# `vdesktop_browser_command` as a temporary diagnostic. Without it `start` fails saying so.
#
# The sampler runs as a TRANSIENT systemd user unit, not nohup. The browser and compositor are
# user units on this host, and a transient unit in the same manager outlives the ssh session
# without inheriting its lifetime -- which `nohup` does not reliably do where logind is set to
# kill session processes.
set -euo pipefail

HOST="${1:-}"
MODE="${2:-}"
INTERVAL="${INTERVAL:-30}"
MATCH="${MATCH:-birbplay}"
USER_NAME="${DESKTOP_USER:-andy}"

# /var/tmp, NEVER /tmp: /tmp on this container is tmpfs advertising 31 G on an 8 G box, so a log
# written there competes with the very memory being measured.
CSV="${CSV:-/var/tmp/chromium-memory-watch.csv}"
UNIT=chromium-memory-watch

case "$MODE" in
  start|stop|status|report) ;;
  *) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
[ -n "$HOST" ] || { echo "error: no host given" >&2; exit 2; }

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SAMPLER="$HERE/chromium-memory-watch.py"
[ -r "$SAMPLER" ] || { echo "error: $SAMPLER not found" >&2; exit 2; }

REMOTE_PY=/var/tmp/chromium-memory-watch.py

run() { ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" 'bash -s'; }

case "$MODE" in
start)
    # Ship the sampler. Copied rather than streamed into python, because the transient unit below
    # has to be able to re-exec it without this ssh session.
    ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
        "bash -c 'cat > $REMOTE_PY && chmod 0755 $REMOTE_PY'" < "$SAMPLER"

    run <<REMOTE
set -euo pipefail
U=\$(id -u "$USER_NAME")
export XDG_RUNTIME_DIR="/run/user/\$U"

# Fail with the cause, not a timeout, when the flag is missing -- that is the likely mistake.
# python3, NOT curl: curl is not installed on this container, and a missing curl reports as a
# connection failure, which sends you debugging Chromium instead of the probe.
if ! /usr/bin/python3 -c 'import urllib.request,sys; urllib.request.urlopen("http://localhost:9222/json/version", timeout=5)' >/dev/null 2>&1; then
    echo "FAILED: nothing is answering CDP on 127.0.0.1:9222." >&2
    echo "        The browser needs --remote-debugging-port=9222. In this repo that is" >&2
    echo "        vdesktop_browser_command in playbook-vdesktop-01.yaml; apply it with" >&2
    echo "        --tags session, which restarts the browser unit." >&2
    exit 1
fi

sudo -u "$USER_NAME" XDG_RUNTIME_DIR="\$XDG_RUNTIME_DIR" \\
    systemctl --user reset-failed $UNIT.service 2>/dev/null || true
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="\$XDG_RUNTIME_DIR" \\
    systemd-run --user --unit=$UNIT --description="Chromium memory attribution sampler" \\
        --collect \\
        /usr/bin/python3 $REMOTE_PY sample --out "$CSV" --interval $INTERVAL --match "$MATCH"
sleep 3
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="\$XDG_RUNTIME_DIR" \\
    systemctl --user is-active $UNIT.service
echo "sampling every ${INTERVAL}s into $CSV"
echo "PLAY THE GAME. The leak only grows while it runs; an idle page measures nothing."
REMOTE
    ;;

status)
    run <<REMOTE
set -uo pipefail
U=\$(id -u "$USER_NAME")
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/\$U" \\
    systemctl --user --no-pager show $UNIT.service -p ActiveState -p SubState 2>/dev/null | sed 's/^/   /'
if sudo test -s "$CSV"; then
    echo "   samples: \$(( \$(sudo wc -l < "$CSV") - 1 ))"
    echo "   latest:"
    sudo tail -2 "$CSV" | sed 's/^/      /'
else
    echo "   no samples yet at $CSV"
fi
REMOTE
    ;;

stop)
    run <<REMOTE
set -uo pipefail
U=\$(id -u "$USER_NAME")
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/\$U" systemctl --user stop $UNIT.service 2>/dev/null || true
echo "stopped. CSV kept at $CSV"
REMOTE
    ;;

report)
    run <<REMOTE
set -uo pipefail
sudo test -s "$CSV" || { echo "no data at $CSV -- did 'start' run, and was the game played?" >&2; exit 1; }
sudo /usr/bin/python3 $REMOTE_PY report --out "$CSV"
REMOTE
    ;;
esac
