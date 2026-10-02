# Hardware support by OS: Turing RK1, CM4, Jetson Orin Nano

Researched 2026-09-26. **[I]** marks inference. Most cells carry a source key (listed at the end), with `file:line` where the source is a config or source file. A bare Y (or Y-V) with no key was verified during research, but its source was not recorded cell by cell.

Kernel-config lines come from grepping the raw files. A WebFetch summary of the 10,638-line Talos config reported most of these symbols as absent, and it was wrong.

Legend: **Y** supported · **P** partial · **N** not supported · **U** unverified.

## The Talos kernel, for reference

- Talos v1.14.1 pins `siderolabs/pkgs@f694e1b`, which is identical to `release-1.14`: Linux 6.18.51 (TC).
- Only modules listed in `hack/modules-arm64.txt` ship in the base image (TM).
- panthor, rocket, v3d and vc4 come from extensions. `siderolabs/panfrost` (20260810-v1.14.1), `rockchip-rknn` and `vc4` are in the v1.14.1 Image Factory list (TE).
- Modules load through the `KernelModuleConfig` document. Extension modules get a combined modules.dep at install (TK).
- The default command line sets `module.sig_enforce=1` (TK). An out-of-tree vendor driver, such as Rockchip's rknpu, therefore needs a Talos build signed with your own key; that is what SC does.

## Turing RK1 (RK3588)

For the 2026-10-01 release state, and an Ubuntu 26.04 generic-kernel (7.0) column built from its config and the RK1 DTB, see [rk1-os-releases.md](rk1-os-releases.md).

| Feature | Talos 1.14.1 (6.18.51) | Armbian vendor 6.1 | Armbian current 6.18 | Turing Ubuntu 22.04 (5.10) | NixOS 26.05 (6.18) | From a pod |
|---|---|---|---|---|---|---|
| CPU, cpufreq | Y: cpufreq-dt on SCMI clocks (TC:682,7604; MS:98,174), schedutil (TC:671). No energy-aware scheduling: ENERGY_MODEL off (TC:631) | Y [I] | Y (AC:82) | Y [I] | Y [I] | — |
| Thermal, throttling | Y (TC:4772,4759; MD:668). GPU not devfreq-throttled (TC:4761) | Y (AV:1439) | Y (AC:1672) | Y [I] | Y [I] | — |
| Fan (PWM) | Y (TC:4686,9053; MD:24-29; trips→fan MD:216-266) | Y (AV:1388; AVD:49) | Y (AC:1616) | Y (U:49) | Y (DEF:718) | — |
| eMMC | Y (TC:7030; module in base TM:113) | Y [I] | Y (AC:2644) | Y (U) | Y (NR) | local PV |
| NVMe, PCIe 3.0 x4 | Y (TC:2069,9245; TM:210; MD:283-289). Booting from NVMe needs u-boot on eMMC/SPI | Y (AVD:509) | Y (AC:630) | Y; the bootloader stays on eMMC (U) | Y (NR) | via CSI; `ISCSI_TCP=y` (TC:2587) |
| PCIe 2.0 x1 (mini-PCIe) | Y controller (TC:9241; MD:271-276). Card drivers are limited to Talos's modules and extensions [I] | Y (AVD:497) | Y (AC:3114) | Y (U:493) | Y [I] | device plugin |
| Ethernet | Y (dwmac-rk TM:187; TC:3346; MD:104-116) | Y [I] | Y [I] | Y [I] | Y [I] | — |
| USB | Y (TC:6729,9248; TM:261; MD:683-744) | Y [I] | Y (AC:3121) | Y [I] | Y [I] | device plugin |
| HDMI (slot 1) | N: DW_HDMI_QP and the HDPTX PHY off (TC:5625,9244); no hdmi node in the RK1 DT through v7.3-rc4 (MD) | Y (AVD:599-676) | N out of the box: driver built (AC:2010), no DT node [I] | Y (U:595-672) | N (NIX; MD) | — |
| GPU Mali-G610 MP4 | P: panthor plus `/usr/lib/firmware/arm` (includes `mali_csffw.bin`) only via the `panfrost` extension (TE). Mesa must be in the container image | Y: kbase + libmali by default (AV:1986; AVD:2952); panthor via an overlay (AVD:2977) | Y: panthor (AC:2116); firmware in armbian/firmware | Y: kbase + panfork (U) | P: panthor=m (DEF:988); firmware must be enabled [I]; the RK1 flake lists the firmware as a TODO (NR) | `/dev/dri/renderD128`, or `/dev/mali0` + libmali on vendor. PanVK is Vulkan-conformant on G610 (PF); Rusticl is OpenCL 3.0 conformant as of 2026-07-29 (KH) |
| NPU (6 TOPS) | P: `rocket` via the `rockchip-rknn` extension (TE) plus the overlay's DTB patch enabling the NPU (TR). Vendor RKNN only via a custom-signed build (SC) | Y: rknpu 0.9.8, RKNN, RKLLM (AVD) | P: rocket (AC:2137) plus an Armbian patch enabling the RK1 NPU | Y, but old: rknpu 0.9.2 (U) | N on 6.18 (no NPU DT nodes, MD). P on `linuxPackages_latest` 7.2 (MD v7.0) with Mesa rocket + teflon (NIX) | rocket: `/dev/accel/accel0` + libteflon, documented in Talos k8s pods (FD, FR). RKNN usually needs a privileged pod (SC); small device plugins exist, unvetted |
| Video decode | N: VIDEO_HANTRO and VIDEO_ROCKCHIP_VDEC off (TC:5347,5318); no V4L2 modules in the base image (TM) | Y via MPP: H.264/HEVC/VP9/AVS2, 10-bit, 8K, AV1 (AV:2018-2031; MPP:67,338-349) | P: Hantro H.264/VP8/MPEG-2/AV1 (AC:1935) plus backported VDPU381 H.264/HEVC | Y via MPP (U:204,414-426) | P: Hantro (DEF:894); H.264/HEVC from 7.2 (MV) | Mainline: `/dev/video*`, `/dev/media*` + GStreamer ≥ 1.28 or an out-of-tree FFmpeg v4l2-request build (COL, FR). Vendor: Jellyfin's device list, documented for Docker only (JF) |
| Video encode (VEPU580) | N | Y: H.264/HEVC (AV:2022; MPP:77) | N (JPEG only) | Y (U:434-446) | N (JPEG only) | vendor only (JF) |
| RGA 2D | N (TC:5316) | Y: RGA2 + RGA3 (AV:2016; AVD:394-410) | P: RGA2 only, 32-bit DMA (AC:1931; MR:842) | Y (U:390-406) | P: RGA2 (DEF:886); RGA3 from 7.2 (MR) | `/dev/rga`, or V4L2 m2m |
| Crypto engine, RNG | RNG Y (TC:3881; MC:470; MS:2187-2193). Crypto N: the driver matches only rk3288/3328/3399 (MC:303-309) | RNG Y. Crypto P: driver binds rk3588 (AVD:731), but the DT node is disabled | RNG Y [I]; crypto N | RNG Y; crypto P (node disabled) | RNG Y [I]; crypto N | — |

### Mainline RK3588 video (6.18)

- **Decode:**
  - Hantro G1 "vpu121": H.264, VP8, MPEG-2 (MH:774-779; MS:1244).
  - Hantro VPU981: AV1 (MH:723,805-812).
  - The main decoder (rkvdec2 / VDPU381) is absent in 6.18. It landed in 7.0 with H.264 and HEVC only (MV). VP9 is out of tree (COL).
  - One field report says Hantro H.264 "has trouble with simultaneous streams" (FR).
- **Encode:** JPEG only, on four VEPU121 blocks (MH:722). VEPU580 (H.264/HEVC) has no mainline driver through v7.3-rc4 (MV).
- **Userspace:** GStreamer 1.28 supports the new controls. FFmpeg's v4l2-request is not upstream (COL; FR 2026-03-22).

### rocket + Mesa Teflon, the mainline NPU path

- **Versions.** The kernel driver is in 6.18; Mesa support first shipped in 25.3 (PH).
  - Use Mesa ≥ 26.1.5. Earlier releases crash roughly every 5 minutes on an mmap leak (`rkt_device.c:79`), fixed by MR 41887 and backported (FR).
  - NixOS 26.05 ships Mesa 26.1.8 with rocket and teflon (NIX).
  - Debian's `mesa-teflon-delegate` 26.1.6 is in trixie-backports and forky; trixie itself has 25.0.7 (DEB).
- **Models.** MobileNet V1/V2 and SSDLite MobileDet (UINT8) are "Fully supported" (MT). The driver's author says "the hardware cannot properly accelerate SiLU", which rules out accelerating YOLOv8 (TV).
- **Speed.**
  - rocket: about 18, 21 and 48 ms on those three models (MT), and about 12–15 ms for MobileNetV1 on an RK1 under Talos (FD).
  - RKNN: mobilenetv2 at 450.7 FPS on one core, about 2.2 ms (RZ).
  - That is roughly a 10× gap [I; the two are measured differently]. The author plans "some performance work, to match that of the proprietary driver" (TV).
- **Missing.** RKLLM, model conversion, anything outside TFLite.
- **Unverified field reports:** spontaneous reboots on a Rock 5B+; only 2 of 3 NPU cores used without out-of-tree fixes (FR).

### What Rockchip's BSP gives that mainline lacks on the RK1

- **NPU:** RKNN and RKLLM, for example Qwen2-0.5B at 41.6 tokens/s (RLLM).
- **Video:** VEPU580 H.264/HEVC encode, and VP9, AVS2, 10-bit and 8K decode, with working FFmpeg and Jellyfin (MPP, JF).
- **Other:** RGA3 (mainline only from 7.2); HDMI in the RK1 DT; an rk3588 crypto driver, though it is disabled in the RK1 DT.
- **The GPU is no longer a vendor advantage** (PF, KH).
- **The cost:**
  - Armbian publishes only vendor 6.1.172 images for the RK1, as a "Community" board with no maintainer (AB).
  - Turing's 22.04/5.10 image is frozen at v1.33 (Feb 2024), its upstream project is archived, and it ships rknpu 0.9.2 (U).

## Raspberry Pi CM4 (BCM2711)

| Feature | Talos 1.14.1 | NixOS + nixos-hardware (RPi kernel 6.18.50) | NixOS, mainline 6.18 | Raspberry Pi OS (6.18.34) | From a pod |
|---|---|---|---|---|---|
| CPU, cpufreq, thermal | Y (TC:693,4788) | Y (R:73,851) | Y [I] | Y (R:73,851) | — |
| eMMC | Y (TC:7037; TM:110). The Talos docs call the CM4 community-tested (TD) | Y (R:1434) | Y [I] | Y | local PV |
| PCIe → SATA (ASMedia, slot 3) | Y (TC:2007,2675; ahci in base TM:15); not confirmed in practice [I] | Y (R:497) | Y [I] | Y (R:497) | via CSI |
| Ethernet (bcmgenet) | Y (TC:2951,3307) | Y (R:533) | Y [I] | Y | — |
| USB 2.0 (dwc2) | P: dwc2 built (TC:6749,6756), but the CM4 needs a host-mode overlay (JG), which can be added through the overlay's `configTxtAppend` (SRP) [I] | Y (R:1315) | P [I] | Y with the overlay (JG) | device plugin |
| GPU (v3d) | P: v3d/vc4 only via the `vc4` extension (TE); CMA defaults to 16 MB (TC:10209) and must be raised (TD) | Y (R:1103) | Y (DEF:974) | Y | `renderD128` + Mesa v3d/v3dv (V3D) |
| H.264 decode/encode (bcm2835-codec) | N: not in mainline (MRPI); STAGING off (TC:7571) | Y (R:1550; NH:36) | N | Y: `/dev/video10` decode, `/dev/video11` encode (R:52-58) | map `/dev/video10-12` (FRD; GDP) |
| HEVC decode | N: not in mainline through v7.3-rc4 (MRPI); the upstream series is at v6 (HEVC) | Y (R:1034) | N | Y (R, hevc_d.c:321) | stateless V4L2; Frigate's `preset-rpi-64-h265` (FRD) |

- **The Talos CM4 overlay boots the Talos mainline kernel.** The Pi firmware loads `kernel=u-boot.bin`, and the downstream kernels are deleted as "not used by Talos boot flow" (SRP). The DTB is the Pi firmware's downstream bcm2711 DTB [I].
- **Open Ethernet report.** On a Pi 4, which uses the same bcmgenet driver: "NETDEV WATCHDOG … transmit queue 1 timed out", Talos 1.12.2, no workaround (sbc-raspberrypi#72, 2026-01-25).

## Jetson Orin Nano 8 GB (P3767-0005)

The first column says what the module has; many blocks exist only under NVIDIA's stack. A -V suffix means verified, -I means inferred.

| Feature (on the module) | Talos 1.14.1, generic image, ACPI | talos-jetson-orin (DT) | JetPack 6.2.x (R36.4.3–36.5.2, kernel 5.15) | JetPack 7.2.1 (R39.2.1, kernel 6.8.12) | jetpack-nixos @825dfea | From a pod | In a Turing Pi 2 slot |
|---|---|---|---|---|---|---|---|
| Boots on this board | Y-V in ACPI (DHCP works). DT reboot-loops even on stock v1.14.0 (I57). A reboot hang was seen on AGX Orin in ACPI (T8316) | N-V: DT reboot-loops on UEFI 36.5.0; only tested on Orin NX 16 GB (I57; TJO) | Y-V | Y-V; needs JP6-generation QSPI first (NVD8) | Y-V; an nvpmodel mis-mapping on Orin Nano Super was fixed in Apr 2026 (JN#478) | — | QSPI reflash needed (below) |
| CPU 6×A78AE, cpufreq (1728 MHz in MAXN SUPER, NVD3) | cores I (all 8 came up on AGX Orin in ACPI, T8316). cpufreq U: firmware emits `_CPC` (EDK) and `ACPI_CPPC_CPUFREQ=y` (TC:701), but `tegra194-cpufreq` is DT-only (LNX) | Y-I (`ARM_TEGRA194_CPUFREQ=y`, TC:698) | Y-V (nvpmodel, NVD3) | Y-V (NVD6) | Y-V (nvpmodel on by default, JN) | host only | — |
| Power modes, MAXN SUPER (7/15/25 W) | N-I: the ACPI tables list the power-management processor (`NVDA2001`) and GPU (`NVDA1081`), but no Linux driver matches either (EDK) | P-V: a DaemonSet pins GPU, memory and CPU clocks via sysfs with NX values (918/1173 MHz), not nvpmodel (TJO) | Y-V: flash `jetson-orin-nano-devkit-super.conf`, then `nvpmodel -m 2` (NVD5, NVD3) | Y-V: the ISO flashes Super by default (NVD7) | Y-V: `super = true` gives the `-super` flash target; needs a USB reflash, not a capsule update (JN#319) | host only | per-node power budget undocumented (TP2) |
| Thermal + fan | N-I: BPMP thermal is DT-only (LNX); no T234 ACPI thermal zones or fan device (EDK); UEFI leaves the fan at about 50% (EDK) | U: drivers built (TC:4686,9056,4804), no fan daemon | Y-V: nvfancontrol + pwm-fan (NVD3) | Y-V (NVD6) | Y-V; nvfancontrol only with `carrierBoard="devkit"` (JN) | host only | The dev-kit fan header is gone. The Turing Pi 2 has 4× micro-JST 1.25 mm 4-pin headers, wiring undocumented (TP2) |
| NVMe | U/I: PCIe works in ACPI (the NIC gets DHCP, I57); NVMe install shown on AGX Orin in ACPI (T8316); `BLK_DEV_NVME=m` (TC:2458) | Y-V on NX | Y-V | Y-V | Y-V | host only | one M.2 x4 per node (TP2) |
| Ethernet: RTL8111-class chip on the module, PCIe C8 (AMB; LNX; JN) | Y-V: DHCP (I57); `R8169=m` (TC:3198) | Y-V on NX | Y-V: NVIDIA's out-of-tree r8168, built only for 5.15 (NVOOT) | Y-I | Y-V | — | pins go to the onboard switch; same driver [I] |
| USB | Y-I: generic xHCI (`PNP0D10`, EDK), `USB_XHCI_PLATFORM=m` (TC:6651); a USB disk was seen on AGX Orin (T8316) | Y-I (`USB_XHCI_TEGRA=m`, TC:6657) | Y-V | Y-V | Y-V | host only | USB 3 only in slot 4 |
| GPU: Ampere, 1024 CUDA cores, 32 tensor cores (NVD1) | N-V: "integrated GPU is not exposed under ACPI" (I57) | Y-V on NX: OE4T nvgpu + JetPack r36.5 userspace (TJO); the upstreaming PR is open (P1518) | Y-V: CUDA 12.6, TensorRT 10.3 (NVD5) | Y-V: CUDA 13.2.2, TensorRT 10.16.2 (NVD7) | Y-V: TensorRT 10.7.0 (with CUDA 12.6) / 10.16.1 (with CUDA 13.2) (JN) | CDI via `nvidia-ctk cdi generate --mode=csv` + k8s-device-plugin `--device-discovery-strategy=tegra` (NCT, KDP). talos-jetson-orin ships its own CDI and plugin (TJO). GPU Operator: no (GPUOP) | unchanged |
| DLA | **none** ("DLA cores 0", NVD3) | — | — | — | — | — | — |
| NVDEC (1× 4K60 H.265) | N-V: no decoder in the T234 ACPI tables (EDK) | N-V: only GPU devices are injected (TJO) | Y-V | Y-I | Y-V via V4L2 + GStreamer; no ffmpeg integration (JN) | CSV mode mounts `/dev/v4l2-nvdec`, `/dev/dri/*`, host1x-fence and nvmap (MTG), plus GStreamer/V4L2 libraries. Works in pods [I] | unchanged |
| NVENC | **none**: "does not have the NVENC engine"; the CPU encodes 1080p30 (NVD4) | — | — | — | — | — | — |
| VIC / PVA | VIC yes, PVA none (NVD3). Under Talos: N (not in the ACPI tables) | N-I | VIC Y-I | VIC Y-I | VIC Y-I | via `/dev/dri` [I] | unchanged |
| CSI camera / ISP (8-lane CSI-2; dev kit has 2× 22-pin) | N-I: "firewalls prevent access from CCPLEX" (EDK) | N-I | Y-V (Argus) | Y-I | Y-I; the camera daemon is opt-in (JN) | via the host's camera daemon socket [I] | **lost**: the Turing Pi 2 lists only DSI + HDMI (TP2) |
| Display (dev kit: DP) | P-V on AGX Orin: firmware framebuffer only (T8316) | N-V: built headless (P1518) | Y | Y | P-V: needs a UEFI setting change and an overlay (JN#450) | — | DP gone; HDMI only in slot 1 [I: needs DT work] |

**Kubernetes stack on JetPack / jetpack-nixos.**
- Generate the CDI spec with `nvidia-ctk cdi generate --mode=csv`. jetpack-nixos does exactly this with NVIDIA's device lists (JN).
- Run NVIDIA's k8s-device-plugin with `--device-discovery-strategy=tegra`.
  - Its CDI device-list modes need NVML. JetPack 6 ships `nvidia-l4t-nvml`, so whether those modes work is U.
  - The documented path is toolkit ≥ 1.11 plus the nvidia runtime (KDP).
- The NGC `l4t-jetpack` page lists only r36.x tags (NGC).

**Where MAXN SUPER works.** JetPack 6.2.x, 7.2.1 and jetpack-nixos, each after a Super-config QSPI flash, then `nvpmodel -m 2`.
- The flash writes the Super BPMP DTB, the `-nv-super` kernel DTB and the Super nvpmodel config (MTG).
- If Super firmware is already flashed, the `TegraPlatformSpec` EFI variable contains "super" (JN#319).
- talos-jetson-orin only approximates it with NX clocks. Stock Talos can't do it at all.

### Moving the Orin into a Turing Pi 2 slot

1. **QSPI reflash from an x86 Ubuntu host with `l4t_initrd_flash.sh`, whatever the OS.**
   - Turing Pi: "The SDK Manager does not support flashing of the Orin modules in the third-party boards".
   - The Turing Pi 2 "does not have the onboard EEPROM", so set `cvb_eeprom_read_size = <0x0>` in `bootloader/generic/BCT/tegra234-mb2-bct-misc-p3767-0000.dts`. That is the JP6 path (NVD9); Turing's page shows the JP5 `t186ref` path (TPO).
   - Pick the `-super` config at this step if you want Super mode.
   - jetpack-nixos has no option for the EEPROM change [I: it needs a flash-script override].
2. **Turing Pi's own guide** (2026-08-20, board 2.5.2, TPG):
   - It flashed a P3767-0005 in slot 2, because slot 1 had USB failures.
   - It used `tpi usb flash --node 2`, an Ubuntu 22.04 host, `l4t_initrd_flash.sh … jetson-orin-nano-devkit-super internal` and JetPack 7.2.1.
   - It then ran the module at 25 W on an NVMe root.
3. **Lost or changed in a slot:**
   - camera: none
   - DP: gone; HDMI only in slot 1
   - fan control: header wiring undocumented; under stock Talos the fan stays at about 50% anyway
   - USB 3: slot 4 only
   - 25 W sustained per slot: unverified
4. **Kept:** Ethernet [I], the module's own microSD slot, one M.2 x4.

## Turing Pi 2 (v2.5)

| Slot | Peripherals (TP2) | What the CM4's single PCIe 2.0 lane reaches (JGT) |
|---|---|---|
| 1 | mini-PCIe + SIM, HDMI, DSI, GPIO, USB 2.0, M.2 T1 | mini-PCIe |
| 2 | mini-PCIe, M.2 T2 | mini-PCIe |
| 3 | 2× SATA 3 (ASMedia), M.2 T3 | SATA |
| 4 | 4× USB 3.0 (VL805), M.2 T4 | USB 3.0 |

- **M.2:** "RK1: PCIe 3.0 x4", "Nvidia Jetson Orin Nano: PCIe 3.0 x4", "CM4 (Raspberry Pi): No NVMe support" (TP2). The RK1's x1 peripherals run at PCIe 2.0 x1 (`pcie2x1l1`, MD).
- **v2.5 vs v2.4** (TP25):
  - OTG moved from USB-A to USB-C.
  - An "internal USB hub connected to USB0 interfaces of all nodes… flash multiple modules at once".
  - The slot-3 "unconnected #clkreq signal (mostly a case with Talos running on Raspberry Pi CM4)" is fixed.
- **Orin support.** Turing Pi lists the Orin Nano as a supported module (TPSM). There is no evidence that `tpi flash` supports Jetson.
- **Firmware and CLI.**
  - BMC firmware: v2.1.0 is GitHub's latest (2025-02-05, "breaking change of network configuration"); firmware.turingpi.com lists up to v2.0.5 (BMC).
  - tpi CLI: 1.0.7 (2024-11-04) (TPI).

## Sources

**Talos**
- **TC**: [`siderolabs/pkgs@release-1.14` `kernel/build/config-arm64`](https://github.com/siderolabs/pkgs/blob/release-1.14/kernel/build/config-arm64). Equal to f694e1b, which talos v1.14.1 pins (`Makefile` L31).
- **TM**: [`siderolabs/talos@v1.14.1` `hack/modules-arm64.txt`](https://github.com/siderolabs/talos/blob/v1.14.1/hack/modules-arm64.txt)
- **TE**: [`siderolabs/extensions@v1.14.1`](https://github.com/siderolabs/extensions/tree/v1.14.1) (`drm/panfrost`, `drm/rockchip-rknn`, `drm/vc4`); [Image Factory v1.14.1 extensions](https://factory.talos.dev/version/v1.14.1/extensions/official)
- **TR**: [`siderolabs/overlays@v1.14.1` `overlays.yaml`](https://github.com/siderolabs/overlays/blob/v1.14.1/overlays.yaml); [`sbc-rockchip@v0.2.1`](https://github.com/siderolabs/sbc-rockchip/tree/v0.2.1) (`artifacts/dtb/turingrk1/patches/rknn.patch`)
- **SRP**: [`sbc-raspberrypi@v0.2.2`](https://github.com/siderolabs/sbc-raspberrypi/tree/v0.2.2) (`artifacts/raspberrypi-firmware/pkg.yaml`, `installers/rpi_generic/src/{config.txt,main.go}`)
- **TK**: [`siderolabs/talos@v1.14.1`](https://github.com/siderolabs/talos/tree/v1.14.1): `pkg/machinery/config/types/runtime/kernel_module.go`, `internal/pkg/extensions/kernel_modules.go`, `pkg/machinery/kernel/kernel.go`
- **TD**: [Talos v1.14 rpi_generic page](https://docs.siderolabs.com/talos/v1.14/platform-specific-installations/single-board-computers/rpi_generic). The CMA warning is from the v1.10 edition.

**Mainline, Armbian, Turing, NixOS, Raspberry Pi**
- **MD**: [torvalds/linux v6.18 `rk3588-turing-rk1.dtsi`](https://github.com/torvalds/linux/blob/v6.18/arch/arm64/boot/dts/rockchip/rk3588-turing-rk1.dtsi), checked through v7.3-rc4.
- **Other mainline keys**, all torvalds/linux at v6.18 / v7.0 / v7.2 / v7.3-rc4:
  - **MS**: `rk3588-base.dtsi`
  - **MH**: `drivers/media/platform/verisilicon/{hantro_drv.c,rockchip_vpu_hw.c}`
  - **MV**: `drivers/media/platform/rockchip/rkvdec/`
  - **MR**: `drivers/media/platform/rockchip/rga/rga.c`
  - **MC**: `drivers/crypto/rockchip/rk3288_crypto.c`, `drivers/char/hw_random/rockchip-rng.c`
  - **MRPI**: `drivers/staging/vc04_services`, `drivers/media/platform/raspberrypi`
- **DEF**: [torvalds/linux v6.18 `arch/arm64/configs/defconfig`](https://github.com/torvalds/linux/blob/v6.18/arch/arm64/configs/defconfig)
- **AB**: [armbian/build `turing-rk1.csc`](https://github.com/armbian/build/blob/main/config/boards/turing-rk1.csc); [armbian.com/turing-rk1](https://www.armbian.com/turing-rk1/)
- **AV** / **AC**: armbian/build `config/kernel/linux-rk35xx-vendor.config` / `linux-rockchip64-current.config`, `patch/kernel/archive/rockchip64-6.18/`
- **AVD**: [armbian/linux-rockchip@rk-6.1-rkr7.2](https://github.com/armbian/linux-rockchip/tree/rk-6.1-rkr7.2) (`rk3588-turing-rk1.dtsi`, `rk3588s.dtsi`, `rknpu_drv.h`, `rk_crypto_core.c`); armbian/firmware `arm/mali/arch10.8`
- **U**: [Turing RK1 flashing docs](https://docs.turingpi.com/docs/turing-rk1-flashing-os); [firmware.turingpi.com/turing-rk1](https://firmware.turingpi.com/turing-rk1/); Joshua-Riek/ubuntu-rockchip README@v1.33; Joshua-Riek/linux-rockchip@5.10.160-30 (DT line numbers)
- **NIX**: [nixpkgs release-26.05](https://github.com/NixOS/nixpkgs/tree/release-26.05) (`linux-kernels.nix`, `common-config.nix`, `mesa/`)
- **NR**: [GiyoMoon/nixos-turing-rk1](https://github.com/GiyoMoon/nixos-turing-rk1)
- **NH**: [nixos-hardware `raspberry-pi/common/kernel.nix`](https://github.com/NixOS/nixos-hardware/blob/master/raspberry-pi/common/kernel.nix)
- **R**: [raspberrypi/linux@stable_20260911](https://github.com/raspberrypi/linux/tree/stable_20260911) (`bcm2711_defconfig`, `bcm2835-v4l2-codec.c`, `hevc_d.c`). RPi OS on 6.18.34 per 9to5linux.

**Userspace and field reports**
- **MT**: [Mesa Teflon](https://docs.mesa3d.org/teflon.html) · **PF**: [Mesa Panfrost](https://docs.mesa3d.org/drivers/panfrost.html) · **V3D**: [Mesa V3D](https://docs.mesa3d.org/drivers/v3d.html)
- **TV**: [Tomeu Vizoso, "Rockchip NPU update 6: we are in mainline"](https://blog.tomeuvizoso.net/2025/07/rockchip-npu-update-6-we-are-in-mainline.html) · **PH**: [Phoronix](https://www.phoronix.com/news/Rockchip-NPU-Linux-Mesa)
- **DEB**: [Debian #1118656](https://bugs.debian.org/1118656); packages.debian.org `mesa-teflon-delegate`
- **RZ**: [rknn_model_zoo](https://github.com/airockchip/rknn_model_zoo) (README:68) · **RLLM**: [rknn-llm benchmark](https://github.com/airockchip/rknn-llm)
- **FR**: [Frigate discussion #18311](https://github.com/blakeblackshear/frigate/discussions/18311) · **FD**: [freed-dev-llc/turing-rk1-cluster](https://github.com/freed-dev-llc/turing-rk1-cluster) (`docs/NPU-TEFLON.md:18-24`) · **SC**: [schwankner/talos-rk3588-npu](https://github.com/schwankner/talos-rk3588-npu)
- **GDP**: [squat/generic-device-plugin](https://github.com/squat/generic-device-plugin) · **JF**: Jellyfin docs, Rockchip hardware acceleration · **MPP**: [rockchip-linux/mpp](https://github.com/rockchip-linux/mpp) (`osal/mpp_soc.c`)
- **COL**: Collabora, "RK3588 and RK3576 video decoders support merged" · **KH**: [Khronos OpenCL conformant products](https://www.khronos.org/conformance/adopters/conformant-products/opencl)
- **FRD**: [Frigate hardware acceleration](https://docs.frigate.video/configuration/hardware_acceleration_video) · **JG**: [Jeff Geerling, CM4 USB 2.0 overlays](https://www.jeffgeerling.com/blog/2020/usb-20-ports-not-working-on-compute-module-4-check-your-overlays/) · **HEVC**: [linux-media HEVC series](https://ratatoskr.run/linux-media/2026/03/3440071/t)

**Orin**
- **NVIDIA documentation:**
  - **NVD1**: [dev-kit datasheet](https://files.seeedstudio.com/wiki/Jetson-Orin-Nano-DevKit/jetson-orin-nano-developer-kit-datasheet.pdf) (NVIDIA 2659382, Feb 2023)
  - **NVD2**: [Jetson Orin page](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/)
  - **NVD3**: [r36.4.3 power and performance](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html)
  - **NVD4**: [r36.4.3 software encode on Orin Nano](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/Multimedia/SoftwareEncodeInOrinNano.html)
  - **NVD5**: [JetPack 6.2 release notes](https://docs.nvidia.com/jetson/jetpack/6.2/release-notes/index.html)
  - **NVD6**: [r39.2.1 power and performance](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html)
  - **NVD7**: [JetPack 7.2.1 archive](https://developer.nvidia.com/embedded/jetpack/downloads/archive-7.2.1)
  - **NVD8**: [dev-kit quick start](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/quick_start.html)
  - **NVD9**: [r36.4.3 module adaptation](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html)
- **Kernel and firmware source:**
  - **LNX**: torvalds/linux v6.18 `tegra234-p3768-0000+p3767.dtsi`, `tegra-bpmp-thermal.c`, `tegra194-cpufreq.c`
  - **EDK**: [NVIDIA/edk2-nvidia r36.5-updates](https://github.com/NVIDIA/edk2-nvidia/tree/r36.5-updates) (`Dsdt_T234.asl`, `TegraCpuFreqDxe.c`, `ThermalZoneInfoParser.c`, `TegraPwmDxe.c`, `UsbInfoParser.c`)
- **Talos on the Orin:**
  - **I57**: [talos-jetson-orin#57](https://github.com/schwankner/talos-jetson-orin/issues/57)
  - **T8316**: [siderolabs/talos discussion #8316](https://github.com/siderolabs/talos/discussions/8316)
  - **P1518**: [siderolabs/pkgs#1518](https://github.com/siderolabs/pkgs/pull/1518)
  - **TJO**: [schwankner/talos-jetson-orin](https://github.com/schwankner/talos-jetson-orin) (README, `manifests/gpu/`)
- **Other Orin software:**
  - **JN**: [anduril/jetpack-nixos](https://github.com/anduril/jetpack-nixos) @825dfea; issues #319, #450, #478
  - **MTG**: [OE4T/meta-tegra scarthgap](https://github.com/OE4T/meta-tegra/tree/scarthgap) (L4T 36.5.2 `tegra-configs/{devices,drivers}.csv`, `orin-nano.inc`)
  - **AMB**: [antmicro/jetson-orin-baseboard](https://github.com/antmicro/jetson-orin-baseboard)
  - **NVOOT**: [OE4T/linux-nv-oot patches-r36.5](https://github.com/OE4T/linux-nv-oot/tree/patches-r36.5)
- **Kubernetes on Jetson:**
  - **NCT**: [nvidia-container-toolkit](https://github.com/NVIDIA/nvidia-container-toolkit)
  - **KDP**: [k8s-device-plugin v0.20.1](https://github.com/NVIDIA/k8s-device-plugin)
  - **GPUOP**: [GPU Operator platform support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)
  - **NGC**: [l4t-jetpack](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/l4t-jetpack)
- **Turing Pi, Orin-specific:**
  - **TPO**: [Turing Pi Orin NX/Nano flashing](https://docs.turingpi.com/docs/orin-nxnano-flashing-os)
  - **TPG**: [Turing Pi Orin Nano Super setup guide](https://turingpi.com/jetson-orin-nano-super-turing-pi-2-5-setup-guide/)

**Turing Pi 2**
- **TP2**: [specs and I/O ports](https://docs.turingpi.com/docs/turing-pi2-specs-and-io-ports)
- **TP25**: [v2.5 improvements](https://docs.turingpi.com/changelog/turing-pi2-v25-list-of-improvements)
- **TPSM**: [supported modules](https://docs.turingpi.com/docs/turing-pi2-supported-compute-modules)
- **JGT**: [Jeff Geerling, Turing Pi 2 (2021)](https://www.jeffgeerling.com/blog/2021/turing-pi-2-4-raspberry-pi-nodes-on-mini-itx-board/)
- **BMC**: [BMC-Firmware releases](https://github.com/turing-machines/BMC-Firmware/releases), [firmware.turingpi.com](https://firmware.turingpi.com/turing-pi2/)
- **TPI**: [turing-machines/tpi](https://github.com/turing-machines/tpi)
