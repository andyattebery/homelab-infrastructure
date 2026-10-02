# Turing RK1: building a custom vendor-kernel image

Researched 2026-10-01. **[I]** marks inference; **U** means unverified. Nothing here was run on an RK1; the build itself is planned in `plans/2026-10-01-rk1-armbian-vendor-image.md` (gitignored) and lands in `armbian/`.

Follows [rk1-os-releases.md](rk1-os-releases.md) and [rk1-gpu-npu.md](rk1-gpu-npu.md). The question was: package Rockchip's vendor kernel for the RK1 — on what base, which distro, which userspace, built where.

## Bottom line

- **Base: the Armbian build framework.** It is the only option where the RK1-specific parts (U-Boot, DT, ttyS9 console, boot glue) are someone else's tested code. Our part is one config file and one `customize-image.sh`.
- **Distro: Debian 13 trixie** (decided 2026-10-01). Ubuntu 24.04 would have gained only distro Python 3.12 for the RKNN wheel and a 2024 multimedia PPA; trixie is Armbian's CI-tested RK1 vendor target, gets newer MPP via `jellyfin-ffmpeg8`, and has LTS to 2030-06-30.
- **Version: Armbian `main`, pinned**, not the v26.08 stable branch: only main has kernel 6.1.172 (rkr7.2) and the RK1 U-Boot clock fix. Kernel, DTB and U-Boot are then updated by rebuilding, not by apt.
- **GPU: kbase + libmali g29p1**, which now exists as a deb. **NPU: RKNN 2.3.2 / RKLLM 1.3.1** from Rockchip's repos, Python via uv 3.12. **Video: `jellyfin-ffmpeg8`.**
- **Build host: an OrbStack Linux machine** on the Mac, after a spike — Armbian's Docker mode does not handle OrbStack's engine, and the kernel tree can't live on case-insensitive APFS.

## Choosing a base

| Base | Verdict | Why |
|---|---|---|
| **Armbian build framework** | chosen | Tested RK1 vendor target (`KERNEL_TEST_TARGET="vendor"`); U-Boot v2026.07 written at 32 KiB, ttyS9 console (`turing-rk1.csc:18-48`), bootscript, partitioning. Cost: Armbian's BSP layer (below). Armbian's RK1 support was contributed by Joshua Riek (d564431dc2e2, 2024-09-10). |
| Stock rootfs + Armbian kernel/DTB/U-Boot debs, no BSP | viable, not chosen | Kernel, DTB and U-Boot debs have no Armbian dependencies; every `/etc/armbian-release` read is guarded. You own extlinux, a partition layout clear of U-Boot (the binary is 9 771 008 B, so start partitions ≥ 16 MiB), the U-Boot `dd`, ttyS9 and first boot. Precedent on Debian: DietPi (pins apt.armbian.com to -1 except `linux-*`, forces base-files back down) and Tinkerbell Captain (mkosi, trixie). No Ubuntu precedent found (U). No fallback kernel: the package name is constant. |
| defcom5-rockchip/ubuntu-rockchip | rejected | Joshua-Riek's ubuntu-rockchip continued ("Continuation of Joshua-Riek/ubuntu-rockchip (archived)"). Kernel = Joshua's `noble` + one CVE commit: rkr3 6.1.75, rknpu 0.9.7 (RKLLM 1.3.1 wants 0.9.8), kbase g18p0. HEAD's `KERNEL_REPO` is `file:///mnt/build/...` (`noble.sh:13`); build runs as root on an Ubuntu host and installs/holds livecd-rootfs on it; SECURITY.md: "`apt update && apt upgrade` will not pull kernel security updates"; scoped to Orange Pi 5B. |
| Radxa rsdk | rejected | RK3588 products are bookworm-only; its kernels (`radxa/kernel` rkr4.1 6.1.84, rkr5.1 6.1.115) have no `rk3588-turing-rk1.dts`. |
| BredOS, Yocto meta-rockchip | rejected | BredOS is Arch, no RK1 image, kernel `rk6.1-rkr3` 6.1.75. Yocto's meta-rockchip has no RK1 machine and is mainline; Rockchip's BSP layer has EVBs only. |

**Image builders** for the stock-rootfs route: debos fits best (a `raw` action writes U-Boot at an offset; runs in Docker with a KVM fakemachine); mkosi assumes an EFI bootloader; ubuntu-image needs a gadget; rpi-image-gen targets Raspberry Pi.

**Armbian's BSP layer on top of the distro:** Armbian `base-files` (version 26.x sorts above the distro's, so distro base-files updates stop), `/etc/apt/apt.conf.d/71-armbian-no-recommends`, `armbian-firstrun`/`firstlogin`/`zram-config`/`ramlog`/`hardware-optimize`/`resize-filesystem` services, motd and cron jobs, a forced gzip initramfs, `vm.swappiness=100`. Don't install `armbian-firmware` on a non-Armbian rootfs: it `Conflicts: linux-firmware`.

## Choosing the distro

- **What Ubuntu 24.04 would gain:** python3 3.12.3 (the RKNN wheel stops at cp312; trixie has 3.13), and `ppa:liujianfeng1994/rockchip-multimedia` (noble only).
- **The PPA in detail:** maintained by amazingfate (an Armbian maintainer; configng adds it on noble only, pinned at 1001, `module_desktops.sh:109-110,135-136,207-213`). Last noble upload 2025-03-05 (chromium); media stack from 2024: `librockchip-mpp1 1.5.0-1+git20240612`, `librga2 2.2.0-1+git20231208`, `gstreamer1.0-rockchip1 1.14-4+git240423`, `ffmpeg 7:6.1.1-3ubuntu5+git240504` (rkmpp h264/hevc/mjpeg encoders, decoders through vp9/av1, rkrga filters). No libmali, Mesa or firmware. `rockchip-multimedia-config`'s postinst creates `/usr/lib64 -> /lib` and runs `udevadm trigger`. No kernel dependency.
- **Does Rockchip target Debian?** Its docs and SDK do: RKNN user guide v2.3.2 Table 3-2 lists the board OS as "Debian 10 / 11 (aarch64)" with Python 3.7–3.11 (the table predates Rockchip's own cp312 wheel); MPP (`rockchip-linux/mpp`, active 2026-09-21) and libmali (`JeffyCN/mirrors` `libmali-next`) carry `debian/` packaging. The binaries don't care: librknnrt needs glibc 2.17, librkllmrt 2.29, libmali 2.34, `jellyfin-ffmpeg8` 2.38; noble has 2.39, trixie 2.41.
- **Support (distro-info):** Ubuntu 24.04 standard to 2029-05-31 (ESM 2034); Debian 12 regular security ended 2026-07-11, LTS to 2028-06-30; Debian 13 to 2028-08-09, LTS to 2030-06-30; Debian 11 LTS ended 2026-08-31.
- **Armbian releases for turing-rk1/vendor:** noble, resolute and trixie are `supported`; jammy and bookworm are `csc` (need `EXPERT=yes`). Armbian's stable-release target list builds RK1 vendor as **trixie minimal CLI** and **noble GNOME** (`armbian/os` `targets-release-community-maintained.yaml:215`, used by `minimal-cli-stable-debian` and `gnome-desktop-stable-ubuntu`). Its rolling images on armbian.com (2026-09-29) are Ubuntu 26.04 GNOME/KDE and Debian 13 minimal. Debian 13 minimal is in both.
- **Radxa's Debian 12 repo** has apt-packaged `rknpu2-rk3588` and `python3-rknnlite2` 2.3.0 (cp311), but no MPP, RGA, GStreamer, FFmpeg or libmali (377 packages). Its noble suite has only metapackages.
- **Trixie gives up** the GStreamer rockchip plugin; `jellyfin-ffmpeg8` covers FFmpeg.

## The Armbian build framework (main `8eb7e43e`, 2026-10-01)

- **Versions:** stable line is branch `v26.08` (23ca24ae; there is no 26.8 tag in armbian/build), still on `rk-6.1-rkr5.1` 6.1.115, without #10543. `main` has rkr7.2 6.1.172 (#10363, 2026-09-04), #10543 and the bootscript PARTUUID fallback (#10617/#10622).
- **#10543 (SCMI CPU clocks in U-Boot):** without it the CPU clusters stay on the 24 MHz oscillator until Linux cpufreq loads; patch header: "a 23 MiB initramfs unpack took 64 seconds, 0.7 after this change" (measured on a YY3588). Slow, not broken.
- **Hosts:** amd64 or arm64, ≥8 GB RAM, ~50 GB disk; native builds need Debian 13 trixie, otherwise any Docker-capable Linux (`docs/build-framework/getting-started.md:10-13`). Docker mode is default, privileged, with loop devices.
  - **macOS:** handled in code (bash 5, coreutils, checkout under `$HOME`); only Docker Desktop and Rancher get static loop devices (`lib/functions/host/docker.sh:226-243`). Any other engine — **OrbStack reports `Name=orbstack`** — falls through and passes the Mac's nonexistent `/dev/loop*` (L729) [I: fails]. One positive report: PR #10279, Docker Desktop 4.83 on an M5, "Compile Test".
  - **OrbStack Linux machine:** `uname` is Linux, so native mode applies (`PREFER_DOCKER=no`). Loop devices are created on demand (orbstack#2329); partition nodes from `losetup -P` are U; Armbian installs `qemu-user-static`, whose binfmt handlers would register in OrbStack's shared kernel [I]. Machine data lives in `~/Library/Group Containers/HUAQ24HBR6.dev.orbstack/data/data.img` (sparse). OrbStack's memory cap defaults to 8 GB; kernel BTF needs ≥ 6451 MiB available (`armbian-kernel.sh:123-133`).
  - **Case-insensitive APFS breaks the kernel tree:** `rk-6.1-rkr7.2` `include/uapi/linux/netfilter/` has 5 groups of names differing only by case (e.g. `xt_CONNMARK.h` / `xt_connmark.h`). Build from a Linux filesystem, never from `/Users`.
  - **Native on an RK1 running Armbian trixie:** supported; build on the NVMe (eMMC is below ~50 GB). One data point: 6.1.115 vendor kernel in 1634 s on a 4-core 16 GB arm64 runner, whole build ~34 min.
- **userpatches:** must be `${SRC}/userpatches` — `entrypoint.sh:134` declares `USERPATCHES_PATH` read-only, contradicting the docs (`switches/host-docker.md:180-184`); issue #6178, PR #10776 open. `config-<name>.conf` (may define hooks) is used by `./compile.sh build <name>`. **`lib.config` now aborts the build** (`main-config.sh:447-448`).
- **customize-image.sh:** 5 args `RELEASE LINUXFAMILY BOARD BUILD_DESKTOP ARCH` (`customize.sh:34`); overlay bind-mounted read-only at `/tmp/overlay`; non-zero exit fails the build; **runs without the Armbian apt repo** (`rootfs-image.sh:37`); distro repos and network are available. `add-apt-repository` needs `software-properties-common`, which BUILD_MINIMAL omits. Hooks `custom_apt_repo`, `post_repo_customize_image` run after repos are enabled.
- **Kernel pin:** `KERNELBRANCH='commit:<sha>'` is supported (`git.sh:11-15`); set it in hook `post_family_config_branch_vendor__<name>` because the family file assigns KERNELBRANCH inside `case $BRANCH`.
- **Boot config:** `userpatches/bootenv/rk35xx.txt` overrides the template (`verbosity=1 bootlogo=false console=both extraargs=cma=256M`); `DEFAULT_OVERLAYS="panthor-gpu"` writes `overlays=`; the board already sets SERIALCON=ttyS9 and `console=ttyS9,115200`.
- **Reproducibility:** release branches pin every `branch:` ref in `config/sources/git_sources.json` (generated by `./compile.sh targets`; use with `OFFLINE_WORK=yes`); main has none. U-Boot is `tag:v2026.07`; rkbin floats on master. Artifacts are content-hashed and fetched from `ghcr.io/armbian/os` when hashes match; the rootfs cache is month-stamped, so userspace isn't byte-reproducible [I].
- **Apt after flashing:** sources `apt.armbian.com $RELEASE main $RELEASE-utils $RELEASE-desktop` plus `github.armbian.com/configng`. On 2026-10-01 stable had `linux-image-vendor-rk35xx` **26.8.3 = 6.1.115**, `linux-u-boot-turing-rk1-vendor` 26.8.3 (without #10543), `armbian-bsp-cli-turing-rk1` 26.2.1; beta had `26.11.0-trunk.66` = 6.1.172. A main build is versioned `26.11.0-trunk` (above stable, below beta); a v26.08 build is `26.08.0-trunk`, **below** stable 26.8.3, so apt would replace it [I: dpkg ordering reimplemented]. `BSPFREEZE=yes` holds every Armbian deb.
- **U-Boot on upgrade:** the deb rewrites eMMC only with `FORCE_UBOOT_UPDATE=yes`, which turing-rk1 doesn't set; otherwise only `armbian-install`/`armbian-config` write it.
- **configng `module_desktops.sh`:** runs only for desktop builds; on noble + vendor + rockchip-rk3588 it adds the multimedia PPA at 1001, installs `libv4l-0 rockchip-multimedia-config libv4l-rkmpp libwidevinecdm0 chromium-browser`, and enables `panthor-gpu`. Not callable from `customize-image.sh` (armbian-config is installed after it). `extensions/mesa-vpu.sh` was deleted 2026-05-09; Armbian's docs still show it.
- **First boot:** `/root/.not_logged_in_yet` drives `armbian-firstlogin` via root console autologin (`CONSOLE_AUTOLOGIN` default yes). Presets `PRESET_ROOT_PASSWORD`, `PRESET_USER_NAME`, `PRESET_USER_PASSWORD`, `PRESET_USER_KEY`, `PRESET_TIMEZONE`, `PRESET_LOCALE`, `PRESET_NET_*`… (`docs/user-guide/autoconfig.md`); **SSH keys only by URL** — a failed `curl` aborts first login. No hostname preset: use `HOST=` at build. `ENABLE_EXTENSIONS=cloud-init` exists (NoCloud on a FAT `/boot`, removes firstlogin) — untested on the RK1 (U).
- **Known issues:** #10216 (U-Boot 2024.04 → 2026.07; boot order now mainline's, "worth a boot test on eMMC + NVMe"; none reported); #10543; #10055 (extension artifacts rebuild every run); #10514 (mainline-kernel fan map, not vendor). No 2026 report of turing-rk1 vendor failing to build or boot.

## Userspace components (vendor kernel rkr7.2)

- **libmali:** kernel kbase is DDK `g29p1-11eac0` (`drivers/gpu/arm/valhall/Kbuild:79`; the unbuilt `bifrost/` dir says 12eac0), CSF UK 1.38, firmware built in. Options for G610:
  - `libmali-valhall-g610-g29p1` 1.10-1 (ginkage/libmali-rockchip v1.10-1-db9112f, 2026-09-26; g29p1-11eac1 so19). Blobs git-SHA-identical to Rockchip's JeffyCN/mirrors `libmali-next` bf621d15. Three mutually exclusive packages: full (GLES + OpenCL + Vulkan; depends on X11/Wayland client libs), `-cl`, `-gles`.
    - Later on 2026-10-01 (22:22 UTC) ginkage published v1.10-1-e96672b and deleted the db9112f release; the tag stays, the assets 404. The two differ by one commit touching only `hook/hook.c`, so the Mali blob is the same. ginkage keeps tags and deletes superseded releases, so a pinned URL breaks at the next release. The build pins e96672b.
  - tsukumijima v1.9-1-20260923-ec78b74: g24p0 only (gbm/x11/wayland/dummy). Every g24p0 field report is on an older kbase (g25p0, rkr5.1, UK 1.31); g24p0 on g29p1 is U. Jellyfin: "ensure that the user space firmware and kernel driver versions match, otherwise OpenCL will not work properly."
  - Rockchip's default `libmali` branch still pairs G610 with g24p0; g29p1 is only on `libmali-next`.
  - The debs install `/etc/OpenCL/vendors/mali.icd`, `/usr/share/vulkan/icd.d/mali.json` (`api_version` 1.3.276) and `/etc/ld.so.conf.d/00-aarch64-mali.conf`.
  - g29p1 issues: JeffyCN/mirrors #77 (UI glitches, fixed in so19), #75 (BCn, fixed in so18), #78 (VOP bus error, not libmali), #82 (libs briefly removed). isac322/rkmon#10: the g29p1 kbase renamed devfreq to `fb000000.gpu`.
- **NPU:** rknpu 0.9.8 registers a DRM render node (renderD129, `root:render 0660`), no `/dev/rknpu` — don't create that symlink (rknn-llm#530).
  - `librknnrt.so` 2.3.2: rknn-toolkit2 v2.3.2 `rknpu2/runtime/Linux/librknn_api/aarch64/`, installed to `/usr/lib/`.
  - `rknn_toolkit_lite2-2.3.2-cp312-…manylinux_2_17_aarch64` (PyPI) requires only `numpy, psutil, ruamel.yaml`; PEP 668 means a venv.
  - `librkllmrt.so` 1.3.1: rknn-llm release-v1.3.1 `rkllm-runtime/Linux/librkllm_api/aarch64/`; needs `libgomp1`; uses OpenCL when present (+7–10%, rknn-llm#531). Server and demos are source-only. rknn-llm#509: SIGSEGV on an RK1 with 1.3.0 from a header mismatch.
  - Radxa's apt `rknpu2-rk3588` 2.3.0 (with `rknn_server`) is bookworm-only; its `python3-rknnlite2` is cp311.
- **Video:** `jellyfin-ffmpeg8` 8.1.3-1 is published for noble, trixie and resolute arm64; it bundles its own MPP (jellyfin-mpp-next, 2025-12) and RGA, depends on `ocl-icd-libopencl1`, and installs under `/usr/lib/jellyfin-ffmpeg/`. Jellyfin requires a BSP 5.10/6.1 kernel. Devices: `/dev/dri`, `/dev/dma_heap`, `/dev/rga`, `/dev/mpp_service`, `/dev/mali0` (tone-mapping). Jellyfin's udev rules (`rockchip.md`) set `mpp_service`/`rga` to video 0660 and the dma_heap nodes to 0666. Armbian's `50-mali.rules` (`KERNEL=="mali*", MODE="0660", GROUP="video"`) is installed by `family_tweaks_bsp` in `rockchip64_common.inc`, but `rockchip-rk3588.conf:61-63` redefines that function as a no-op. RK3588 images therefore have no Mali rule, which the first build on 2026-10-01 confirmed. An image must bring its own.
- **jjriek PPAs** still serve noble but stopped in 2024; their `libmali-g610-x11` is g13p0 with no Vulkan ICD.

## Vendor kernel trees, maintenance (window since 2026-07-03)

| Tree | Sublevel (upstream 6.1.188) | Activity | Notes |
|---|---|---|---|
| armbian/linux-rockchip `rk-6.1-rkr7.2` @44bbd021 (2026-09-30) | 172 | 825 commits by committer date (mostly the rkr7.2 port and LTS merges) | Upstream stable arrives only through Rockchip SDK merges. |
| unifreq/linux-6.1.y-rockchip @253cd768 (2026-09-30) | 174 | single maintainer, re-commits history | RK1 DTS, rknpu 0.9.8, kbase g29p1; no deb channel. |
| defcom5 `noble-security`, Joshua `noble`, BredOS `rk6.1-rkr3` | 75 | 0 commits | Frozen. BredOS also has `rk6.1-rkr6.1` (6.1.118). |

## Flashing with `tpi` (v1.0.7)

`tpi flash -n <1-4> -i ./image.img [--sha256 <hex>] [--skip-crc]` streams a local file from the client; `-l` instead names a file on the BMC's microSD. The BMC accepts `.xz`. Turing: "about 8 minutes for each 1 GB of the image file, plus an additional minute at the end for verification".

## Open

- g29p1 libmali on the 11eac0 kbase, RKNN Lite2 on a uv CPython 3.12, and an OrbStack machine as an Armbian host are all untested.
- Whether Armbian's published RK1 desktop images carry the `panthor-gpu` overlay (the rootfs cache is built before the board package) is U.
- The Turing forum returned HTTP 429 throughout.
- **Custom image result (2026-10-01).**
  - The build from `armbian/` boots on `turingpi-rk1-01` from the eMMC (U-Boot v2026.07): under 48 s from power-on to the login prompt.
  - On the node:
    - The g29p1 libmali runs on the g29p1-11eac0 kbase: OpenCL finds the Mali-G610, and Vulkan reports device apiVersion 1.4.305 with conformance 1.4.1.0, although the ICD manifest says 1.3.276.
    - RKNN Lite2 runs resnet18 on the uv CPython 3.12.14 (top-1 space shuttle, 0.9997; driver 0.9.8), and `librkllmrt.so` loads.
    - `jellyfin-ffmpeg8` encodes H.264 at 13.6x realtime (1080p) and decodes into `scale_rkrga` at 30x.
  - So all three untested items in the first bullet held up; the OrbStack machine built the image.
  - The Armbian side needed two settings:
    - `INCLUDE_HOME_DIR=yes`: Armbian leaves `/home` out of images by default.
    - A Mali udev rule of its own: `rockchip-rk3588.conf` makes `family_tweaks_bsp` a no-op, so `50-mali.rules` is never installed.
  - Details: `armbian/README.md`.

## Sources

- armbian/build @8eb7e43e (and branch `v26.08` @23ca24ae, `v26.5.1` @8de11a01): `config/boards/turing-rk1.csc`, `config/sources/families/rockchip-rk3588.conf`, `config/sources/families/include/rockchip64_common.inc`, `lib/functions/host/{docker.sh,host-release.sh,mountpoints.sh}`, `lib/functions/cli/{entrypoint.sh,utils-cli.sh}`, `lib/functions/configuration/main-config.sh`, `lib/functions/main/{config-prepare.sh,rootfs-image.sh}`, `lib/functions/rootfs/{customize.sh,distro-agnostic.sh,distro-specific.sh}`, `lib/functions/compilation/{armbian-kernel.sh,uboot.sh}`, `lib/functions/general/git.sh`, `extensions/cloud-init/`, `patch/u-boot/v2026.07/general-rk3588-raise-cpu-clocks-via-scmi.patch`; PRs/issues #6178, #10055, #10216, #10279, #10363, #10514, #10543, #10617, #10622, #10776.
- armbian/documentation @f50d47c1: `docs/build-framework/getting-started.md`, `switches/host-docker.md`, `user-guide/autoconfig.md`, `releases/release-model.md`. armbian/configng @68cf7614: `tools/modules/desktops/module_desktops.sh`. armbian/os @abd348f5: `userpatches/targets-release-community-maintained.yaml`.
- apt.armbian.com and beta.armbian.com `noble`/`resolute` arm64 Packages (2026-10-01).
- armbian/linux-rockchip `rk-6.1-rkr7.2` @44bbd021, `rk-6.1-rkr5.1`; defcom5-rockchip/ubuntu-rockchip @1a4db0b0 and linux-rockchip-rk3588 @8027f108; Joshua-Riek/ubuntu-rockchip @38dfb495; radxa-pkg, RadxaOS-SDK/rsdk @54a73ca7, radxa-repo bookworm Packages; BredOS/linux-bredos; unifreq/linux-6.1.y-rockchip; DietPi `dietpi-installer` @e928cdbd; Tinkerbell Captain.
- ginkage/libmali-rockchip v1.10-1-db9112f; tsukumijima/libmali-rockchip v1.9-1-20260923-ec78b74; JeffyCN/mirrors `libmali` @34f62629, `libmali-next` @bf621d15; JeffyCN/mirrors #75, #77, #78, #82; isac322/rkmon#10.
- airockchip/rknn-toolkit2 v2.3.2 (`02_User_Guide_RKNN_SDK_V2.3.2_EN.pdf` Table 3-2); airockchip/rknn-llm release-v1.3.1; rknn-llm #509, #530, #531; PyPI `rknn-toolkit-lite2`, `ai-edge-litert`.
- Launchpad `~liujianfeng1994/+archive/ubuntu/rockchip-multimedia`, `~jjriek/*`; distro-info-data `ubuntu.csv`, `debian.csv`; Ubuntu noble `python3-defaults`, `glibc`.
- repo.jellyfin.org `debian/dists/trixie` and `ubuntu/dists/noble` Packages; jellyfin.org docs `rockchip.md` @85e9359.
- rockchip-linux/mpp `debian/changelog`; OrbStack docs (architecture, machines, file-sharing, FAQ, release notes), orbstack/orbstack #1158, #2329, #2655.
- turing-machines/tpi v1.0.7 `src/{cli.rs,legacy_handler.rs}`; turing-machines/bmcd v2.3.7 `streaming_data_service/data_transfer.rs`; docs.turingpi.com `turing-rk1-flashing-os`.
