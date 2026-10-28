# ZFS on the Turing Pi nodes

Researched 2026-10-25. **[I]** marks inference. Sources are at the end.

- The node facts come from one read-only check per node on 2026-10-25: `uname -r`,
  `modinfo -F filename zfs`, `dpkg-query`, and `apt-cache policy` for `zfs-dkms` and
  `zfsutils-linux`.
- Package contents were listed by streaming each `.deb` from ports.ubuntu.com through `tar`.
- Nothing was installed, built or booted.

**The question (owner, 2026-10-25):**
- "do all of the turing pi nodes have zfs support in the kernel?"
- And: Canonical has an Ubuntu 24.04 image for the Jetson, not linked from its docs, which "might
  have zfs built-in".

**Why it matters:** `data_disk_offload` formats each node's data disk ext4, which goes against the
owner's planned backup of Docker bind-mount data on these disks. See
`ansible/roles/data_disk_offload/tasks/main.yaml`, "Make the data filesystem".

## Bottom line

- **Only the CM4's kernel has ZFS today.** Ubuntu's `linux-raspi` ships `zfs.ko`. The RK1s' Rockchip
  vendor 6.1.172 and the Jetson's NVIDIA 6.8.12 kernels have no ZFS module.
- **Canonical's Ubuntu 24.04 Jetson image has ZFS built in, but it is the Thor release.**
  - Canonical: "This release only targets Jetson AGX Thor, it does not support the Jetson Orin
    development kits."
  - None of its kernel packages contains `nvgpu.ko`, the driver NVIDIA uses for every Orin GPU. On the
    Orin Nano it would be ZFS without CUDA or NVDEC [I: not booted].
- **On the current Jetson install, nothing found stops ZFS by DKMS.**
  - The L4T kernel was built with gcc 13.2.0 (crosstool-NG's, per its `/proc/config.gz`), exports
    every symbol, doesn't force module signatures, and has no lockdown.
  - noble's `zfs-dkms 2.2.2-0ubuntu9.5` is the ZFS release Canonical builds into its own tegra kernel.
  - It rebuilds with each L4T kernel. **Tested 2026-10-26:** it builds by DKMS against the
    installed L4T headers, loads, and opens `/dev/zfs` (Load test, below).
- **On the RK1, nothing found stops DKMS either, though two version-specific failures are on
  record.**
  - On 6.1.84, an Armbian kernel build oopsed loading any out-of-tree module, ZFS or not.
  - On 6.1.115, ZFS 2.3.5 loaded but `/dev/zfs` answered ENODEV. The cause was never found.
  - Neither is reported for 6.1.172 with ZFS 2.4.4, Armbian's candidate, which can't be installed
    (Update, under Open). The nodes have no kernel headers installed; the image doesn't ship them.
  - **Tested 2026-10-26 on rk1-02:** Ubuntu's ZFS 2.4.1 builds by DKMS against the image's own
    kernel headers, loads, and opens `/dev/zfs` (Load test, below).
  - The other route is Canonical's generic 26.04 kernel: ZFS prebuilt, but no RKNN/RKLLM.
- **Viability, after the 2026-10-26 load test:** ZFS works on every node's current kernel: by DKMS
  on the RK1 (rk1-02) and the Jetson, prebuilt on the CM4. What decides it is upkeep, plus one
  untested step:
  - **RK1s:** the kernel changes only with a reflash. Each image release needs its own kernel
    headers, which only that build's Armbian kernel artifact has: the image neither ships nor
    publishes them. Without them a reflash leaves ZFS unbuildable. ZFS itself has to be Ubuntu's
    2.4.1, pinned.
  - **Jetson:** each L4T kernel release rebuilds ZFS by DKMS [I: not tested]. A failed rebuild
    leaves the pool unavailable after that reboot. ZFS 2.2.2's `META` lists 6.6 as its newest
    kernel; it built on 6.8 anyway.
  - **Untested:** a pool, its import and mounts at boot next to `data_disk_offload`'s binds, real
    I/O, and memory use.
- **Installed 2026-10-26, through `zfs_install`** (`playbook-turingpi.yaml`, tag `zfs`), no pool:
  - the CM4: `zfsutils-linux 2.4.1-1ubuntu5.1`, with the raspi kernel's own module
    (`zfs-kmod-2.4.1-1ubuntu5.1`). Each raspi kernel's modules package depends on its ZFS module
    package, so kernel updates keep it;
  - the Jetson: `2.2.2-0ubuntu9.5`, built by DKMS, plus `gcc`;
  - the RK1s: `2.4.1-1ubuntu5.1`, built by DKMS against the headers in release `6.1.172-8` of
    rk1-armbian-minimal, the first image that carries them (installed and held). Ubuntu's ZFS, not
    Armbian's 2.4.4: their host_vars block apt.armbian.com's `zfs-linux` binaries. They run
    without `data_disk_offload` since that reflash, so their data disks are unbound;
  - all four load it at boot, through `zfs.target`: each was rebooted on 2026-10-26, and the
    role's rerun found the module already loaded (`changed=0`).

## Each node today

Before the install above.

| Node | Kernel | ZFS module | ZFS packages |
|---|---|---|---|
| turingpi-rk1-01, turingpi-rk1-02 | `6.1.172-vendor-rk35xx` (Armbian `linux-image-vendor-rk35xx` 26.11.0-trunk) | none: `modinfo: ERROR: Module zfs not found.` | none installed, and no kernel headers. apt offers `zfs-dkms 2.4.4-2arter97~ubuntu26.04.1` and `zfsutils-linux 2.4.4-1arter97~ubuntu26.04.1` |
| turingpi-cm4-01 | `7.0.0-1020-raspi` | `ubuntu/dkms/zfs/zfs.ko.zst`, not loaded | none installed. apt offers `zfsutils-linux 2.4.1-1ubuntu5.1` |
| turingpi-jetson-01 | `6.8.12-1021-tegra` (L4T R39.2.1, `nvidia-l4t-kernel`) | none | none installed; `nvidia-l4t-kernel-headers` is installed. apt offers `zfs-dkms 2.2.2-0ubuntu9.5` |

## Jetson

### Canonical's Ubuntu 24.04 image

**What it is:**
- `ubuntu-24.04-preinstalled-server-arm64+tegra-jetson.img.xz`: 734 MB, dated 2026-01-30.
- It is in `cdimage.ubuntu.com/releases/24.04/release/nvidia-tegra/`, under the heading "Ubuntu
  Server 24.04.4 LTS (Noble Numbat) Tegra".
- Its `.manifest` names the kernel:
  - Canonical's `linux-image-6.8.0-1013-nvidia-tegra`, with `linux-modules`, `linux-modules-extra`,
    `linux-modules-tegra-oot-jetson` and `linux-modules-tegra-igpu-jetson` for that ABI;
  - plus `linux-firmware-nvidia-tegra 38.2.2`, the R38 line.

**ZFS: yes.**
- The kernel's build list includes ZFS: `debian.nvidia-tegra/dkms-versions` on the noble branch has
  `zfs-linux 2.2.2-0ubuntu9.5 modulename=zfs …` for arm64.
- The generic noble kernel's list has the same entry, the positive control.
- The current modules package, `linux-modules-6.8.0-1036-nvidia-tegra`, contains
  `kernel/zfs/zfs.ko.zst` and `kernel/zfs/spl.ko.zst`.
- The image's own 1013 package is gone from the archive [I: it has ZFS too, from the same build
  list].
- `zfsutils-linux` is not in the image.

**It is the Thor release:**
- Canonical's how-to page: "currently supporting Ubuntu 22.04 LTS (Jammy Jellyfish) for Jetson Orin
  platforms" and "Ubuntu 24.04 LTS (Noble Numbat) for Jetson Thor devices".
- Its release notes list three releases: "Ubuntu for Jetson 22.04 Server (Jammy)", "Ubuntu for
  Jetson 24.04 Server Thor release (Noble)", and "Ubuntu Core 22 for Jetson (Jammy)".
- The Thor note says: "This release only targets Jetson AGX Thor, it does not support the Jetson
  Orin development kits." That is the search engine's copy; the page rendered empty when fetched.
- That is what [orin-nano-install.md](orin-nano-install.md) recorded on 2026-10-02 as "24.04 is
  Thor-only". The docs link only 22.04 for Orin because Canonical's only Orin release is 22.04.

**No GPU driver for the Orin:**
- NVIDIA's r39.2 docs say "Jetson Orin devices use the NVGPU driver, `nvgpu.ko`"
  ([os-alternatives.md](os-alternatives.md)).
- `nvidia-l4t-init` 39.2.1 says "tegra23x chips use nvgpu-l4t; tegra264 and later use openrm-l4t"
  ([kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md)).
- Canonical's 6.8.0-1036 packages, listed in full:

  | Package | Modules | GPU-related modules |
  |---|---|---|
  | `linux-modules-6.8.0-1036-nvidia-tegra` | 1019 | mainline `tegra-drm` and `host1x`, and the old `nvidiafb` |
  | `linux-modules-extra-6.8.0-1036-nvidia-tegra` | 6661 | only the `nvidia_cspmu` perf driver |
  | `linux-modules-tegra-oot-jetson-6.8.0-1036-nvidia-tegra` | out-of-tree drivers | no GPU driver, only `nv-gpu-static-pg` [I: a power-gating helper]; its defaults package calls them "jetson Thor OOT modules" |
  | `linux-modules-tegra-igpu-openrm-jetson-6.8.0-1036-nvidia-tegra` | the iGPU modules | NVIDIA's open driver (`nvidia.ko`, `nvidia-drm`, `nvidia-modeset`, `nvidia-uvm`), the tegra264 (Thor) path |

  None has `nvgpu.ko`.
- That igpu package's defaults package is described as "Extra configuration required for jetson
  IGX Orin iGPU modules". But its contents are OpenRM, and NVIDIA doesn't use OpenRM on tegra23x
  [I: whether OpenRM could drive the Orin's GA10B is undocumented].

**So:**
- On the Orin Nano this image would bring ZFS and Canonical's kernel updates, and lose CUDA and
  NVDEC. Those are why the Orin is on the board [I: not booted].
- Which QSPI firmware the image expects wasn't read either. The module runs R39.2.1 with the
  carrier's EEPROM fix ([orin-nano-qspi-updates.md](orin-nano-qspi-updates.md)).

### DKMS on the current L4T install

**The kernel's build config** is the `.config` in `nvidia-l4t-kernel-headers 6.8.12-tegra-39.2.1`
(`3rdparty/canonical/linux-noble/.config`). It allows an out-of-tree module:
- `CONFIG_CC_VERSION_TEXT="gcc (Ubuntu 13.2.0-23ubuntu4) 13.2.0"`: noble's own compiler. The
  running kernel's `/proc/config.gz` names crosstool-NG's gcc 13.2.0 instead, and otherwise
  differs from this `.config` only in the binutils version and `GCC_PLUGINS` (Load test,
  below). DKMS builds with noble's gcc-13, 13.3.0 from noble-updates.
- `TRIM_UNUSED_KSYMS` is unset, so every exported symbol stays exported.
- `MODULE_SIG=y`, but not `MODULE_SIG_FORCE`, and no `SECURITY_LOCKDOWN_LSM`. So an unsigned module
  loads; it taints the kernel.
- `PAHOLE_VERSION=0`, with no BTF, so there is no module BTF to mismatch.
- `MODVERSIONS=y`, `MODULE_UNLOAD=y` and `PREEMPT=y` (not RT). No clang CFI, shadow call stack or LTO.

**The rest:**
- noble's `zfs-dkms 2.2.2-0ubuntu9.5` is the candidate, and the headers are installed.
- Canonical compiles that ZFS release into its own 6.8 tegra kernel (above). So the build very
  likely succeeds [I].
- The one Jetson DKMS failure on record is from JetPack 5.1.1 on a Xavier NX (NVIDIA forum 269858):
  no headers package matched the `-tegra` kernel. R39 ships one.
- Nobody has reported ZFS on JetPack 6 or 7, as success or failure.
- The kernel changes with each L4T release, which the private apt repo publishes by itself. DKMS
  rebuilds then, and a failed build would leave the pool unmounted after that reboot [I].

## RK1

**What failed before.** Armbian forum threads, read 2026-10-25:
- **5.10.160 BSP (Rock 5B), ZFS 2.1.11, October 2023** (topic 30555):
  - ZFS's configure found "None of the expected "file_fallocate" interfaces".
  - The BSP is forked from Android's common kernel.
- **6.1.84 (Rock 5 ITX, Orange Pi 5 Plus), ZFS 2.2.6, January 2025** (topic 49378):
  - The error: `Oops … pc : mod_sysfs_setup+0x230/0x518` inside `load_module`.
  - The same oops hit `r8168-dkms`, a non-ZFS module. So that kernel build broke every out-of-tree
    module.
  - Disabling `CONFIG_MODULE_UNLOAD` stopped it. One reply suggested the kernel and the module were
    built from mismatched configs.
  - 6.1.75 had worked.
- **6.1.115 (Orange Pi 5), ZFS 2.3.5, January 2026** (topic 57323):
  - The module loaded and `/dev/zfs` existed as `10, 249`, but `openat` returned ENODEV.
  - The cause wasn't found. Pinning 2.3.2 was offered as a workaround, unconfirmed.
  - [I] A static `/dev/zfs` node at minor 249, with the module registered at a different minor,
    would give exactly this.
  - That thread is where an Armbian admin wrote "It is not recommended to match ZFS with vendor
    kernel(s)", recommending mainline instead.

**What that means for 6.1.172 with ZFS 2.4.4:**
- Neither failure is reported for it.
- Neither was shown to be ZFS against the vendor kernel in general. One was a broken kernel build;
  the other is unexplained, in one ZFS release.

**The kernel's build config** is Armbian's `config/kernel/linux-rk35xx-vendor.config` (a defconfig,
main at 894f10be9, 2026-10-19):
- `MODULE_UNLOAD=y`, `MODVERSIONS=y`, `PREEMPT_VOLUNTARY=y` and `DEBUG_INFO_BTF=y`.
- No module signing, symbol trimming or clang hardening is set.
- [I] A defconfig lists only non-defaults, and the node's own `/boot/config-*` wasn't read. With BTF
  on, a module built without the kernel's `vmlinux` skips its BTF, with a warning.

**What the nodes lack:**
- Kernel headers matching `linux-image-vendor-rk35xx 26.11.0-trunk`. None are installed, and
  whether the nodes' apt sources carry them wasn't checked. On 2026-10-08 the 6.1.172 headers were
  only on beta.armbian.com.
- apt does offer ZFS 2.4.4 (`zfs-dkms 2.4.4-2arter97~ubuntu26.04.1`), from a repository not
  identified here.

**The other routes:**
- **Canonical's generic Ubuntu 26.04 kernel.**
  - It ships ZFS: `linux-modules-7.0.0-38-generic` depends on `linux-main-modules-zfs-7.0.0-38-generic`
    (resolute-updates).
  - But it is the mainline-hardware path ([rk1-os-releases.md](rk1-os-releases.md)): GPU, the
    rocket NPU and H.264/HEVC decode.
  - It has no RKNN or RKLLM, needs a hand-assembled EFI boot, and needs a Mesa fix for rocket that
    Ubuntu's 26.0 branch never got ([rk1-gpu-npu.md](rk1-gpu-npu.md)).
  - The nodes kept the vendor kernel because RKNN and RKLLM need it.

## CM4

- ZFS is prebuilt: `linux-main-modules-zfs-7.0.0-1020-raspi`, pulled in by the kernel's modules
  package ([node-storage.md](node-storage.md)).
- Only `zfsutils-linux` is missing.

## Changing the data disks

- They hold `/var/log` and `/var/tmp` now, and on the Jetson also the Docker and containerd
  directories.
- `data_disk_offload` can't undo a bind and never reformats. So a new filesystem needs, per node:
  1. the binds undone, which takes a role change or a committed script, not hand work;
  2. the disk wiped;
  3. the role taught ZFS.
- Longhorn's V1 engine needs an ext4 or XFS disk (Longhorn 1.14.0 `nodes/multidisk.md:29,94`, read
  2026-10-09). That matters only if k3s with Longhorn is chosen. The Orin can't hold Longhorn
  volumes on L4T anyway ([README.md](README.md)).

## Load test (2026-10-26)

A playbook installed the headers and ZFS, then built, loaded and opened `/dev/zfs`. A second
playbook purged it all and checked each node against its baseline. No pool was created, and
neither node was rebooted. Both nodes passed.
- **turingpi-rk1-02, `6.1.172-vendor-rk35xx`: pass.**
  - **What ran:** Ubuntu's `zfs-dkms`/`zfsutils-linux 2.4.1-1ubuntu5.1`, all six packages pinned
    (Armbian's 2.4.4 pair can't be installed: the Update, under Open).
  - **Headers:** `linux-headers-vendor-rk35xx` from the image's own Armbian kernel artifact,
    downloaded from Armbian's build cache. Its identity line equals the installed kernel's: the
    git revision and every hash.
  - **ABI check:** the headers' `Module.symvers` agrees with the CRCs in the kernel's own modules,
    78066 compared, 0 mismatched. The control, with zeroed CRCs, mismatched all of them.
  - **Build:** 226 s with resolute's gcc 15.2.0. The kernel was built by gcc 14.2.0; kbuild warns,
    and the module loads.
  - **`/dev/zfs`** is at the static misc minor 249 in the module's alias, in sysfs and on the node.
    So boot-time `/dev/zfs` matches, the mismatch suspected in the 6.1.115 ENODEV report above
    [I: not booted].
  - **`zpool version`:** `zfs-2.4.1-1ubuntu5.1`, `zfs-kmod-2.4.1-1ubuntu5.1`.
  - **Not covered:** a pool, I/O, a reboot, and future kernels. rk1-01 runs the same image and
    wasn't tested.
- **turingpi-jetson-01, `6.8.12-1021-tegra`: pass** (the third run).
  - **What ran:** noble's `zfs-dkms`/`zfsutils-linux 2.2.2-0ubuntu9.5`, pinned, with NVIDIA's
    `dkms 1:3.4.0-1ubuntu1` and noble's gcc 13.3.0, against the installed
    `nvidia-l4t-kernel-headers`.
  - **Headers:** every in-tree module (1352) has vermagic `6.8.12-1021-tegra SMP preempt mod_unload
    modversions aarch64`. The running kernel's `/proc/config.gz` and the headers' `.config` differ
    only in the toolchain: the kernel came from crosstool-NG's gcc 13.2.0 with binutils 2.40 and
    `GCC_PLUGINS=y` (no plugin enabled), and the headers' copy was regenerated with noble's gcc
    13.2.0 and binutils 2.42.
  - **No CRC pre-check:** noble's kmod 31 can't read these modules' symbol versions (`modprobe
    --dump-modversions` fails on every one with "Invalid argument"; a module without them fails
    with "No data available") [I: the cause in kmod 31 not looked into]. The kernel still checks
    each symbol's CRC at load.
  - **Build:** 209 s. dkms didn't sign the module ("Binary update-secureboot-policy not found,
    modules won't be signed"). `MODULE_SIG` isn't forced, so it loads with "module verification
    failed … tainting kernel".
  - **`/dev/zfs`** is at minor 249 in the alias, in sysfs and on the node.
  - **`zpool version`:** `zfs-2.2.2-0ubuntu9.5`, `zfs-kmod-2.2.2-0ubuntu9.5`.
  - **Not covered:** a pool, I/O, a reboot, and the rebuild that each L4T kernel release
    triggers.

## Open

- **The test that settles DKMS, per kernel, in two parts:**
  - **Build: in the image repos' CI** (rk1-armbian-minimal, jetson-orin-nano-l4t-minimal).
    - Install the release's kernel headers and `zfs-dkms` into a throwaway chroot of the built
      rootfs, then run `dkms build` for the release's kernel. Every release re-checks it, and nothing
      ships in the image.
    - Also diff the headers' `.config` against the image's `/boot/config-*` [I: the 6.1.84 oops was
      blamed on such a mismatch].
    - On the RK1 this also answers whether matching headers exist for each release.
  - **Load: on a node.** Run `modprobe zfs`, then `zpool version`, which opens `/dev/zfs`.
    - A runner runs its own kernel, so CI can't do this part [I: QEMU might boot the L4T kernel,
      which is built from Canonical's config; the RK1 vendor kernel targets Rockchip hardware].
    - Both RK1 failures on record were at this stage, after a clean build.
    - It installs packages and loads a module, so it goes through a playbook (the repo has a
      `zfs_install` role), with the owner's OK.
- **If DKMS fails on the RK1s:** the generic kernel, without RKNN/RKLLM.
- **The RK1s' `zfs-dkms 2.4.4-2arter97` candidate:** which repository serves it wasn't checked. Nor
  was whether headers for 6.1.172 are installable there now.
- **Booting Canonical's 24.04 image on the Orin Nano:** untried. Which QSPI firmware it expects
  wasn't read.
- **Update (2026-10-26):**
  - The RK1s' 2.4.4 is Armbian's (`apt.armbian.com resolute/resolute-utils`, arter97's builds), and
    it can't be installed: `zfsutils-linux 2.4.4-1arter97` Breaks every `zfs-dkms` but
    `2.4.4-1arter97`, and the repo has `2.4.4-2arter97`. Ubuntu's own `2.4.1-1ubuntu5.1` is a
    consistent pair, but its libraries aren't the candidates: with only `zfs-dkms` and
    `zfsutils-linux` pinned, apt failed the same way.
  - **Why Armbian's pair is split:**
    - `zfs-dkms` is architecture-independent (`_all.deb`), and the repo has it only at `-2`.
    - `zfsutils-linux`, `zfs-zed` and the four libraries are arm64 builds, only at `-1`. [I: the
      `-2` rebuild reached the repo only as the `all` package.]
    - `zfsutils-linux -1`'s Breaks allow no `zfs-dkms` but `-1`. Ubuntu's `zfsutils-linux` puts no
      such lock on `zfs-dkms`.
  - **Using Armbian's needs the repo to carry one revision of all of them.** Nothing on the node
    can fix it, since apt installs only versions a repo offers. The payoff over Ubuntu's would be
    the fixes in 2.4.2 to 2.4.4.
  - No apt source the RK1s use has headers for 6.1.172: apt.armbian.com's stop at 6.1.115, and
    beta.armbian.com's 6.1.172 headers are another build (git revision 85233a85, not the image's
    44bbd021). The image's own headers are in its Armbian kernel artifact, which the image neither
    installs nor publishes.
  - The CI build check is dropped. The load test ran on rk1-02, with the image artifact's headers,
    and on the Jetson (Load test, above).
- **The RK1 headers and the ZFS pin (2026-10-26):**
  - **Headers:** `INSTALL_HEADERS=yes` in rk1-armbian-minimal's `config-rk1.conf` would put the
    kernel artifact's own `linux-headers-vendor-rk35xx` in the image, for any 6.x kernel (armbian/build
    8eb7e43e, `lib/functions/rootfs/distro-agnostic.sh:380-384`). `BSPFREEZE` then holds it with the
    kernel, since it holds every artifact deb installed in the image (`:424-435`). Other families set
    it for DKMS (`config/sources/families/cix-p1.conf:16`).
  - **Its cost:** the headers' Depends put gcc and its toolchain on every RK1 [I: the image's size
    not measured].
  - **The pin** belongs with whatever installs ZFS, not in the image or in cloud-init. It's a ZFS
    choice, not hardware support, and nothing installs ZFS before Ansible runs. The RK1s' cloud-init
    also runs only once. The Jetson's apt settings are in cloud-init only because its pin has to be
    in place before the first apt upgrade (the QSPI capsule).

## Sources

- **The nodes:** read-only check, 2026-10-25, one ssh per node.
- **Canonical:**
  - `cdimage.ubuntu.com/releases/24.04/release/nvidia-tegra/`: the listing and
    `ubuntu-24.04-preinstalled-server-arm64+tegra-jetson.manifest`;
  - canonical-ubuntu-for-jetson.readthedocs-hosted.com: `how-to/build-server-image/`, `classic/`
    (release notes index), and `classic/release-note-noble-thor-ga/` (via a search engine's copy).
- **Ubuntu kernel sources** (git.launchpad.net):
  - `~canonical-kernel/ubuntu/+source/linux-nvidia-tegra/+git/noble`: `debian.nvidia-tegra/dkms-versions`
    and `debian.nvidia-tegra/rules.d/arm64.mk`;
  - `~ubuntu-kernel/ubuntu/+source/linux/+git/noble`: `debian.master/dkms-versions`, the control.
- **Ubuntu archive** (ports.ubuntu.com):
  - noble, noble-updates, noble-security and noble-proposed `Packages.xz` for arm64;
  - file lists of `linux-modules-6.8.0-1036-nvidia-tegra`, `linux-modules-extra-6.8.0-1036-nvidia-tegra`,
    `linux-modules-tegra-oot-jetson-6.8.0-1036-nvidia-tegra` and
    `linux-modules-tegra-igpu-openrm-jetson-6.8.0-1036-nvidia-tegra`;
  - resolute and resolute-updates `main` arm64 `Packages.xz`.
- **NVIDIA:** `nvidia-l4t-kernel-headers_6.8.12-tegra-39.2.1-20260806224157_arm64.deb` from
  `repo.download.nvidia.com/jetson/som` (its `.config`); NVIDIA forum topic 269858 (JetPack 5.1.1,
  zfs-dkms).
- **Armbian:**
  - the forum, read 2026-10-25: topics 30555 ("Fail to build zfs dkms module"), 49378 (the 6.1.84
    oops) and 57323 ("zfs : Failed to initialize the libzfs library");
  - armbian/build `config/kernel/linux-rk35xx-vendor.config` at main (894f10be9, 2026-10-19).
- **Longhorn 1.14.0:** `nodes/multidisk.md`, read 2026-10-09.
- **This directory:** [node-storage.md](node-storage.md), [orin-nano-install.md](orin-nano-install.md),
  [os-alternatives.md](os-alternatives.md), [kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md),
  [rk1-os-releases.md](rk1-os-releases.md), [rk1-gpu-npu.md](rk1-gpu-npu.md),
  [orin-nano-qspi-updates.md](orin-nano-qspi-updates.md) and [README.md](README.md).
