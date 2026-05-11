# shutdown_tracker

Coordinate auto-poweroff of a backup-target host after expected sources have signaled completion.

The role owns both halves of the protocol; mode is selected by two boolean flags (both default `false`):

- `shutdown_tracker_destination: true` — apply destination-side configuration (the host that receives signals and powers off)
- `shutdown_tracker_source: true` — apply source-side configuration (the host that signals completion)

Both can be set on the same host if needed; if neither is set, the role is a no-op.

## Destination mode

Renders:
- `/usr/local/sbin/shutdown_tracker_complete` — POSIX-sh script invoked by sources via SSH+sudo. Marks the source complete and, if all expected sources have signaled, schedules `systemctl poweroff` via `systemd-run`.
- `/usr/local/sbin/shutdown_tracker_watchdog` — POSIX-sh script run by a systemd timer. Deadline-triggered safety net for cases where signals never arrive: evaluates each pending source's `busy_check_command`, defers if any reports busy, otherwise powers off.
- `/etc/shutdown_tracker/sources.d/<source_name>` — one file per expected source containing the source's `busy_check_command` shell command.
- `/etc/sudoers.d/shutdown_tracker_complete` — scoped sudoers grant for `shutdown_tracker_destination_username` to invoke the complete script.
- `/etc/systemd/system/shutdown_tracker_watchdog.{service,timer}`, `/etc/tmpfiles.d/shutdown_tracker.conf`.

State (in tmpfs, auto-cleared on reboot):
- `/run/shutdown_tracker/completed/<source_name>` — touched when a source signals.
- `/run/shutdown_tracker/pause` — admin-managed override file (see Operations).

### Required vars
- `shutdown_tracker_expected_sources` — list of dicts, each with `name` and `busy_check_command`. Example:
  ```yaml
  shutdown_tracker_expected_sources:
    - name: backup-01
      busy_check_command: "pgrep -fa 'zfs receive'"
    - name: nas-01
      busy_check_command: "pgrep -fa 'zfs receive'"
  ```
- `shutdown_tracker_destination_username` — the unprivileged user sources SSH in as.

### Optional vars (defaults shown)
- `shutdown_tracker_complete_signal_timeout_minutes: 720` — when to first fire the watchdog (12h after boot).
- `shutdown_tracker_watchdog_retry_minutes: 60` — re-check interval after a deferred fire.
- `shutdown_tracker_poweroff_grace_seconds: 30` — delay between "all signaled" and `systemctl poweroff`.
- Path overrides — see `defaults/main.yaml`.

### busy_check_command semantics
Each `busy_check_command` is a shell command run on the destination at watchdog fire time:
- exit `0` — busy (defer poweroff)
- exit `1` — idle (eligible for poweroff)
- any other exit — treated as busy (fail-safe; a typo or missing binary should never cause premature poweroff)

## Source mode

Renders one wrapper script per destination:
- `/usr/local/bin/shutdown_tracker_complete_call_<destination_host_with_dots_replaced>` — POSIX-sh wrapper that SSHes to the configured destination and invokes the destination's complete script with the source key.

The wrapper is invoked from existing systemd units (e.g. via `syncoid_post_sync_commands`) as `<wrapper_path> <source_key>`.

### Required vars
- `shutdown_tracker_source_ssh_key_path` — absolute path to the SSH private key the wrapper uses.
- `shutdown_tracker_destination_host` — SSH target (e.g. `offsite-nas.<tailnet>`).
- `shutdown_tracker_destination_username` — SSH user on the destination (matches the destination's `shutdown_tracker_destination_username`).

## Operations

### Pause auto-poweroff during maintenance
Before logging into the destination for maintenance, run:
```sh
sudo touch /run/shutdown_tracker/pause
```
Both poweroff paths (complete script + watchdog) short-circuit while this file exists. The file lives in tmpfs, so a reboot auto-clears it — a forgotten pause is self-healing within one cycle.

### Inspect state
```sh
ls /etc/shutdown_tracker/sources.d/        # expected sources
ls /run/shutdown_tracker/completed/        # who has signaled this cycle
journalctl -t shutdown_tracker -n 50       # recent activity
systemctl list-timers shutdown_tracker_watchdog.timer
```
