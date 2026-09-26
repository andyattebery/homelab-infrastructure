# CM4 path: a Compute Module 4 Lite with NVMe

Researched 2026-09-25. **[S]** means source, **[E]** means an eval run against this repo, and
**[I]** marks inference. "Docs" means raspberrypi/documentation@34dfb87 (2026-09-23). "Datasheet"
means the CM4IO datasheet (build date 2022-06-07). "KiCad" means the CM4IO design files
(2022-06-15).

The owner has a CM4 **Lite** (no eMMC) and the official CM4 IO Board, a Waveshare CM4-IO-BASE, and
other carriers.

## Official CM4 IO Board

- [S] §2.8: "PCIe Gen 2 x1 socket". KiCad: J12 "PCIe x1 connector", 10018783-11200TLF.
- **The slot is closed-ended.** [S] Jeff Geerling ([pcie-devices#3](https://github.com/geerlingguy/raspberry-pi-pcie-devices/issues/3),
  2020-10-22): "an x4 card… won't slot into the stock PCIe x1 slot… I bought an x16 to x1 riser".
  x4 M.2 adapters need a riser.
- **Slot power:** [S] KiCad notes: "NB PCIe x1 takes a maximum of +12v @0.6A or +3.3v@3A ,
  10Watts combined" and "3.3v @ 3.3A PSU for PCIe Only ( 12v Input )".
- **Board power:**
  - [S] §2.2: J19 "2.1mm DC tip positive +12V input". The 3.3 V converter "is only used for the
    PCIe slot".
  - [S] introduction.adoc:253: "5 V through the GPIO header… supports up to 26 V if PCIe is
    unused". Feeding 5 V means removing L5, which "will prevent the on-board +5V and +3.3V supplies
    from starting up".
  - [S] §2.4: with a PoE HAT, "PCIe expansion cards… will not function".
  - [I] NVMe here needs the 12 V barrel.
- **Jumpers:** [S] J2 "1-2 nRPIBOOT - if fitted, forces USB booting"; "3-4 EEPROM_nWP". micro-USB
  **J11** is the USB slave port (cm-emmc-flashing.adoc:42).
- [S] §2.8: "successfully used with an NVMe drive via a passive PCIe adaptor"; "Booting isn't
  supported via a PCIe switch"; no MSI-X.

## Waveshare CM4-IO-BASE A/B

- [S] Both: "M KEY, which only supports PCIE channel devices"; power "5V/2.5A" over USB-C; "does
  not support the POE function". A only: "M.2 interface power supply is limited to 1.5A… buy
  version B."
- **Lengths:** [S] forum t=332911 (2022-04-12): "2230 or 2242 NVMe's only"; a 2280 "will require
  some mechanical fixture".
- [S] forum p=2032397: M10 and 800p on a "Mini Base Board (B)" give "failed to open device 'nvme'",
  while ordinary NVMe drives boot there.

## NVMe boot and usbboot from a Mac

- **Minimum EEPROM:** 2021-03-04 beta "NVMe boot mode "6""; stable for CM4 on 2021-07-07.
  usbboot@3090a13 (2026-08-17) ships pieeprom-2026-05-17.
- **BOOT_ORDER:** `0xf6` (cm-bootloader.adoc:46); `0xf46`, "Try NVMe first, followed by USB-MSD"
  (eeprom-bootloader.adoc:150).
- **Build on macOS** (Readme.md:101-112):
  ```
  git clone --recurse-submodules --shallow-submodules --depth=1 https://github.com/raspberrypi/usbboot
  cd usbboot && brew install libusb && brew install pkg-config
  make INSTALL_PREFIX=/usr/local
  sudo ./rpiboot -d mass-storage-gadget64
  ```
  The owner's Mac (macOS 26.5.2 arm64) already has libusb 1.0.30, pkg-config, python3 and
  sha256sum. Caveats: usbboot#397 (build fails on the macOS 27 SDK), and an RPi engineer "can't
  gurantee that it will work on every Mac" (#314).
- **EEPROM flash:** `cd recovery; ./update-pieeprom.sh; ../rpiboot -d .`. J2 pins 3-4 must be open.
- **Mass-storage gadget** (Readme lists CM4): it "scans for SD/EMMC, NVMe, and USB block devices
  and… expose[s] them as USB mass-storage devices". usbboot#394 shows an NVMe in macOS Disk
  Utility (on a CM5).
- **RAM size:** `sudo rpiboot -j metadata -d .` writes `USER_BOARDREV`, and memory size is in bits
  20–22.

## BCM2711 PCIe caveats

- [S] bcm2711.dtsi:577-583 (raspberrypi/linux@c8c7494): "a bug preventing it from accessing
  beyond the first 3GB". [I] The kernel handles it transparently via swiotlb, at the cost of
  bounce buffers on 4/8 GB modules.
- **Optane on CM4:** every report is "won't boot, works as data disk" (see
  `optane-and-pi5-hats.md`).

## nixos-raspberrypi (rev 7e39508) and CM4

- There is no separate CM4 module. `raspberry-pi-4.nix:22-24` has `"nvme" # cm4 may have nvme
  drive`. `configtxt.nix:93-103` sets `[cm4] otg_mode=1`. The kernel builds
  `bcm2711-rpi-cm4.dtb`.
- [E] The DTB filter is null and there are no overlays; `install-device-tree.sh:55` copies
  `broadcom/*.dtb` into `nixos/<gen>/`. That matters because `os_prefix` "is ignored" unless the
  kernel and .dtb are there (boot.adoc:107).
- [E] config.txt sections are `all`, `cm4` and `cm5`: `os_prefix=nixos/default/`,
  `kernel=kernel.img`, `[cm4] otg_mode=1`, and it ends with `initramfs initrd followkernel`.
- [I] Without `otg_mode` the IO Board's USB ports stay off; pi-rack doesn't need them (NUT uses
  SNMP).
- **Issues:**
  - #181 (open, 2026-04-29): CM4 on the official IO Board with the installer (U-Boot) image —
    random crashes, no Ethernet, no USB keyboard.
  - #60 (open) calls `kernel` "the only fully-supported option for RPi5".
  - **No report of `kernel` on a Pi 4 / CM4** was found.
- **U-Boot fallback:** [E] the flake's U-Boot 2026.04 `rpi_arm64_defconfig` has no NVMe;
  `boot_targets=mmc usb pxe dhcp`. The NixOS wiki (2026-07-18): "released U-Boot can [not] load
  the NixOS boot files from NVMe".

## Why the CM4 path was dropped

- The slot's 3.3 V @ 3 A would carry an 8 W enterprise drive at ~80 %.
- The owner's x4 adapters need a riser.
- It needs 12 V (PoE disables PCIe).
- `kernel` on BCM2711 is unproven.
- The Pi 5 + X1001-Max has more power headroom and the upstream-exercised boot path.
