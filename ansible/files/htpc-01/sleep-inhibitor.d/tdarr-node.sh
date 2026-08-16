#!/usr/bin/env bash
set -euo pipefail

# Busy while the Tdarr node has an ffmpeg running — a transcode or a health check in
# flight. Suspending through one loses the work: the server re-queues the file, but
# however far that encode had got is discarded along with its partial in /temp.
#
# Read from the HOST, not from inside the container. `podman top` is served by psgo
# reading the host's /proc, so this needs no ps/pgrep in the tdarr image — unlike
# llama-swap.sh, which has to `podman exec` because it wants an HTTP endpoint that is
# only reachable on the container network. A node exposes no such endpoint.
#
# Not based on the presence of files in /temp, which looks equivalent and is not: a
# partial left behind by a crash or by a `gpu-mode` switch never goes away on its own,
# and would pin the host awake forever. A process either exists or it does not.
#
# Container stopped, or podman unreachable, means nothing is encoding: idle. That is
# also the gpu-mode case — `gpu-mode llm` stops tdarr-node, and the host should then be
# free to sleep rather than held awake by a container that is deliberately down.
#
# Exit 0 = busy (hold the inhibitor), exit 1 = idle.

podman top tdarr-node args 2>/dev/null | grep -qi ffmpeg || exit 1
exit 0
