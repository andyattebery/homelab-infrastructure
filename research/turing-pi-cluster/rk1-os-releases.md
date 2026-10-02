# Turing RK1: OS releases as of 2026-10-01

Researched 2026-10-01. **[I]** marks inference; **U** means unverified. This follows up the RK1 parts of [hardware-support.md](hardware-support.md) and [os-alternatives.md](os-alternatives.md), both from 2026-09-26.

**Bottom line.**
- **Turing has released nothing new.** Its firmware server still offers only the Ubuntu 22.04 / BSP 5.10 image from Feb 2024.
- **The current packaged release is Armbian's:** Ubuntu 26.04 and Debian 13 images on vendor kernel 6.1.172, built 2026-09-29. The board is still "Community", with no maintainer.
  - The kernel is not new since 2026-09-26: the move to 6.1.172 landed on 2026-09-04. What the earlier research didn't record is the distro set.
- **New since 2026-09-26:** Ubuntu 26.04's own generic kernel (7.0.0-38) ships the RK1 device tree with the GPU, all three NPU cores and both rkvdec decoders enabled. Its config builds panthor, rocket and rkvdec, plus `iscsi_tcp` for Longhorn.
  - It is an EFI (PE) image, so it can't boot through extlinux. One community repo boots it through GRUB.
  - Follow-up, with how to boot it and get the GPU and NPU working on Ubuntu and Armbian: [rk1-gpu-npu.md](rk1-gpu-npu.md).

## What exists

| Release | Distro | Kernel | Who, status | Latest | Source |
|---|---|---|---|---|---|
| Turing official | Ubuntu 22.04 server/desktop, plus an "Experimental … Mainline Kernel" 22.04 | BSP 5.10 (the experimental image: mainline) | `ubuntu_22.04_rockchip_linux/`, last modified 2024-02-16; `talos/` 2024-01-24. Nothing newer on the server. Turing's own 2026 guides still use it: the setup guide (2026-04-15, "tested specifically on Ubuntu 22.04 Server ARM64") and the Jellyfin guide (2026-07-04, "Rockchip 5.10.160 BSP kernel") | 2024-02-16 | TF, TD, TG |
| ubuntu-rockchip (Joshua-Riek) | Ubuntu 22.04 / 24.04 | 5.10 / 6.1 | archived | v2.4.0, 2024-10-23 | UR |
| **Armbian `turing-rk1`** | Ubuntu 26.04 Gnome (1008 MB), Ubuntu 26.04 KDE Plasma (1.3 GB), Debian 13 minimal CLI (308 MB) | vendor 6.1.172 (`rk-6.1-rkr7.2`) | "Community", rolling, `BOARD_MAINTAINER=""` | 2026-09-29 | AW, AB, AF |
| kurochan/turing-rk1-ubuntu-image | Ubuntu 26.04 minimal | vendor 6.1.115 (`rk-6.1-rkr5.1`) | one person, 2 stars, created 2026-05-25. Builds stock Armbian with no patches of its own, and attests them (`gh attestation verify`) | 2026-08-30, from Armbian v26.08 | KU |
| Ubuntu 26.04 generic kernel | Ubuntu 26.04 (released 2026-04-23) | 7.0.0-38-generic | Canonical builds and patches the kernel. No Canonical statement about the RK1 was found. The boot path is community-only | 7.0.0-38.38 (resolute-updates) | UK, CR |

### Other vendor-kernel trees (checked 2026-10-01)

None of these publishes an RK1 image. Each one either carries the RK1 device tree in a vendor kernel, or names the RK1 somewhere.

| Project | What it is | Kernel | RK1 status | Latest | Source |
|---|---|---|---|---|---|
| defcom5-rockchip/ubuntu-rockchip | One person's maintained fork of ubuntu-rockchip; Ubuntu 24.04 desktop; 3 stars, created 2026-05-31 | `defcom5-rockchip/linux-rockchip-rk3588` `noble-security`, ABI 6.1.0-1027.27. That is Joshua's tree (last change 2025-03-30) plus one CVE backport (8027f1082, 2026-05-23). It has `rk3588-turing-rk1.dts` | The release says "Orange Pi 5B only. Other RK3588(S) boards unsupported." Its `turing-rk1.sh` is inherited, last changed 2025-01-24 | defcom5-v1.0.1, 2026-06-01 | DF |
| 7Ji/archrepo | An Arch Linux ARM package repo (pushed 2026-08-24). Kernel packages only, no images | `linux-aarch64-rockchip-bsp6.1-joshua-git`: Joshua's `noble` branch plus hbiyik's panthor backport (PKGBUILD last changed 2026-01-15). Also `bsp5.10-joshua-git` | No RK1 image. The kernel is frozen with Joshua's tree [I] | — | 7J |
| BredOS | An Arch-based SBC distro | `BredOS/linux-bredos` `rk6.1-rkr3`, 6.1.75 (pushed 2026-09-04). It has rknpu and the RK1 DTS. Its own site: "Help us move BredOS from the crusty Rockchip BSP kernel to upstream Linux mainline!" | The installer's `sbcs` list names "Turing Machines RK1" (`Bakery/bakery/config.py`). But `images.json` (35 devices) and all 368 release assets have no RK1 image. Positive control: Rock5B is found | — | BR |
| unifreq/linux-6.1.y-rockchip | Kernel tree used by ophub's Armbian rebuilds | vendor 6.1.174 (has `drivers/rknpu`, `drivers/video/rockchip/mpp`, `drivers/gpu/arm/valhall`), newer than Armbian's 6.1.172. RK1 is in the DT Makefile | ophub's README doesn't list the RK1 | 2026-09-30 | UF |

### Does the RK1 need its own build?

Only the bootloader and the device tree are RK1-specific. The kernel and rootfs aren't.

This compares the RK1's Linux v7.0 DT (`rk3588-turing-rk1.dtsi` + `.dts`, 799 lines) with eight other RK3588 boards' v7.0 DTs:
- carrier boards: Rock 5B, Orange Pi 5 Plus, NanoPC-T6
- SoMs with their carriers: Edgeble Neu6A-IO, CoolPi CM5 EVB, FriendlyElec CM3588 NAS, Theobroma Tiger/Haikou
- Rockchip's EVB1

The script and files are in `tasks/2026-10-01-rk1-artifacts/dt-compare/`.

- **Shared: the SoC and the power design.**
  - Every board includes the same `rk3588.dtsi`.
  - The RK1's power tree is Rockchip's reference design: one RK806 on `spi2`, plus RK8602/8603 on `i2c0` (big cores) and `i2c1` (NPU).
  - All 21 RK806 rails match Rock 5B, NanoPC-T6, CM3588 and Tiger by name and minimum voltage.
- **The kernel isn't the problem.** The RK1 DT is in mainline (since v6.7) and in every vendor 6.1 tree checked: Armbian rkr7.2, Joshua/defcom5, BredOS, unifreq. A kernel built for "RK3588" ships the RK1 DTB alongside the others.
- **The board layer differs enough that another board's DTB is wrong for an RK1.**
  - The RK1 enables 33 nodes. Overlap with the others' enabled sets is 0.25–0.51 (Jaccard).
  - **Ethernet:** `gmac1` with an RTL8211F RGMII PHY, reset on GPIO3_B7. None of the eight other boards enables `gmac1`. With a different board's DTB, the RK1's Ethernet wouldn't be described [I: no network].
  - **Console:** `serial9:115200n8`. Every other board uses `serial2`, seven of them at 1500000.
  - **Fan:** on `pwm0` with a tach interrupt. No other board enables `pwm0`.
  - **USB0:** USB 2.0 only; `usbdp_phy0` is lane-muxed to the DisplayPort pins.
  - **PCIe:** `pcie3x4` and `pcie2x1l1` only, with RK1-specific reset GPIOs.
  - **Things most boards enable that the RK1 doesn't** (on ≥ 6 of 8): `hdmi0`, `hdmi1`, `vop`, `sdmmc`, `i2s0_8ch`, `i2s5_8ch`, `saradc`, `pcie2x1l0`, `combphy0_ps`, `combphy1_ps`, `i2c7`, `u2phy3`, and USB1 EHCI/OHCI.
- **The bootloader is RK1-specific.**
  - U-Boot `turing-rk1-rk3588_defconfig` puts the console on uart9 (`DEBUG_UART_BASE=0xFEBC0000`), and has PCIe and NVMe. Armbian pairs it with a DDR blob variant named `…uart9_115200…`.
  - U-Boot's `generic-rk3588_defconfig` enables only eMMC, SD and USB OTG (as a peripheral), with its console on uart2 at 1500000. On an RK1 it would see no NVMe, and its output wouldn't reach the BMC's uart9 [I].
- **What follows:**
  - **A mainline distro booted through UEFI** (e.g. Ubuntu 26.04 generic) needs no RK1 build at all. RK1 U-Boot on eMMC supplies the DT.
  - **A vendor-kernel image made for another RK3588 board** doesn't work as-is. You'd swap in RK1 U-Boot, point `fdtfile` at `rk3588-turing-rk1.dtb` (which its kernel must build), and set `console=ttyS9,115200`.
  - **The custom build** this leads to (Armbian framework, Debian 13, vendor kernel): [rk1-custom-image.md](rk1-custom-image.md).

**Not found:**
- DietPi has no RK1 image. Its forum's RK1 request thread says it would reuse Armbian's kernel.
- edk2-rk3588 has no Turing platform, so there is no UEFI-firmware route for a generic ISO. Its vendor list was the positive control.
- Searches for Manjaro, Fedora, openSUSE, NixOS, Gentoo or Rocky vendor-kernel RK1 images turned up nothing.
- `sabban/debian-rk1` (last pushed 2025-06-22) copies the DTB out of an installed `linux-image-*`, so it uses Debian's kernel [I: mainline].
- `j0ju/sbc-fw-alchemy` repackages Armbian builds.

## Armbian

- **Kernel.**
  - The vendor branch moved from `rk-6.1-rkr5.1` (SUBLEVEL 115) to `rk-6.1-rkr7.2` (SUBLEVEL 172) in commit 81e862448, "rk35xx-vendor: bump to 6.1.172 rkr7.2 sdk kernel", on 2026-09-04.
  - That is after the v26.08 tag, which still pins `rk-6.1-rkr5.1` (`rockchip-rk3588.conf@v26.08:38` vs `@main:25`). That file applies because the RK1's family is `BOARDFAMILY="rockchip-rk3588"`; the same commit changed both it and `rk35xx.conf`. So kurochan's v26.08-based release ships 6.1.115.
- **Hardware coverage is the "Armbian vendor 6.1" column of [hardware-support.md](hardware-support.md).** That column was researched against `rk-6.1-rkr7.2` (AVD), so it describes these images unchanged [I].
- **U-Boot:** mainline `v2026.07` since 2026-07-19 (61f623201, "bump u-boot v2024.04 -> v2026.07").
- **Kernel targets.**
  - `turing-rk1.csc` keeps `KERNEL_TARGET="current,edge,vendor"`, but `KERNEL_TEST_TARGET="vendor"` (867258a3b, 2026-07-19).
  - armbian.com publishes only vendor images. Current (6.18) and edge (7.2) can be built yourself, but Armbian doesn't test or publish them for this board (`rockchip64_common.inc`).
- **Support.** Still "Community". Community boards are "untested and Armbian team won't respond on troubles or apply any fixes" (os-alternatives.md, option B).
- 2026-09-25 abbebe10e deprecates the BSP 5.10 "legacy" kernel. The RK1 has no legacy target, so it isn't affected.

## Ubuntu 26.04 generic kernel on the RK1

The checks were made against the `linux-modules-7.0.0-38-generic` arm64 package from ports.ubuntu.com:
- `/boot/config-7.0.0-38-generic` for the config lines below
- `usr/lib/firmware/7.0.0-38-generic/device-tree/rockchip/rk3588-turing-rk1.dtb` for the node status, read with a small FDT parser

The parser's output includes `disabled` nodes (HDMI, the second GMAC, unused UARTs), so it does tell the two states apart.

| Feature | Config (`config-7.0.0-38-generic`) | RK1 DTB | Verdict |
|---|---|---|---|
| GPU, Mali-G610 (panthor) | `DRM_PANTHOR=m` :8747 | `gpu@fb000000` okay | Y. Mali CSF firmware in Ubuntu's `linux-firmware`: U |
| NPU (rocket) | `DRM_ACCEL_ROCKET=m` :9051 | `npu@fdab0000`, `@fdac0000`, `@fdad0000`, `iommu@fdab9000` okay | Y kernel side; the Mesa caveat is below |
| Video decode, rkvdec (H.264/HEVC, from 7.0, MV) | `VIDEO_ROCKCHIP_VDEC=m` :7783 | `video-codec@fdc38000`, `@fdc40000` (`rk3588-vdec`), no status property = okay | Y |
| Video decode, Hantro (H.264/VP8/MPEG-2) + AV1 | `VIDEO_HANTRO=m` :7820, `VIDEO_HANTRO_ROCKCHIP=y` :7823 | `vpu121` @fdb50000, `av1-vpu` @fdc70000 | Y |
| Video encode | same | 4× `vepu121` (JPEG only) | JPEG only; VEPU580 H.264/HEVC has no mainline driver (MV) |
| RGA | `VIDEO_ROCKCHIP_RGA=m` :7780 | `rga@fdb80000` | P: RGA2 [I, per MR] |
| HDMI | `ROCKCHIP_DW_HDMI_QP=y` :8773, `PHY_ROCKCHIP_SAMSUNG_HDPTX=m` :13921 | `hdmi@fde80000`, `@fdea0000` **disabled** | N: the DT doesn't enable it |
| NVMe (PCIe 3.0 x4), mini-PCIe | `PCIE_ROCKCHIP_DW_HOST=y` :2380, `PHY_ROCKCHIP_SNPS_PCIE3=m` :13922, `PHY_ROCKCHIP_NANENG_COMBO_PHY=m` :13918, `BLK_DEV_NVME=m` :2978 | `pcie@fe150000`, `@fe180000` okay | Y |
| Longhorn (iSCSI) | `ISCSI_TCP=m` :3135 | — | Y |
| eMMC | `MMC_SDHCI_OF_DWCMSHC=m` :10726 | `mmc@fe2e0000` okay | Y |
| Ethernet | `DWMAC_ROCKCHIP=m` :4007 | `ethernet@fe1c0000` okay | Y |
| cpufreq | `ARM_SCMI_CPUFREQ=m` :733; schedutil not the default governor :706; `ENERGY_MODEL=y` :666 | — | Y |
| Thermal, fan | `ROCKCHIP_THERMAL=m` :6698, `SENSORS_PWM_FAN=m` :6593 | `tsadc@fec00000` okay, `pwm-fan` present | Y in DT and config. One report of no thermal zones at runtime (below) |
| RNG | `HW_RANDOM_ROCKCHIP=y` :5351 | `rng@fe378000` | Y |

- **Mesa.** Ubuntu 26.04 ships `mesa-libgallium` and `mesa-teflon-delegate` 26.0.3, and 26.0.8-1ubuntu0.3 in `resolute-updates` (UP).
  - Upstream 26.1.5's release notes list "rocket: fix mmap leak in buffer map/unmap". 26.0.6, 26.0.7 and 26.0.8 don't mention rocket (MN).
  - Without that fix, rocket crashes roughly every 5 minutes (hardware-support.md, FR).
  - It doesn't: the 26.0 branch ended at 26.0.8 without the fix. See [rk1-gpu-npu.md](rk1-gpu-npu.md).
- **Compared with the 2026-09-26 columns:**
  - Over Talos 1.14.1 (6.18): adds H.264/HEVC decode, Hantro, RGA, and NPU DT nodes without an overlay patch.
  - Same mainline gaps as everywhere: the RK1 DT leaves HDMI disabled, there is no VEPU580 encode, and no RKNN/RKLLM.

### Booting it

- `vmlinuz` is a PE image: Canonical's stubble wrapper around the compressed (`CONFIG_EFI_ZBOOT=y`, :2642) kernel, not a raw arm64 `Image`. Details: [rk1-gpu-npu.md](rk1-gpu-npu.md).
- **JM** reports that extlinux fails with "Bad Linux ARM64 Image magic!". JM says extlinux is the only active boot path on stock ubuntu-rockchip RK1 images.
- **JM's fix:**
  - Put GRUB at `/EFI/BOOT/BOOTAA64.EFI` on the root partition, which is already GPT-flagged as an ESP.
  - U-Boot's EFI boot manager then loads GRUB ahead of extlinux, and GRUB boots the generic kernel.
  - Done in place on ubuntu-rockchip installs. extlinux stays pinned to the old vendor kernel as the fallback.
- **JM's reported problems:**
  - No thermal zones under the generic kernel. Ubuntu's DTB has `tsadc` okay and `thermal-zones`, but the kernel never got that DTB. It got the DT of ubuntu-rockchip's U-Boot, which has no thermal zones (see [rk1-gpu-npu.md](rk1-gpu-npu.md)).
  - `GRUB_DEFAULT` is ignored unless `GRUB_DISABLE_SUBMENU=y` is set.
  - The serial console moves between `ttyS0` and `ttyS9`. The UART is uart9 throughout. Its ttyS number depends on each kernel's `SERIAL_8250_RUNTIME_UARTS`: 32 on Ubuntu gives ttyS9, and 8 on Armbian mainline gives ttyS0 ([rk1-gpu-npu.md](rk1-gpu-npu.md)).
- **Caveats.** JM is one author with 0 stars, created 2026-09-15, and its README credits Claude Code with "doing the implementation". Nothing in it was verified here.
- **The role checks the RK1 DTB but never loads it.** `preflight.yml:157` checks that the generic modules package contains `rk3588-turing-rk1.dtb`. No role file loads it: the embedded GRUB config is only `search` plus `configfile`, and its standalone GRUB has no `fdt` module. So the kernel runs on U-Boot's tree.

## What this changes in the 2026-09-26 conclusions

This applies only if the RK1s are reused: the cluster moved to the Super6C ([README](README.md)).

- **Option B / option 4 ("k3s on vendor OSes").**
  - The README called the RK1 vendor images "unmaintained", and that holds for every vendor-kernel image above.
  - There is now a third RK1 path: Ubuntu 26.04 with Canonical's kernel. It gives mainline-level hardware (GPU, rocket NPU, H.264/HEVC decode, Longhorn), and the distro's kernel updates.
  - Its cost is a hand-assembled EFI boot path, and a Mesa from a PPA for the NPU. The Mali firmware is in Ubuntu's `linux-firmware-misc` ([rk1-gpu-npu.md](rk1-gpu-npu.md)).
- **Talos (option 1):** unchanged by any of this.

## Open

- The firmware, Mesa and U-Boot questions that were open here are answered in [rk1-gpu-npu.md](rk1-gpu-npu.md).
- The Turing forum thread "RK1 Ubuntu 22.04 and 24.04 Availability, Issues and Patches" returned HTTP 429 twice and wasn't read.

## Sources

- **TF**: [firmware.turingpi.com/turing-rk1/](https://firmware.turingpi.com/turing-rk1/) · **TD**: [Turing RK1 flashing docs](https://docs.turingpi.com/docs/turing-rk1-flashing-os)
- **UR**: [Joshua-Riek/ubuntu-rockchip](https://github.com/Joshua-Riek/ubuntu-rockchip) (`gh repo view`: archived; `gh release list`)
- **AW**: [armbian.com/boards/turing-rk1](https://armbian.com/boards/turing-rk1)
- **AB**: armbian/build `config/boards/turing-rk1.csc` @main and its history (61f623201, 867258a3b); `config/sources/families/rockchip-rk3588.conf` @main and @v26.08 (81e862448); `config/sources/families/rk35xx.conf` (abbebe10e); `config/sources/families/include/rockchip64_common.inc` @main
- **AF**: armbian/linux-rockchip `Makefile` @`rk-6.1-rkr5.1` (SUBLEVEL 115) and @`rk-6.1-rkr7.2` (SUBLEVEL 172)
- **KU**: [kurochan/turing-rk1-ubuntu-image](https://github.com/kurochan/turing-rk1-ubuntu-image): README and the three release notes
- **UK**: `linux-modules-7.0.0-38-generic_7.0.0-38.38_arm64.deb` and `linux-image-unsigned-7.0.0-38-generic_7.0.0-38.38_arm64.deb` from ports.ubuntu.com `pool/main/l/linux/`; `linux-image-generic` 7.0.0-38.38 on [packages.ubuntu.com resolute-updates](https://packages.ubuntu.com/resolute-updates/arm64/linux-image-generic)
- **CR**: [Canonical, Ubuntu 26.04 LTS release](https://canonical.com/blog/canonical-releases-ubuntu-26-04-lts-resolute-raccoon) ("Linux 7.0", 2026-04-23)
- **UP**: packages.ubuntu.com `resolute` and `resolute-updates`, arm64: `mesa-libgallium`, `mesa-teflon-delegate`
- **MN**: Mesa release notes [26.0.6](https://docs.mesa3d.org/relnotes/26.0.6.html), [26.0.7](https://docs.mesa3d.org/relnotes/26.0.7.html), [26.0.8](https://docs.mesa3d.org/relnotes/26.0.8.html), [26.1.5](https://docs.mesa3d.org/relnotes/26.1.5.html)
- **TG**: Turing guides: [Turing Pi 2.5 + RK1 setup guide](https://turingpi.com/turing-pi-2-5-rk1-complete-setup-guide-from-unboxing-to-a-running-k3s-cluster/) (2026-04-15); [Jellyfin RK3588 hardware transcoding](https://turingpi.com/jellyfin-rk3588-hardware-transcoding-turing-pi-arm64/) (2026-07-04)
- **DF**: [defcom5-rockchip/ubuntu-rockchip](https://github.com/defcom5-rockchip/ubuntu-rockchip): release notes defcom5-v1.0.0 and v1.0.1, `config/boards/turing-rk1.sh` history; [defcom5-rockchip/linux-rockchip-rk3588](https://github.com/defcom5-rockchip/linux-rockchip-rk3588) `noble-security` commits and `arch/arm64/boot/dts/rockchip/`
- **7J**: [7Ji/archrepo](https://github.com/7Ji/archrepo) `aarch64.yaml`; [7Ji-PKGBUILDs/linux-aarch64-rockchip-bsp6.1-joshua-git](https://github.com/7Ji-PKGBUILDs/linux-aarch64-rockchip-bsp6.1-joshua-git) `PKGBUILD`; Joshua-Riek/linux-rockchip (last pushed 2025-03-30)
- **BR**: [BredOS/linux-bredos](https://github.com/BredOS/linux-bredos) `rk6.1-rkr3` (`Makefile`, DT dir, `drivers/rknpu`); BredOS/Bakery `bakery/config.py`; [BredOS/images](https://github.com/BredOS/images) `images.json` and releases; [bredos.org](https://bredos.org/)
- **UF**: [unifreq/linux-6.1.y-rockchip](https://github.com/unifreq/linux-6.1.y-rockchip) (`Makefile`, driver dirs, commits); ophub/amlogic-s9xxx-armbian README
- **JM**: [JohanElmis/turing-rk1-mainline-kernel](https://github.com/JohanElmis/turing-rk1-mainline-kernel): README, every file under `roles/rk1_kernel_migrate/` grepped for DTB handling; `tasks/preflight.yml`, `templates/grub-embed.cfg.j2`
- **MV**, **MR**, **AVD**, **FR**: as defined in [hardware-support.md](hardware-support.md)
