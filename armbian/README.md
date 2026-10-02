# Turing RK1 image: Debian 13 on Rockchip's vendor kernel

A flashable eMMC image for the Turing RK1 (RK3588) nodes in the Turing Pi 2, built with the
Armbian build framework: Debian 13 trixie on Rockchip's vendor kernel, which is the only kernel
that runs the NPU's full RKNN/RKLLM stack, MPP video and the Mali GPU's OpenCL. One image per
node: the hostname and the password of user `services` are built in.

## Status: Built

Built 2026-10-01 and running on both RK1 nodes: `turingpi-rk1-01` (node 1, 192.168.1.216) and
`turingpi-rk1-02` (node 2, 192.168.1.217). Verified on each: OpenCL and Vulkan on the Mali-G610,
RKNN resnet18 on the NPU, the RKLLM runtime, H.264 encode and decode through MPP, RGA scaling,
sensors and fan, NVMe, gigabit Ethernet, SSH policy and the package holds. Why each choice was
made is in
[research/turing-pi-cluster/rk1-custom-image.md](../research/turing-pi-cluster/rk1-custom-image.md).

## What the image holds

| Part | What | From |
|---|---|---|
| Kernel, DTB | 6.1.172 `vendor-rk35xx` (rkr7.2), `rk3588-turing-rk1.dtb` | armbian/linux-rockchip `44bbd021`, built by Armbian |
| Bootloader | U-Boot v2026.07 with the RK3588 SCMI clock fix, at 32 KiB on the eMMC | Armbian |
| Userspace | Debian 13 trixie, Armbian minimal CLI | Debian, Armbian |
| GPU | `libmali-valhall-g610-g29p1` 1.10-1: OpenCL 3.0, Vulkan 1.4 (the device reports 1.4.305), GLES 3.2 | ginkage/libmali-rockchip |
| NPU | `/usr/lib/librknnrt.so` 2.3.2, `/usr/lib/librkllmrt.so` 1.3.1; RKNN Toolkit Lite2 in the venv `/opt/rknn-lite2` (CPython 3.12) | airockchip, PyPI, uv |
| Video | `jellyfin-ffmpeg8` 8.1.3-1 (rkmpp codecs, rkrga filters) in `/usr/lib/jellyfin-ffmpeg/` | repo.jellyfin.org |
| Access | user `services` (uid/gid 1000, fish, groups `sudo video render`, passwordless sudo), keys from `nix/modules/ssh-keys.nix`; root locked; SSH keys only | this repo, 1Password |

## Files

| Path | What it is |
|---|---|
| `versions.env` | Every pin: the Armbian commit, the kernel commit, and each download's URL and SHA-256. |
| `mise.toml` | `tpi` (BMC CLI) and `uv`; `TPI_HOSTNAME`, the BMC's IP. |
| `userpatches/config-rk1.conf` | The Armbian build config, including the kernel-pin hook. |
| `userpatches/customize-image.sh` | Runs in the image chroot: GPU, NPU, video, access, time zone, locale. |
| `userpatches/overlay/` | Files `customize-image.sh` installs: the apt pin for Jellyfin's repo, the udev rules for the GPU (`50-mali.rules`) and for MPP, RGA and the DMA heaps (Jellyfin's), the sshd drop-in, and `rknn-requirements.txt`, the hash-locked RKNN Lite2 dependencies. |
| `userpatches/rknn-requirements.in` | What that lock is compiled from. |
| `scripts/` | `build-image.sh <hostname>`, `flash-node.sh <node> <image> [--yes]`. Each prints its usage with `-h`. |
| `images/` | Gitignored: built images. |

## Inputs

- **`versions.env`.** Each download is checked against its SHA-256 inside the build, so a wrong
  hash, a moved file or a 404 stops the build at that step. A wrong `ARMBIAN_BUILD_SHA` fails at
  the fetch. `KERNEL_COMMIT` must equal the commit in `config-rk1.conf`'s hook;
  `build-image.sh` refuses to start otherwise.
- **The hostname argument** becomes `/etc/hostname`, and names the 1Password item whose
  `password` field becomes the password of `services`: `op://Home Lab/<hostname>/password`. A
  missing item fails at `op inject`, before the build starts. 1Password asks once per build.
- **OrbStack.** `build-image.sh` creates the machine `armbian-build` (debian:trixie, arm64) on
  first use and keeps the Armbian checkout and its caches in that machine's home, at
  `~/armbian-build`. `orb delete armbian-build` removes all of it. Armbian's host packages add
  one binfmt entry to the machine (`python3.13`, from Debian's binfmt-support); OrbStack's own
  Rosetta and qemu handlers are untouched (checked 2026-10-01).
- **The BMC login.** `tpi` prompts for it, or uses the token it cached on the last login
  (`~/Library/Caches/tpi_token`).

## Build and flash

From `armbian/`, after `mise install`:

```sh
scripts/build-image.sh turingpi-rk1-01
scripts/flash-node.sh 1 images/turingpi-rk1-01/<name>.img          # shows power state; writes nothing
scripts/flash-node.sh 1 images/turingpi-rk1-01/<name>.img --yes    # power off, flash, power on
mise exec -- tpi uart -n 1 get                                      # the serial console, buffered
rm images/turingpi-rk1-01/*                                         # the image holds a password hash
```

`build-image.sh` prints the image's name. The first build is the long one: Armbian builds the
kernel, U-Boot and the Debian rootfs, or fetches matching ones from its own cache, and later
builds reuse the machine's caches. Flashing streams the image from the Mac and the BMC verifies
it: Turing quotes about 8 minutes per GB, and node 1's 2.4 GiB image took 9 minutes in all.

## Updating

Debian packages and `jellyfin-ffmpeg8` update with apt. Every Armbian package (kernel, DTB,
U-Boot, BSP) is held (`BSPFREEZE=yes`): apt.armbian.com's stable kernel is 6.1.115, older than
this one, and would replace it. They change only by bumping pins in `versions.env` and
`config-rk1.conf`, rebuilding and reflashing. Move off Armbian `main` to a stable branch once one
carries rkr7.2.

## Traps

- **Not on the Mac's own filesystem.** The kernel tree has file names that differ only by case,
  which the case-insensitive APFS volume cannot hold. The checkout lives in the OrbStack
  machine's Linux filesystem.
- **Not through OrbStack's Docker engine.** Armbian's Docker mode hands the container static loop
  devices only on Docker Desktop and Rancher; on any other engine it passes the Mac's `/dev/loop*`,
  which do not exist, so imaging would fail [I]. Inside the machine Armbian builds natively, as
  root through sudo.
  `PREFER_DOCKER=no` goes on the command line: Armbian decides between Docker and sudo before it
  reads `config-rk1.conf`.
- **userpatches must be inside the checkout.** On this Armbian commit `USERPATCHES_PATH` is
  read-only, set to `<checkout>/userpatches`, whatever the docs say. `build-image.sh` rsyncs
  `userpatches/` in on every run, so edit it here, never in the machine.
- **No `lib.config`.** Armbian `main` aborts a build that has `userpatches/lib.config`.
- **`customize-image.sh` runs without Armbian's apt repo**; only Debian's are enabled at that
  point.
- **Armbian leaves `/home` out of the image** unless `INCLUDE_HOME_DIR=yes`. Without it the
  `services` account exists but has no home and no SSH keys.
- **Armbian's RK3588 family installs no GPU udev rule.** `rockchip64_common.inc` would install
  `50-mali.rules`, but `rockchip-rk3588.conf` replaces that function with a no-op, so
  `/dev/mali0` would be root-only. The overlay brings the rule.
- **libmali must match the kernel's GPU driver.** The vendor kernel's kbase is DDK g29p1, so the
  userspace is g29p1. If OpenCL or Vulkan finds no device, the fallback is tsukumijima's g24p0
  packages: kbase negotiates down to an older userspace, but g24p0 on this kbase is untested.
  ginkage deletes superseded releases: a 404 at the libmali download means re-pin to the
  current release.
- **No panthor.** The `panthor-gpu` overlay binds the GPU to panthor instead of kbase, and
  libmali needs kbase. Armbian's desktop setup (configng) enables it on noble vendor builds;
  this build sets no overlays.
- **`CONSOLE_AUTOLOGIN=no`.** Armbian's default logs root in on the serial console to run its
  first-login wizard. This image removes the wizard, so that autologin would be a passwordless
  root shell.
- **Root is locked.** Log in as `services` (keys over SSH, the password on the serial console).
  An emergency-mode boot has no root password to ask for [I]; the recovery is a reflash.
- **`jellyfin-ffmpeg` is not on PATH.** It is `/usr/lib/jellyfin-ffmpeg/ffmpeg`. The RGA filters
  take hardware frames only: decode with
  `-init_hw_device rkmpp=rk -hwaccel rkmpp -hwaccel_output_format drm_prime` before
  `scale_rkrga`, or the filter fails with "Function not implemented".
- **`tpi uart get` is not a live stream.** Each call returns the BMC's whole buffer since the
  node powered on; call it again to see newer lines.
- **Delete images after flashing.** Each holds its node's password hash in `/etc/shadow`.
