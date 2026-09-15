# sunshine

Installs [Sunshine](https://github.com/LizardByte/Sunshine), a self-hosted game-stream host
for Moonlight clients, from LizardByte's own apt repository.

The role supplies the mechanism. **What gets streamed, and from which display, is entirely
the caller's** — the role has no opinion about desktop environments and does not install one.

## Status: Production

Deployed 2026-09-12. Proven on the host: Sunshine starts under a lingering user manager with
nobody logged in, opens the render node, selects the VA-API encoder, and advertises over Avahi.

Extended 2026-09-14 for Wayland callers: `sunshine_display` may now be empty,
`sunshine_environment` and `sunshine_environment_files` add drop-in lines, and
`sunshine_unit_after`/`_wants` express ordering against the session being captured.

Read "Pin `capture`" below before adding a caller. The default capture order silently
degrades to a PipeWire path that can saturate journald, and it does not announce itself.

## Why an apt repository and not `github_release_install`

Sunshine is third-party, but it *is* packaged: LizardByte publish a Cloudsmith apt repository
covering trixie, so `apt upgrade` maintains it like any other package. Installing the GitHub
release `.deb` instead would mean no security updates, a version-regex idempotency check to
get right, and a `github_release_install` dependency — all avoidable.

## Inputs

Everything has a default; none of them are secrets.

Optional:

- `sunshine_apt_source_name` — default `lizardbyte`. **This is the filename**, not a label:
  `deb822_repository` derives both `/etc/apt/sources.list.d/<slug>.sources` and
  `/etc/apt/keyrings/<slug>.asc` from it. Keep it lowercase with only hyphens and digits —
  the slug rule differs between ansible-core 2.20 and 2.21, and names in that shape are
  identical under both.
- `sunshine_apt_repo_url` / `sunshine_apt_gpg_key_url` — upstream's repository and key.
  A wrong key URL fails loudly at `apt-get update`; a wrong repo URL does not necessarily
  (see "A wrong source is quiet").
- `sunshine_apt_suite` — default `{{ ansible_facts['distribution_release'] }}`. LizardByte
  publish one suite per Debian codename, so this follows the host rather than naming a
  release. A host whose codename upstream does not publish gets a valid, signed, **empty**
  source and "no candidate" at install time — not an error.
- `sunshine_apt_components` — default `[main]`.
- `sunshine_arch_map` — kernel architecture to Debian architecture. Templated into
  `Architectures:` rather than left to apt's `$(ARCH)`: `sources.list(5)` documents that
  substitution for suites, not for this field.
- `sunshine_package` — default `sunshine`. An input because the same repository also carries
  beta and nightly channels under other names.
- `sunshine_display` — default `:0`, and **may be empty**. Empty renders no
  `Environment=DISPLAY` line at all, which is what a Wayland host wants. Setting it alongside a
  Wayland session is not harmful (Sunshine checks `WAYLAND_DISPLAY` first and guards the X11
  branch on `window_system != WAYLAND`), but it logs a warning, and a drop-in naming a display
  the host does not have is a lie a later reader has to disprove.
- `sunshine_environment` — dict, default `{}`, rendered one `Environment=K=V` per entry. For
  values known at **render** time. **Not** the place for `WAYLAND_DISPLAY` on a headless
  compositor — see "Sunshine must start after what it captures".
- `sunshine_environment_files` — list, default `[]`, rendered one `EnvironmentFile=` per entry.
  For values known only at **runtime**. Prefix a path with `-` for systemd's ignore-if-missing
  behaviour; without it a missing file fails the unit, which is usually what you want.
- `sunshine_unit_after` / `sunshine_unit_wants` — lists, default `[]`. Added to the drop-in
  **after** it resets the packaged unit's `After=`/`Wants=`.
- `sunshine_global_prep_cmd` — list of `{do, undo}` mappings, default `[]`. Commands Sunshine
  runs around **every** stream, whichever app is launched. Pass real YAML structures, not a
  hand-written string; the template renders them with `to_json`. See "A prep command can abort
  the stream".

## Example

```yaml
- name: Configure the apt repository
  ansible.builtin.include_role:
    name: sunshine
    tasks_from: apt_repo.yaml
```

A full example, from a Wayland caller -- note the empty display and the runtime file:

```yaml
- name: Stream the session with Sunshine
  ansible.builtin.include_role:
    name: sunshine
  vars:
    sunshine_user: "{{ vdesktop_desktop_user }}"
    sunshine_display: ""
    sunshine_environment_files: ["{{ vdesktop_session_env_file }}"]
    sunshine_unit_after: ["{{ vdesktop_wayland_unit_name }}"]
    sunshine_unit_wants: ["{{ vdesktop_wayland_unit_name }}"]
    sunshine_config:
      encoder: vaapi
      capture: wlr
```

## A wrong source is quiet, which is why the tests assert an install simulation

A source pinned to the wrong architecture does **not** fail. `apt-get update` returns 0, and
`apt-cache policy sunshine` reports a candidate at priority 500 — apt fetches the foreign
index perfectly happily. The only visible symptoms are that apt names the package
`sunshine:<foreign arch>:` and that `apt-get install --simulate` fails rc=100 on
unsatisfiable dependencies.

This is not hypothetical: the first hand-written version of this source hardcoded
`Architectures: amd64`, and the first version of the test asserted "no candidate" and did not
reproduce. `tests/vdesktop/repro.yml` CONTROL 1 now constructs that state deliberately, and
both verify playbooks assert a clean **install simulation** rather than the mere existence of
a candidate. Do not weaken that back to a candidate check.

## Predecessors are removed before the new source is written

Not after. Two sources describing the same repository with different `Signed-By` values make
apt refuse *every* operation — `E: Conflicting values set for option Signed-By`,
`E: The list of sources could not be read`, rc=100. Written in the other order there is a
window where every apt call fails, **including this role's own**, so an interrupted run could
not be repaired by re-running it. `tests/vdesktop/repro.yml` CONTROL 2 reproduces exactly that.

## The apt half is split out so it can be tested

`tasks/apt_repo.yaml` touches no service and no GPU, which is what lets
`ansible/tests/vdesktop/` import it into a throwaway container. Anything needing systemd, a
render node or a running X server belongs in `tasks/main.yaml` and is only ever exercised on
a host. Keep that boundary.

## Upstream ships a systemd *user* unit, and nothing else

This decides how `tasks/main.yaml` works. The `.deb` contains only `/usr/lib/systemd/user/app-dev.lizardbyte.app.Sunshine.service` —
there is no system unit in the package at all:

    After=graphical-session.target xdg-desktop-autostart.target xdg-desktop-portal.service
    ExecStartPre=/bin/sleep 5
    ExecStart=/usr/bin/sunshine
    [Install]
    WantedBy=graphical-session.target
    Alias=sunshine.service

Three consequences:

- `systemctl is-active sunshine` finds nothing. It is `systemctl --user`, and the short name
  only works there because of the `Alias=`.
- A user unit does not run with nobody logged in. `loginctl enable-linger <user>` is required,
  and on a box whose whole purpose is running unattended that is not optional.
- `WantedBy=graphical-session.target` is useless if X is started from a *system* unit, which
  never creates a user-scope `graphical-session.target`. The unit would be enabled and never
  start — and `systemctl --user is-enabled` would cheerfully report `enabled` the whole time.
  `templates/override.conf.j2` rebinds it to `default.target` and sets `DISPLAY`, and
  `tests/test.yml` asserts exactly that, on the directive lines rather than on the file text.
  (The template explains itself, and that prose mentions `graphical-session.target`; a naive
  substring check matches the explanation and fails a correct render. It did, once.)

## Its udev rules and module-load fragment are inert in an unprivileged container

The package ships `modules-load.d/60-sunshine.conf` (loads `uhid`, for descriptor-driven gamepad
emulation) and `udev/rules.d/60-sunshine.rules` (permissions on `/dev/uinput` and `/dev/uhid`).
An unprivileged LXC can do neither module loading nor udev, so both fail quietly at install.
That is expected, not a fault.

**It does not follow that input falls back to XTest.** An earlier version of this file said so,
and it was wrong. `UI_DEV_CREATE` **succeeds** in an unprivileged PVE container — measured
2026-09-14 as an ordinary desktop account holding nothing but `input` group membership, with no
`CAP_SYS_ADMIN` and no privileged container. `uinput.c` contains no capability check at all;
access is governed purely by file permissions. That matters because **Wayland has no XTest**, so
a fallback assumption here is the difference between a working session and an unusable one.

What the inert fragments actually cost is that the **caller** must supply the two things they
would have done: load `uinput` on the host, and pass `/dev/uinput` into the container with a gid
the container maps.

`/dev/uhid` is a separate question and remains out of scope — it is the gamepad path, gated on
`can_access_uhid()`. **Gamepads still will not work.** Keyboard and mouse only.

## Sunshine must start after what it captures

Its capture backend is chosen exactly once, inside `platf::init()`, and never recomputed. A
Sunshine that starts before the session it captures will **never** capture it, however healthy
`systemctl --user is-active` looks — `main.cpp:390-396` logs the platform failure and
deliberately continues so the web UI stays reachable.

`sunshine_unit_after` / `sunshine_unit_wants` express that ordering. Both units must live in the
same systemd manager for it to bind at all: systemd has no cross-manager dependencies, so a
*user*-scope Sunshine cannot be ordered against a *system*-scope session. Move the session into
the user manager rather than reaching for a workaround.

For a Wayland session the socket name is not knowable at render time — the compositor picks it
at runtime — so `WAYLAND_DISPLAY` reaches Sunshine through `sunshine_environment_files`, a file
the compositor writes, never through `sunshine_environment`.

## Pin `capture`, or a broken display becomes a log flood

Sunshine's `capture` option is documented as *"Force specific screen capture method"*, with the
default *"Automatic. Sunshine will use the first capture method available."* That order, from
`src/platform/linux/misc.cpp`, is:

    nvfbc -> wlr -> kms -> x11 -> portal -> kwin

`portal` sits **after** `x11`, so on a host whose X session is down Sunshine does not fail — it
falls through to the XDG portal backend, which is the PipeWire path. With no PipeWire daemon
its thread loop spins:

    pw.thread-loop: 0x...: iterate error -22 (Invalid argument)

Measured on a deployed host: **~1,250 messages/second, 1.2 GB of journal in 46 minutes**, with
`systemd-journald` pinned at 100% of a core for 32 minutes of CPU time. Nothing in the stack
reports this as an error — the unit is `active`, and the only symptom is a busy journald.

Naming a method makes Sunshine attempt **only** that one, so a broken display fails quietly:

    sunshine_config:
      capture: x11       # or `wlr` on a wlroots compositor, `kms`, ...

**PipeWire is not a dependency to add.** Sunshine's Linux audio is PulseAudio-only
(`src/platform/linux/audio.cpp` includes `pulse/pulseaudio.h` and nothing else); `libpipewire`
is linked for portal *screen capture*. Installing the daemon would only make the wrong capture
path work.

The calling playbook's own documentation carries these numbers alongside the rest of that host's
reasoning; they are repeated here because the trap belongs to the role, not to any one caller.

## A prep command can abort the stream

`sunshine_global_prep_cmd` renders `global_prep_cmd`, whose `do` runs before a stream starts and
whose `undo` runs after it ends. **Sunshine treats a failing prep command as a reason to abort
the launch**, which is the same behaviour that makes the stock `apps.json` worth replacing — its
"Low Res Desktop" entry runs `xrandr` against an output most hosts do not have.

So anything wired here should end in a deliberate `exit 0` unless a failure genuinely should mean
"no stream". A command that is merely *missing* has the same effect, which is why a caller
naming a script from another role should carry the path in one variable read by both, rather than
writing it out twice.

The canonical use is making a virtual display follow the client: Sunshine exports
`SUNSHINE_CLIENT_WIDTH`, `SUNSHINE_CLIENT_HEIGHT`, `SUNSHINE_CLIENT_FPS` and `SUNSHINE_CLIENT_HDR`
to these commands. Note that **`$VAR` is not expanded for free** — upstream's own examples are
written `sh -c "... ${SUNSHINE_CLIENT_WIDTH} ..."`, supplying the shell themselves. A script that
reads its own environment needs no shell and no quoting inside the JSON.

Leaving `undo` as `""` means whatever the `do` command changed is **not** reverted when the
stream ends. That is a legitimate choice, but it makes the role's declared state and the live
machine diverge, so say so where you set it.

Two things this is **not**: it is not `dd_resolution_option` and friends, which are Windows-only
("Applies to Windows only" in upstream's configuration docs) despite those strings being present
in Linux builds; and it is not per-app `prep-cmd`, which lives in `sunshine_apps` and applies to
one entry rather than to the host.

## Configuring Sunshine without its Web UI

Out of the box Sunshine makes its web page mandatory: with no credentials set it redirects
every request to `/welcome` and refuses to do anything else. That is not something a playbook
can drive, so the role seeds the login itself and the UI is left needed only for pairing.

| Input | Effect when unset |
| --- | --- |
| `sunshine_config` | dict rendered as `key = value` into `sunshine.conf` |
| `sunshine_apps` | **empty: apps.json is not managed at all** and Sunshine's stock file stands |
| `sunshine_apps_env` | no `env` block in apps.json |
| `sunshine_web_username` / `_password` | **both empty: credentials are not touched**, and the Web UI demands first-run setup |

Absence and emptiness differ for `sunshine_apps` on purpose: an empty list is a meaningful
value (a host with nothing to stream), so "no apps configured" must not be spelled the same way
as "do not manage this file".

**Why the stock `apps.json` is worth replacing.** It ships a `Low Res Desktop` entry whose
prep-cmd runs `xrandr --output HDMI-1`, and a `Steam Big Picture` entry. On a host with a
different output name, or without Steam, those are not merely unused — a prep-cmd that fails
takes the stream launch with it.

**Credentials are stored with the pairing state.** `credentials_file` defaults to `file_state`
(`src/config.cpp`), which is `sunshine_state.json`. So the obvious way to change a password —
delete the file and re-run — **unpairs every client**. The role therefore seeds credentials
only when they are absent. To change them deliberately:

    ansible-playbook <playbook> -e sunshine_web_force_credentials=true

The password reaches `sunshine --creds` through argv and is readable from `/proc` for the
duration of that one call. `no_log` is set on the task; the argv exposure is inherent to the
CLI Sunshine provides.

**The role restarts Sunshine when its config changes.** Earlier it only reported that a
restart was owed, which made every config change a two-step procedure with a human in the
middle. A restart costs an in-flight stream and nothing else -- pairings are in
`sunshine_state.json`, not in the process.

**Pairing can be automated, and this role does not do it.** `POST /api/pin` takes
`{pairing_id, pin, name}` with basic auth, and the client side accepts a chosen PIN
(`moonlight --pin 1234 pair <host>`), so the exchange can be scripted end to end. It is left
out because it needs a Moonlight install on the controller, and because the PIN exchange is the
security boundary of the whole protocol — worth doing deliberately rather than as a side effect
of a converge run.
