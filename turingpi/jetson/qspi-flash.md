# Jetson Orin Nano: flashing QSPI for the Turing Pi

The Turing Pi 2 has no carrier-board EEPROM, and NVIDIA's stock boot firmware hangs in MB2 trying
to read one. So before the module boots in a Turing Pi node, its QSPI boot flash needs NVIDIA's
firmware with the carrier-EEPROM read size set to 0.

- Do it once per module. Later L4T releases reach QSPI through apt ([README.md](README.md),
  "Updating").
- The release and board config must match the card's image: R39.2.1 and
  `jetson-orin-nano-devkit-super` ([README.md](README.md)).

It uses [Hi5808/turing-pi-2.5-jetson-eeprom-fix](https://github.com/Hi5808/turing-pi-2.5-jetson-eeprom-fix).
That repo backs up the boot flash, verifies the backup, then runs NVIDIA's QSPI-only flash; it never
writes the card or the NVMe.

Its README flashes the module in a Turing Pi node, through the BMC. Here the module is on its dev
kit carrier, because the Turing Pi stays racked. So recovery mode is the dev kit's jumper, and the
repo's `tp-recovery.sh` and `tp-park-usb.sh` aren't used.

Not yet run.

## What you need

- An x86-64 Ubuntu host with sudo and about 3.5 GB free: ideapad3 (Ubuntu 24.04).
- The module on its dev kit carrier. No card is needed.
- A jumper for the dev kit's button header.
- A USB-C data cable from the dev kit to the host.

## Steps

On ideapad3, unless the step says the dev kit.

1. Make a work directory and go into it:
   `mkdir ~/jetson-qspi && cd ~/jetson-qspi`
2. Download NVIDIA's BSP (the Driver Package) for R39.2.1:
   `wget https://developer.download.nvidia.com/embedded/L4T/r39_Release_v2.1/release/Jetson_Linux_R39.2.1_aarch64.tbz2`
3. Check it. NVIDIA publishes no checksum; this is the hash of the copy downloaded on 2026-10-02:
   `echo "2e5619088ba88e85dab25247f033d70659b6f676ff835176a07766dcb0fdbe6b  Jetson_Linux_R39.2.1_aarch64.tbz2" | sha256sum -c`
4. Extract it as your user. No sample rootfs or `apply_binaries.sh` is needed:
   `tar xf Jetson_Linux_R39.2.1_aarch64.tbz2`
5. Get the fix's scripts:
   `git clone https://github.com/Hi5808/turing-pi-2.5-jetson-eeprom-fix eeprom-fix`
6. Install the host packages the repo's `docs/HOST-NOTES.md` lists. Any already installed are left
   as they are:
   `sudo apt-get install -y abootimg lbzip2 whois python3-usb`
7. Apply the EEPROM fix:
   `eeprom-fix/scripts/apply-eeprom-fix.sh ~/jetson-qspi/Linux_for_Tegra`
   It prints a diff for its two files. Only the `cvb_eeprom_read_size` lines change, to `<0x0>`.
8. On the dev kit, with its DC power unplugged, fit a jumper across pins 9 and 10 (FC REC, GND) of
   the button header J14.
9. Connect the dev kit's USB-C port to ideapad3.
10. Plug in the dev kit's DC power.
11. Check the module is in recovery mode. Expect one line, `0955:7523 … APX`:
    `lsusb -d 0955:`
12. Detect the module and build NVIDIA's command file. This writes nothing to the module:
    `TARGET=nano8 eeprom-fix/scripts/qspi.sh prepare`
13. Back up the module's boot flash. It ends with `SUMMARY: 60 partitions read OK, 0 failed`. Keep
    `~/jetson-qspi/qspi-backup-nano8/`: it's the way back.
    `TARGET=nano8 eeprom-fix/scripts/qspi.sh dump`
14. Unplug the dev kit's DC power, leaving the jumper on.
15. Plug the DC power back in.
16. Check the module is back in recovery mode. The device number differs from step 11's:
    `lsusb -d 0955:`
17. Flash QSPI. Type `FLASH` when asked. It ends with
    `*** The target … has been flashed successfully. ***`
    `TARGET=nano8 eeprom-fix/scripts/qspi.sh flash`
18. Unplug the dev kit's DC power. With the jumper on, the module's reboot after the flash lands
    back in recovery.
19. Remove the jumper.

## Undo

1. Put the module back into recovery (steps 8–11).
2. From `~/jetson-qspi`, run `TARGET=nano8 eeprom-fix/scripts/qspi.sh restore`.

It writes back only the partitions that differ from the backup, and reads each one back to verify
it. With `DRY_RUN=1` it only lists what would change.

## If a run fails

`prepare`, `dump` and `flash` each need the module freshly in recovery. A failure right after a
successful run calls for a power cycle (steps 14–16), then the same command again. The messages
that mean this are "No Board Spec. and no target connected" and "might be timeout in USB write".

The repo's
[TROUBLESHOOTING.md](https://github.com/Hi5808/turing-pi-2.5-jetson-eeprom-fix/blob/main/docs/TROUBLESHOOTING.md)
covers the rest.

## Next

The module goes into node 4 with its card: [README.md](README.md), "Making a card".
