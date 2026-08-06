#!/usr/bin/env bash
set -uo pipefail

# Busy while a benchmark holds the GPU, declared by a lock file rather than inferred.
#
# WHY THE OTHER CHECKS DO NOT COVER THIS: the backend A/B
# (research/local-llm/bench/llama-swap/run_matrix.py) STOPS llama-swap.service for its entire ~92-minute run.
# llama-swap.sh then fails its `podman exec` and reports idle — correctly, for its own
# purposes. comfyui.sh is idle because `gpu-mode llm` is a precondition of any measurement
# run, and ansible.sh is idle unless a playbook is writing. So without this check all three
# report idle while a process holds ~10 GiB across a ROCm or Vulkan context, and this host
# suspends on its own schedule. llama-swap.sh's own comment notes that suspending a process
# in that state "does not reliably survive resume" — it would void the session.
#
# A LOCK FILE, not a container-name match: the benchmark says when it is busy instead of
# this script guessing from names it would have to be kept in sync with. It also makes the
# behaviour testable without a GPU — see test_integration.py.
#
# The lock holds one line: the PID of the process that took it.
#
# STALENESS IS THE POINT OF THE PID. /run is tmpfs so a reboot clears the lock, but a run
# killed with SIGKILL leaves it behind, and a lock nothing can clear would pin this host
# awake indefinitely. If the recorded process is gone the lock is ignored, so the worst
# case of a crash is a stale file, not a machine that never sleeps again.
#
# Exit 0 = busy (hold the inhibitor), exit 1 = idle.

LOCK=/run/llama-bench.lock

[[ -f "$LOCK" ]] || exit 1

pid=$(head -n1 "$LOCK" 2>/dev/null) || exit 1

# Malformed or empty: treat as idle. Refusing to sleep on an unparseable file would be the
# same indefinite-hold failure the PID check exists to prevent.
[[ "$pid" =~ ^[0-9]+$ ]] || exit 1

# Signal 0 tests for existence without delivering anything. Run as root, so this succeeds
# for any live PID regardless of its owner.
kill -0 "$pid" 2>/dev/null || exit 1

exit 0
