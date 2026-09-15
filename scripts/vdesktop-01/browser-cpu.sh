#!/usr/bin/env bash
#
# Measure how much CPU a browser burns on a remote host, engine-agnostically.
#
# Usage:
#   scripts/vdesktop-01/browser-cpu.sh <host> [--match PATTERN] [--seconds N]
#
#   scripts/vdesktop-01/browser-cpu.sh vdesktop-01                      # firefox, 5s
#   scripts/vdesktop-01/browser-cpu.sh vdesktop-01 --match chrom        # chromium/chrome
#   scripts/vdesktop-01/browser-cpu.sh vdesktop-01 --seconds 15
#
# Run it while the game is IN THE SLOW PART. The comparable number between engines is the
# TOTAL core-seconds, not the per-thread breakdown: Firefox and Chromium name their threads
# entirely differently, so the tables do not line up even when the workload is identical.
#
# Read-only. Samples /proc twice and subtracts; starts and stops nothing.

set -euo pipefail

HOST=""
MATCH=firefox
SECONDS_WINDOW=5

while [ $# -gt 0 ]; do
  case "$1" in
    --match)   MATCH="$2"; shift ;;
    --seconds) SECONDS_WINDOW="$2"; shift ;;
    -h|--help) sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
    -*)        echo "unknown option: $1" >&2; exit 2 ;;
    *)         HOST="$1" ;;
  esac
  shift
done

[ -n "$HOST" ] || { echo "error: no host given" >&2; exit 2; }

# The sampler must run as root: an unprivileged caller can only read its own processes'
# /proc/<pid>/task and reports nothing while looking like it worked.
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" \
  "sudo python3 - '$MATCH' '$SECONDS_WINDOW'" < "$(dirname "$0")/browser-cpu.py"
