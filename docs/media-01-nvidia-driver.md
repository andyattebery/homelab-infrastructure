# media-01 rebuild — NVIDIA driver install method

> **Status as of 2026-08-09 — the rebuild below never happened, and the driver is not managed
> by Ansible.**
>
> media-01 still runs **Ubuntu 24.04.4** on the GA kernel, not 26.04. The driver is
> **595.71.05**, open kernel modules, `-server` flavour, built by **DKMS**, installed from
> Canonical's archive (`noble-updates`/`noble-security`) — which is the source this document
> recommends, arrived at by hand rather than by playbook:
>
> - 2025-11-20 — `nvidia.nvidia_driver` installed `cuda-drivers-580` from the **CUDA repo**.
> - 2026-03-26 — that entire stack was purged by hand and replaced with
>   `apt install nvidia-driver-590-server-open`.
> - 2026-05-01 — Ubuntu's 590 metapackage now `Depends: nvidia-driver-595-server-open`, so a
>   routine `dist-upgrade` carried the host to the 595 branch.
>
> Because Ansible had never successfully owned the driver, the `nvidia.nvidia_driver` role was
> **removed** from `playbook-media-01.yaml` rather than rewritten as proposed below, and both
> `nvidia.nvidia_driver` and `nvidia.nvidia_docker` were dropped from `requirements.yaml`. The
> driver is now maintained by `apt` on the host. The "Other repo cleanup" items were done:
> the toolkit apt sources are deduped and its Docker restart is now a checksum-gated reload.
>
> The rest of this document is retained for its reasoning — the Canonical-vs-NVIDIA comparison
> and the package-set notes are still accurate and are why the host is where it is. Treat the
> Implementation section as **not applied**, and read it as *adoption in place* rather than as part
> of a rebuild: the 26.04 upgrade is now planned as an in-place `do-release-upgrade`
> (`media-01-upgrade-to-26.04.md`), which removes the rebuild that was this role's original excuse
> for existing.

> **Two claims in the status block above were wrong, corrected 2026-08-22 by reading the host.**
> Both were recorded from intent rather than from the machine, which is the failure mode worth
> noticing here:
>
> - *"the toolkit apt sources are deduped"* — **they are not.**
>   `/etc/apt/sources.list.d/nvidia-container-toolkit.list` still carries both
>   `stable/deb/$(ARCH)` and the legacy `stable/ubuntu18.04/$(ARCH)`, plus two commented
>   experimental lines. That is NVIDIA's stock published file verbatim, so it was written by hand
>   from NVIDIA's install docs and the role has never successfully written it — the role emits a
>   single line via `copy: content:`.
> - **the March 2026 CUDA purge removed the packages, not the source.**
>   `/etc/apt/sources.list.d/cuda-ubuntu2404-x86_64.list` is still present and live, at apt
>   **priority 600** — above the archive's 500. Canonical still wins the driver only because that
>   repo does not carry `nvidia-driver-595-server-open`. It is pinned to `ubuntu2404` and must be
>   removed before the 26.04 upgrade.
>
>   **UPDATE 2026-08-26 — "removed the packages" was itself too generous.** Checked per-package
>   with `apt-cache policy` on 2026-08-26, **eight installed packages still resolve to that repo**:
>   `cuda-keyring`, `dkms`, `libnvidia-egl-wayland1`, `libxnvctrl0`, `nvidia-settings`, and all
>   four of `nvidia-container-toolkit`, `nvidia-container-toolkit-base`, `libnvidia-container1`,
>   `libnvidia-container-tools`.
>
>   The last four are the point: the 600 pin outranks `nvidia.github.io/libnvidia-container` at
>   500, so the CUDA repo has been serving the very packages `nvidia_container_toolkit` configures
>   a source for. That role has not owned them. `dkms` — which builds the kernel module — comes
>   from there too.
>
>   "Nothing is orphaned" needs qualifying, and **`do-release-upgrade` does not fix it** — checked
>   against resolute, the installed version is *higher* than 26.04's for three of them:
>
>   | package | installed | noble | resolute (26.04) |
>   | --- | --- | --- | --- |
>   | `nvidia-container-toolkit` ×4 | 1.20.0-1 | — | identical at `nvidia.github.io` |
>   | `dkms` | 1:3.4.1-1ubuntu1 | 3.0.11-1ubuntu13 | 3.2.2-1ubuntu1 |
>   | `libnvidia-egl-wayland1` | 1:1.1.21-1ubuntu1 | 1:1.1.13-1ubuntu0.1 | 1:1.1.21-1 |
>   | `libxnvctrl0`, `nvidia-settings` | 610.57.04-1ubuntu1 | 510.47.03-0ubuntu4.24.04.1 | 510.47.03-0ubuntu7 |
>
>   The four toolkit packages are genuinely neutral — `nvidia.github.io` publishes the identical
>   `1.20.0-1`, and every version back to `1.16.1-1`. The rest stay installed above any configured
>   source, and apt will not downgrade them on its own.
>
>   **`dkms` is the one that cannot resolve itself: NVIDIA's carries epoch `1:` and Ubuntu's does
>   not**, so `1:3.4.1` outranks any Ubuntu version at any release, forever. It needs one explicit
>   `--allow-downgrades` — scheduled as a numbered step of the 26.04 upgrade, forcing resolute's
>   3.2.2 rather than noble's 3.0.11, because 3.4.1 → 3.0.11 crosses dkms 3.0.13's module-compression
>   rework and 3.1.7's archived-module relocation, while 3.4.1 → 3.2.2 crosses neither.
>
>   The repo removal is now a `pre_task` in `playbook-media-01.yaml`, asserted every run rather than
>   done once.
>
>   The earlier claim rested on `apt list --installed | grep -c 'developer.download.nvidia'`
>   returning 0 — but that command never prints repository URLs, so it could only ever return 0.
>   Recorded because the shape of the mistake matters more than the fact: a check that cannot fail.
>
> More generally: the roles in this repo have not been applied to media-01 in their current state
> (`geerlingguy.docker` 8.0.0 would have removed `docker.list`, and it is still there), so the
> host's apt configuration is an older generation of the repo than the repo now contains.

> **The package set recommended below was wrong, corrected 2026-08-24. The role is now adopted.**
>
> This document recommended `nvidia-headless-{branch}-server-open` on the reasoning that a headless
> VM does not need Xorg. The reasoning is sound; the conclusion was not. Read from
> `archive.ubuntu.com/ubuntu/dists/noble-updates/multiverse/binary-amd64/Packages.gz`:
>
>     nvidia-headless-no-dkms-595-server-open Depends:
>         nvidia-kernel-common-595-server, nvidia-kernel-source-595-server-open,
>         libnvidia-compute-595-server, nvidia-compute-utils-595-server, libnvidia-cfg1-595-server
>
> No `libnvidia-encode`, no `libnvidia-decode`. The two metapackages are **parallel**, not nested —
> `nvidia-driver-*` is not "headless plus Xorg", it depends on the same leaves *and* on
> `libnvidia-encode`, `libnvidia-decode`, `libnvidia-gl`, `libnvidia-extra`, `libnvidia-fbc1` and
> `xserver-xorg-video-nvidia`.
>
> Those codec libraries are what the container toolkit injects for
> `NVIDIA_DRIVER_CAPABILITIES=all`, which is what Plex
> (`ansible/files/media-01/docker-compose-media.yml:75`) and the Tdarr server
> (`roles/docker_compose_tdarr/templates/docker-compose-tdarr-server.yaml.j2:33`) both request —
> and every Tdarr flow is `hevc_nvenc` / `av1_nvenc` / `tonemap_cuda`. Headless would have left CUDA
> working and silently removed the encoder from every container: Immich fine, Plex and Tdarr broken.
>
> The role therefore owns `nvidia-driver-{branch}-server-open` — the set the host was already
> running — so adopting it changed no packages and needed no reboot. `ansible/roles/nvidia_driver/`
> is rewritten and wired into `playbook-media-01.yaml` as of 2026-08-24; its README carries the
> package-set comparison in full.

## Context

media-01 was, when this was written, expected to be rebuilt on Ubuntu 26.04 and reprovisioned from scratch. **That rebuild never happened and is no longer the plan** — see `media-01-upgrade-to-26.04.md`, which recommends an in-place upgrade and adopting this role on 24.04 beforehand. The reasoning below is unaffected by that change; only the "fresh install" framing is.

It's a Proxmox VM with an A4000 (Ampere) passed through. Workloads are Immich-ML, Obico-ML, Plex transcoding — all in containers. No bare-metal CUDA work.

Decision: how to install the NVIDIA driver on the fresh host, and bake that into Ansible going forward.

Inputs locked in:

- CUDA toolkit: **containers only** — host gets driver + `nvidia-container-toolkit` only.
- Kernel modules: **open** (`-open` packages). A4000 is Ampere; NVIDIA's stated default for Turing+ is the open kernel modules, and future branches will be open-only on these GPUs.
- Upgrade cadence: **deliberate, pinned**. Driver branch is a variable in the playbook; upgrades happen when the user changes the variable and re-runs the play. No rolling auto-upgrades.

Existing repo state:

- Galaxy role `nvidia.nvidia_driver` (pinned in [../ansible/requirements.yaml](../ansible/requirements.yaml)).
- Local role [../ansible/roles/nvidia_driver/](../ansible/roles/nvidia_driver/) — trivial wrapper around `ubuntu-drivers install --gpgpu`, unreferenced by any playbook.
- Local role [../ansible/roles/nvidia_container_toolkit/](../ansible/roles/nvidia_container_toolkit/) — adds NVIDIA's `libnvidia-container` apt repo, installs `nvidia-container-toolkit`, runs `nvidia-ctk runtime configure --runtime=docker`. Keep this; it's the only viable source for the container toolkit. **Note:** `nvidia.github.io/libnvidia-container` (used here) is a *different* apt repo from `developer.download.nvidia.com/compute/cuda/...` (the CUDA repo). Using the toolkit doesn't pull us into the CUDA repo for the driver.

---

## What the authoritative sources recommend

Both vendors recommend their own source. Honest disagreement:

- **Canonical** ([Ubuntu Server docs — install nvidia drivers](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/)): recommends `ubuntu-drivers install --gpgpu` against their archive. Calls their `-server`-suffixed packages "Enterprise Ready Drivers (ERD)". Warning: *"NVIDIA drivers installed from sources outside of those listed in this guide could potentially overwrite those provided by ubuntu-drivers and may break Secure Boot."* `ubuntu-drivers` ships only pre-built signed kernel modules.
- **NVIDIA** ([Driver Installation Guide for Ubuntu](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/ubuntu.html)): recommends their CUDA apt repo, with `apt install libnvidia-compute nvidia-dkms-open` for compute-only systems. Doesn't acknowledge Canonical's path.
- **Both agree on one rule**: don't mix sources. Common failure is "default repo + PPA + CUDA repo all enabled → kernel module from one source, userland utilities from another → CUDA breaks."

When each wins:

| Canonical archive (`nvidia-driver-XXX-server-open`) | NVIDIA CUDA repo (`nvidia-driver-XXX-open`) |
|---|---|
| Signed for Secure Boot | Latest patch releases ship faster |
| SRU-tested security backports via `-updates` pocket | Has more branches available (NVIDIA's full set) |
| Canonical's official recommended path | NVIDIA's official recommended path |
| Single-vendor lifecycle (Ubuntu controls kernel + driver together) | Useful if Canonical hasn't packaged the branch you want |
| No third-party apt repo for the driver | — |

---

## Recommendation: Canonical archive, branch-pinned in the playbook

**Install `nvidia-driver-{branch}-server-open` from Canonical's archive via direct `apt` in a rewritten local role.** Branch number is a variable passed from the playbook, not the role default.

> **UPDATE 2026-08-24** — this said `nvidia-headless-…` until the package-set correction at the top
> of this file. Everything else in this section stands: the archive-over-CUDA-repo choice and the
> direct-`apt`-over-`ubuntu-drivers` choice are unaffected by which metapackage is named.

Why Canonical archive over NVIDIA's CUDA repo, given pinning:

- The only reason to pick NVIDIA's CUDA repo over Canonical was "latest Recommended/Certified is only there." If we're pinning, "latest" doesn't apply — and Canonical's archive does have current production branches (resolute ships 535, 570, 580, 590, 595 in `-server-open` at release; newer branches arrive via `-updates` over time).
- Pre-signed for Secure Boot — no MOK enrollment dance if/when you flip SB on later.
- One fewer apt source to maintain. We still need `nvidia.github.io/libnvidia-container` for `nvidia-container-toolkit` (separate repo), but the driver itself comes from `archive.ubuntu.com`.
- Matches Canonical's official path verbatim — if anything goes wrong with the driver on Ubuntu, the failure mode lines up with documented troubleshooting.

Why direct `apt` instead of wrapping `ubuntu-drivers install --gpgpu`:

- `ubuntu-drivers` is a non-idempotent `command:` task unless you wrap it carefully; Ansible's `apt` module is idempotent and explicit about the exact package set.
- `ubuntu-drivers` reads from *whatever* apt sources are configured. If a stray CUDA repo gets added later, `ubuntu-drivers` will silently start preferring NVIDIA's packages. Direct `apt install nvidia-driver-595-server-open` is unambiguous.
- The package name is descriptive: `nvidia-driver-{branch}-server-open` says everything (branch, ERD/server, open kernel modules).

### Branch choice

**Pin to `nvidia-driver-595-server-open`.** On media-01 today that resolves to
`595.71.05-0ubuntu0.24.04.1` from `noble-updates/multiverse` — the version already installed, which
is why adoption is a no-op.

Verified by direct probe of `archive.ubuntu.com/ubuntu/dists/resolute/restricted/`:

- Resolute (26.04) release archive ships these `-server-open` branches: **535, 570, 580, 590, 595**. Noble (24.04) `-updates` currently carries **550, 575, 595**.
- 595 is the highest, and it matches NVIDIA's current Recommended/Certified branch for the A4000 (NVIDIA ships 595.71.05; Canonical ships 595.58.03-0ubuntu2 — same branch, one patch release behind; expect Canonical to catch up via `-updates`).

Re-verify before any bump, in case Canonical has added a newer branch via `-updates`:

```
apt-cache search '^nvidia-driver-[0-9]\+-server-open$' | sort -V
```

Pick the highest number from that output.

---

## Implementation

**Done 2026-08-24.** What follows describes the role as written, not as proposed; the authority is
`ansible/roles/nvidia_driver/` and its README.

`defaults/main.yaml` carries two variables: `nvidia_driver_branch` (default `"595"`) and
`nvidia_driver_reboot_on_change` (default `true`).

`tasks/main.yaml`:

```yaml
- name: Install NVIDIA driver (ERD, open kernel modules)
  ansible.builtin.apt:
    name: "nvidia-driver-{{ nvidia_driver_branch }}-server-open"
    state: present
  register: nvidia_driver_apt_result

- name: Enable nvidia-persistenced
  ansible.builtin.systemd_service:
    name: nvidia-persistenced
    enabled: true

- name: Reboot into the new driver
  when:
    - nvidia_driver_apt_result.changed
    - nvidia_driver_reboot_on_change | bool
  ansible.builtin.reboot:
```

Notes on the package set:

- `nvidia-driver-{branch}-server-open` is Canonical's ERD meta for the open kernel modules. It pulls
  `nvidia-dkms-{branch}-server-open` (modules via DKMS, pre-signed), `libnvidia-compute`,
  `nvidia-kernel-common`, **and** `libnvidia-encode` / `libnvidia-decode` — the last two being the
  reason it is used instead of `nvidia-headless-…`. See the correction at the top of this file.
- `nvidia-utils-{branch}-server` provides `nvidia-smi` and is pulled transitively; it is not named
  separately.
- The nouveau blacklist ships in `nvidia-kernel-common-{branch}-server`. No explicit task needed.
- `nvidia-persistenced` comes from `nvidia-compute-utils-{branch}-server`; the role only enables the
  unit.

**The reboot is an inline conditional task, not a handler.** Handlers notified from a play's
`roles:` section flush at the end of the play's `tasks:` section — after every other role. This role
runs before the `docker_compose_*` roles, so a handler would deploy every GPU container against a
mismatched module and reboot afterwards. `roles/nvidia_container_toolkit` avoids the same trap for
the same reason.

### Playbook delta

In `ansible/playbook-media-01.yaml`, between `geerlingguy.docker` and `nvidia_container_toolkit`:

```yaml
- role: nvidia_driver
  tags: nvidia
  vars:
    nvidia_driver_branch: "595"
```

Order is `geerlingguy.docker` → `nvidia_driver` → `nvidia_container_toolkit` → the compose roles.

### Other repo cleanup tied to this change

All three are **done**:

- `nvidia.nvidia_driver` and `nvidia.nvidia_docker` dropped from `ansible/requirements.yaml`;
  `grep -rn 'nvidia\.nvidia' ansible/` returns nothing.
- The toolkit apt sources were deduped by the 2026-08-23 deb822 migration — one source, architecture
  resolved by Ansible, legacy `stable/ubuntu18.04` suite gone.
- The toolkit's Docker restart is now a checksum-gated `reload`, not an unconditional `restart`.

### Files modified

- `ansible/roles/nvidia_driver/defaults/main.yaml` (rewritten)
- `ansible/roles/nvidia_driver/tasks/main.yaml` (rewritten)
- `ansible/roles/nvidia_driver/README.md` (new)
- `ansible/playbook-media-01.yaml` (role added, `tags: nvidia`)

No `handlers/main.yaml` — see above.

---

## Verification

The adoption run is expected to change **nothing** — the role names the package set the host is
already on. That is the check.

```
cd /Users/andy/Projects/homelab-infrastructure/ansible
.venv/bin/ansible-playbook playbook-media-01.yaml --limit media-01 --tags nvidia
```

0. **Pass = `changed=0` on the apt task.** A non-zero `changed` means the host is not on
   `nvidia-driver-595-server-open` and the premise is wrong — stop rather than let the reboot task
   fire on a host running Plex, Immich and the Tdarr server.
1. `apt-cache policy nvidia-driver-${branch}-server-open` → installed, candidate from
   `archive.ubuntu.com` (`noble-updates/multiverse`), **not** from
   `developer.download.nvidia.com`. `dpkg -l 'nvidia-*'` shows one consistent versioned set.
2. `nvidia-smi` → reports `${branch}.xx.yy` and lists the A4000.
3. `lsmod | grep nvidia` → `nvidia`, `nvidia_uvm`; `lsmod | grep nouveau` is empty.
4. `modinfo nvidia | grep -i license` → open-source licensed modules (MIT/GPL dual).
5. `systemctl is-enabled nvidia-persistenced` → enabled.
6. `docker info | grep -i runtimes` → `nvidia` listed.
7. `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi` → succeeds, sees the
   A4000. **This is the one that matters most**: it is the only step that exercises the container
   toolkit's library injection, which is what the headless package set would have broken.
8. A Tdarr transcode using an `hevc_nvenc` or `av1_nvenc` flow completes. Steps 1–7 all pass on a
   compute-only driver; this is the step that would have caught the wrong package set.

### Bumping the driver later

1. `apt-cache search '^nvidia-driver-[0-9]\+-server-open$' | sort -V` on the host, for branches
   Canonical has added to `-updates` since.
2. Edit `nvidia_driver_branch` in [../ansible/playbook-media-01.yaml](../ansible/playbook-media-01.yaml).
3. Re-run `--tags nvidia`. apt swaps the versioned set and the role reboots the host, because the
   new DKMS module cannot load against the running kernel until it does. Set
   `nvidia_driver_reboot_on_change: false` only if that reboot is being scheduled by hand — until it
   happens, `nvidia-smi` returns `Driver/library version mismatch` and every GPU container fails.
4. Re-run the verification block above, step 8 included.
