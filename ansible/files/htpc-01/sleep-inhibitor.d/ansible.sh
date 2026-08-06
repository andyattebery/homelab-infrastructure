#!/usr/bin/env bash
set -uo pipefail

# Busy while an Ansible run is in flight.
#
# This host sleeps on its own schedule and a provisioning run can outlast the idle
# timeout — a multi-GB model download holds nothing else awake, since no container is
# running yet. Sleeping mid-run drops the SSH connection and fails the whole play, not
# just the current task.
#
# Ansible creates a per-task temp directory under the remote user's ~/.ansible/tmp and
# removes it when the task ends. Presence alone is NOT a usable signal: a run that dies
# leaves the directory behind, and this host had one orphaned since June. So match on
# recency instead, which also ignores those orphans.
#
# -maxdepth 2 deliberately reaches the files inside, not just the directory. A long
# task (get_url writing a 10 GiB model) only sets the directory's mtime once at
# creation, but the temp file inside is written continuously, so it stays fresh.
#
# The 5 minute window plus sleep-inhibitor.sh's 300s GRACE_PERIOD means roughly 8
# minutes of no Ansible write activity before the host is allowed to sleep.
#
# Exit 0 = busy (hold the inhibitor), exit 1 = idle.

for tmp_root in /var/home/*/.ansible/tmp /home/*/.ansible/tmp /root/.ansible/tmp; do
    [[ -d "$tmp_root" ]] || continue
    if find "$tmp_root" -mindepth 1 -maxdepth 2 -mmin -5 -print -quit 2>/dev/null | grep -q .; then
        exit 0
    fi
done

exit 1
