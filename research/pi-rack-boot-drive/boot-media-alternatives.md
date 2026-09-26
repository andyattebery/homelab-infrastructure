# Boot media alternatives for a Pi-class last-resort host

Researched 2026-09-25. **[I]** marks inference. Quotes from HTML pages and forums came through a
summarizing fetch tool and were not checked word for word. PDF quotes were checked against the
documents.

Context: pi-rack is simple and independent by design — the only NUT server, and the DNS node that
must outlive the cluster. Its write load: AdGuard query log and stats (7-day interval), journald,
NUT, node_exporter, Tailscale, occasional NixOS deploys, and a 4 GB swapfile.

## Comparison

| Option | Failure modes / how they show | Power-loss safety | Endurance | Cost / effort | Src |
|---|---|---|---|---|---|
| **High-endurance or RPi microSD** (Pi 4 native slot) | wear-out: "SD card failure is usually indicated by random file corruptions"; the internal map can be damaged on a power cut | no PLP. RPi claims its cards survived "over 100,000 surprise power cycles under I/O heavy load" (vendor claim, method not published) | rated in video-recording hours (sequential). Samsung PRO Endurance 17,520–140,160 h at 26 Mbps (256 GB ≈ 1.6 PB, [I]). SanDisk MAX 15k–120k h, 3–15 yr warranty. Pi 4: ~1,200 random-write IOPS | $10–30; no bridge chip | 1–5 |
| **USB flash drive** | same internals as SD; runs hot (one stick >60 °C); still on the USB stack | no PLP claim | no TBW published; FIT Plus "5 years limited" | $15–40; no advantage over SD | 6, 7 |
| **Spare S3520 + new USB adapter** | same failure class as last time (bridge, link, power); shows early as SMART 199 rising | the drive has PLP ("Tested and Proven power-loss data protection with self-test"); the bridge has none | 1–1.4 DWPD (240 GB: 599 TB) | $0. M.2 S3520 is "3.3V only", so a "passive" M.2→2.5" adapter converts 5 V → 3.3 V: one more regulator | 8–11 |
| **Innodisk mSATA 3ME2 + USB adapter** | same bridge risk; old part | 2016 datasheet: MLC, no DRAM buffer, no PLP feature listed. Innodisk's "iData Guard" is a voltage detector plus firmware ("enough power for the last programing operation"), with no backup capacitors, and is not documented for the 3ME2 | not stated. Successor 3ME3 (2025): 3,000 P/E, 153 TB max, 2-yr warranty | $0; max 2.2 W. No product page found → probably discontinued | 14–16 |
| **Network boot** | server or network down = host down | n/a | n/a | breaks "survive the cluster/NAS being down" | 1 |
| **CM4 eMMC on a PoE board** | soldered flash, same kind of controller as SD | no PLP. RPi engineer (2017): "MUCH higher [reliability]… since it uses MLC rather than TLC". RPi (2026): newer modules are "transitioning to triple-level cell (TLC)"; pSLC "does not, by itself, guarantee improved reliability" | not published | new board; CM4 prices rose Feb 2026 | 1, 29–31 |
| **Pi 5 + NVMe** | no USB bridge; drive-compatibility risk | no 2230 drive with capacitor PLP found | RPi SSD: no TBW published | 2230 drive (~$30/256 GB) + power arrangement | 21–28 |
| **Intel N100 mini PC** | removes USB storage and Pi firmware; an M.2 SATA slot would take the S3520 natively ([I]) | keeps the S3520's PLP | S3520 | "10.5-12W at idle", "22-23W" max; an 802.3at splitter (12 V/2 A from 25.5 W) is marginal at peak ([I]) | 34, 35 |

## Follow-up questions

**Innodisk 3ME2:** MLC, no documented PLP, no endurance figure, 2.2 W max, probably discontinued.
Don't use it as the main drive.

**2230 NVMe with PLP: none found with capacitor PLP.**
- ATP 2230: "Power Loss Protection Options: Firmware Based" (Aug 2022), plus optional warning pins
  the host must drive.
- Innodisk 4TE2 (2230): iData Guard / iPower Guard, no DRAM, 852 TB max.
- Cervoz Powerguard (capacitor PLP) is listed only on 2.5", mSATA, 2280 and U.3.
- Capacitor PLP starts at 2280: e.g. Kingston DC2000B 240 GB, "Power loss protection (power caps)
  Yes", 4.09 W max write, 175 TB (datasheet Jul 2024). Now >$300 used, per the owner.
- Consumer 2230 drives (WD SN740, Kioxia BG5/BG6, Micron 2400/2550, Samsung PM991a) have no PLP
  and no published power-cut tests. In a 2022 flush test, half of the first four consumer NVMe
  drives "lose FLUSH'd data on power loss"; 2 of 12 failed overall.

**Pi 5 + 2230 NVMe power:**
- The 27 W USB-C PSU is enough: 5 A supply; Pi 5 "800mA" typical; the official M.2 HAT+ gives "up
  to 3A to connected M.2 devices".
- The official Pi 5 PoE+ HAT+ is still unreleased. A Raspberry Pi engineer (2026-05-23): "still
  under development… the RAM crisis have meant changed priorities".
- PoE today means a combined PoE+NVMe board: Waveshare PoE M.2 HAT+ (802.3af/at, 5 V 4.5 A,
  2230/2242), GeeekPi P33, HackerGadgets. Pineboards HatDrive! PoE+ is discontinued.
- Those HATs don't signal a 5 A supply, so the Pi 5 caps USB at 600 mA. That doesn't affect NVMe.
- RPi docs: Gen 3 "isn't certified… might be unstable". Non-HAT+ boards need `PCIE_PROBE=1` and
  `BOOT_ORDER=0xf416`.
- Geekworm's incompatibility list (vendor wiki, 2026-08-24, anecdotal) includes WD SN740,
  SN5xx/SN770/SN850, Micron 2450 and Kingston NV3.
- Alternative: Pi 5 + Radxa Penta SATA HAT (JMB585) runs the S3520 on native SATA with PLP and no
  USB, but needs 12 V in and wants PCIe Gen 3.

## Reducing flash writes

**Correction (2026-09-25):** size caps like journald `SystemMaxUse` limit how much history is kept,
not how many bytes are written, so they don't reduce wear. `SyncIntervalSec` is about durability;
kernel writeback flushes dirty pages about every 30 s regardless. Real write reducers:
- a single logger (no rsyslog alongside journald)
- no swap on flash
- tmpfs `/tmp`
- keeping AdGuard's query log in memory (`querylog.file_enabled = false`)
- `Storage=volatile`, at the cost of logs across reboots

Where the system is built is not a lever: the closure lands on the device either way.

The whitepaper points below are about resilience, not wear:

- RPi whitepaper "Making a more resilient file system" (rev 3, 7 Aug 2026):
  - `commit=30` is a "reasonable starting point on devices where flash wear is the bigger concern".
  - `Storage=volatile` "discards all logs on reboot… exactly the information you are most likely to
    need". Tuned persistent storage instead: `SystemMaxUse=512M`, `SyncIntervalSec=2m`.
  - With swap enabled, tmpfs data can still reach flash. The FAT /boot "has no journal".
- NixOS (25.11 checked): `services.journald.storage` (default persistent), `zramSwap.enable`
  (default false).
- AdGuard: `querylog.file_enabled`, `size_memory` ("entries kept in memory before they are flushed
  to disk").

## Published evidence on boot-medium reliability

No large-sample study compares Pi boot media.
- Evidence:
  - FAST'13: "thirteen out of the fifteen tested SSD devices exhibit surprising failure behaviors
    under power faults".
  - A 2013 single-tester run: only Intel 320/S3500 (PLP) survived; the S3500 took ~6,500 cycles.
  - The 2022 consumer NVMe flush test.
- Claims, not data: RPi's 100,000-cycle test; the 2017 eMMC statement.
- Jeff Geerling publishes speed benchmarks, not failure rates.

## Sources

1. RPi whitepaper RP-003610-WP rev 3 — https://pip.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-003610-WP/Making-a-more-resilient-file-system.pdf
2. RPi news (jdb), 7 Oct 2024 — https://www.raspberrypi.com/news/sd-cards-and-bumper/
3. RPi SD card product brief — https://datasheets.raspberrypi.com/sd-card/sd-card-product-brief.pdf
4. Samsung PRO Endurance datasheet — https://download.semiconductor.samsung.com/resources/data-sheet/samsung_data_sheet_2022_pro_endurance_card_rev.1.0.pdf
5. SanDisk MAX Endurance datasheet — https://documents.sandisk.com/content/dam/asset-library/en_us/assets/public/sandisk/product/memory-cards/max-endurance-uhs-i-microsd/data-sheet-max-endurance-uhs-i-microsd.pdf
6. Samsung FIT Plus datasheet — https://download.semiconductor.samsung.com/resources/data-sheet/2024_Samsung_Data_sheet_UFD_FIT_Plus_v1.2.pdf
7. Jeff Geerling, USB storage options — https://www.jeffgeerling.com/blog/2020/fastest-usb-storage-options-raspberry-pi/
8. Intel DC S3520 spec 334826-001US (mirror) — https://gzhls.at/blob/ldb/2/d/b/0/7971fcfc6d5b5b6fb75e7551ac9b7f48cade.pdf
9. `uas-detect.h` — https://github.com/torvalds/linux/blob/master/drivers/usb/storage/uas-detect.h
10. `unusual_uas.h` — https://github.com/torvalds/linux/blob/master/drivers/usb/storage/unusual_uas.h
11. RPi forum UAS sticky — https://forums.raspberrypi.com/viewtopic.php?t=245931
12. Jeff Geerling, PoE+ HAT review — https://www.jeffgeerling.com/blog/2021/review-raspberry-pis-poe-hat-june-2021/
14. Innodisk 3ME2 datasheet — https://www.wdlsystems.com/specifications/spec_1IMS3432.pdf
15. Innodisk 3ME3 datasheet — https://www.innodisk.com/upload/file/innodisk_msata_3me3_datasheet.pdf
16. Innodisk iData Guard white paper — https://www.innodisk.com/upload/file/innodisk_idata_guard_white_paper_en.pdf
17. ATP 2230 — https://www.atpinc.com/about/news/industrial-M2-2230-SSD-with-customizable-security-features
18. Cervoz Powerguard — https://www.cervoz.com/technology/powerguard-power-loss-protection/detail
19. Innodisk 4TE2 — https://www.innodisk.com/en/products/flash-storage/pcie-m2/m2-p30-4te2
20. Consumer NVMe flush test — https://news.ycombinator.com/item?id=30419618 ; https://www.tomshardware.com/news/sk-hynix-sabrent-rocket-ssds-data-loss
21. RPi docs, PCIe — https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/pcie.adoc
22. RPi docs, power supplies — https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/power-supplies.adoc
23. RPi M.2 HAT+ — https://www.raspberrypi.com/products/m2-hat-plus/
24. RPi forum, Pi 5 PoE HAT status — https://forums.raspberrypi.com/viewtopic.php?p=2377088
25. Jeff Geerling, third-party PoE+NVMe HATs — https://www.jeffgeerling.com/blog/2024/3rd-party-poe-hats-pi-5-add-nvme-fit-inside-case/
26. Waveshare PoE M.2 HAT+ — https://www.waveshare.com/poe-m.2-hat-plus.htm
27. Geekworm NVMe incompatibility list — https://wiki.geekworm.com/Template:NVMe_SSD_Incompatibility_List
28. RPi SSD product brief — https://datasheets.raspberrypi.com/ssd/raspberry-pi-ssd-product-brief.pdf
29. RPi price rises — https://www.raspberrypi.com/news/more-memory-driven-price-rises/
30. RPi forum, eMMC reliability — https://forums.raspberrypi.com/viewtopic.php?t=195293
31. Compute Blade datasheet — https://computeblade.com/wp-content/uploads/2024/02/Compute_Blade_DataSheet_01.pdf
32. FAST'13 — https://www.usenix.org/conference/fast13/technical-sessions/presentation/zheng
33. SSD power-loss test — https://hardware.slashdot.org/story/13/12/27/208249/power-loss-protected-ssds-tested-only-intel-s3500-passes
34. ServeTheHome N100 — https://www.servethehome.com/fanless-intel-n100-firewall-and-virtualization-appliance-review/4/
35. Planet POE-162S — https://planetechusa.com/product/poe-162s-ieee-802-3at-gigabit-high-power-poe-splitter-12v-24v/
38. Radxa Penta SATA HAT — https://pipci.jeffgeerling.com/hats/radxa-penta-sata-hat.html
40. Kingston DC2000B datasheet — https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/968/DataCenterDC2000BPCIe40NVMeM2ServerSSDKingstonTechnology.pdf
