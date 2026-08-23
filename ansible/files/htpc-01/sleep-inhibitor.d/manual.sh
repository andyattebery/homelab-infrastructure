#!/usr/bin/env bash
set -uo pipefail

# Busy while an operator holds a manual inhibit, declared by a lock file rather than inferred.
#
# For work no other check can see: a firmware flash, a long copy, anything where the host must
# stay up because a person says so. Taken and released with `sleep-inhibit` (/usr/local/bin).
#
# THE LOCK HOLDS ONE LINE, either:
#   - an epoch second, the moment the hold expires; or
#   - the literal `indefinite`, a hold with no expiry.
#
# A deadline is the default and the better choice. An open-ended lock is the failure
# llama-bench.sh's PID check exists to prevent — nothing invalidates it, and the person who
# set it has by then forgotten, so the host never sleeps again.
#
# `indefinite` is nonetheless allowed, because the alternative was worse: without it the
# operator reaches for a hand-rolled `systemd-run … systemd-inhibit … sleep infinity`, which
# holds sleep just as hard while being invisible to `sleep-inhibit status` and to every other
# check here. An unbounded hold that is listed and releasable beats an unbounded hold that is
# neither. Two things still bound it: it is one word in `sleep-inhibit status`, and /run is
# tmpfs so a reboot clears it.
#
# Every UNCLEAR state falls to IDLE: no lock, unreadable, malformed, or past its deadline.
# Refusing to sleep because a file could not be parsed is an indefinite hold nobody asked for,
# which is the thing worth avoiding. The cost of being wrong here is one missed hold, not a
# machine that never sleeps again.
#
# Exit 0 = busy (hold the inhibitor), non-zero = idle.

LOCK=/run/sleep-inhibit-until

[[ -f "$LOCK" ]] || exit 1

until_epoch=$(head -n1 "$LOCK" 2>/dev/null) || exit 1

# Explicit, deliberate, and the only non-numeric value treated as busy.
[[ "$until_epoch" == "indefinite" ]] && exit 0

[[ "$until_epoch" =~ ^[0-9]+$ ]] || exit 1

[[ "$(date +%s)" -lt "$until_epoch" ]] || exit 1

exit 0
