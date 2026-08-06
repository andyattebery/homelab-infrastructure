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

Prefer an explicit signal over inference where you can. A long-running job that takes a
lock file and writes its PID is testable without the hardware, and it stops the check from
having to guess from process or container names it would then have to be kept in sync with.
Record a PID rather than an empty lock: a lock nothing can invalidate pins the host awake
forever if the job is killed.

## Why a grace period

Without one, a host with several sequential jobs releases and reacquires the inhibitor in
every gap, and can win the race to suspend in between. The grace period is additive with
whatever window a check uses internally — a check matching activity in the last 5 minutes
plus a 300s grace means roughly 8 minutes of genuine quiet before the host may sleep.
