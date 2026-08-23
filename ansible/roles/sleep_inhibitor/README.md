# sleep_inhibitor

Holds `systemd-inhibit --what=sleep` while any caller-supplied check reports a workload
active, so a host on an autosuspend timer does not suspend mid-job.

The role supplies the mechanism — a polling runner and its unit. **What counts as busy is
entirely the caller's**, as a directory of check scripts.

## Status: Production

## Inputs

Required:

- `sleep_inhibitor_checks_src` — directory of executable check scripts, relative to the
  playbook. Every file in it is copied to `/etc/sleep-inhibitor.d`. Asserted, because a
  service with no checks starts cleanly, finds nothing busy, and never inhibits anything —
  a unit that looks healthy while doing nothing.

  **`/etc/sleep-inhibitor.d` is managed exclusively.** Anything in it that this directory
  does not supply is **deleted** on the next run. That is what makes a check renameable:
  `copy` only ever adds, so without it a retired check keeps running and keeps voting
  "busy" from logic that no longer matches anything — the same pin-the-host-awake failure
  the checks are written to avoid, reached from the other direction. The practical
  consequence is that hand-dropping a script into that directory is not a way to hold
  sleep; it will survive until the next playbook run and no longer.

Optional:

- `sleep_inhibitor_grace_period` — default `300`. Seconds every check must report idle
  before the inhibitor is released. Stops a brief gap between two jobs from dropping the
  lock.
- `sleep_inhibitor_poll_interval` — default `30`. Seconds between polls. Each check gets a
  10s timeout, so keep this comfortably above `checks × 10`.

## Example

```yaml
- name: Inhibit sleep while GPU work is running
  ansible.builtin.include_role:
    name: sleep_inhibitor
  vars:
    sleep_inhibitor_checks_src: files/<host>/sleep-inhibitor.d/
```

## Writing a check

A check is any executable in the directory. The contract is one line:

> **exit 0 = busy** (hold the inhibitor) · **non-zero = idle**

Notes that matter in practice:

- **Executable or ignored.** The runner skips anything without the execute bit, silently.
  The role copies with `0755` for this reason.
- **10 second timeout**, enforced per check. A check that hangs is treated as idle, so
  prefer a short `--max-time` on anything that talks to a network or a container.
- **Failure is idle.** A check that errors reports idle. Decide deliberately which way an
  *unknown* state should fall: probing a service that is unreachable usually means nothing
  is running, but a check that cannot tell should often claim busy rather than risk
  suspending mid-work.
- **Name it after the workload.** The name appears in the inhibitor's `--why`, which is
  what `systemd-inhibit --list` shows.

- **Prefer host-wide over per-container.** Container processes appear in the host's own
  `/proc` with host-side PIDs, so `pgrep -x <name>` sees them without any container runtime
  in the check — and covers an ad-hoc run of the same program, which a `podman top <name>`
  check cannot. Match the process **name** (`-x`), not the command line (`-f`): `conmon`'s
  argv carries the container name, so `-f` matches the supervisor as well as the workload.

Prefer an explicit signal over inference where you can. A long-running job that takes a
lock file is testable without the hardware, and it stops the check from having to guess
from process or container names it would then have to be kept in sync with.

**Never write an open-ended lock.** A lock nothing can invalidate pins the host awake
forever once the job that took it is gone. Two shapes that cannot do that:

- a **PID**, ignored once that process no longer exists — for a job that supervises itself
- a **deadline** (an epoch second), ignored once it passes — for a hold a person takes, who
  will forget

Put the lock under `/run` so a reboot clears it either way, and let every unclear state —
missing, unreadable, malformed — fall to *idle*. Refusing to sleep because a file could not
be parsed is an indefinite hold nobody asked for, which is the thing worth avoiding.

The one defensible open-ended lock is an **operator** taking one deliberately, and only when
it is visible and releasable — listed by whatever CLI sets it, and clearable with one
command. That is a narrow exception to the rule above, not a softening of it: it exists
because the thing people otherwise reach for is a hand-rolled
`systemd-run … systemd-inhibit … sleep infinity`, which holds sleep just as hard while being
invisible to every check here. An unbounded hold that is listed and releasable beats one that
is neither. A *job* should still never write one.

## Why a grace period

Without one, a host with several sequential jobs releases and reacquires the inhibitor in
every gap, and can win the race to suspend in between. The grace period is additive with
whatever window a check uses internally — a check matching activity in the last 5 minutes
plus a 300s grace means roughly 8 minutes of genuine quiet before the host may sleep.
