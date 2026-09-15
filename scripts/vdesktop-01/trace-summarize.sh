#!/usr/bin/env bash
#
# Summarise a Chrome JSON trace that lives on a remote host, without moving it and without
# reading it whole. Ships scripts/vdesktop-01/trace-summarize.py over ssh stdin and runs it there.
#
# A 120s Chromium capture is ~667 MB. Copying it across a remote link is slow and json.load of
# it took CT 120 down on 2026-09-13 (4 GB limit, swap full, oom_kill 0, sshd unreachable,
# hypervisor load 99). The analyser streams one event at a time; this wrapper keeps that the
# only way it gets run.
#
# Usage:
#   scripts/vdesktop-01/trace-summarize.sh <host> [path] [top_n] [name_substring]
#
set -euo pipefail

HOST="${1:-}"
TRACE="${2:-/tmp/chromium-trace.json}"
TOP="${3:-14}"
NEEDLE="${4:-}"
[ -n "$HOST" ] || { sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
ANALYSER="$HERE/trace-summarize.py"
[ -r "$ANALYSER" ] || { echo "error: $ANALYSER not found" >&2; exit 2; }

# The trace is written by the desktop account and read by whoever ssh'd in -- not the same
# user, which has bitten this workflow three times. sudo the read, and only the read.
{
  printf 'set -euo pipefail\n'
  printf 'TRACE=%s\n' "$TRACE"
  printf 'TOP=%s\n' "$TOP"
  printf 'NEEDLE=%s\n' "$NEEDLE"
  printf 'sudo test -r "$TRACE" || { echo "FAILED: $TRACE not readable on this host" >&2; exit 1; }\n'
  printf 'sudo python3 - "$TRACE" "$TOP" $NEEDLE <<'"'"'ANALYSER_EOF'"'"'\n'
  cat "$ANALYSER"
  printf 'ANALYSER_EOF\n'
} | ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" 'bash -s'
