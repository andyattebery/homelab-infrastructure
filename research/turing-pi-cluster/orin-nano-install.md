# Jetson Orin Nano in a Turing Pi slot: install paths

Researched 2026-10-02; the SD image findings, `UDA`, cloud-init, the capsule command and the first boot updated 2026-10-03. **[I]** marks inference; **U** means unverified. Pinned to JetPack 7.2.1 (Jetson Linux R39.2.1) and JetPack 6.2.3 (R36.5.2). This follows [hardware-support.md](hardware-support.md) ("Moving the Orin into a Turing Pi 2 slot") and [os-alternatives.md](os-alternatives.md).

What came of it (2026-10-03): a generic SD image built in GitHub Actions by [jetson-orin-nano-l4t-minimal](https://github.com/andyattebery/jetson-orin-nano-l4t-minimal). Each card gets its hostname, user and keys at first boot from cloud-init seed files. This homelab's are in [turingpi/jetson/cloud-init/](../../turingpi/jetson/cloud-init/), and the procedure is in [turingpi/jetson/README.md](../../turingpi/jetson/README.md). The first card, release R39.2.1-2, booted this module in node 4 the same day. The image repo builds new R39.x releases automatically, from a daily check of NVIDIA's Jetson Linux archive page; a newer major only opens an issue.

The question: does putting jetson-01's Orin Nano (P3767-0005) into a Turing Pi 2.5 slot mean NVIDIA's "JetPack installer" and Ubuntu with a desktop, or are there other ways to get NVIDIA's kernel, CUDA and NVDEC? And can the OS live on its own boot medium, so the NVMe holds only data?

## Bottom line

- **One QSPI flash from an x86-64 host is unavoidable in a Turing Pi slot, whatever the OS.**
  - The board "does not have the onboard EEPROM", and stock firmware hangs in MB2: "E> eeprom: Failed to read I2C slave device", "I> Busy Spin" (NVIDIA forum).
  - The fix is `cvb_eeprom_read_size = <0x0>` in the MB2 BCT (NVIDIA's adaptation guide, "EEPROM Modifications").
  - NVIDIA's flash tools are x86 only: in R39.2.1 they are 32-bit i386 ELF binaries.
- **Neither SDK Manager nor the JetPack 7.2.1 ISO:**
  - SDK Manager: "does not support flashing of the Orin modules in the third-party boards" (Turing).
  - The ISO: for dev kits; it applies NVIDIA's stock bootloader package, which undoes the fix [I].
  - NVIDIA's command-line BSP can flash QSPI only, or QSPI plus an NVMe/SD/USB root in one run.
- **The OS can live on the module's own microSD, with the NVMe left for data:**
  - QSPI once: `flash.sh --no-systemimg -c bootloader/generic/cfg/flash_t234_qspi.xml`.
  - A `dd`-able SD image from the BSP's `jetson-disk-image-creator.sh`, built on x86 without the module. NVIDIA booted an R39.2 image from it in an internal test. Nothing grows its root on R39.2: NVIDIA dropped `nvresizefs` (forum 380597).
  - The card must be ≥ 64 GB.
- **Headless doesn't need the desktop.** The sample rootfs *is* GNOME; `nv_build_samplefs.sh` builds `minimal` or `basic` instead.
- **Firmware updates are the trap.** NVIDIA's bootloader package re-stages its stock capsule (EEPROM read on), and a boot-time service triggers it whenever the package is newer than QSPI.
  - Hold every `nvidia-l4t-*` package and set `ENABLE_AUTO_QSPI_UPDATE="0"`.
  - Upgrade QSPI and the OS together: QSPI must match the JetPack on the card.
- **Other distros with NVIDIA's kernel or kernel modules and a working GPU exist for the Orin Nano:**
  - Canonical Ubuntu Server 22.04 (certified, R36 firmware)
  - RHEL 9.8 / Red Hat Device Edge (GA)
  - OE4T meta-tegra
  - jetpack-nixos
  - balenaOS v8
  - SUSE Linux Micro 6.2

  All need the same x86 QSPI flash. Mainline-kernel distros boot CPU-only.

## Install paths in a Turing Pi slot

| Path | In a slot? | Why |
|---|---|---|
| SDK Manager (GUI) | No | "does not support flashing of the Orin modules in the third-party boards" (Turing). Its Docker mode "does not currently support flashing to external storages on all Jetson devices" |
| JetPack 7.2.1 ISO (bootable USB installer) | No [I] | See the ISO details below |
| `l4t_initrd_flash.sh` from an x86-64 host | Yes (Turing, P3767-0005, R39.2.1) | QSPI plus the NVMe/USB/SD root in one run |
| QSPI-only `flash.sh` + an SD image from `jetson-disk-image-creator.sh` | Yes (this module, node 4, R39.2.1, 2026-10-03) | OS on microSD, rewritable from any machine with `dd` |

**The JetPack 7.2.1 ISO, why not:**
- What it is: "Jetson ISO lets you install the Jetson BSP (Jetson Linux) directly on the developer kit without using an Ubuntu host PC." It runs the UEFI capsule update first if QSPI is still JP6-generation.
- What it does to the bootloader: it "pulls the Debian package during installation and applies the BUP or capsule like any other bootloader update". BCT changes need a custom `nvidia-l4t-bootloader` package repacked into the ISO.
- It needs JetPack 6.x-generation QSPI already booting, which this board doesn't have.
- It installs "L4T Ubuntu 24.04" with a desktop and oem-config.
- The 8 GB Nano can't use network install: "UEFI HTTPv4 boot requires a Jetson device with at least 16 GB of RAM".
- On a dev kit with QSPI already at 39.2.1, the installer skips the capsule ("No need to trigger capsule update") [I from code].
- Known issue 6236205: "Jetson IO tool fails on Jetson Orin Nano Super devices when flashed using ISO images."

## The command-line flash (R39.2.1)

**Host**
- Architecture: "An x86-64 Linux build machine" (r39.2.1). The BSP tools (`tegrarcm_v2`, `tegrabct_v2`, `mksparse`, `mkbootimg`, …) are ELF 32-bit i386.
- OS version:
  - The R39.2.1 release notes list "Ubuntu 24.04 and 22.04". The Quick Start still says 22.04/20.04.
  - Turing used an Ubuntu 22.04 live USB.
- VMs: an NVIDIA moderator said "No, not support." (forum, 2024).
- NGC's `jetson-linux-flash-x86` container stops at r36.4.

**Recovery and config**
- The node is put into recovery by the BMC: `tpi power off --node N`, `tpi usb flash --node N`, `tpi power on --node N`.
- The cable runs from the board's `USB_OTG` USB-C port to the host.
- `lsusb` shows `0955:7523`: "7523 for Jetson Orin Nano (P3767-0003 and P3767-0005 with 8GB)".
- Config: `jetson-orin-nano-devkit-super`. It "has a higher power budget and extended clock-frequency steps". NVIDIA's on-device tooling forces the -super capsule for SKU 0005, and a 36.x QSPI under JP7.2 lost the 25 W modes (forum 377553).
- P3767-0005 storage: no eMMC. NVIDIA: "Flashes QSPI-NOR and microSD Card/USB/NVMe drive (only supported via l4t_initrd_flash.sh)".

**One run, QSPI plus the external root** (r39.2.1 Quick Start):
- NVMe: `sudo ./l4t_initrd_flash.sh --erase-all jetson-orin-nano-devkit-super internal`. NVMe is the default target.
- SD: add `--external-device mmcblk0p1`.
- USB: add `--external-device sda1`.
- Turing's guide used the NVMe form, with `l4t_create_default_user.sh -u … -p … -n … --accept-license` before it and `apt install nvidia-jetpack` after.

**QSPI only** (r39.2.1 FlashingSupport):
- "To flash only QSPI on Jetson Orin series: `$ sudo ./flash.sh --no-systemimg -c bootloader/generic/cfg/flash_t234_qspi.xml <board> <rootdev>`". The same line is in r36.5.2.
- NVIDIA staff (forum 376777) gave `… jetson-orin-nano-devkit internal`, and said it "can generally be used even if the Jetson Orin Nano Dev Kit SOM is installed on a different carrier board".
- "Flashing in Two Phases": `tools/qspi_flash/generate_qspi_for_flash.sh <board>`, then `hostflash/host_flash_qspi.sh`. This writes the whole 64 MB QSPI (both A/B slots and the UEFI variables) and verifies by reading back. Host: x86 only.
- `l4t_initrd_flash.sh --qspi-only` is documented for Thor only.

**The EEPROM fix reaches every QSPI path**
- `p3767.conf.common:219` sets `MB2_BCT="tegra234-mb2-bct-misc-p3767-0000.dts"`, and the -super, -qspi, `generate_qspi_for_flash.sh` and capsule paths all source it.
- NVIDIA names only `bootloader/generic/BCT/tegra234-mb2-bct-misc-p3767-0000.dts`. That file overrides the eeprom block in `bootloader/tegra234-mb2-bct-common.dtsi`. Community tools patch both.
- Don't confuse it with `SKIP_EEPROM_CHECK`, which is only for "CRC-8 checksum bit corruption".

**JetPack 6.2.3 / R36.5.2 one-run equivalent:**
```
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 -c tools/kernel_flash/flash_l4t_t234_nvme.xml -p "-c bootloader/generic/cfg/flash_t234_qspi.xml" --showlogs --network usb0 --erase-all jetson-orin-nano-devkit-super internal
```

## OS on microSD, NVMe for data

**SD images: no longer published, but the tool still ships**
- "Starting with JetPack 7.2, SD Card images are no longer supported. Do not flash the Jetson ISO to a microSD card." No prebuilt image is published.
- The tool still ships in the R39.2.1 BSP: `tools/jetson-disk-image-creator.sh -o <img> -b jetson-orin-nano-devkit-super -d SD`.
  - It runs `BOARDID=3767 BOARDSKU=0005 FAB=300 BUILD_SD_IMAGE=1 … flash.sh --no-flash --sign`, then `sgdisk`/`losetup`.
  - The default revision of 300 matches SKU 0005; the docs' `-r 100` looks wrong [I].
  - Host: x86 Linux with root. No module or recovery needed.
  - Writing: `dd if=<img> of=/dev/mmcblk<n> bs=1M oflag=direct`.
  - `-d` is required. The script rejects NVIDIA's documented line without it: "Incorrect root filesystem device" (forum 380597, post 17).
- **Scope, and a doc error** (r39.2.1 Flashing Support):
  - The section "Flashing to an SD Card" says "Applies to: only the Jetson Orin Nano Developer Kit … with the p3767-0005 module".
  - Its subsection "Generating an Image to be Flashed to an SD Card" says "Applies to: only the Jetson Orin NX series", but its own example is `-b jetson-orin-nano-devkit -r 100`. The subsection line is the error.
  - The code agrees with the section:
    - the script hard-codes SKU `0005` for both `jetson-orin-nano-devkit` configs (lines 213-224);
    - `flash.sh` accepts SD layouts for board 3767 only with SKU 0005 (lines 2811-2813).
- **Does its R39.2 output boot?**
  - NVIDIA, 2026-08-26: "In our internal test, the generated image booted successfully from a 256 GB microSD card".
  - NVIDIA, 2026-09-02: "On R39.2 the image from jetson-disk-image-creator.sh never expands, so the root filesystem stays at its generated size with no free space. Up to R36.5 this expansion was done on first boot by nvresizefs, which R39.2 no longer ships."
  - The script sizes `APP` at the rootfs plus 10% plus 100 MiB (lines 273-275). NVIDIA's docs leave "Resizing the Root Partition" to oem-config, which the minimal rootfs doesn't have. cloud-init's growpart and resizefs do the job instead.
  - This module, 2026-10-03: yes. The generic image's R39.2.1-2 booted from microSD in node 4, and growpart grew `APP` to 56.5G on the 58G card.
- Fallback (documented): initrd-flash README Workflow 11, `--direct`, which writes a bootable SD or USB attached to the host, given `BOARDID`/`FAB`/`BOARDSKU`/`BOARDREV`.

**SD as the root device**
- A documented target in the Quick Start, the ISO and the configuration table.
- Size: "the storage size must be 64GB or larger".
- Performance: NVMe is "recommended if you want more capacity and better storage performance".
- Endurance: U.
- Rootfs A/B on SD exists: `flash_t234_qspi_sd_rootfs_ab.xml`.
- A forum report: an ISO install to microSD on R39.2 failed on 2 of 3 dev kits, and an initrd flash fixed it.

**Boot layout and order**
- The SD layout (`flash_t234_qspi_sd.xml`) is A/B kernel and kernel-dtb partitions, recovery, `esp`, `UDA`, then `APP` last, which is why it can be grown.
- **`UDA`, 400 MiB:** "**Required.** This partition may be mounted and used to store user data."
  - Only flashing touches it:
    - `flash.sh --uda-dir` builds an encrypted UDA for disk encryption (`flash.sh:336,4334-4352`);
    - the initrd flash skips it unless given that image (`l4t_flash_from_kernel.sh:1001-1004`);
    - the bootloader's USB-recovery flash server lists it among special partition names, in the strings of the `TEGRA_BL_*.Cap` capsules.
  - Nothing at runtime does. None of the 77 R39.2.1 packages, the initrd, `tools/ota_tools` or `tools/backup_restore` reference it (2026-10-03).
  - With no explicit GUID, its type is `8300` (`nvptparser.py:19`).
- L4TLauncher (`EFI/BOOT/BOOTAA64.efi` on the ESP) reads `/boot/extlinux/extlinux.conf` from the `APP` partition, and falls back to the kernel partitions.
- Default order:
  - The UEFI page says removable media come first. But the shipped `L4TConfiguration.dtbo` has `DefaultBootPriority = "usb,nvme,emmc,sd,ufs"`: NVMe before SD.
  - `BootOrderSD.dtbo` ships in the BSP (`DefaultBootPriority = "sd"`). It's applied at flash time with `ADDITIONAL_DTB_OVERLAY` [I]. "This method only sets the default boot order on the first boot after flashing."
  - Later changes: the UEFI menu (ESC, then Boot Maintenance Manager) or `efibootmgr`.
- A data-only NVMe with no ESP: NVIDIA's EDK2 creates a boot option for every disk, tries each in turn and moves on when one fails [I from the source].

**USB boot from node 4's ports**
- They sit behind a VL805 PCIe controller.
- EDK2 for Orin includes generic PCI xHCI and USB mass storage [I], but no report of a Jetson booting from them was found (U).
- NVIDIA: "Jetson devices can be booted from a mass storage class USB device… Hot plugging is not supported."

## Headless root filesystems

**`nv_build_samplefs.sh` flavors** (r39.2.1 and r36.5.2 Root File System pages):
- **desktop:** "the same as the NVIDIA prebuilt sample root file system, which includes the Ubuntu Desktop with a slightly modified version of the GNOME Desktop Environment".
- **minimal:** "does not provide the GUI mode, and all manipulations can be completed only by using the SSH or UART console". It "does not also provide an OEM configuration, so we recommend that you create a default user before you flash".
- **basic:** "the smallest root file system… contains the dependencies for BSP and NVIDIA Docker". You "must create a default user before you flash".

**Running it**
- R39.2.1: `sudo ./nv_build_samplefs.sh --abi aarch64 --distro ubuntu --flavor minimal --version noble`. "The script can be executed only on an Ubuntu 24.04 host."
- Other hosts use Docker: `docker run --privileged … ubuntu:24.04`, then `apt-get install -y qemu-user-static wget sudo bzip2`.
- Time: "Depending on the Internet speed of your host machine, it might take several hours to run."
- An arm64 host works behind an `arch` shim that prints `x86_64`, for the script's only host check (`arch | grep x86_64`, line 106).
  - 2.5 minutes on an M4 Mac (2026-10-02).
  - In CI, 4 minutes on GitHub's arm64 runner, against 73 under qemu on x86 (2026-10-03).

**Skipping first-boot setup and the desktop**
- `l4t_create_default_user.sh -u -p -n --accept-license` skips oem-config. Its `-a` turns on autologin [I].
- After a desktop install: `sudo systemctl set-default multi-user.target` (NVIDIA Holoscan docs).

**cloud-init on L4T** (R39.2.1 packages, read 2026-10-03)
- NVIDIA ships it neutralized. `nvidia-l4t-configs` installs:
  - `/etc/cloud/cloud.cfg.d/99-disable-cloud-init.cfg`: `datasource_list: [None]`, plus user-data that turns off growpart and resize and writes `/etc/cloud/cloud-init.disabled`;
  - `/etc/cloud/ds-identify.cfg`: `policy: enabled`.
- NVIDIA's rootfs scripts expect it to be installed:
  - `nv_customize_rootfs.sh:99-119`, run at the end of `apply_binaries.sh`, comments out cloud-init's default user and hands networking to NetworkManager.
  - `nvfb-ssh-keygen.service` skips itself when `/lib/systemd/system/cloud-init.service` exists.
- The `minimal` package list (986 packages) has no cloud-init.
- **Seed:** NoCloud reads `user-data` and `meta-data`, both required, from a vfat or iso9660 filesystem labelled `CIDATA` (cloud-init 26.1, `DataSourceNoCloud.py:52-60,101`).
- **Enabling it** takes a `cloud.cfg.d` file that sorts after NVIDIA's, with `datasource_list: [NoCloud, None]`. The lexically last file wins a key (`util.py`, `read_conf_d`).
- Raspberry Pi OS has used the same seed files on its FAT boot partition since Trixie (2025-11-27).
- **First boot on this module** (R39.2.1-2, 2026-10-03): NoCloud found the seed (`DataSourceNoCloud [seed=/dev/mmcblk0p14]`) and applied the user, keys and hostname.
- **The clock is at 1970 on the first boot.**
  - cloud-init's log read `1970-01-01 00:00:56`.
  - apt refused Ubuntu's indexes: "Release file … is not valid yet (invalid for another 20729d)".
  - DNS also failed: "Temporary failure resolving".
  - `cloud-final.service` (26.1) is `After=network-online.target time-sync.target`, but neither target waits here:
    - NVIDIA masks `NetworkManager-wait-online` (`nv_customize_rootfs.sh:80-85`, "for Bug 200290321");
    - systemd ships `systemd-time-wait-sync` disabled.
  - **The fix:** image releases after R39.2.1-2 enable it, so the final stage waits for NTP. NVIDIA's mask stays.
  - **What else waits:** only the calendar timers, such as `apt-daily`.
    - No NVIDIA unit in the 77 debs is ordered after `time-sync.target`.
    - NVIDIA disables `isc-dhcp-server` and `isc-dhcp-server6` (`nv_customize_rootfs.sh:42-52`), the only Ubuntu units that would otherwise have held `multi-user.target`.

## Firmware updates after the first flash

**What NVIDIA says** (r39.2.1 Update and Redundancy, OTA)
- "OTA updates ensure that the firmware, userspace, and driver packages remain consistent, aligning the firmware version in the QSPI with the corresponding versions in the Linux userspace and kernel drivers. NVIDIA advises against installing a combination of packages from different releases."
- NVIDIA staff: "the QSPI version must match the JetPack version flashed onto the SD card".

**How a stock update reaches QSPI** (the 39.2.1 package scripts)
- `nv-l4t-bootloader-config.service` runs on every boot. For SKU 0005 it runs `dpkg-reconfigure nvidia-l4t-bootloader` whenever the package version is newer than QSPI.
- The package's install script stages the stock `TEGRA_BL_3767_super.Cap` with `fwupdtool install-blob`, with no version check of its own. Without fwupd, which NVIDIA's minimal rootfs lacks, it exits 1 before staging. The generic image adds fwupd (2026-10-03), so on its cards that exit no longer stands in the way ([orin-nano-qspi-updates.md](orin-nano-qspi-updates.md)).
- The stock capsule restores `cvb_eeprom_read_size = <0x100>` [I].
- Capsules update the non-current slot, and a failed slot is marked `unbootable`. Whether that rescues an MB2 hang is U.
- Turing went from R39.2.0 to R39.2.1 by apt and the node came back. They never checked the QSPI version.

**Locking it**
- Hold `nvidia-l4t-bootloader` and `nvidia-l4t-bootloader-utils`. Its exact-version dependency also pins `nvidia-l4t-jetson-io`.
- Better, hold every `nvidia-l4t-*`, so userspace doesn't drift from QSPI.
- Set `ENABLE_AUTO_QSPI_UPDATE="0"` in `/opt/nvidia/l4t-bootloader-config/nv-l4t-bootloader-config.conf`. It's not a conffile, so a `-utils` upgrade would overwrite it.
- Never `dpkg-reconfigure` or `--reinstall` the bootloader package.
- Check: `/sys/class/dmi/id/bios_version` matches `/etc/nv_tegra_release`, and `nvbootctrl dump-slots-info` shows "Capsule update status: 0".

**Upgrading on purpose**
- A QSPI-only reflash from the host.
- Or a capsule from the patched tree. This module needs `t23x_3767_bl_super_spec`. NVIDIA's documented `t23x_3767_bl_spec` builds non-super images, which this module's spec never matches ([orin-nano-qspi-updates.md](orin-nano-qspi-updates.md)):
  ```
  sudo ./l4t_generate_soc_bup.sh -e t23x_3767_bl_super_spec t23x
  ./generate_capsule/l4t_generate_soc_capsule.sh -i bootloader/payloads_t23x/bl_only_payload -o ./TEGRA_BL.Cap t234
  ```
  Then on the node: `nv_bootloader_capsule_updater.sh -q TEGRA_BL.Cap` and reboot. The mechanism is documented; on this board it's [I].
- Or through apt, from a private repo that carries the release with NVIDIA's bootloader package rebuilt around that capsule ([orin-nano-qspi-updates.md](orin-nano-qspi-updates.md)).

## Other distros on NVIDIA's kernel, Orin Nano

| Distro | GPU/CUDA | NVDEC | Install | Carrier without an EEPROM |
|---|---|---|---|---|
| NVIDIA JetPack 7.2.x (Ubuntu 24.04; minimal/basic rootfs for headless) | Y | Y (decode; no NVENC on Nano) | `l4t_initrd_flash.sh`, or QSPI-only + SD image, from x86 | Y (Turing) |
| Canonical Ubuntu Server 22.04, certified (`linux-nvidia-tegra-jetson`, 5.15) | Y: `ppa:ubuntu-tegra/updates`, `nvidia-tegra-drivers-36`, then NVIDIA's r36.5 repo and `cuda` | Y [I] | R36 QSPI via `flash.sh` from x86, then a raw `.img` via `dd` to SD/USB/NVMe (GRUB). 24.04 is Thor-only | Y [I] with the BCT edit; needs R36 firmware |
| Ubuntu Core 22 (24 announced, no download found) | Y [I] | U | raw image + R36 QSPI | Y [I] |
| OE4T meta-tegra: scarthgap = R36.5.2; wrynose/blacksail/master = R39.2.1 | Y (CUDA 13.2.2 on R39) | Y [I] | build `demo-image-base` yourself, then `./initrd-flash` from x86 | Y: documented `TEGRA_FLASHVAR_MB2BCT_CFG` override |
| jetpack-nixos (JP5/6/7) | Y | Y (V4L2 + GStreamer) | flash script (x86-64 only) for QSPI, then an installer ISO | Y [I] via `flashScriptOverrides.postPatch`; officially dev kits only |
| balenaOS v8 (L4T 39.2) | Y in containers | U | jetson-flash in privileged Docker on x86, or a USB flasher once UEFI ≥ 36.3 boots | Y [I]: its flasher disables the read |
| SUSE Linux Micro 6.2 | Y (kernel-module packages) | U | x86 firmware flash first | Y [I] with the edit |
| RHEL 9.8 / Red Hat Device Edge (GA 2026-05-12) | Y (NVIDIA kmods + L4T containers) | Y (`nvv4l2decoder`) | x86 QSPI flash + RHEL image | Y [I] with the edit |
| Fedora, Debian (mainline) | **N** (no GA10B driver) | N [I] | generic arm64 UEFI | — |
| Talos, official / community fork | N / U on Nano (P3767-0005 boot-loops in DT mode) | N/U | — | — |

## Turing Pi specifics

- **Turing's 2026-08-20 guide:**
  - Board 2.5.2, node 2 ("repeatedly encountered USB transfer failures" in node 1).
  - Cable from `USB_OTG` (USB-C) to the host; Ubuntu 22.04 live host.
  - Crucial P310 NVMe root; R39.2.0, then R39.2.1.
  - "make sure an appropriate heatsink and active cooling solution are installed".
- **Node 4:** the M.2 T4 slot, and 4× USB 3.0 behind the VL805. The 2.5 board's new USB-A port goes to node 1 only, and each node's first USB port goes to the internal flashing hub. Node 4 recovery on board 2.5 is untested for a Jetson (U).
- **Community tool:** Hi5808/turing-pi-2.5-jetson-eeprom-fix does a QSPI-only reflash ("Your NVMe is never touched"). Tested on P3767-0003, not 0005.

## Open

- Whether the wait for NTP works on this module: the first release with it hasn't booted yet.
- `BootOrderSD.dtbo` at QSPI flash time: [I].
- microSD endurance: U.
- USB boot behind the VL805: U.
- Node 4 recovery on board 2.5: U.
- Fan-header wiring and sustained 25 W per slot: U.
- Whether the stock capsule actually breaks boot on this board, or A/B fallback saves it: [I], not observed.

## Sources

**NVIDIA documentation**
- Jetson Linux r39.2.1 Developer Guide: Quick Start; Flashing Support (QSPI-only, Flashing in Two Phases, jetson-disk-image-creator); Root File System; Update and Redundancy; Software Packages and the Update Mechanism; UEFI; Jetson ISO Customization; Module Adaptation, Orin NX/Nano ("EEPROM Modifications"). Base URL: https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/
- R39.2.1 release notes (PDF).
- The same Developer Guide pages for r36.5.2.
- Orin Nano dev-kit quick start and update_firmware pages: https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/
- JetPack 7.2.1 archive: https://developer.nvidia.com/embedded/jetpack/downloads/archive-7.2.1
- BSP: `Jetson_Linux_R39.2.1_aarch64.tbz2`, 1287223769 bytes, last-modified 2026-08-11. Read inside: `p3767.conf.common`, `flash.sh`, `tools/jetson-disk-image-creator.sh`, `tools/qspi_flash/`, `bootloader/generic/cfg/flash_t234_qspi_sd.xml`, the BootOrder dtbos.
- `nvidia-l4t-bootloader` and `nvidia-l4t-bootloader-utils` 39.2.1 package scripts; edk2-nvidia tag `r39.2.1`.
- 2026-10-03, read inside the BSP: `tools/l4t_create_default_user.sh`, `apply_binaries.sh`, `nv_tools/scripts/nv_customize_rootfs.sh`, `tools/nvptparser.py`, `tools/samplefs/nvubuntu_samplefs.sh`; the `nvidia-l4t-configs`, `-firstboot`, `-oobe`, `-init`, `-apt-source` and `-bootloader` packages; all 77 packages and `bootloader/l4t_initrd.img` searched for `UDA`; the license, `Tegra_Software_License_Agreement-Tegra-Linux.txt`.

**Forums**
- NVIDIA forum threads 278468 and 308407 (the EEPROM hang), 313442 (VMs), 376777 (QSPI on another carrier), 377553 (QSPI mismatch, missing 25 W), 376673 (an ISO install to microSD failing).
- Release announcements 379954 (JetPack 7.2.1) and 379873 (JetPack 6.2.3).
- 380597 (jetson-disk-image-creator.sh on R39.2: the internal test booted; never expands; nvresizefs dropped).

**cloud-init and Raspberry Pi OS**
- cloud-init 26.1 docs (docs.cloud-init.io/en/26.1: NoCloud, base config, modules, disabling) and source at tag `26.1` (`DataSourceNoCloud.py`, `util.py`, `stages.py`, `tools/ds-identify`, `config/cloud.cfg.tmpl`, `systemd/`). Ubuntu noble ships `26.1-0ubuntu1~24.04.1`.
- Ubuntu's `26.1-0ubuntu1~24.04.1` package, read 2026-10-03: its systemd units, `cloud.cfg` and `cmd/`.
- systemd 255 on noble (`255.4-1ubuntu8.17`): man pages `systemd-time-wait-sync.service`(8), `systemd.timer`(5) and `systemd.target`(5) at manpages.ubuntu.com, and the units of the minimal rootfs and the 77 R39.2.1 debs (2026-10-03).
- raspberrypi.com/news/cloud-init-on-raspberry-pi-os (2025-11-27).

**Turing Pi**
- docs.turingpi.com "orin-nxnano-flashing-os" (updated 2025-11-12), "turing-pi2-specs-and-io-ports", "tpi-uart", and the 2.5 changelog.
- turingpi.com "NVIDIA Jetson Orin Nano Super on Turing Pi 2.5: Complete Setup Guide" (2026-08-20).
- github.com/Hi5808/turing-pi-2.5-jetson-eeprom-fix; gist dudo/4093b5d14f2b003cad507e4f4ac1aa83.

**Other distros**
- Canonical: ubuntu.com/download/nvidia-jetson; canonical-ubuntu-for-jetson.readthedocs-hosted.com (how-to/flash, classic/jp-installation, release notes); Launchpad `linux-nvidia-tegra`.
- OE4T: oe4t.github.io (Which branch, wrynose Flashing); meta-tegra `docs/Creating-a-custom-MACHINE.md`; tegra-demo-distro.
- jetpack-nixos @825dfea: README, `modules/flash-script.nix`, `overlay-with-config.nix`, `devices.nix`.
- balena: docs.balena.io device types; balena-os/balena-jetson-orin; balena-os/jetson-flash `Orin_Flash/flash_orin.sh`.
- Red Hat: RHEL 9.8 Jetson Orin GA.
- SUSE: SL Micro 6.2 JetPack 6.2.2 driver kit.
