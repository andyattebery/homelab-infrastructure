# Optane M10, Pi 5 2280 HATs, and the Pi 5 EEPROM

Researched 2026-09-25 (web). **[I]** marks inference.

## Intel Optane Memory M10 16 GB

- **Part numbers** (Intel PCN 117368, 2020-01-14): `MEMPEK1J016GA01`, `MEMPEK1J016GA` and
  `MEMPEK1J016GAXT` are all "M.2 80mm" (2280).
  - Firmware moves from K4110400/K4110410 to K4110440.
  - `MEMPEI1J016GA` (sold as `…GAL`) is the 2242 part. Mapping it to Intel's "16GB, M.2 42mm" ARK
    SKU is inference.
  - `MEMPEK1W016GA` is first-generation Optane Memory. `MEMPEK1F016GA` appears in no Intel
    document.
- **Specs.**
  - ARK: "PCIe 3.0 x2, NVMe", "Power - Active: 2W", "Power - Idle: L1.2 : 8mW", "365 TBW",
    discontinued.
  - Product brief 337302-001: "Active: 3.5W … Drive Idle: 900mW to 1.2W", "200 GB Writes Per Day",
    "M.2 2280-S3-B-M".
  - EOL 2021-01-13.
  - The drive reports 13.41 GiB (actor-framework#1383).
- **Power loss.**
  - ARK has no "Enhanced Power Loss Data Protection" field for the M10.
  - The 905P review (ServeTheHome, 2018-12-14): "Without that DRAM, host writes are acknowledged
    when data is written to the device media."
  - One inventory (GitHub Tanguille/cluster PR #5246, 2026-09-24): "Intel Optane M10 32GB | … |
    [PLP] no | write through, vwc 0".
  - No power-cut test of consumer Optane was found.

## Optane cannot boot on the Pi bootloader (CM4 or Pi 5)

- pcie-devices#511:
  - pxpunx (2023-02-21), CM4: "The M10 would not boot, but the H10 would. However, *both* could be
    used as a secondary (non-boot) disk."
  - BarsMonster (2024-04-12), Pi 5: "M10 16Gb does not boot (Failed to open device 'nvme'), but
    works as data drive". The same user (forum t=368951): the Pi 5 boots a Samsung 970 Pro but
    not the M10.
- **rpi-eeprom#640** (CM4 + M10, bootloader 2024-04-15):
  - Raspberry Pi engineer timg236: "I'm pretty sure we don't support Optane"; it "would require
    custom firmware support and therefore a fairly low priority."
  - On a custom board, Linux only saw the drive after `pcie_tperst_clk_ms` was set to 500.
  - Closed 2025-10-21: "we're not doing anything with it."
- CM4 forum t=347936 (2023): a MEMPEK1J032GAD fails the same way, while booting fine through an
  NVMe-to-USB adapter.
- rpi-eeprom#474 (2023-04-13): MEMPEK1J016GAH on the CM4 IO Board, same failure.
- forum p=2032397 (2022-08-24): M10 and 800p on a Waveshare CM4 base board (B) give "failed to
  open device 'nvme'", while ordinary NVMe drives boot there.
- P1600X also failed to boot (#640 comment; forum t=364927).
- The Compute Blade SSD list: the Optane M10 "will not function as a boot disk".
- **Conclusion:** Optane works only as a root or data disk under Linux, with the boot files on
  another device.

## Pi 5 HAT detection and power (RPi PCIe connector spec 1.1, 2024-01-15)

- The ribbon cable carries "5V power via pins 1 and 2 … each rated at 500mA (for 1A total
  current)", so ~5 W on cable-only boards.
- DET_WAKE pulled high → the "Raspberry Pi will detect this high pull at boot time, and will
  automatically probe the PCIe bus". Other boards need `PCIE_PROBE=1`.
- Bootloader 2023-10-18: "Automatically set dtparam=nvme if booted from nvme".
- The official M.2 HAT+ takes 2230/2242 only and supplies "Up to 3 A".

### Single-slot 2280 boards

| Board | Mount | Detection | 3.3 V | Extra 5 V | Status |
|---|---|---|---|---|---|
| Pimoroni NVMe Base | bottom | follows the spec: "doesn't need this option" | not published | none documented | on sale |
| Geekworm X1001 | top | `dtparam=pciex1`; `PCIE_PROBE=1` if not recognised | max 3.5 A | cable "max 5W" + XH2.54 aux | wiki 2026-08-27 |
| Geekworm X1002 | bottom | `PCIE_PROBE=1` | max 3.5 A | cable + GPIO header | wiki 2026-05-27 |
| 52Pi N04 | top | — | — | — | "production" (Geerling DB) |
| Pineboards HatDrive! Bottom | bottom | `PCIE_PROBE=1` | up to 3 A | optional 4-pin, 2 A @ 5 V | discontinued |
| Waveshare PCIe TO M.2 HAT+ | top | HAT+ EEPROM | — | — | 2230/2242 only |

### Dual-slot boards

| Board | Switch | Sizes | Boot | Power |
|---|---|---|---|---|
| Pimoroni NVMe Base Duo | ASM1182e | 2230–2280 ×2 | "2024-05-17 … or newer" | extra +5 V pads; "Pre-order" |
| Geekworm X1004 | ASM1182e | 2280 only ×2 | EEPROM 2024/05/17+ | "3.3V, max 3.5A + 3.5A" |
| Geekworm X1005 (bottom) | ASM1182e | 2230–2280 ×2 | same | "3.3 V, max 6A" |
| Pineboards HatDrive! Dual | ASM1182e | 2230/2242 | — | — |
| Waveshare 2-CH M.2 HAT+ (B) | "only supports Gen2" | 2230–2280 ×2 | `NVME_CONTROLLER=1`, `BOOT_ORDER=0xf416` | HAT+ |
| Seeed PCIe3.0 dual M.2 HAT+ | ASM2806 (Gen 3) | 2230–2280 ×2 | needs `pcie-fix.dtbo` | pogo 5 V/2 A + cable 5 V/1 A |

**Booting behind a switch:**
- rpi-eeprom 2024-05-13 added "preliminary support for booting NVMe devices behind PCIe switches".
- peterharperuk (firmware#1833): "tested with asmedia and pericom… NVME_CONTROLLER=x".
- 2024-10-21: "Fix PCIe BAR setup issue which prevented NVMe boot from working with some PCIe
  switches".

**Known issues:**
- rpi-eeprom#718 (open since 2025-06-23): a Pineboards HAT with a WD SN530 boots cold but "does
  not find the NVMe device the second time around"; ~50 % success on a 2026-08 bootloader.
- The ASM1182e is a Gen 2 x1 switch shared by both drives (~450 MB/s total).
- Phison E13 ASPM problems behind a switch are fixed with `dtparam=pciex1_no_l0s=on`.
- raspberrypi/linux#7635 (2026-09-21): an X1005 drive disappears on kernels ≥ 6.18.39 / 6.12.96;
  the cause was a defective board trace that older kernels had hidden.

## Pi 5 EEPROM

- **Minimum versions:**
  - NVMe boot: "December 6, 2023 or a later date".
  - Boot behind a switch: 2024-05-13 (vendors say 2024-05-17).
  - 2025-06-09: "NVMe: Fix loading of files > 32MB" (default channel from 2025-11-05).
- **BOOT_ORDER** is read right to left: 1 SD, 4 USB, 6 NVMe, 3 RPIBOOT, f restart. `0xf416` =
  NVMe → SD → USB. Default `0xf41`.
- **`PCIE_PROBE`** is Pi 5 only, default 0.
- **Updating without an SD card:**
  - Raspberry Pi OS booted from USB, then `rpi-eeprom-update -a` / `rpi-eeprom-config --edit`
    (self-update on Pi 5 since 2023-09-13).
  - usbboot `recovery5` from another computer: hold the power button while connecting USB-C.
    `mass-storage-gadget` can expose the NVMe to the host.
  - **The Imager bootloader image is SD-only**: "The ROM found on BCM2711 and BCM2712 does not
    support loading recovery.bin from USB mass storage or TFTP."
- nixpkgs `raspberrypi-eeprom` (2026.05.11-2712, not unfree) wraps flashrom on PATH
  (`pkgs/by-name/ra/raspberrypi-eeprom/package.nix:51-62`), so it can run from NixOS.
