#!/usr/bin/env bash
# Run one bench.py row on htpc-01 from the Mac. All arguments pass through.
#
#   ./run-remote.sh --model gemma --ctx 32768 --fa 1 --ub 1024
#
# The harness is a multi-file Python program, so it cannot be piped over stdin the way
# the old single-file shell version was — the files are copied to the host first.
#
# For anything long (the backend A/B is ~2h) use run_matrix.py under tmux instead: this
# wrapper ties the run to the ssh connection and cannot be reattached.
set -euo pipefail
HOST="${BENCH_HOST:-htpc-01}"

# ssh flattens its argument list into a single command string, so quoting is lost
# unless we re-quote each argument ourselves. Without this, --label "two words"
# arrives as two arguments and the option parser rejects the second.
ARGS=""
for a in "$@"; do ARGS="$ARGS $(printf '%q' "$a")"; done

D="$(dirname "$0")"
scp -q "$D/bench.py" "$D/prompts.py" "$HOST":~/ || exit 1
exec ssh "$HOST" "python3 ~/bench.py $ARGS"
