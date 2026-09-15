# sway_headless_wayland_session

Runs a headless wlroots compositor as a **systemd user unit**, owning a GPU render node and real
evdev input devices, and publishes the Wayland socket name it picked so other user units can
attach to it.

**What runs inside it is entirely the caller's.** This role starts no desktop, no browser and no
capture — it provides a compositor and gets out of the way.

## Status: Production since 2026-09-14

Replaced `sway_headless_x11_session`, which was deleted on 2026-09-14. That role put a rootful
Xwayland on top of a compositor so X11 clients could get DRI3; this one has no X server, no
Xwayland and no XTest anywhere in it. The reason it had to go: **Chromium cannot reach the GPU
through Xwayland** -- measured at 0 render-node fds and 3 GPU-process crashes there, against 9
fds and 0 crashes as a native Wayland client on the same compositor.

## Inputs

Required, asserted, no default:

- `sway_headless_wayland_session_user` — the account the compositor runs as **and whose user
  manager the unit is installed into**. Wrong: a guessed account installs a unit into a manager
  nobody runs, and the play reports success.

Optional:

- `_width` / `_height` / `_refresh` (1920/1080/60) — the headless output's size **at startup**.
  sway parses this **at runtime**, so a bad value is not an error at converge time — it is a
  session that comes up the wrong size with nothing in any log. If a caller wires
  `_client_mode_script_path` to a streaming server, these become the boot default only; see
  "The resolution can stop being yours".
- `_client_mode_script_path` (`/usr/local/bin/sway-headless-wayland-set-mode`) — asserted
  absolute. Always rendered; inert unless something invokes it. See below.
- `_swaymsg_path` (`/usr/bin/swaymsg`), `_logger_path` (`/usr/bin/logger`) — baked into that
  script and run **at runtime**, never by Ansible, which is what lets the fixture test point them
  at stubs and assert the exact command.
- `_render_node` (`/dev/dri/renderD128`) — asserted to be a `renderD*` node. A card node does not
  exist in an unprivileged container at all, and a colon-separated list is `WLR_DRM_DEVICES`
  syntax, which belongs to a backend this role never loads. Both surface as an EGL error a long
  way from the value that caused them.
- `_wlr_backends` (`headless,libinput`) — **asserted to contain both**. See "libinput is not
  optional here".
- `_wlr_renderer` (`gles2`) — asserted to be `gles2` or `vulkan`. See "Losing the GPU is a
  refusal to start".
- `_libseat_backend` (`noop`) — there is no seat and nothing to assign one; `input` group
  membership replaces logind/seatd.
- `_no_devices` (`true`) — see "WLR_LIBINPUT_NO_DEVICES is mandatory, and is not what it sounds
  like".
- `_env_file_name` (`wayland-session.env`) — a bare **name**, asserted; the wrapper joins it to
  `$XDG_RUNTIME_DIR` at runtime. See "The socket name cannot be a literal".
- `_unit_name` (`sway-headless-wayland.service`), `_wanted_by` (`default.target`) —
  `multi-user.target` is refused; see "It is a user unit, and that is the point".
- `_home`, `_unit_directory_path`, `_config_path`, `_script_path`, `_sway_path`,
  `_systemd_notify_path`, `_loginctl_path`, `_packages`, `_start_timeout_seconds`,
  `_file_owner`/`_file_group`, `_unit_owner`/`_unit_group` — every path is an input so the
  fixture test can point it at a tempdir.

## Example

```yaml
- name: Run a headless Wayland compositor on the iGPU
  ansible.builtin.include_role:
    name: sway_headless_wayland_session
  vars:
    sway_headless_wayland_session_user: "{{ vdesktop_desktop_user }}"
    sway_headless_wayland_session_unit_name: "{{ vdesktop_wayland_unit_name }}"
    sway_headless_wayland_session_width: "{{ vdesktop_width }}"
    sway_headless_wayland_session_height: "{{ vdesktop_height }}"
    sway_headless_wayland_session_render_node: "{{ vdesktop_render_node }}"
```

## It is a user unit, and that is the point

The X11 role this replaced installed a **system** unit with `User=` and `PAMName=login`. This one
does not, because systemd has **no dependencies that cross between the system and user managers**
— upstream closed that request as not planned. Anything that must be ordered against the
compositor (a browser, a stream host) can only express that if it lives in the same manager, so
the compositor moves to where its consumers are.

What falls out of that, all deliberate:

| directive | why it is absent |
| --- | --- |
| `User=` | the manager already runs as the account |
| `PAMName=login` | it exists on a **system** unit to obtain `XDG_RUNTIME_DIR`; a user manager supplies `/run/user/<uid>` natively |
| `TTYPath=` | nothing allocates a tty here |
| `WantedBy=multi-user.target` | **that target does not exist in a user manager** — a unit enabled against it reports `enabled` forever and never starts. Refused by an assert. |

The account needs `loginctl enable-linger`, or the user manager does not exist while nobody is
logged in and the compositor stops the moment a session ends. `tasks/main.yaml` does it, before
anything else touches the manager.

## The socket name cannot be a literal

sway 1.10.1 `sway/server.c` loops `wayland-1`…`wayland-32`, takes the first socket that binds, and
deliberately never uses `wayland-0`. **No environment variable or option sets it.** So the name
depends on what else is already on the runtime directory, and a consumer with a hardcoded
`wayland-1` is right until it silently is not — capture and clients attach to nothing, and
neither reports an error.

The wrapper is `exec`ed by sway and therefore inherits the real value. It writes it once to
`$XDG_RUNTIME_DIR/<env file name>` as `WAYLAND_DISPLAY=<socket>`, which consumers read with
systemd's `EnvironmentFile=`. One writer, any number of readers.

Written to a temp name and `mv -f`'d into place: a consumer reading a half-written file gets a
truncated socket name, which fails in exactly the same silent way as a wrong one.

## Type=notify, because "started" must mean "attachable"

With `Type=simple` the unit is active the instant sway is exec'd — before the Wayland socket
exists and before the environment file is written. Everything ordered `After=` it would then race
both.

sway implements no readiness protocol of its own (checked: no `sd_notify` anywhere in 1.10.1), so
the notification comes from the wrapper, and `NotifyAccess=all` is what lets it: systemd accepts
status updates from *any process in the unit's cgroup*, not just the main one. Without that
directive the notification is refused and the unit hangs until its start timeout.

That hang is the intended failure mode. A unit stuck in `activating` and then failing loudly beats
a unit reporting `active` with no socket behind it.

## libinput is not optional here

`headless` supplies the output; **`libinput` supplies input**. The X11 role used `headless`
alone because everything reaching it went through Xwayland's XTest — and **there is no XTest on
Wayland**. A compositor without the libinput backend can never receive a keystroke, and it looks
entirely healthy while failing to. The role asserts both backends are present.

## WLR_LIBINPUT_NO_DEVICES is mandatory, and is not what it sounds like

wlroots' libinput backend **exits** if it starts with zero input devices
(`backend/libinput/backend.c:110-114`). A compositor whose input devices are created later — by
whatever will inject input into it — has zero of them at every cold boot, so without this it loses
every one.

It suppresses a **startup abort**, not device detection: enumeration already happened one line
earlier, at `:109`, and the log line the check prints says so itself. The variable's name suggests
the opposite and every search summary repeats the wrong reading. Do not remove it on the strength
of its name.

## Losing the GPU is a refusal to start, not a silent downgrade

`WLR_RENDERER=gles2` is a safety device rather than a preference. wlroots refuses to initialise
EGL on a software device unless `WLR_RENDERER_ALLOW_SOFTWARE` is set (`render/egl.c`). So a lost
GPU becomes a compositor that will not start, instead of one that comes up looking correct and
rasterises on the CPU. **Never set that variable**, and never set `WLR_RENDERER=pixman`; the role
asserts against the latter.

## `sway --validate` is not a config check

It looks like one and is not: sway 1.10.1's `--validate` **creates a backend**, so without
`WLR_BACKENDS` in the environment it reaches for DRM and dies on libseat with `Could not open
target tty` — which reads exactly like a config error. There is deliberately no pre-flight
validation task.

## Nothing is started inside the compositor

The wrapper does not `exec` a session command, and that differed from the X11 role on purpose.
What runs inside belongs to the caller and to its own units, which order themselves `After=` this
one and read the socket name from the environment file. A session command here would tie the
compositor's lifetime to a client's, which is backwards — the compositor is what everything else
attaches to.

There is also no `Conflicts=`. The X11 role has it to take a display number from a predecessor
atomically; there is no predecessor here.

## The resolution can stop being yours

The role renders `_client_mode_script_path` unconditionally. It does nothing until something runs
it — the intended caller is a streaming server's connect hook, e.g. Sunshine's
`global_prep_cmd`, which exports `SUNSHINE_CLIENT_WIDTH` / `_HEIGHT` / `_FPS`. The script reads
those from **its own environment** (Sunshine does not expand `$VAR` for free; its documented
examples wrap commands in `sh -c`) and runs `swaymsg output '*' mode --custom WxH@RHz`.

Wire that up and **`_width`/`_height`/`_refresh` become the boot default, not a description of
the running output.** Nothing restores the mode when a stream ends. That divergence is
deliberate and it has a cost worth stating plainly: a reader who trusts the playbook about this
host's resolution will be wrong, and `swaymsg -t get_outputs` is the only truth.

Two behaviours of the script are not preferences and should not be "tidied":

- **It always exits 0**, including every refusal. Sunshine aborts the stream launch when a prep
  command fails, so an error path that exits non-zero converts *"the resolution did not change"*
  into *"there is no stream at all"*. On a host that exists to be streamed from, degrading to the
  current mode is always better. The cost is that failure is silent, which is why every path
  logs through `logger -t sway-set-mode` — `journalctl -t sway-set-mode` is the whole diagnostic
  surface.
- **It finds the IPC socket in three tiers**: `$SWAYSOCK`, then the published env file, then
  derived from the running compositor as `sway-ipc.<uid>.<pid>.sock`. The last tier exists so the
  helper works *before* the compositor has been restarted to pick up a wrapper that publishes
  `SWAYSOCK` — restarting it kills every attached client. It **derives** that path rather than
  globbing `sway-ipc.*.sock`, because the runtime directory accumulates stale sockets from
  previous sessions and a glob returns one nothing is listening on, which fails as a timeout
  rather than an error.

`swaymsg -s` is passed explicitly. Without it swaymsg discards the path and redoes its own
discovery, which would make the whole lookup decorative.

## Changing the configuration does not restart the session

This unit **is** the live session. Restarting it kills every client attached to it, which on a
single-purpose streaming host is the entire point of the machine. The role reports that a restart
is owed and leaves the decision to an operator.

## What the test proves, and what it does not

`tests/test.yml` proves the role renders a **user** unit with `Type=notify` + `NotifyAccess=all`
and without `User=`/`PAMName=`/`TTYPath=`/`multi-user.target`; that the config sets the mode,
execs the wrapper, mentions no Xwayland and binds no keys; that the wrapper publishes
`$WAYLAND_DISPLAY` atomically and notifies readiness without ever naming a literal socket; that a
second render changes nothing; and that four bad callers are refused **before anything is
written** — no user, the software renderer, a backend list without libinput, and
`multi-user.target` as a user unit's install target.

It proves **nothing** about whether the compositor starts, whether EGL reaches the GPU, whether
libinput opens a device, or whether a client can attach. None of that is answerable on a
controller with no GPU and no systemd; it belongs to the build.

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/sway_headless_wayland_session/tests/inventory \
    roles/sway_headless_wayland_session/tests/test.yml
```
