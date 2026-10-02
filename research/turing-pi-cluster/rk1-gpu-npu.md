# Turing RK1: GPU and NPU on Ubuntu 26.04 and Armbian

Researched 2026-10-01. **[I]** marks inference; **U** means unverified. Nothing here was run on an RK1. Every step is read from source, packages and docs.

This closes the open items in [rk1-os-releases.md](rk1-os-releases.md).

## Bottom line

- **No single OS gets the whole GPU and the whole NPU.** The NPU decides it:
  - **Rockchip's RKNN and RKLLM** (fast NPU, LLMs, any model RKNN converts) need the vendor kernel. That means **Armbian vendor 6.1.172**.
  - **The open stack** (panthor + Mesa for the GPU, rocket + Mesa Teflon for the NPU) runs on **Ubuntu 26.04's stock kernel**.
    - It also needs Mesa ≥ 26.2.0. Ubuntu itself ships 26.0.8, which crashes the NPU, so the newer Mesa comes from a PPA.
- **The GPU is good either way.** Ubuntu gives Vulkan 1.4 and OpenCL 3.0. Armbian's default libmali gives OpenCL 3.0, Vulkan 1.3 and GLES 3.2.
- **Booting Ubuntu's kernel on the RK1 works in principle.** U-Boot v2026.07 on eMMC chains through shim and GRUB to Ubuntu on NVMe. Each link checks out in source, but nobody has reported the whole chain end to end.
  - Its device tree is Linux v7.0's RK1 tree, so the GPU, NPU and thermal nodes are there.
  - The steps that need care are the serial console and making U-Boot skip the eMMC.

## Comparison

| | Ubuntu 26.04, generic 7.0.0-38 | Armbian vendor 6.1.172, kbase (default) | Armbian vendor, `panthor-gpu` overlay | Armbian edge 7.2, self-built |
|---|---|---|---|---|
| GPU kernel driver | panthor | Mali kbase g29p1-11eac0 | panthor (uAPI 1.5) | panthor |
| GPU userspace | Mesa 26.0.8 (Ubuntu) or 26.2.3 (kisak PPA) | libmali, which you install | Mesa: 26.0.8 on Ubuntu 26.04, 25.0.7 on Debian 13 | Mesa from the distro |
| GLES / GL | 3.1 / 3.1 | GLES 3.2 | 3.1 / 3.1 | 3.1 / 3.1 |
| Vulkan | 1.4 (PanVK) | 1.3 (ICD `api_version` 1.3.276) | 1.4 on Ubuntu 26.04; 1.1 on Debian 13 | 1.4 on Ubuntu 26.04 |
| OpenCL | 3.0 (Rusticl; set `RUSTICL_ENABLE=panfrost` on 26.0.x) | 3.0 (libmali) | Rusticl on Ubuntu 26.04 [I]; U on Debian 13 | as Ubuntu [I] |
| NPU | rocket + Teflon: TFLite only, conv and add only, 200 MHz | **RKNN 2.3.2, RKLLM 1.3.1** | same as kbase | rocket + Teflon, Ubuntu 26.04 userspace only, with the same Mesa ≥ 26.2 requirement |
| Video decode | V4L2 stateless via GStreamer 1.28.2: H.264, HEVC (one core), AV1, VP8, MPEG-2. No VP9, no FFmpeg | MPP: H.264, HEVC, VP9, AV1, 10-bit, 8K (hardware-support.md), via `jellyfin-ffmpeg8` | same | mainline-level [I] |
| Video encode | JPEG only | H.264 / HEVC (MPP) | same | JPEG only |
| HDMI | N (DT disables it) | Y | Y [I] | N (no hdmi/vop nodes in the RK1 DT) |
| Kernel updates | Canonical | Armbian "Community"; 6.1.172 against upstream 6.1.188; 6.1 EOL Dec 2027 | same | you rebuild |
| Boot | U-Boot EFI → shim → GRUB, assembled by hand (below) | Armbian image, `boot.scr` | same | same |

The two Armbian vendor columns are exclusive: the `panthor-gpu` overlay disables the kbase GPU node.

## Ubuntu 26.04 on the generic kernel

### Hardware gaps

1. **GPU firmware: closed.**
   - `linux-firmware-misc` ships `usr/lib/firmware/arm/mali/arch10.8/mali_csffw.bin.zst`, a symlink to `../arch10.10/mali_csffw.bin.zst`. This holds for 20260319.git217ca6e4-0ubuntu2 (resolute) and -0ubuntu2.2 (resolute-updates).
   - panthor requests that path (`panthor_fw.c` v7.0 `MODULE_FIRMWARE("arm/mali/arch10.8/mali_csffw.bin")`), and the kernel loads `.zst` (`FW_LOADER_COMPRESS_ZSTD=y`).
   - `linux-image-generic` Depends on `linux-firmware`, which Depends on `linux-firmware-misc`.
   - Trap: `linux-firmware-minimal` also Provides `linux-firmware` but only *Recommends* -misc. An install with `--no-install-recommends` that picks -minimal has no GPU firmware.
2. **Mesa, for the NPU: Ubuntu's own Mesa can't be used.**
   - The mmap-leak fix is upstream commit 75d5cded5a58 (MR 41887, 2026-07-04). It is backported to 26.1.5 as ed6ccee15b84.
   - The 26.0 branch ended at 26.0.8 (2026-05-27) without it. Ubuntu's 26.0.8-1ubuntu0.3 carries five patches, none for rocket.
   - Rocket correctness fixes landed only in 26.2.0:
     - 8aeac023473b: "For a conv whose input channel count is not a multiple of 16 (e.g. MobileNetV2's 24-channel blocks) the weight stride misaligned and corrupted every output channel".
     - 72fd7032fbcd: "MobileNetV2 produced noise".
     - 831b9b32ee49.
   - Mesa's Teflon doc still calls MobileNetV2 "Fully supported" at every version, which contradicts those commits.
   - The only source of Mesa ≥ 26.2 for resolute arm64 is **`ppa:kisak/kisak-mesa`**: 26.2.3~kisak1~r, built 2026-09-18, with rocket, Teflon, PanVK and Rusticl. The PPA says "Resolute (26.04) - Preliminary support (Not tested locally)" and "ARM builds are not tested locally".
   - `ppa:kisak/turtle` (26.1.8) has the crash fix but not the 26.2 correctness fixes.
   - Ubuntu 26.10 has 26.2.3-1ubuntu1. Nothing newer is queued for 26.04: no proposed, backports or upload-queue entries.
3. **What the NPU runs under rocket.** The limits are the same in 26.0.8 and 26.2.4:
   - Only CONVOLUTION (per-tensor quantisation, no dilation) and ADD go to the NPU. Everything else runs on the CPU (`rkt_ml.c`).
   - The ops added to Teflon in 26.2.0 (MUL, TANH, HARD_SWISH and others) are frontend-only, and rocket rejects them.
   - Upstream runs the NPU at a fixed 200 MHz. Raising it to 600 MHz needs out-of-tree patches (gregordinary/tflite-rocket README; techveda.live 2026-08-19).
   - Rocket splits an op's tasks across cores. Whether they actually run in parallel is U: all jobs share one output buffer.
4. **Teflon runtime.**
   - Ubuntu 26.04's Python is 3.14. `tflite-runtime` stops at cp311. **`ai-edge-litert` 2.2.0** has a `cp314 manylinux_2_27_aarch64` wheel and `load_delegate()`.
   - The delegate is `/usr/lib/teflon/libteflon.so` (package `mesa-teflon-delegate`, universe). Use it with `load_delegate("/usr/lib/teflon/libteflon.so")` [I]. Mesa's own example assumes Python 3.10 and tflite-runtime 2.13, and Ubuntu has neither.
   - That ai-edge-litert and libteflon work together is U. `libteflon.so` has no undefined TfLite symbols, so it should [I].
5. **GPU APIs.**
   - Mesa's G610 row: GLES 3.1, GL 3.1, Vulkan 1.4. PanVK is in Ubuntu's `mesa-vulkan-drivers`.
   - OpenCL: `mesa-opencl-icd` contains Rusticl with panfrost. On 26.0.x it needs `RUSTICL_ENABLE=panfrost`; 26.2.0 enables it by default.
   - Khronos lists Rusticl on Mali-G610 as OpenCL 3.0 conformant (submission 474, 2026-07-29, "26.2.0-devel", kernel 7.0).
6. **Video.**
   - GStreamer 1.28.2's `v4l2codecs` (`gstreamer1.0-plugins-bad`) drives:
     - rkvdec: H.264 and HEVC. v7.0 uses one of the two cores: "missing multi-core support, ignoring this instance".
     - Hantro: H.264, MPEG-2, VP8.
     - AV1.
   - No VP9. FFmpeg 8.0.1 has no v4l2-request.
7. **Kernel-side items not in 7.0.0-38** (by its changelog):
   - Rocket fixes 70e6a33d68a9, a85402bff218 and 9b2dedadf6a9 (July 2026; NULL deref and overflow in `rocket_job_push`).
   - Panthor firmware-parsing CVE-2026-80577 and CVE-2026-74452 (fixed in 7.1.10/6.18.46 and 7.1.8/6.18.44). These need a malicious firmware file [I].
8. **Open Mesa issues on RK3588:**
   - #15721: panfrost intermittent performance.
   - #15226: `drmPrimeHandleToFD() failed (err=-22)`.
   - #15703: PanVK WSI "Failed to find a supported modifier".
   - LP #2153548: gnome-remote-desktop black screen with panthor on 26.04.
   - #16278 (PanVK device loss with overlapping submissions) is closed. Which commit fixed it is U.

### How it boots

**What's on the RK1:**
- **No SPI flash.**
  - Turing's spec lists "32 G eMMC 5.1, SD 3.0". The U-Boot defconfig has `# CONFIG_SPI_FLASH is not set`. The SFC node is disabled in the DT.
  - The RK3588 BootROM tries SPI NOR, then eMMC, then SD. **U-Boot must live on eMMC**: `u-boot-rockchip.bin` at 32 KiB (sector 64), with `u-boot.itb` at sector 16384.
- **The kernel image is a stubble PE, not a bare zboot.** This corrects rk1-os-releases.md.
  - `vmlinuz-7.0.0-38-generic` is Canonical's stubble (a systemd-stub fork, SBAT `stubble,9`). It wraps the zboot kernel in `.linux` and carries 32 `.dtbauto` DTBs, all Qualcomm laptops. No section mentions turing or rk3588.
  - When a firmware DT exists and no `.dtbauto` matches, stubble does nothing (`stubble` v9 `pe.c`: "Do nothing if a firmware dtb exists").
  - So on the RK1 the kernel runs on whatever DT U-Boot or GRUB installed.
- **Mainline U-Boot v2026.07, `turing-rk1-rk3588_defconfig`.** Resolved with U-Boot's own kconfiglib:
  - On: `EFI_LOADER`, `EFI_BOOTMGR`, `BOOTSTD_FULL`, `BOOTMETH_EFILOADER`, `BOOTMETH_EFI_BOOTMGR`, extlinux, script, NVMe + `PCIE_DW_ROCKCHIP` + `PHY_ROCKCHIP_SNPS_PCIE3`, `USB_STORAGE`, `EFI_DT_FIXUP`, `EFI_LOAD_FILE2_INITRD`, `ENV_IS_NOWHERE`.
  - `bootcmd` is `bootflow scan -lb`.
  - Off: Secure Boot, TPM, `EFI_RT_VOLATILE_STORE`.
  - **Its built-in DT is Linux v7.0's RK1 DT, byte-identical** (dts/upstream "Subtree merge tag 'v7.0-dts'", 5d401bfbdf1d). It has the GPU, `rknn_core_0..2` "okay", tsadc and thermal zones, and `stdout-path = "serial9:115200n8"`.
- **Boot order is eMMC first.** `boot_targets` = `"mmc1 mmc0 nvme scsi usb pxe dhcp spi"` (`include/configs/rockchip-common.h:17`).
  - Anything bootable on eMMC wins over NVMe.
  - The env can't be saved (`ENV_IS_NOWHERE`).
  - Armbian dropped its NVMe-first patch in 61f623201.
- **How U-Boot finds and starts Ubuntu:**
  - `bootmeth_efi` looks for `/EFI/BOOT/BOOTAA64.EFI` on each bootdev's bootable partitions. In GPT, "bootable" means the ESP type GUID or the legacy-bootable attribute.
  - DT: it tries `/dtb/$fdtfile`, `/$fdtfile`, `/dtb/current/$fdtfile` and `/dtbs/$fdtfile` on that partition (`lib/efi_loader/efi_fdt.c`), with `fdtfile=rockchip/rk3588-turing-rk1.dtb`. Otherwise it falls back to its built-in DT (`bootmeth_efi.c` `BOOTFLOWF_USE_BUILTIN_FDT`).
  - extlinux/`booti` can't load Ubuntu's PE image ("Bad Linux ARM64 Image magic!", `arch/arm/lib/image.c`). Only the EFI path works.
- **GRUB and device trees (grub2 2.14-2ubuntu2.1).**
  - Ubuntu's `ubuntu-add-devicetree-command-support.patch` makes `10_linux` emit `devicetree` when `/boot/dtb-<ver>`, `/boot/dtb-<alt>` or `/boot/dtb` exists. There is no `GRUB_DEFAULT_DTB`.
  - That code sits in the `else` of the `GRUB_FORCE_PARTUUID` branch. The ubuntu-cpc image hooks in livecd-rootfs (`disk-image.binary`, `disk-image-uefi.binary`, `disk-image-uefi-non-cloud.binary`) set `GRUB_FORCE_PARTUUID` only for `SUBPROJECT=minimized`, and those images never get a `devicetree` line.
  - `flash-kernel` 3.110ubuntu2.3 would create `/boot/dtb-<ver>`, but its `all.db` has no Turing entry. The only RK3588 entry is "MNT Reform 2 with RCORE RK3588 Module".
  - GRUB's `devicetree` is blocked only under Secure Boot lockdown, which U-Boot doesn't enable.
- **UEFI variables are read-only at runtime.** Without `EFI_RT_VOLATILE_STORE`, Linux mounts efivarfs read-only.
  - Ubuntu's grub-install only warns in that case (`efivar-check-that-efivarfs-is-writeable`, LP #1965288).
  - grub-install also maintains the removable path `EFI/BOOT/BOOTAA64.EFI` (shim + `fbaa64.efi`).
  - shim's fallback rewrites the boot entries into U-Boot's `ubootefi.var` on the ESP at every boot [I]. With no TPM it continues to `shimaa64.efi` instead of resetting.
- **Ubuntu ships no U-Boot for the RK1.** `u-boot-rockchip` 2025.10-0ubuntu2 builds only rk3399 and rk3328 targets.
- **The images** (26.04.1):

  | Image | ESP | Login | Notes |
  |---|---|---|---|
  | `ubuntu-26.04.1-preinstalled-server-arm64.img.xz` | p15, LBA 2048–204800 | built-in NoCloud seed `ubuntu`/`ubuntu`, password change forced | has shim, GRUB, flash-kernel, linux-generic |
  | `resolute-server-cloudimg-arm64.img` | p15, same range | none without a NoCloud seed | qcow2: needs `qemu-img convert -O raw` |
  | `ubuntu-26.04.1-live-server-arm64.iso` | appended ESP with shim and GRUB | installer | needs a USB host port the RK1's U-Boot can use (below) |

  - Both disk images put the ESP over sector 16384, where `u-boot.itb` sits. Neither can be written to the eMMC that holds U-Boot. **The Ubuntu root goes on NVMe.**
- **Serial console.**
  - The RK1 console is uart9 (`serial@febc0000`). Ubuntu's kernel has `SERIAL_8250_RUNTIME_UARTS=32`, so it becomes **`ttyS9`, 115200**.
    - Armbian current and edge have 8 runtime UARTs, which is why they call it `ttyS0`.
    - This explains the split in Armbian's `turing-rk1.csc`.
  - The ubuntu-cpc hook `999-cpc-fixes.chroot` hard-codes `console=tty1 console=ttyAMA0` on arm64 ("QEMU virt machine provides AMBA PrimeCell UART"). That UART doesn't exist on the RK3588.
    - The cloud image has it. Whether the preinstalled image runs that hook is [I].
- **Why JohanElmis's migration saw no thermal zones.**
  - ubuntu-rockchip's U-Boot for the RK1 (`u-boot-turing-rk3588` 2024.01-4, upstream cb493752) has a DT with no `thermal-zones`, no GPU, no VOP and no NPU nodes. Positive control: `uart9` is found.
  - JohanElmis's GRUB (`grub-mkstandalone`, no `fdt` module) loads no DTB, so the kernel ran on that DT.
  - The same setup would have no GPU or NPU either. With U-Boot v2026.07 the built-in DT is v7.0's, and this doesn't apply.

**Procedure.** Every link is checked in source, and the whole chain is [I]. Per AGENTS.md, steps 2–4 belong in a committed script that finds the eMMC and NVMe by serial, not by `mmcblkN`/`nvmeN`, before they run on a node.

1. **Put U-Boot v2026.07 on eMMC.** Take it from an Armbian turing-rk1 image, which also carries Armbian's PCIe link-retry patch, and `tpi flash` that image to the node. Armbian then runs from eMMC as a staging OS.
2. **From the staging OS, write the preinstalled image to NVMe:** `xzcat ubuntu-26.04.1-preinstalled-server-arm64.img.xz | dd of=<nvme> bs=4M`.
3. **Fix the console before first boot.** In the NVMe image's `grub.cfg` and `/etc/default/grub.d/50-cloudimg-settings.cfg`, replace `console=ttyAMA0` with `console=ttyS9,115200` if it's there. Without this, the serial console is silent [I].
4. **Make the eMMC unbootable while keeping U-Boot.** Zero the eMMC's primary GPT (LBA 0–33) and its backup GPT (last 33 LBAs); U-Boot falls back to the backup if only the primary is wiped. The bootloader at sector 64 onward stays.
   - Without this step, U-Boot boots Armbian from eMMC every time, because eMMC comes first in `boot_targets`.
   - Wiping both GPTs is what disables the staging Armbian. Re-flashing the eMMC with `tpi flash` brings it back.
   - The alternative is rebuilding U-Boot with NVMe first.
5. **Expected first-boot chain:**
   1. U-Boot finds the NVMe ESP (bootable) and starts `BOOTAA64.EFI` (shim).
   2. shim runs `fbaa64.efi`, which writes the boot entry and continues to `shimaa64.efi`, then GRUB.
   3. GRUB starts the stubble `vmlinuz`; no `.dtbauto` matches.
   4. The kernel runs on U-Boot's v7.0 RK1 DT.
6. **Install the userspace:**
   - `add-apt-repository ppa:kisak/kisak-mesa`, then the upgrade to 26.2.3.
   - `mesa-teflon-delegate`.
   - `ai-edge-litert` 2.2.0 in a venv.
   - `mesa-opencl-icd` + `clinfo` for OpenCL; `RUSTICL_ENABLE=panfrost` isn't needed on 26.2.
7. **Pin the DT to the kernel. This is needed once the kernel moves past 7.0.**
   - Today U-Boot's DT equals the kernel's, so skipping this changes nothing on 7.0.0-x. A later HWE kernel would run on v7.0's DT, missing any newer RK1 nodes.
   - Fix: an `/etc/flash-kernel/db` stanza (`Machine: Turing Machines RK1`, `DTB-Id: rockchip/rk3588-turing-rk1.dtb`). flash-kernel then writes `/boot/dtb-<ver>` on every kernel install, and GRUB emits `devicetree` [I]. flash-kernel reads `/etc/flash-kernel/db` first, matches `Machine:` against `/proc/device-tree/model`, and finds DTBs in `/lib/firmware/<kver>/device-tree`. The RK1 DTB's model is "Turing Machines RK1".
   - The alternative is copying the DTB to `ESP:/dtb/rockchip/` and keeping it in sync by hand.

**Other routes:**
- **Live-server ISO from USB.**
  - The RK1's USB0 is OTG, and U-Boot binds it as a gadget.
  - USB1 (USB 3) and USB2 are host ports. Turing's v2.5 USB-A port is "connected to the USB2 interface … of Node 1" [I: that it maps to the RK1's host-only USB2]. Node 4 has 4× USB 3.0 through a VL805.
  - Whether v2026.07 needs the USB host patch Bennett used in 2024 is U.
- **NVMe written on another machine** through a USB-NVMe enclosure, which skips the staging OS. Step 4 is still needed if the eMMC holds anything bootable [I].
- **Netboot** (`ubuntu-26.04.1-netboot-arm64.tar.gz` + U-Boot EFI PXE): not explored.

## Armbian

**Traps when reading Armbian's source:**
- **Family.** The RK1 is `BOARDFAMILY="rockchip-rk3588"`, so the family file is `rockchip-rk3588.conf`, not `rk35xx.conf`. Both pick the same vendor kernel (`rk-6.1-rkr7.2`, `LINUXFAMILY=rk35xx`, kernel config `linux-rk35xx-vendor.config`). The overlay prefix is `rockchip-rk3588`.
- **kbase directory.** The vendor kbase is `CONFIG_MALI_VALHALL=y` (`drivers/gpu/arm/valhall`). The `bifrost` directory in the same tree isn't built.
- **mesa-vpu.** `extensions/mesa-vpu.sh` was deleted on 2026-05-09 (27c66834326e) and folded into armbian-config (configng `module_desktops.sh`). Armbian's docs still show `ENABLE_EXTENSIONS=mesa-vpu`.

**GPU on vendor 6.1.172: two exclusive paths.**
- **Path A: kbase + libmali.** This is the default and gives the most API coverage.
  - The kernel side: built-in kbase g29p1-11eac0 with the CSF firmware compiled in (`MALI_CSF_INCLUDE_FW` default y), and the RK1 DT enables `&gpu`.
  - Userspace isn't installed. The deb for G610 is `libmali-valhall-g610-g24p0-gbm` from tsukumijima/libmali-rockchip. The latest release is v1.9-1-20260923-ec78b74; Jellyfin's doc names v1.9-1-2131373 for "6.1 LTS kernel on … Armbian".
  - It gives GLES 3.2, OpenCL 3.0 and a Vulkan 1.3 ICD.
  - A g29p1 libmali that matches the kernel is now packaged: ginkage/libmali-rockchip v1.10-1-db9112f (2026-09-26; its release was replaced by v1.10-1-e96672b on 2026-10-01, a hook-only change), whose blobs are git-SHA-identical to Rockchip's JeffyCN/mirrors `libmali-next` bf621d15 ([rk1-custom-image.md](rk1-custom-image.md)). kbase negotiates down to the older userspace's version at the handshake. Whether g24p0 works correctly on g29p1 is U.
  - `MALI_VALHALL_DEBUG=y` is set, which builds a debug kbase [I: performance cost].
- **Path B: panthor + Mesa.**
  - Enable it with `overlays=panthor-gpu` in `/boot/armbianEnv.txt`, or `armbian-config --api module_devicetree_overlays install overlays=panthor-gpu`.
  - The overlay disables `&gpu` and enables `&gpu_panthor`. `armbian-firmware` ships `arm/mali/arch10.8/mali_csffw.bin`.
  - Mesa comes from the distro: 26.0.8 on Ubuntu 26.04 (Vulkan 1.4, Rusticl [I]); 25.0.7 on Debian 13 (Vulkan 1.1), with 26.1.6 in trixie-backports.
- **Desktop images.** configng's mid tier installs distro Mesa and is coded to add `panthor-gpu` on vendor. Whether the published RK1 desktop images actually carry the overlay is U: the rootfs cache is built per release, desktop and tier, before the board package exists [I].
- **No GPU or MPP packages exist for Ubuntu 26.04 or Debian 13 beyond the distro's own.** Armbian's repo has none. The Rockchip PPAs (`liujianfeng1994/rockchip-multimedia`, `panfork-mesa`; `jjriek/*`) stop at noble.

**NPU on vendor: full Rockchip stack.**
- **Driver:** rknpu **0.9.8** (`DRIVER_DATE "20240828"`), built in.
  - The RK1 DT enables `&rknpu` and `&rknpu_mmu`.
  - It registers a DRM render device named `rknpu` (DRM GEM mode). There is no `/dev/rknpu`.
  - `librknnrt` scans `/dev/dri`.
- **RKNN:** airockchip/rknn-toolkit2 **v2.3.2** (2025-04-09; the latest release).
  - `librknnrt` 2.3.2 needs driver ≥ 0.9.2 ("It is recommended that RKNPU2 driver version >= 0.9.2").
  - `rknn-toolkit-lite2` 2.3.2 has aarch64 wheels for **cp37–cp312 only**. Debian 13 ships Python 3.13 and Ubuntu 26.04 ships 3.14, so use a non-distro Python 3.12 (uv, pyenv). glibc isn't a problem.
- **RKLLM:** airockchip/rknn-llm **release-v1.3.1** (2026-09-29).
  - It needs "the NPU kernel on the board is version v0.9.8", which this kernel meets.
  - The on-board runtime `librkllmrt.so` is a C library.
  - Model conversion runs on an x86_64 PC, Python 3.10–3.12.
  - Rockchip's version check reads `/sys/kernel/debug/rknpu/version`; `dmesg | grep -i rknpu` works without debugfs.
- Armbian doesn't package librknnrt. Copy it from rknn-toolkit2's `rknpu2/runtime/Linux/librknn_api/aarch64/`.

**Video on vendor.** The kernel has the MPP service, all codecs and RGA. Userspace for Ubuntu 26.04 and Debian 13 is **`jellyfin-ffmpeg8` 8.1.3-1** from repo.jellyfin.org, which bundles MPP and RGA. HDR tone-mapping needs OpenCL from libmali: Path A.

**Install.**
1. `tpi flash -n <N> -l -i /mnt/sdcard/images/<image>.img` writes eMMC. The path must be absolute and on the BMC's microSD. Armbian ships `.img.xz`, so decompress it first [I]. Expect "about 8 minutes for each 1 GB".
2. From eMMC, run `armbian-install --target /dev/nvme0n1 --boot sd --fs ext4 --yes`. `/boot` stays on eMMC and root moves to NVMe (`rootdev=` rewritten). `armbian-install` is now a shim to `armbian-config --api module_partitioner`. Not run.
3. U-Boot is v2026.07 on every Armbian RK1 branch, including vendor, with eMMC first. That's fine here, because `/boot` stays on eMMC.

**Known RK1 items:**
- Armbian PR #10216 (U-Boot v2024.04 → v2026.07, "Worth a boot test on eMMC + NVMe").
- PR #10543 ("boot again with the CPU clusters parked on the 24 MHz oscillator", merged 2026-08-28).
- PR #10514 (fan curve on mainline kernels, merged 2026-08-24).
- linux-rockchip #547 (stmmac dead after suspend; suspend only).
- Edge 6.17 had no display ("No available vop found"). Forum 55751, Oct 2025.
- The Turing forum returned HTTP 429 throughout.

**Maintenance.**
- `rk-6.1-rkr7.2` had 825 commits since 2026-07-03, mostly LTS merges. Its head was 44bbd021d780 on 2026-09-30.
- It's at 6.1.172 against upstream 6.1.188. 6.1 is EOL in Dec 2027.
- The board is still "Community" with no maintainer.

**Mainline Armbian (edge 7.2).**
- `DRM_PANTHOR=m` and `DRM_ACCEL_ROCKET=m` in current and edge.
- The RK1 NPU nodes are upstream from v7.0 (5360ad495b7b), so edge needs no patch. Current 6.18 uses `rk3588-1202-arm64-dts-rockchip-Enable-the-NPU-on-Turing-RK1.patch`.
- Build: `./compile.sh build BOARD=turing-rk1 BRANCH=edge RELEASE=resolute BUILD_DESKTOP=no BUILD_MINIMAL=no KERNEL_CONFIGURE=no` (not run).
- It gets the same open stack as Ubuntu, under Armbian's boot. Rocket userspace needs Ubuntu 26.04: Debian 13's Mesa 25.0.7 has no rocket.

## Open

- An end-to-end boot of Ubuntu 26.04 on U-Boot v2026.07 on an RK1: nobody has reported one. Bennett (Hackaday, 2024-12-09) booted Ubuntu 24.10, Fedora 41 and Tumbleweed installers through UEFI on an RK1 with U-Boot 2024.10 plus DTB and USB patches.
- libmali g24p0 on kbase g29p1.
- Whether rocket actually runs on 3 cores in parallel.
- Whether the preinstalled image carries `console=ttyAMA0`.
- Whether Armbian's RK1 desktop images carry the `panthor-gpu` overlay.
- Which U-Boot USB host ports work for booting the live ISO.
- The Turing forum.

## Sources

Downloaded copies are in the gitignored `tasks/2026-10-01-rk1-artifacts/`. The line references are to the files at the versions named.

- **Ubuntu packages** (ports.ubuntu.com, resolute / resolute-updates):
  - `Contents-arm64`, `Packages` and `Sources` indexes
  - `linux-firmware-misc`, `linux-firmware`, `linux-firmware-minimal` 20260319.git217ca6e4
  - `linux-image-7.0.0-38-generic` 7.0.0-38.38 (PE section dump), with its changelog
  - mesa 26.0.8-1ubuntu0.3 debian tarball (`patches/series`, `rules`)
  - `mesa-teflon-delegate`, `mesa-opencl-icd` 26.0.8-1ubuntu0.3
  - grub2 2.14-2ubuntu2.1 (patched `10_linux.in`), flash-kernel 3.110ubuntu2.3 (`functions`, `db/all.db`)
  - `u-boot-rockchip` 2025.10-0ubuntu2
  - livecd-rootfs 26.04.35 (`live-build/functions`, `ubuntu-cpc/hooks.d/`)
  - 26.04.1 image manifests and partition tables
- **Mesa** (gitlab.freedesktop.org/mesa/mesa):
  - MR 41887 and commits 75d5cded5a58, ed6ccee15b84, 8aeac023473b, 72fd7032fbcd, 831b9b32ee49
  - `rkt_device.c` and `rkt_ml.c` at 26.0.8, 26.1.5 and 26.2.4
  - `docs/teflon.rst`, `docs/drivers/panfrost.rst`, `features.txt`, relnotes 26.0.x–26.2.4
  - Issues #14963, #15226, #15703, #15721, #16278
- **PPAs:** Launchpad `~kisak/kisak-mesa` build 33606480 and debian/rules; `~kisak/turtle`; oibaf, jjriek and liujianfeng1994 PPA series lists.
- **Khronos:** [OpenCL conformant products](https://www.khronos.org/conformance/adopters/conformant-products/opencl), submission 474.
- **PyPI:** `ai-edge-litert` 2.2.0, `tflite-runtime`, `rknn-toolkit-lite2` 2.3.2.
- **Linux v7.0:** `drivers/gpu/drm/panthor/panthor_fw.c`; `drivers/media/platform/rockchip/rkvdec/rkvdec.c`; `drivers/media/platform/verisilicon/rockchip_vpu_hw.c`; `drivers/tty/serial/8250/`; `arch/arm64/boot/dts/rockchip/rk3588-turing-rk1.dtsi`.
- **U-Boot v2026.07** (commit ece349ade297):
  - `configs/turing-rk1-rk3588_defconfig`, `include/configs/rockchip-common.h`, `rk3588_common.h`
  - `boot/bootmeth_efi.c`, `lib/efi_loader/efi_fdt.c`, `efi_helper.c`, `efi_runtime.c`, `arch/arm/lib/image.c`
  - `dts/upstream/` (5d401bfbdf1d)
  - `doc/usage/cmd/bootefi.rst`, `doc/develop/uefi/uefi.rst`
- **stubble** v9 (github.com/ubuntu/stubble): `pe.c`, `README.md`.
- **shim** 15.8 `fallback.c`.
- **Armbian:**
  - armbian/build d9fb61be0c48: `config/boards/turing-rk1.csc`, `config/sources/families/rockchip-rk3588.conf`, `config/kernel/linux-rk35xx-vendor.config`, `linux-rockchip64-{current,edge}.config`, `config/bootscripts/boot-rk35xx.cmd`, `patch/kernel/archive/rockchip64-6.18/rk3588-1202-…`, PRs #10216, #10514, #10543
  - armbian/linux-rockchip `rk-6.1-rkr7.2` 44bbd021d780: `drivers/gpu/arm/valhall/`, `drivers/rknpu/`, `arch/arm64/boot/dts/rockchip/{rk3588s.dtsi,rk3588-turing-rk1.dtsi,overlay/rockchip-rk3588-panthor-gpu.dts}`, issue #547
  - armbian/firmware 2a9e1c194604
  - armbian/configng 11d2130d9e41: `module_desktops.sh`, `module_devicetree_overlays.sh`, `module_partitioner.sh`
  - forum.armbian.com threads 55751 and 61638
- **Rockchip:**
  - airockchip/rknn-toolkit2 v2.3.2: `01_Quick_Start_RKNN_SDK_V2.3.2_EN.pdf`, `librknnrt.so`
  - airockchip/rknn-llm release-v1.3.1: `Rockchip_RKLLM_SDK_EN_1.3.1.pdf`, README
  - tsukumijima/libmali-rockchip releases; JeffyCN/mirrors `libmali`, `libmali-next`
- **Jellyfin:** jellyfin.org docs `rockchip.md` (85e9359); repo.jellyfin.org Packages for trixie and resolute.
- **Turing:** [RK1 flashing](https://docs.turingpi.com/docs/turing-rk1-flashing-os), RK1 specs, v2.5 changelog, `tpi` v1.0.7 `cli.rs`.
- **Community:**
  - [JohanElmis/turing-rk1-mainline-kernel](https://github.com/JohanElmis/turing-rk1-mainline-kernel) at 7b7db25b
  - Joshua-Riek/ubuntu-rockchip v2.4.0 `config/boards/turing-rk1.sh`, plus the u-boot-turing-rk3588 packaging and its U-Boot cb493752 DT
  - [Hackaday, "Finally Putting The RK1 Through Its Paces"](https://hackaday.com/2024/12/09/finally-putting-the-rk1-through-its-paces/)
  - gregordinary/tflite-rocket README
  - techveda.live, 2026-08-19
