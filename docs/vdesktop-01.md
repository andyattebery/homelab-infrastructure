# vdesktop-01 — headless Wayland session streamed with Sunshine + Quick Sync

> **Status as of 2026-09-14 — built, running, and the game is playable.** The container was
> destroyed and recreated from the playbook, and a person played through Moonlight at
> **80-90 fps**.
>
> CT **120** on **vm-host-01**, unprivileged Debian 13 LXC at **192.168.1.237**. Created from
> nothing by `ansible/playbook-vdesktop-01.yaml` with no typed arguments and no hand steps.
>
> A headless **sway** compositor owning the iGPU, the browser as a native Wayland client with
> hardware rendering, Sunshine capturing through `wlr` and injecting input through
> `/dev/uinput`, and `wayvnc` on a UNIX socket as a second viewer. **There is no X server on
> this host** — no Xorg, no Xwayland, no XFCE, no XTest.
>
> **This supersedes an X11 build that worked but could not render.** That version streamed and
> paired correctly and the game was unplayable: `xf86-video-dummy` exposes no DRM device and no
> DRI3, so the browser rasterised on the CPU while the GPU did nothing but encode. Sections
> marked *superseded* below record why the replacement looks the way it does.
>
> The reasoning, with every claim traced to source or measurement, is in
> `plans/vdesktop-01-wayland-native.md`.

## Why this host exists

Two requirements drove every decision, and they pull in different directions:

1. **It keeps running when the laptop is off.** So the browser lives on a server, not the Mac.
2. **The Mac side must be cheap.** Firefox on the MBP burns ~8% CPU and hurts battery. A remote
   desktop that costs the client as much as the browser did solves nothing.

Requirement 2 is why this is a *hardware-encoded video stream* rather than a remote desktop
protocol that ships drawing primitives. The client decodes H.264 in fixed-function silicon and
does nothing else.

## Why an LXC and not a VM — the decisive argument

The host has a 9th-gen Intel CPU with Quick Sync. **A VM can only reach the UHD 630 by
exclusive passthrough of `00:02.0`, which is the host's own primary VGA.** The alternatives
do not exist on this hardware:

- **SR-IOV** for Intel graphics is Gen12+. This is Gen9.5.
- **GVT-g** was archived by Intel in October 2024 and has been broken since roughly kernel 6.8.
  The node runs 7.0.14-16-pve.

A container just shares `/dev/dri/renderD128`. That is the whole argument, and it is why this
host is a container even though a VM would have been more conventional.

**This also decided the distribution.** Fedora Atomic (and Bazzite) were considered seriously
and rejected: ostree/bootc own the boot path and cannot run as an LXC, so atomic forces a VM —
which costs the Quick Sync that justified the container in the first place. Recorded here so it
is not re-litigated.

## How it is built

    ansible-playbook playbook-vdesktop-01.yaml

Two plays. The first targets **the node** (`vm-host-01`), because the container may not exist
yet; the second targets the container.

| Play | Role | What it does |
| --- | --- | --- |
| create | `kernel_module` | loads `uinput` on the node; autoload cannot be relied on from a container |
| create | (playbook task) | the `lxc-input` group at gid **100996**, which is what the container's `input` (996) maps to |
| create | `udev_rule` | publishes Sunshine's virtual devices into that group, `MODE="0660"` |
| create | `pve_lxc` | container lifecycle via the PVE API token, plus the two option families the API refuses from a token |
| configure | (playbook tasks) | desktop account, GPU + input group membership, VA-API driver |
| configure | (playbook task) | **Chromium**, from Debian's own archive — the browser this host runs |
| configure | `udev_shim` | fakes `/run/udev/control` and the device-add events a container never receives |
| configure | `sway_headless_wayland_session` | the compositor, as a **user** unit |
| configure | (playbook tasks) | the browser as a Wayland client, user unit |
| configure | `sunshine` | LizardByte apt repo, config, user unit, lingering |
| configure | (playbook tasks) | `wayvnc` on a UNIX socket as a second viewer |

**There is deliberately no `configure_server`.** An earlier version of this table claimed there
was, and it was wrong. That role carries the fleet baseline — beszel_agent, node_exporter,
textfile_collector, fail2ban, unattended-upgrades — which is right for a server and wrong for a
box that runs one application: every agent it gained would be another row in Beszel and another
target in Prometheus for a host nobody needs to monitor that way.

Host-specific values live in `ansible/host_vars/vdesktop-01/vars.yaml` and the vault; the roles
know nothing about this host. The MAC comes from 1Password via the vault, which is why the
container can be rebuilt without anyone typing it — and why the DHCP reservation and DNS name
in `network-inventory/` keep working across a rebuild.

## Traps

Each of these cost real time. They are here so they cost it once.

### `xinit` silently discards a relative client program — *superseded, lesson retained*

There is no `xinit` on this host any more, and the role that ran it (`xorg_dummy_session`) was
deleted on 2026-09-14 once the Wayland build was proven. This is kept because the lesson at the
end of it is the most reusable thing in this document, and it applies unchanged to the
compositor that replaced it.

`xinit(1)`, verbatim:

> Both the client program name and the server program name must begin with a slash (/) or a
> period (.). Otherwise, they are treated as an arguments to be appended to their respective
> startup lines.

So `xinit startxfce4 -- :0` does **not** run `startxfce4`. It appends it to the *default*
client, which is `xterm`, absent on a headless box:

    xinit: Unable to run program "xterm": No such file or directory

X starts, the client fails, the session exits, systemd restarts it. **The unit reports
`active (running)` throughout**, because each restart is briefly alive. This shipped once and
reached **187 restarts** before anyone read the journal. The role grew an assert refusing a
command that did not begin with `/` or `.`, with a fixture-test control that constructed one --
both deleted with it, which is why the lesson is written out here rather than left in the code.

**The general lesson: `systemctl is-active` is not health.** A service failing by restart-loop
is indistinguishable from one that works unless you look at `NRestarts` or the journal.

### Sunshine falls back to PipeWire capture and floods the journal

Sunshine's capture backends are tried in this order when `capture` is unset
(`src/platform/linux/misc.cpp`):

    nvfbc -> wlr -> kms -> x11 -> portal -> kwin

**`portal` sits after `x11`.** So when the X session was restart-looping, Sunshine did not fail
— it degraded into the XDG portal backend, which is the PipeWire path. With no PipeWire daemon
its thread loop spins:

    pw.thread-loop: 0x...: iterate error -22 (Invalid argument)

Measured here: **~1,250 messages/second, 1.2 GB of journal in 46 minutes**, with
`systemd-journald` pinned at 100% of a core for 32 minutes of CPU. Nothing reported an error;
the only visible symptom was a busy journald.

Naming a method makes Sunshine attempt **only** that one, so a broken display fails quietly.
The playbook sets `capture: wlr` — the `zwlr_screencopy_manager_v1` path a wlroots compositor
offers. The literal string is checked at `misc.cpp:1350`.

**PipeWire is not a dependency to add.** Sunshine's Linux audio is PulseAudio-only
(`src/platform/linux/audio.cpp` includes `pulse/pulseaudio.h` and nothing else); `libpipewire`
is linked for portal *screen capture*. Installing the daemon would only make the wrong capture
path work.

### Quick Sync reports `VAEntrypointEncSliceLP`, not `VAEntrypointEncSlice`

From inside the unprivileged container, as the desktop user:

    VAProfileH264Main               : VAEntrypointEncSliceLP
    VAProfileH264High               : VAEntrypointEncSliceLP
    VAProfileH264ConstrainedBaseline: VAEntrypointEncSliceLP

There is **no plain `VAEntrypointEncSlice` at all**. A health check that greps for it will read
as a failure on working hardware. LP is the only H.264 encode path this chip offers through
iHD, and it works. This also disproves the common claim that LP depends on HuC: HuC is *not*
loaded here and LP is present regardless.

### The container-side render gid is not the host's

Host `render` is gid **993**; inside the container it is **992**. Assuming they match produces
a device mapping that looks right and grants nothing. `pve_lxc` resolves the group *by name
inside the container* and its fixture test covers exactly this case.

### PVE refuses `dev[n]` from any API token

`PVE::LXC::check_ct_modify_config_perm` returns early on a literal `$authuser eq 'root@pam'`
(`/usr/share/perl5/PVE/LXC.pm:1681`) — which a `root@pam!token` also fails. Four option
families are root-only:

| Option | Line | Note |
| --- | --- | --- |
| `dev\d+` | 1709-1710 | unconditional — this is the GPU passthrough |
| `mp\d+` | 1688-1693 | only when type is not `volume`, i.e. **bind** mounts |
| `features` | 1753-1755 | everything except `nesting` |
| `hookscript` | 1759-1760 | outright |

So `pve_lxc` uses the API token for everything the API allows and `pct` over ssh for exactly
the families it forbids. Root-over-ssh is *reduced*, not eliminated.

### `community.proxmox` 2.0.0 cannot converge a container it created

The module defaults `cmode` to the sentinel string `"default"` meaning "omit it", but only
`create_lxc_instance()` honours it (`proxmox.py:1169-1170`). `update_lxc_instance()` (`:969`)
drops `None` values and nothing else, so it posts the sentinel verbatim:

    400 Bad Request: {'cmode': "value 'default' does not have a value in the
    enumeration 'shell, console, tty'"}

**A container builds fine and fails every run afterwards.** 2.0.0 is the latest release, so
`pve_lxc` always sends a real value — `tty`, which is PVE's own documented default
(`pct.conf.5`), so sending it explicitly changes nothing.

This is the clearest argument for running a playbook **twice**: a create-once test cannot find
a converge bug.

### The Mozilla apt pin is load-bearing — *no longer applies to this host*

**Firefox was removed on 2026-09-14, and so was Mozilla's apt source, its signing key and this
pin.** Not because Chromium benchmarked better — that is the weaker argument — but because
**there is no way to launch a second browser here**. This host has no desktop shell, no
launcher, no terminal on the session and no tray; the compositor runs exactly one client, whose
command is `vdesktop_browser_command`. An installed Firefox was not a fallback anyone could
reach. It had never once been started: no `~/.mozilla` existed on the rebuilt container.

Dropping the role call alone would have left the package and a live third-party apt source on a
box whose entire attack surface is its browser — reverting the instruction does not revert the
effect. So the removal was done as one-time playbook tasks (`apt state=absent purge=yes`, plus
deleting `mozilla.sources`, its keyring and `preferences.d/mozilla`), which were **deleted again
once they had run**: a rebuilt container never installs Firefox, so keeping them would mean
removing something that was never there, on every run, forever. Verified after the run: package
not-installed, no `mozilla.sources`, `apt-get update` clean, Chromium untouched.

`roles/firefox/` still exists and still carries the trap below, which is real and cost time:

> Debian trixie ships `firefox-esr` 140.15.0; Mozilla's repo ships 153.2.0. Without the pin
> Debian's wins. The suite is the literal string `mozilla`, **not** the Debian codename —
> templating `distribution_release` there yields a signed, valid, empty source. Proven by a
> container test that applies the role at priority 1000, re-applies at 100, and asserts the
> winning version *changes*.

## Verification

Everything below runs as the desktop account. The session is a **user** unit now, so
`systemctl` without `--user` finds nothing at all.

    systemctl --user is-active sway-headless-wayland.service
    systemctl --user show sway-headless-wayland.service -p NRestarts --value  # climbing = loop

**The compositor is `Type=notify`**, so `active` means its Wayland socket exists and the
environment file is written — not merely that sway was exec'd. That is the point of the notify
protocol here; with `Type=simple` every consumer ordered after it would race both.

The socket name is **not** predictable — sway loops `wayland-1`..`wayland-32` and takes the
first that binds. Read it, never assume it:

    cat "$XDG_RUNTIME_DIR/wayland-session.env"
    swaymsg -t get_version

**Input is the part that was hard, so check it directly.** The devices must exist, be owned by
a group the container maps, and be visible to the compositor:

    ls -ln /dev/input/          # gid 996, NOT 65534 -- 65534 means the udev rule did not fire
    swaymsg -t get_inputs       # Sunshine's keyboard AND mouse, events: enabled

A device at gid 65534 is the signature failure: the compositor can see it and cannot open it,
because the host published it to a group outside the container's id map.

Frames are actually being produced — `grim` is the `zwlr_screencopy_manager_v1` probe that
`capture: wlr` depends on, so a blank PNG here means capture will be blank too:

    grim /tmp/frame.png && file /tmp/frame.png

What resolution is it actually running at? The playbook does not answer this — a connected
client sets the mode and nothing restores it, so ask the compositor:

    swaymsg -t get_outputs | grep -A3 current_mode
    journalctl -t sway-set-mode -n 5 -o cat   # what the last client asked for

Sunshine picked the right paths — read its log, not just its state:

    journalctl --user -t sunshine -o cat | grep -iE "capture|encoder|adapter|uinput|XTest"
    # expect: capture = wlr, encoder = vaapi, adapter_name = /dev/dri/renderD128
    # and the uinput path, NOT an XTest fallback -- there is no X server to fall back to

    # the socket Sunshine got must be the socket sway is answering on
    systemctl --user show app-dev.lizardbyte.app.Sunshine.service -p Environment

Quick Sync, as the desktop user:

    vainfo --display drm --device /dev/dri/renderD128 | grep EncSliceLP

**Read the journal with privileges.** An ordinary user sees only their own journal, and user
journals are capped at 8 MB, so `journalctl --disk-usage` unprivileged reported 8 MB here
against an actual **1.1 GB**. That one bad number sent a debugging session hunting exotic
journald bugs instead of reading the log.

## Configuring Sunshine

**The base configuration is managed by Ansible**, not through the web page. `sunshine.conf`,
`apps.json` and the Web UI login are all rendered by `playbook-vdesktop-01.yaml`; the web page
is needed only for **pairing**.

| What | Where it is set | Value here |
| --- | --- | --- |
| encoder / GPU | `sunshine_config` | `vaapi`, `/dev/dri/renderD128` |
| capture method | `sunshine_config` | `wlr` — pinned, see the trap above |
| display | `sunshine_environment_files` | the compositor's env file; **no `output_name`**, which is an XRandR index and means nothing to `wlr` |
| Web UI exposure | `sunshine_config` | `origin_web_ui_allowed: lan` |
| application list | `sunshine_apps` | one entry, `Desktop` |
| Web UI login | `sunshine_web_username` / `_password` | vault |
| output resolution | `sunshine_global_prep_cmd` | a helper that follows the CLIENT — see "The resolution comes from Moonlight" |

**Why the app list is managed rather than left stock.** Sunshine's default `apps.json` ships a
`Low Res Desktop` entry whose prep-cmd runs `xrandr --output HDMI-1` — an output this host does
not have — and a `Steam Big Picture` entry for a Steam that is not installed. A prep-cmd that
fails takes the stream launch with it. There is exactly one entry, `Desktop`, because the point
of this host is a browser session that is *already running*: the client attaches to that
desktop rather than launching anything.

**Credentials live in the same file as the pairing state.** `credentials_file` defaults to
`file_state` (`src/config.cpp`) — `sunshine_state.json`. Deleting that file to change a
password also **unpairs every client**. The role seeds credentials only when absent; to change
them, re-run with `-e sunshine_web_force_credentials=true`.

### The resolution comes from Moonlight, not from Ansible

**Change the resolution on the client; the host follows. No playbook run.** Sunshine exports the
client's request to its prep commands as `SUNSHINE_CLIENT_WIDTH` / `_HEIGHT` / `_FPS`, and
`sunshine_global_prep_cmd` runs `/usr/local/bin/sway-headless-wayland-set-mode` on every connect,
which turns those into `swaymsg output '*' mode --custom WxH@RHz`.

Consequences worth knowing before something confuses you:

- **`vdesktop_width` / `vdesktop_height` in `host_vars` are the BOOT default only.** There is no
  `undo` command, so the output keeps whatever the last client asked for. Those variables and the
  live output can legitimately disagree, and when they do the variables are the stale ones.
  `swaymsg -t get_outputs` is the only truth about what this host is running at.
- **The helper always exits 0**, including every refusal. Sunshine aborts the stream launch when a
  prep command fails, so an error path that exited non-zero would turn "the resolution did not
  change" into "there is no stream at all". Its only signal is
  `journalctl -t sway-set-mode`, which logs what arrived on every invocation.
- `swaymsg` needs `--` before the command. Without it its own getopt claims `--custom` and exits
  *"unrecognized option"* — the message never reaches sway. It looks right because
  `output * mode --custom WxH` is exactly what the compositor's config file contains; that file
  is read by sway's config parser, which has no getopt in front of it.

Measured trade: 1920x1080 @ 60 gives 59.3 fps (vsync-capped); **2560x1600 @ 90 gives 80-90**;
the panel's native 3024x1890 @ 60 was tried and was far too slow. Resolution spends headroom,
refresh converts it, and this box had enough for both.

The `dd_resolution_option` family in Sunshine's config does **not** do this — those are Windows
only ("Applies to Windows only" in upstream's docs), despite the strings being present in Linux
builds.

### Pairing

The Web UI is at **https://vdesktop-01:47990** — HTTPS with a self-signed certificate
(`CN=Sunshine Gamestream Host`), so expect a browser warning. It binds `0.0.0.0` and
`origin_web_ui_allowed` is `lan`, so it is reachable directly from a machine on the LAN; no
tunnel needed. With no credentials set it answers `307` to `/welcome` and nothing else works,
which is why Ansible seeds the login.

Pairing itself is a PIN exchange: Moonlight generates a PIN, and it is submitted to Sunshine.

**It can be automated, and deliberately is not.** `POST /api/pin` accepts
`{pairing_id, pin, name}` with basic auth, and the client side takes a chosen PIN
(`moonlight --pin 1234 pair <host>`), so both halves are scriptable. It is left manual because
it needs Moonlight on the controller and because the PIN exchange is the security boundary of
the protocol — worth doing on purpose rather than as a side effect of a converge run.

### Two X11-era traps that no longer apply — *superseded*

Both are gone with the desktop, and are noted only so nobody reinstates the fixes:

- **`xdg-utils` for Sunshine's tray.** The tray item runs `xdg-open` and fails silently without
  it. There is no tray and no desktop shell now, so the package is out of the playbook.
- **A polkit rule for colord.** An X session started from a **system** unit gets no seat, so
  polkit fell through to `auth_admin` and put an unanswerable *"Password for root:"* dialog on
  the desktop. Nothing here runs colord, and the session is a user unit with a real login
  session, so the rule went with XFCE.

## Access

Ssh with the fleet key as the login user; the desktop account is separate and has no sudo,
deliberately, so the browser does not run as an account that can become root.

**wayvnc** listens on a **UNIX socket with no TCP port at all**, which ssh forwards natively:

    ssh -L 5900:/run/user/$(ssh vdesktop-01 id -u andy)/wayvnc.sock vdesktop-01
    open vnc://localhost:5900        # macOS Screen Sharing

This is tighter than the x11vnc it replaces, and not by choice: wayvnc 0.9.1 has **no
password-only mode**. `enable_auth=true` requires `certificate_file` **and**
`private_key_file` **and** `username` **and** `password` (`wayvnc.scd`, CONFIG FILE KEYWORDS),
and wayvnc ships no equivalent of `x11vnc -storepasswd` — so authentication would have meant
generating a TLS certificate *and* storing a password in plaintext in
`~/.config/wayvnc/config`, to defend a port that was already unreachable. A socket with no port
removes the question. The ssh key is the only gate, which is what was already true before.

Consequence, stated rather than hedged: anyone with a shell on this container who can reach
that socket path can watch the session. Same class of exposure as the old loopback port,
narrowed by file mode instead of by a password.

    ss -ltn    # nothing on 5900; if there is, something is not using the socket

**Moonlight** is the primary client and is paired and in use. Recovery if everything else
fails is `pct enter 120` from the node as root — no password, which is one of the quiet
advantages a container has over the VM this replaced.

## Known non-convergent tasks

**None on this host.** An earlier version of this document listed two — `textfile_collector`
fighting `prometheus.prometheus.node_exporter` over `/var/lib/node_exporter`, and
`oefenweb.locales : set default locale`. Both come from `configure_server`, which this playbook
deliberately does not run (see "How it is built"), so neither applies here.

They are still real on the six other playbooks that do include `textfile_collector`; the record
of that belongs with those hosts, not with this one.

## The performance problem — SOLVED 2026-09-14

This host was built to run one browser game. It streams it correctly and cheaply — Moonlight on
the Mac costs ~2% CPU against Firefox's ~8%, which was the point — and after the Wayland rebuild
**the game is playable**. Operator verdict, after playing it: *"much better. definitely
playable."*

| | fps | the game's own rAF callback |
| --- | --- | --- |
| Chromium, software (X11 build) | 17.4 | — |
| Chromium, GPU session but browser still on CPU | 19.2 | — |
| Firefox on the GPU | 43.0 | 10.64 ms |
| **Chromium, native Wayland, GPU** | **59.3** at 1080p60 | **4.52 ms** |
| **the same, at 2560x1600 @ 90 Hz** | **80-90** | |

**59.3 fps is 98.9% of a 60 Hz output**, which is the real finding: at 1080p60 the host stopped
being compute-limited and became *display*-limited. Raising the client to 90 Hz while
simultaneously doubling the pixels still produced ~50% more frames. **Do not quote 59.3 as this
host's capability — it is a vsync ceiling.**

The section below was written before any of that was measured. It is kept, with corrections,
because one of its predictions was badly wrong in an instructive way.

**What the old X11 build did, for contrast.** A root-owned scan of `/proc/*/fd` showed only
`sunshine` holding `/dev/dri/renderD128`. Firefox never opened it, because `xf86-video-dummy`
exposes no DRM device and no DRI3, so Mesa had nothing to accelerate against and the browser fell
back to software rasterisation. Measured during play, on 4 cores at load 7.89: roughly 112% of a
core across `Renderer`, `SwComposite`, `WRRenderBackend` and `WRSceneBuilder`, against 44% on the
content main thread. None of that is true of this host any more.

### What the game actually does — and why "the GPU is not the fix" was wrong

The game is served from `birbplay.com` (the itch.io page is a stub). Greps of its shipped
bundles:

| marker | count |
| --- | --- |
| `getContext("2d")` | **49** |
| `webgl` / `webgl2` / `webgpu` | **0** |
| `OffscreenCanvas` / worker rendering | **0** |
| `createElement("canvas")` | 45 |
| `save()` / `restore()` | 271 / 178 |
| `filter:` | ~33 |
| `shadowBlur` | ~9 |
| `getImageData` / `putImageData` | 5 / 5 |

**It is a Canvas 2D game drawing on the content main thread.** That matters more than anything
else in this document: giving the container a GPU-backed compositor would move *compositing*
off the CPU — the ~112% in `Renderer`/`SwComposite` — while leaving the game's own drawing
exactly where it is. `shadowBlur` and `filter` are CPU-rasterised even where canvas
acceleration exists, and with no worker or OffscreenCanvas every draw call shares one thread
with the game's JavaScript. That thread was measured pegged at ~101% of a single core.

**CORRECTED 2026-09-14, by measuring it. The claim that the GPU would leave the game's own
drawing "exactly where it is" is the one thing in this document that was flatly wrong.** The
game's `requestAnimationFrame` callback — which is precisely "the game's own drawing", and which
was 71.5% of Firefox's per-frame work at 10.64 ms — came out at **4.52 ms** in Chromium on the
GPU. Less than half.

The reasoning failed because it treated "Canvas 2D on the main thread" as meaning the drawing
must be CPU work. It is not: Chromium GPU-rasterises canvas, so the draw calls issued on that
thread are handed to the GPU process rather than executed on it. The trace shows **18,801
`RasterDecoderImpl::DoRasterCHROMIUM`** calls on `CrGpuMain` where the software runs showed
`SoftwareRenderer::DoDrawQuad`. The one prediction that held is that the game is
single-thread-*shaped*: `CrRendererMain` is still the busiest thread at ~70%.

~~So the expensive route below — a privileged container, or a udev rule on the hypervisor, to
reach Wayland — **is not recommended**.~~

**Withdrawn, 2026-09-14.** Two of the three premises turned out to be false, and the third was
never checked:

- **It does not need a privileged container.** `UI_DEV_CREATE` succeeds in an *unprivileged*
  one — measured as the ordinary desktop account holding nothing but `input` group membership,
  with no `CAP_SYS_ADMIN`. `uinput.c` contains no capability check at all; access is governed
  purely by file permissions. Every published guide takes a precaution that is unnecessary here.
- **The udev rule on the hypervisor is a no-op on current hardware by construction.** It matches
  vendor `1209`, which no device on that node carries. Its cost was overestimated.
- **The payoff was never only compositing.** That is the part below that still stands, and it is
  why this is honest rather than a reversal: moving rendering to the GPU does not fix a Canvas 2D
  game drawing on one thread. What the rebuild buys is the *removal of a hard ceiling* — the
  browser can now reach the GPU at all — not a guarantee that the game is playable.

Whether it is playable was the open question, and the build answered it: **yes.** See the table
at the top of this section.

**A different browser engine is not the answer either, measured rather than assumed.** On an
identical fixed Canvas 2D workload -- a `scripts/canvas-bench.sh` that was **deleted on
2026-09-14**, for the reason given immediately below -- on the same session:

| engine | per frame | fps equivalent |
| --- | --- | --- |
| Firefox 155 | 41.8 ms | **23.9** |
| Chromium 152 | 546.8 ms | **1.8** |

**That result was retracted.** It disagrees with the real game, and the benchmark is what was
wrong: it runs its frames in a tight synchronous loop with no `requestAnimationFrame`, which
measures single-threaded canvas throughput and defeats the multi-threaded compositing pipeline
Chromium depends on. Measured on the actual game instead:

| | total CPU | shape |
| --- | --- | --- |
| Firefox | 111% | `Isolated Web Co` **101%** — one thread saturated, three cores idle |
| Chromium | 150% | `chromium` 72% + `VizCompositorTh` 55% — spread, neither pegged |

Chromium uses more CPU in total but is **not single-thread-bound**, which on a 4-core box is the
distinction that matters: Firefox's saturated main thread is a hard frame-rate ceiling.
Chromium's own command line shows `--disable-gpu-compositing --num-raster-threads=2` — it found
no usable GPU and fell back, and still parallelises better here.

**Settled 2026-09-14: Chromium, and CPU shape was the wrong reason.** Chromium is faster here
because its JS and canvas work on this game is faster — the game's rAF callback is **4.52 ms**
against Firefox's **10.64 ms** — not because of how the load spreads across threads. "Firefox has
no GPU" was never the difference either: Firefox reaches the GPU perfectly well, by a different
X11 path (`dri3_open()` then `gbm_create_device()`) that works with a render node where
Chromium's GPU process does not.

**Read that comparison with its caveat.** The two figures come from different session
architectures — Firefox measured on the Xwayland session *with* the GPU, Chromium measured after
the rebuild as a native Wayland client. Firefox has never been profiled on native Wayland, so
what is established is "Chromium on the configuration it needs beats Firefox on the configuration
it had", not a controlled single-platform A/B. The gap is large enough (2.26x on the dominant
term) that the ranking is not in doubt; the exact margin is.

Separately, and not the reason Chromium wins: **Chromium could not use the GPU through Xwayland
at all** — 0 render-node fds and 3 GPU-process crashes, against 9 fds and 0 crashes as a native
Wayland client on the same compositor. That is a constraint on the HOST, not a property of the
browser race, and it is the single fact that forced this box to have no X server.

45 offscreen canvases and 271 `save()` calls also suggest a meaningful share of the cost is
structural to the game, which nothing on this host can change.

### Why hardware rendering was hard here — and how it was solved

The original problem, stated correctly: hardware rendering needs a compositor that can reach the
GPU, which on this hardware means Wayland — and **Wayland has no XTest**. The X11 build's
keyboard and mouse worked *only* because Sunshine fell back to XTest. A naive Wayland session
would render fast and accept no input at all.

That is a real constraint and it is why this took three days rather than an afternoon. What was
wrong was the conclusion that it could not be paid for. Every step is now measured:

| claim | result |
| --- | --- |
| `UI_DEV_CREATE` in an unprivileged container | **works**, as an ordinary user with `input` group membership only. No `CAP_SYS_ADMIN`, no privileged container, no `vuinputd`. |
| the device the container creates | published by the **host** as uid/gid `65534` mode **0600** — outside the container's id map, and unopenable until the udev rule puts it in `lxc-input` (gid 100996 → 996 inside) with `MODE="0660"` |
| a wlroots compositor seeing it | libinput reaches devices **only** through udev, and a container gets no kernel uevents — so the events are synthesised |
| synthesising a udev event | **works**: the container's own root may send to the udev multicast group, because the kernel tests `CAP_NET_ADMIN` against the user namespace owning the *network* namespace, not `init_user_ns` |
| a real libudev subscriber receiving it | **15 of 15** devices announced and received, with real sysfs `DEVPATH`s |

**The trap that is easiest to lose.** `/run/udev/control` must exist *before* any libudev
subscriber starts. One created while that file is absent binds to **no multicast group at all**
and is deaf for its whole life — it does not error, and creating the file afterwards does not
repair it. That is why `udev_shim` has a prime unit ordered ahead of the user manager, and it is
the failure that cost two debugging rounds during development with a perfectly formed message
and a successful `sendmsg` both times.

The privileged-container route was also never necessary on its own terms: `PVE::API2::LXC`
requires `Sys.Modify` on `/` for privileged containers, which the automation token does not
have, so it was never reachable from a playbook anyway.

### Why moving it elsewhere does not work

There is **no always-on host in this fleet with a spare GPU**:

| host | GPU | why not |
| --- | --- | --- |
| htpc-01 | RX 9070 XT | not always on |
| media-01 | RTX A4000 | Tdarr node, Immich ML, Whisper |
| media-01 | Arc B580 | QSV for jellyfin/plex/tdarr |
| vm-host-01 | UHD 630 | a VM reaches it only by exclusive passthrough of the host's own primary VGA — which is why this is a container |

The investigation, the gates and what has been ruled out are in
`plans/vdesktop-01-hardware-rendering.md`; the running record is
`tasks/vdesktop-01-performance.md`. Two committed tools support it:
`scripts/vdesktop-01/browser-profile.sh` (headless profile capture, validated against the
installed build -- it began as an `ff-profile.sh` that only knew Firefox, and grew a Chromium
branch because the two engines share no mechanism) and
`scripts/vdesktop-01/browser-cpu.sh` (engine-agnostic per-thread CPU sampling, which refuses to
run unprivileged because an unprivileged caller silently measures nothing).
