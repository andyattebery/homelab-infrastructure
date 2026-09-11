# systemd_unit_watchdog

Restarts systemd units that should be up and are not, on a timer.

Exists because a failed `.mount` has no way back. `Restart=` is not a mount-unit option, and a
consumer whose `RequiresMountsFor=` dependency failed never runs its own `Restart=` either —
that governs a service which started and exited, not one whose dependency failed. So a NAS that
reboots leaves the mounts `failed` and everything above them down until a person notices.

The role supplies the mechanism. **What should be up is entirely the caller's**, as two
explicit lists. This role never discovers work for itself — see the trap below.

## Status: Production

## Inputs

Required — at least one of the two lists must be non-empty, asserted, because a watchdog with
both empty installs, fires on schedule, reconciles nothing and reports success:

- `systemd_unit_watchdog_mount_paths` — default `[]`. Mount **points**, not unit names. Each is
  escaped to a `.mount` unit at runtime with `systemd-escape --path --suffix=mount`, so a
  caller passes the same paths it already has. A path whose unit does not exist is warned about
  on every pass, not skipped silently.
- `systemd_unit_watchdog_units` — default `[]`. Unit names, reconciled **after** every mount
  above, and **only if every mount came up**. Starting a consumer whose `Requires=` mount is
  still down is a guaranteed failure that burns start-limit budget and marks a healthy unit as
  failing.

Optional:

- `systemd_unit_watchdog_interval` — default `2min`. `OnUnitActiveSec=`, and therefore the
  worst-case recovery latency once the far end returns. Lower it and a long outage retries more
  often for no benefit; raise it and recovery takes longer.
- `systemd_unit_watchdog_boot_delay` — default `2min`. `OnBootSec=`. At boot the mounts are
  still being attempted for the first time; firing into that races them.
- `systemd_unit_watchdog_script_path` — default `/usr/local/sbin/systemd-unit-watchdog`.
- `systemd_unit_watchdog_unit_directory_path` — default `/etc/systemd/system`.
- `systemd_unit_watchdog_state_dir` — default `/run/systemd-unit-watchdog`. One marker per
  currently-failing unit. Under `/run` on purpose: the markers mean nothing across a reboot, and
  clearing them is how a reboot produces a fresh "went down" line instead of silence.
- `systemd_unit_watchdog_systemctl` — default `/usr/bin/systemctl`.
- `systemd_unit_watchdog_systemd_escape` — default `/usr/bin/systemd-escape`. Both are paths
  rather than bare names so the fixture test can point them at stubs; a wrong path makes every
  unit look like it does not exist, which the script warns about loudly.

## Example

Lifted from the calling playbook (`playbook-<host>.yaml`). The mount list is the same one the
mount role is given, so the watchdog cannot be guarding a different set than exists:

```yaml
- name: Keep the storage mounts and their consumers up
  tags: mount-watchdog
  ansible.builtin.include_role:
    name: systemd_unit_watchdog
    apply:
      tags: mount-watchdog
  vars:
    systemd_unit_watchdog_mount_paths: "{{ storage_cifs_mounts | map(attribute='path') | list }}"
    systemd_unit_watchdog_units:
      - tdarr-node.service
      - comfyui.service
```

## It will not start a unit that was deliberately turned off

A unit that is installed, not active, and has an **empty `WantedBy`** is left alone, silently.
That is the same test as `podman_quadlet`'s `__podman_quadlet_installed_off` and `gpu-mode`'s
`boot_enabled()`, and it is what lets this role coexist with a GPU-arbitration script that
stops a container on purpose by removing its `[Install]` drop-in.

Consequence worth knowing: listing a GPU container such as `comfyui.service` here is safe precisely because
`gpu-mode` clears its `WantedBy` when another mode is selected. The watchdog brings it back only
when `gpu-mode comfy` is the chosen mode.

## Why it takes an explicit list and never scans for failed mounts

**The `WantedBy` test is only sound over units that something in this repo installed with an
`[Install]` section.** udisks removable-disk mounts also report an empty `WantedBy`, and there it
means "mounted by udisks", not "turned off" — any removable or internal disk the desktop
mounted for itself will look exactly like a unit you turned off.

So a future version that discovered its own work by scanning `systemctl --failed` for mounts
would start fighting udisks over disks it knows nothing about. Feed it a list.

The same boundary means the watchdog cannot help when a udisks-managed mount fails, even if a
unit in your list depends on it. udisks owns that mount, and this role deliberately does not.

## One instance per host

The unit names are fixed (`systemd-unit-watchdog.{service,timer}`), so a second `include_role`
on the same host overwrites the first rather than running alongside it. Put every unit for a
host in the one invocation.

## No handlers

Deliberate. A handler fires at end of play, which in a fixture test means a `systemd` call on a
controller that has none. `tasks/install.yaml` renders and registers; `tasks/main.yaml` is the
only place that talks to systemd, and it restarts the timer when a unit file actually changed.
That split is what makes `tasks_from: install.yaml` testable — see `tests/test.yml`.
