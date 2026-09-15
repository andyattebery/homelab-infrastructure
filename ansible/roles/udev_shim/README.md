# udev_shim

Makes udev's *client* side work inside a container that runs no udevd. It fakes exactly two
things: the `/run/udev/control` file a libudev subscriber checks before it will join the udev
multicast group, and the device-add events themselves.

It does **not** install udev rules, run udevd, or process any kernel uevent. A container never
receives one — the shim manufactures the events a subscriber would otherwise wait for forever.

## Status: Production since 2026-09-14

Every step was measured rather than assumed, on an unprivileged Debian 13 PVE container:
a group-2 `sendmsg` from the container's own root is permitted, a real libudev subscriber
receives the message, **15 of 15** input devices announced by `--reconcile` arrived, and a second
reconcile delivered the same 15 again. See "What was verified".

Deployed the same day, and the end-to-end proof is not a test: the compositor picks up Sunshine's
virtual keyboard and mouse when a Moonlight client connects, and a person played a game through
it. That is the whole point of the role — libinput sees devices that no udevd ever announced.

## Inputs

Everything has a working default. The one that matters is `udev_shim_before_units`.

- `udev_shim_before_units` — **list** of units that must not start until `/run/udev/control`
  exists. Default `[]`. Wrong or unset: nothing orders your subscriber after the shim, and a
  subscriber that starts first is deaf **for its whole life** — see "Why ordering is the
  whole game". A *string* here is refused: `join(' ')` over a string iterates it character by
  character and renders `Before=u s e r @ 1 ...`, which systemd reads as nonsense unit names and
  ignores.
- `udev_shim_sender_path` — default `/usr/local/bin/fake-udev-send`. Must be absolute; a systemd
  `ExecStart=` does no `PATH` lookup.
- `udev_shim_python_path` — default `/usr/bin/python3`. The sender is stdlib-only.
- `udev_shim_watch_path` — default `/dev/input`. Must be absolute; systemd refuses a relative
  `PathChanged=` at unit load, which surfaces as a watcher that never fires.
- `udev_shim_prime_unit_name` / `_announce_unit_name` — default `udev-shim-prime.service` /
  `udev-shim-announce.service`. Must end `.service`.
- `udev_shim_announce_path_unit_name` — default `udev-shim-announce.path`. Must end `.path`:
  systemd derives a unit's type from its suffix, so a path unit named `.service` loads as a
  service with a `[Path]` section it ignores entirely — it starts, does nothing, and reports
  itself active.
- `udev_shim_unit_directory_path` — default `/etc/systemd/system`.
- `udev_shim_file_owner` / `_file_group` — default `root`/`root`. Inputs so the fixture test can
  render as an unprivileged user.

## Example

```yaml
- name: Fake udev for the container's compositor
  ansible.builtin.include_role:
    name: udev_shim
  vars:
    # A USER-scope compositor is ordered against by naming its user manager. A system unit
    # cannot be ordered against a user unit directly -- systemd has no cross-manager
    # dependencies, and upstream closed that request as not planned.
    udev_shim_before_units: ["user@{{ vdesktop_uid }}.service"]
```

## Why ordering is the whole game

systemd v257 `src/libsystemd/sd-device/device-monitor.c:158-175`:

```c
if (group == MONITOR_GROUP_UDEV &&
    access("/run/udev/control", F_OK) < 0 &&
    dev_is_devtmpfs() <= 0) {
        /* ... We do not set a netlink multicast group here, so the socket
         *     will not receive any messages. */
```

A subscriber created while that file is absent **binds to no multicast group at all**. It does
not error, it does not retry, and creating the file afterwards does not repair it — the check
runs once, at monitor creation. The only symptom is input that never arrives.

This is not a theoretical failure. It is what happened twice while this role was being built,
with a perfectly formed message and a successful `sendmsg` both times. `/run` is a tmpfs, so the
file vanishes at every boot and the prime unit has to recreate it every time.

`Before=` and deliberately **not** `Requires=`: if the shim fails, the caller's session should
still come up so an operator can log in and look at it, rather than the desktop failing to start.

## Two units, and why the second is trigger-only

**`udev-shim-prime.service`** runs once, early, `RemainAfterExit=yes`. It creates
`/run/udev/control` and announces every device already present. That second half matters more
than it looks: announcing writes `/run/udev/data/c<major>:<minor>`, and those files are what a
subscriber's **startup enumeration** reads. libinput skips any device whose db entry is missing
(`src/udev-seat.c:193`, `is_initialized`), so priming is what makes already-present devices
visible to a compositor that starts afterwards.

**`udev-shim-announce.path`** watches the directory and triggers
**`udev-shim-announce.service`**, which re-announces. The service has **no `[Install]` section**
on purpose — enabling it directly would run it once at boot and never again, which is
indistinguishable from working for the first thirty seconds and then silently dead. Enable the
path unit; never the service.

## Re-announcing is safe, which is why there is no state file

libinput's `device_added()` calls `filter_duplicates()` (libinput 1.28.1 `src/udev-seat.c:55-73`),
which ignores a device whose syspath the seat already has. So the shim can announce everything on
every trigger with no bookkeeping.

That is not just a simplification — it is required for correctness. A device node appears
**before** the host's udev has finished setting its ownership. Measured: one `IN_CREATE` followed
by three `IN_ATTRIB`. `PathChanged=` watches `IN_ATTRIB` too (systemd v257 `src/core/path.c:42`),
so the shim runs again after the ownership lands, and that later announcement carries the device
in its final, openable state. A design that announced once and remembered it had done so would
publish the device in its pre-rule state and never correct it.

`PathChanged=` rather than `PathModified=`: the only thing `PathModified` adds is `IN_MODIFY` —
writes to a file's *contents* — which for a directory of device nodes means waking on every write
to a device.

## The sender needs to run as root, and that is a kernel rule

Binding to the netlink multicast group is unprivileged (`lib/kobject_uevent.c:776-780` sets
`NL_CFG_F_NONROOT_RECV`). **Sending** to one is not: `af_netlink.c:1843-1846` gates it on
`netlink_allowed(sock, NL_CFG_F_NONROOT_SEND)`, which that config does not set, so it falls to
`ns_capable(sock_net(sk)->user_ns, CAP_NET_ADMIN)` (`:904-908`).

That capability is tested against the user namespace owning the socket's **network** namespace,
not `init_user_ns`. An unprivileged container's netns is owned by the container's own userns, so
**the container's root passes** — no `CAP_SYS_ADMIN`, no privileged container. An ordinary user
gets `EPERM`. Do not confuse `netlink_allowed()` with `netlink_capable()` (`:894-897`), which
*does* use `init_user_ns` and gives the opposite answer.

## What was verified, and what was not

Measured on an unprivileged Debian 13 PVE container, kernel 7.0:

| claim | result |
|---|---|
| unprivileged send to group 2 | refused, `EPERM` — as the kernel source predicts |
| root send with a *wrong* subsystem hash | sent successfully, **never arrived** (the silent drop) |
| root send with the correct hash | arrives at a real libudev subscriber |
| `--reconcile` | 15 of 15 devices announced, 15 of 15 received, real sysfs `DEVPATH`s |
| second `--reconcile` | same 15 delivered again; libinput de-duplicates |
| inotify on a bind-mounted `/dev/input` | fires: `IN_CREATE`, then three `IN_ATTRIB`, then `IN_DELETE` |

**Not** verified: that a wlroots compositor's libinput adds these devices and delivers keystrokes.
That needs a compositor and belongs to the build. `udevadm monitor --subsystem-match=input`
installs the same BPF filter libinput installs, so the transport and the filter are covered; the
evdev classification layer above them is not.

## What the tests prove

Two, deliberately different:

`tests/test_fake_udev_send.py` (pytest, 22 assertions) pins every byte of the wire format that
can fail **silently** — the MurmurHash2 vectors, the mixed endianness, the 40-byte header layout.
Its reference hashes came from compiling Austin Appleby's original C, not from calling the Python,
because asserting a port against itself proves only that it is deterministic. It was shown red
against three deliberate breaks before being trusted.

`tests/test.yml` (Ansible fixture) proves the units render correctly — that prime carries
`Before=`, that the announce service has no `[Install]`, that the path unit uses `PathChanged`,
that an empty before-list emits no `Before=` line at all (a bare `Before=` *resets* the list
rather than doing nothing), and that three bad callers are refused before anything is written.

```
cd ansible
.venv/bin/pytest roles/udev_shim/tests/ -q
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/udev_shim/tests/inventory \
    roles/udev_shim/tests/test.yml
```
