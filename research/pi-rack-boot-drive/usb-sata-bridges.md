# USB-SATA bridges on a Raspberry Pi 4

Researched 2026-09-25. Kernel files were fetched raw and diffed, and forum quotes were checked
against a Wayback capture of 2025-12-31. **[I]** marks inference.

## Are any USB-SATA chipsets actually reliable?

**Not with evidence.** No bridge has published long-run reliability data on a Pi; everything is
community anecdote. The best-reported:

- **ASMedia ASM1153E on firmware `141126_A1_EE_82`.**
  - "firmware 140509_A1_82_40 or 141126_A1_EE_82… UASP and TRIM just fine on RPi4, no quirks
    necessary" (RPi forum t=296030, 2020-12-24).
  - "gold standard firmware" (t=330242).
  - Caveat: it shares `174c:55aa` with a dozen other ASMedia chips, so the ID can't tell you which
    chip or firmware you have.
- **JMicron JMS578.** Worked only after flashing firmware "v00.04.01.04" (RPi sticky, page 3,
  2019-11-22). Others: "Avoid those." The kernel flags JMS567/578 (`152d:0567` / `152d:0578`)
  `BROKEN_FUA`.
- **Realtek RTL9210/RTL9210B** (`0bda:9210`). No kernel quirk for the generic ID. The kernel does
  disable UAS for one RTL9210 product (HIKSEMI MD202, commit dbd24ec17b85), and a community repo
  fixes idle-suspend disconnects via firmware config. No long-run Pi 4 source for SATA mode.
- **VIA VL716** (mSATA). "works great with the Pi!" (James Chambers, page modified 2026-05-03).
- **ASM2235.** One user updated firmware 171120d10000 → 171120d11e80 because it "Was previously
  giving me strange errors".
- **JMS580.** Seen only in a bootloader-interop issue (rpi-eeprom#266). Tim Gover (Raspberry Pi):
  "The Realtek and AsMedia devices worked fine" (2021-01-04). That is about booting, not long-run
  stability.

**On a Pi 4 the bridge is only half the problem:**
- Raspberry Pi engineer P33M found a bug in the Pi 4's own VL805 USB controller that needs "A hub
  in the datapath" (raspberrypi/linux #4844).
- On 2022-03-04, with a USB 3.1 ASMedia bridge in mass-storage (non-UAS) mode, he saw "a single 1K
  chunk… was corrupt". On 2022-03-16: "VIA in Taiwan have reproduced the issue".
- On 2022-02-09: "SSDs can draw in excess of 1.5A - causing brownouts on the Pi's USB ports" and
  "Resetting the device will obviously cause corruption if there are pending writes."

**If staying on USB, the recipe [I]:**
- ASM1153E on 141126 firmware, or an RTL9210B
- behind a **powered USB 3 hub** (addresses the VL805 bug and the 1.2 A cap)
- UAS disabled
- watch SMART 199, the counter that exposed this failure

PCIe (a Pi 5 with an NVMe HAT) is the only change that removes all of it.

## How Linux handles `174c:55aa`

- `drivers/usb/storage/uas-detect.h` is **byte-identical in torvalds v6.8 and raspberrypi
  rpi-6.18.y** (diffed). The ASMedia logic dates from 2014–15 (a9c54caa456d, 078fd7d6308a,
  8e779c6c4a39).
- Lines 82–87: "the device-id is useless to determine if we're dealing with an ASM1051", and "The
  ASM1153 can be identified by config.MaxPower == 0".
- Lines 98–112, which apply only to `0x5106` / `0x55aa`:
  - `bMaxPower == 0` → "ASM1153, do nothing"
  - slower than SuperSpeed → `US_FL_IGNORE_UAS`
  - status-pipe streams == 32 → "Possibly an ASM1051, disable uas"
  - otherwise → "ASM1053" → `US_FL_MAX_SECTORS_240` (120 KiB transfers; `uas.c` v6.8 l.836,
    rpi-6.18.y l.847)
- `NO_REPORT_OPCODES` appears only in a comment and is never set. `unusual_uas.h` has no `174c`
  entries in either version. `unusual_devs.h` (usb-storage only) has
  `UNUSUAL_DEV(0x174c, 0x55aa, 0x0100, 0x0100, "ASMedia", "AS2105", … US_FL_NEEDS_CAP16)`.
- **A UAS binding does not identify the chip.** raspberrypi/linux#5060 shows an ASM225CM on
  `174c:55aa` reporting "MaxPower 0mA" and "MaxStreams 32" with uas bound. P33M (#4844,
  2022-02-17): a Sabrent adapter "reports the common ASmedia ASM1153e PID:VID of 174c:55aa, but is
  clearly a different chip."
- "ASMT 2235" maps to the ASM235CM/ASM2235 family: "USBDEV in windows, reports ASMT2235… its the
  AMS235CM" (forum t=330242). pi-rack's enclosure links at 10 Gb/s, which is consistent.
- The junk "optimal transfer size" warning is harmless: `sd_validate_opt_xfer_size()` logs it and
  discards the value (sd.c v6.8 l.3354–3408).

## Pi 4 + USB-SATA problem reports

- **RPi sticky** by jdb (Raspberry Pi engineer), 2019-07-16: https://forums.raspberrypi.com/viewtopic.php?t=245931
  - "these devices will just stop responding… or may in rare cases throw write data away which can
    cause filesystem corruption."
  - "The Linux kernel has a built-in blacklist… This is not an exhaustive list"
  - "These errors may also appear due to poor power quality or overloading the Pi's maximum 1.2A
    downstream USB port current, but if they persist when using a powered hub then they are
    genuine UAS issues."
  - The fix: "add the text usb-storage.quirks=aaaa:bbbb:u".

| Issue | Status | What it shows |
|---|---|---|
| raspberrypi/linux **#5060** | open, 2022, 111 comments | ASM225CM on `174c:55aa`: `uas_eh_abort_handler` → "xHCI host controller not responding, assume dead" → "Aborting journal". The reporter says disabling UAS "doesn't seem to help". A commenter runs a Pi 4 cluster on the official PoE HAT with the same resets and recovers nodes by cycling PoE ports |
| raspberrypi/linux **#5076** | open, 2022 | ASM235CM on `174c:55aa`: slowdowns and lockups |
| raspberrypi/linux **#7570** | open, 2026-08-23 | Pi 4 Rev 1.4 with M.2 SATA via ASMedia `174c:1156` on uas: write errors → ext4 journal abort → total hang needing a power cycle. P33M (2026-09-11) on disabling UAS: "Why not? It's the recommended workaround." |

## `usb-storage.quirks=174c:55aa:u`

- kernel-parameters.txt (v6.8 l.7003): "u = IGNORE_UAS (don't bind to the uas driver)". It is
  read through `uas-detect.h` l.132.
- It matches **every** `174c:55aa` device (ASM1051/1053/1153/1153E/225CM/235CM). Once usb-storage
  binds, the `NEEDS_CAP16` entry also applies at bcdDevice 1.00 (harmless [I]).
- Cost:
  - jdb: usb-storage has a "lock-step relationship between commands and data" but "should still get
    150-200MB/s".
  - Jeff Geerling (2020-07-03): UAS gave "50% and 40% speedups" sequential, "Random reads are 35%
    faster, and random writes are 20% faster", and "8% peak power savings".
  - [I] The S3520 150 GB is rated only 170/140 MB/s sequential, so the sequential loss is small.
- **It would not have fixed pi-rack's CRC errors.** Those happen on the SATA side of the bridge;
  the quirk only changes the USB protocol.

## Power budget

- **Pi 4:** "Raspberry Pi 2, 3, 4 | 1200mA total across all ports"
  (`usb-bus-on-raspberry-pi.adoc` l.15–16). Pi 4B: 3.0 A PSU, 1.2 A max USB peripherals
  (`power-supplies.adoc` l.73–76).
- **PoE+ HAT** (product brief, April 2024): "IEEE 802.3at-2009", "37–57 V DC, Class 4", "Output
  power: 5 V DC/4 A". It says nothing about USB, and the docs give no PoE exception to the 1.2 A.
  Forum t=312879 (2021-05-29): both PoE HATs hit the limit near 1.2 A.
- **SSDSCKJB150G7:**
  - Intel ARK (archived 2022-08-10): Active 2 W, Idle 600 mW, Enhanced Power Loss Data
    Protection Yes.
  - Spec 334826-001US lists the M.2 150 GB power as "TBD". Its M.2 table (240–960 GB):
    "3.3 V (±5%)", "Inrush Current (Typical Peak) 1.5 A, < 1 s".
  - The 2.5" 150 GB model: write 2.2 W avg / 3.65 W burst, read 1.95 / 3.3 W, idle 0.53 W.
  - [I] At 85–90 % conversion from 5 V: ~0.45 A average, ~0.8 A write bursts, ~1.1–1.2 A inrush
    for under 1 s, plus the bridge.
- Martin Rowan's PoE+ HAT review part 2 (June 2021): powering the Pi via USB-C with the PoE+ HAT
  attached gave coil whine and ~37 V on test pads (inadequate reverse-power protection). Its power
  use is 5.2 W, vs 3.2 W for the original PoE HAT.

## Flushes, FUA and power cuts

- "Write cache: enabled… doesn't support DPO or FUA" means `sd_set_flush_flag` (sd.c v6.8
  l.121–131) turns flushes on and FUA off.
- writeback_cache_control.rst l.76–86: FUA writes become "an empty REQ_OP_FLUSH request after the
  actual write", sent as SYNCHRONIZE CACHE(10) (l.1073). **ext4 does get barriers**; whether they
  work depends on the bridge.
- The dangerous case is "Assuming drive cache: write through" (l.2995), where no flushes are sent
  at all. That was not this device.
- PLP caveat (334826-001US): "Fall time must be equal or better than minimum in order to guarantee
  full functionality of enhanced power loss management" (M.2 minimum 3.3 kV/s). [I] A slow USB or
  PoE brownout might not meet it.
- No source found for a USB-SATA bridge that acknowledges flushes it hasn't done. The nearest:
  - bridges that reject SYNCHRONIZE CACHE outright (LKML 2017/2019)
  - jdb's "throw write data away"
  - JMS583 silent corruption under UASP (goughlui.com, 2025-08-17)
  - the UAS reset path itself discards writes: #5060 shows `uas_zap_pending` → write I/O errors →
    "Aborting journal"

## S3520 firmware

- Intel PCN 115781-00 (2017-08-28) moved factory firmware N2010112 → N2010121. The N2010121 notes
  fix "Drive may enter a disabled logical state or report SMART AFh failure if powered on after
  storage in certain conditions".
- A Solidigm moderator (2024-11-26): "N2010112 is currently the latest… N2010121… was incorrectly
  included for the DC S3520."
- No other S3520 hang/brick advisory found; the HPE hour-count advisories cover SAS SSDs.

## The VL805 quirks in the vendor kernel

rpi-6.18.y adds VL805 quirks absent from mainline v6.8 and v6.18 (xhci-pci.c l.460–469):
`XHCI_EP_CTX_BROKEN_DCS`, `XHCI_AVOID_DQ_ON_LINK`, `XHCI_VLI_SS_BULK_OUT_BUG` and
`XHCI_VLI_HUB_TT_QUIRK`. Whether Ubuntu's linux-raspi 6.8 carried them was not checked (Launchpad
git returned 403).

## Kernel quirks by ID (for checking an unknown adapter)

Check with `lsusb` (VID:PID) and `lsusb -t` (uas vs usb-storage).
- `174c:55aa` / `174c:5106`: ASMedia; "the device-id is useless"; the heuristic above.
- `152d:0578` / `152d:0567`: `BROKEN_FUA`. `152d:0583` (JMS583): `NO_REPORT_OPCODES`.
- `2109:0711`: `NO_ATA_1X`.
- `2537:1068`, `357d:7788`, `0781:55e8`: UAS forced off.

The chip ID doesn't say whether the board is sound. The real test is a burn-in while watching
SMART 199 through the adapter (`smartctl -d sat`); reject the adapter if the count moves at all.

## The owner's on-hand adapters (Mac IORegistry, 2026-09-25, no drives attached)

| Device | VID:PID | USB string / SCSI identity | Link | Serial |
|---|---|---|---|---|
| Failed pi-rack enclosure (stale entry, hung) | `174c:55aa` | `ASMT1051` | 10 Gb/s | `123456792B8C` |
| 2.5"→USB adapter | `174c:55aa` | `ASMT105x` / **`ASMT 2235`** (same SCSI identity as the failed one) | 5 Gb/s | `234567890126` |
| USB→mSATA adapter | `174c:55aa` | `ARTofSERVER` / `USB3 mSATA Adapt` | 5 Gb/s | `202005280032` |

All three are the same ASMedia ID family. macOS showed no block device only because no drives
were attached. That says nothing about compatibility.
