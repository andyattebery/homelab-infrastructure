#!/usr/bin/env bash
set -uo pipefail

# Busy while any ffmpeg is running anywhere on this host — in a container or not.
#
# Suspending through an encode loses the work: a Tdarr server re-queues the file, but however
# far that encode had got is discarded along with its partial in /temp. An ad-hoc encode in a
# shell just dies.
#
# HOST-WIDE, NOT PER-CONTAINER. This replaced `podman top tdarr-node args | grep -qi ffmpeg`,
# which saw exactly one container and reported idle for everything else — another container,
# or a plain `ffmpeg` in a terminal, and the host would suspend mid-encode. Container
# processes appear in the host's own /proc with host-side PIDs, so one match covers all of
# them. Verified on this host: llama-swap's in-container PID 1 is host PID 2330 with the same
# cmdline. That also drops the podman dependency — no `podman top`, no per-container loop,
# and rootless containers are covered for free.
#
# -x, NOT -f. -x matches the process NAME; -f matches the whole command line, which here
# would also match `conmon` (its argv carries `-n <container>`, so any container named
# *ffmpeg* would trip it), any shell whose command line merely mentions ffmpeg, and parts of
# this check's own pipeline. Verified: `pgrep -f llama-swap` returns conmon as well as the
# process itself.
#
# ffmpeg only, not ffprobe: Tdarr probes finish in seconds, so suspending across one costs
# nothing, while holding the host awake for every probe is noise. The pattern is an ERE, so
# 'ffmpeg|ffprobe' is the change if that turns out wrong.
#
# Exit 0 = busy (hold the inhibitor), non-zero = idle. pgrep's own exit status is already
# exactly that contract, so there is nothing to translate.

pgrep -x 'ffmpeg' >/dev/null
