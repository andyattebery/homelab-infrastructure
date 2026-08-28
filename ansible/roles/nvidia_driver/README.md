# nvidia_driver

Installs the NVIDIA driver from Canonical's archive — ERD (`-server`) flavour, open kernel
modules — pinned to a branch chosen by the caller, and enables `nvidia-persistenced`.

Does **not** install the container runtime; that is `nvidia_container_toolkit`, which must run
after this role.

## Status: Production

## Inputs

- `nvidia_driver_branch` — default `"595"`. The branch number only, as a string. Becomes
  `nvidia-driver-<branch>-server-open`. A branch Canonical has not published for the host's
  release fails the play at the apt task with `No package matching`. List what the host can
  actually see with `apt-cache search '^nvidia-driver-[0-9]\+-server-open$' | sort -V` and pick
  from that; the archive gains branches over time through the `-updates` pocket, so the answer
  differs per host and per month.
- `nvidia_driver_reboot_on_change` — default `true`. Reboots the host when, and only when, the
  apt task reports changed. Setting it `false` does not avoid the reboot, it defers it: the host
  runs a freshly-built DKMS module against a still-loaded old one, `nvidia-smi` returns
  `Driver/library version mismatch`, and every GPU container fails until someone reboots by
  hand. Set it `false` only when that reboot is being scheduled deliberately.
- `nvidia_driver_superseded_packages` — default `[]`. Old driver metapackages to remove once the
  wanted one is installed. Named packages that are already absent are a no-op. Removal is
  `purge`, with `autoremove: false` — this role never runs an autoremove, because the failure
  mode it guards against is precisely an autoremove taking too much. See "Removing an old branch
  is an ordering problem" below; that ordering is the reason this is a role input and not a task
  in the playbook.

  Non-empty values are **guarded**: the role runs `apt-mark showmanual` for the wanted driver
  first and fails the play if it is not manually installed, rather than proceeding into a
  removal whose safety depends on that. The check is on stdout — `apt-mark showmanual <pkg>`
  exits 0 whether or not the package is manual, and only the presence of the name distinguishes
  the two.

## Example

From `playbook-media-01.yaml`:

```yaml
- role: nvidia_driver
  tags: nvidia
  vars:
    nvidia_driver_branch: "595"
    nvidia_driver_superseded_packages:
      - nvidia-driver-590-server-open
```

Ordering is load-bearing: `geerlingguy.docker` → `nvidia_driver` → `nvidia_container_toolkit` →
the `docker_compose_*` roles. The toolkit's `nvidia-ctk runtime configure` assumes a driver is
already present, and the compose roles assume the runtime is registered.

## It marks the package manual, even when it reports no change

`ansible.builtin.apt` calls `apt-mark manual` on every name it was given, on every run, from
outside the branch that actually invokes apt — `modules/apt.py`, `mark_installed(..., manual=True)`.
So a run that reports `changed=false` still flips the package from auto to manually installed, and
Ansible will not tell you it did.

That is wanted here, and it is the difference between the role naming the driver and the role
owning it. A host can reach the current branch by dependency rather than by choice — a transitional
`nvidia-driver-<old>-server-open` metapackage whose only `Depends:` is the current one, with the old
name manual and the current one auto. Nothing is wrong while that holds, and `apt-get autoremove`
finds nothing to do. Drop the transitional package, though — a `dist-upgrade` retiring it is enough
— and the current driver becomes an orphan the next `autoremove` is entitled to take, along with
the whole stack under it.

Running this role converts that arrangement into an explicit one without changing a single package.

## Removing an old branch is an ordering problem

`nvidia_driver_superseded_packages` exists because the removal is only safe in one order, and
nothing in a playbook can express that ordering against a role.

The install task above is what promotes the wanted driver to manually installed. Until it has run,
the *old* metapackage may be the only manual reference holding the stack up. Remove it first and
the current driver is an orphan; the next `apt autoremove` — from a cron job, a `topgrade` run, or
someone tidying by hand — takes the driver, the DKMS module and every `libnvidia-*` under it. The
host keeps running until it reboots into a kernel with no NVIDIA module.

Putting the removal in the calling playbook cannot fix this. `pre_tasks` runs before the role, which
is the wrong order outright; `post_tasks` runs after every other role in the play, so the compose
workloads come up in between. Inside the role, immediately after the install, is the only place the
ordering is guaranteed.

The task therefore sets `autoremove: false` explicitly, and this role never runs an autoremove
anywhere. Removing a transitional metapackage takes no files and unloads no module — its entire
content is its `Depends:` — so it also does not trigger the reboot.

## Why `-driver-` and not `-headless-`

This is the trap in this role, and it is not obvious from the package names.

`nvidia-driver-<branch>-server-open` and `nvidia-headless-<branch>-server-open` are **parallel**
metapackages. The driver one is not built on top of the headless one, so "headless is the same
thing minus Xorg" is wrong. From `noble-updates/multiverse`:

    nvidia-headless-no-dkms-595-server-open Depends:
        nvidia-kernel-common-595-server, nvidia-kernel-source-595-server-open,
        libnvidia-compute-595-server, nvidia-compute-utils-595-server,
        libnvidia-cfg1-595-server

    nvidia-driver-595-server-open Depends:
        ... the same set, plus libnvidia-encode-595-server, libnvidia-decode-595-server,
        libnvidia-gl-595-server, libnvidia-extra-595-server, libnvidia-fbc1-595-server,
        xserver-xorg-video-nvidia-595-server

The headless set is **compute-only**: no `libnvidia-encode`, no `libnvidia-decode`. On a host
whose containers request `NVIDIA_DRIVER_CAPABILITIES=all`, those are the libraries the container
toolkit injects for NVENC and NVDEC. Choosing headless on a host that transcodes removes the
encoder from every container on it while leaving CUDA working — so Immich keeps running and
Plex and Tdarr do not, which is a slow thing to diagnose.

`docs/media-01-nvidia-driver.md` recommended the headless set until 2026-08-24 for exactly the
"headless VM does not need Xorg" reason. That reasoning is sound and the conclusion was still
wrong; the correction is recorded there.

If a caller genuinely runs compute-only workloads, headless is the smaller set — but it is a
different package list, not a variable this role exposes.

## Why not `ubuntu-drivers`

Canonical documents `ubuntu-drivers install --gpgpu` as the supported path, and the previous
version of this role wrapped it. Two problems:

- It resolves against whatever apt sources are configured. This host carried NVIDIA's CUDA repo
  at apt priority **600**, above the archive's 500, for five months after its packages were
  purged — `ubuntu-drivers` would have silently preferred it. An explicit package name cannot
  drift that way.
- It is a `command:`, so it reports `changed` every run unless wrapped in `changed_when`
  guesswork, which makes "did the driver move?" unanswerable — and that question is the one
  gating the reboot.

## Why the reboot is an inline task, not a handler

Handlers notified from a play's `roles:` section are flushed at the end of the play's `tasks:`
section, after every other role has run. Callers place this role before the `docker_compose_*`
roles, so a handler would bring up every GPU container against a driver whose kernel module does
not match its userspace, and reboot afterwards. `roles/nvidia_container_toolkit` avoids the same
trap for the same reason, and its README has the longer version.

## Secure Boot

Canonical's `-server-open` packages ship pre-signed modules, so no MOK enrollment is needed if
Secure Boot is turned on later. That is one of the reasons this role uses the Ubuntu archive
rather than NVIDIA's CUDA repository; the comparison is in `docs/media-01-nvidia-driver.md`.
