# Enterprise 22110 PLP NVMe on a Pi, and boards that can power it

Researched 2026-09-25. Quotes are verbatim. **[I]** marks inference. Scope: a single
self-contained host. Cluster boards (DeskPi Super6C, Turing Pi 2, Sipeed NanoCluster) are
excluded, and the Compute Blade is sold out everywhere (the project looks dead).

## Drive power (22110, capacitor PLP)

| Drive (22110 capacities) | Max / idle | Power states | PLP wording | Source |
|---|---|---|---|---|
| Samsung **PM983** (MZ1LB…): 960G, 1.92T, 3.84T | "Read7.5W7.6W6.9W Write7.2W8.0W8.0W", idle "2.6W"; inrush 1.5 A | one state, PS0 = 8.00 W; "does not manage any low power modes except for the Active/Idle and Off mode" | "supports power loss protection (PLP)" | [datasheet Rev 1.0, Jan 2018](https://www.stesz.com/Upload/SAMSUNG/PM983/PM983-M.2-Datasheet.pdf) |
| Samsung **PM963** M.2 (MZ1LW…): 960G, 1.92T | "Active 8 8 W Idle 2.5 2.5 W"; Samsung: "Up to 7.5/7.5 W, Idle: 2.5 W" | PS0 decodes to 9.00 W | "stored energy from tantalum capacitors" | [Viking manual, 2017](https://www.vikingtechnology.com/wp-content/uploads/2021/03/M2_NVMe_110mm_Samsung_PM963.pdf); [Samsung brochure, 2016](https://www.compuram.de/documents/datasheet/Samsung_PM963-1.pdf) |
| Samsung **PM9A3** M.2 (MZ1L2…): 960G, 1.92T, 3.84T | "Read7.5W8.0W8.2W Write6.5W8.2W8.2W", idle 2.5 W; inrush 1 A | one state, PS0 = 8.25 W; no APST | "supports power loss protection (PLP)" | [datasheet Rev 1.0, Jan 2021](https://www.stesz.com/Upload/SAMSUNG/PM9A3/PM9A3-M.2-Datasheet.pdf) |
| Intel **P4511**: 1T, 2T | "Power Up to 8.25 Watt" | not published | "power loss imminent (PLI) protection scheme with a built-in self-test" | [brief, Nov 2019](https://www.solidigm.com/content/dam/solidigm/en/site/products/data-center/d7/p4511/documents/dc-p4511-series-product-brief.pdf); discontinued |
| Micron **7300 PRO** (MTFDHBG…): 1.92T, 3.84T | "12W MAX U.2 / 8.25W M.2" | not found | "power-loss protection for data in-flight" | [brief, Oct 2019](https://www.edgeelectronics.com/media/pdf/micron_7300_nvme_ssd_product_brief.pdf) |
| Micron **7400** PRO 480G–3.84T / MAX 400G–3.2T (all in 22110) | M.2 "8.25W"; PRO idle 3.0 W; 3.3 V "MAX average current (RMS) 2.4A", "Inrush current (typical peak) 2.5A" | PS0–PS4 = 8.25/7/6/5/4 W; "does not support autonomous power state transitions" | "power hold up mechanism…" | [brief, Sep 2021](https://www.simms.co.uk/PDFS/Products/SSD/micron_7400_nvme_ssd_product_brief.pdf); [datasheet Rev B, 2021](https://www.ssd.group/wp-content/uploads/2022/07/7400_nvme_ssd-_revb_june_25.pdf) |
| Kioxia **XD5**: 1.92T, 3.84T | "7" W (stated for 2.5" only) | ? | PLP listed | [press release, 2019](https://americas.kioxia.com/en-us/business/news/2019/ssd-20190313-1.html) |
| **Synology SNV3510-400G** | "4.0 W" read (typ.), 1.7 W idle | ? | PLP "Yes" | [Synology datasheet, 2021](https://gzhls.at/blob/ldb/a/0/7/7/fffdb76f32e36713f98adcdf80edc1a72d34.pdf) |
| SK hynix PE3110/PE6110/PE9010 | no datasheet found | ? | unverified | — |

Notes:
- MZ1LV… is the PM953; the SM963 M.2 is MZ1KW… (no power figures found).
- The Micron 7300 480/960 GB PRO and all 7300 MAX, plus the 7400 at 400–960 GB, also come in
  **2280** with PLP. The Micron 7300 PRO 480 GB 2280 lists "Operating Power Consumption: 8.25 W"
  (SabrePC).
- [I] 8.25 W ÷ 3.3 V = 2.5 A (2.63 A at −5 %). Samsung rates power as the "maximum RMS average
  value over 100 ms", so short peaks go higher.
- The Micron 7400 can be capped at PS4 (4 W) by the OS, but only after boot: there is no APST.

## Evidence of these drives on a Raspberry Pi: none

- GitHub searches of geerlingguy/raspberry-pi-pcie-devices, raspberrypi/rpi-eeprom,
  raspberrypi/linux and raspberrypi/firmware, for PM983/PM963/PM9A3/PM953/SM963/P4511/SSDPELKX,
  the Micron part-number prefixes, "22110" and "power loss protection": nothing relevant.
- Jeff Geerling's pipci database has no enterprise NVMe except the Kioxia CM6 U.3, and that only
  through a MegaRAID card: "The Raspberry Pi can't directly interface with this drive" (CM4,
  2021, #129).
- RPi forum (2026-01-02): "These long SSDs don't fit on a standard Pi hat…".
- **Closest positive:** the [Compute Blade SSD list](https://docs.computeblade.com/blade/compatibility/ssd)
  (2025-12-02) includes "Synology SNV3510 | SNV3510-400G | 400GB | Uptime" on a CM4 carrier.
  Booting is not stated.
- **Boot-timing risk:**
  - Ready timeouts (CAP.TO): PM983 "30 seconds", PM9A3 "20 seconds" / "25 seconds".
  - A Raspberry Pi engineer: "20s should be plenty of time!" (rpi-eeprom#519) and "short delay in
    the NVMe initialisation which is required for some drives" (#535).
  - [I] Whether the bootloader waits the full timeout is undocumented.
- [I] PM983 = "Phoenix" and PM9A3 = "Elpis" controllers, the same families as the 970 EVO Plus
  and 980 PRO, which run on Pis. That suggests compatibility but proves nothing.

## Pi 5 boards not limited to the ribbon cable's 5 W

| Board | Position / sizes | SSD 3.3 V rating | How it's powered | Probe / boot | Availability | Issues |
|---|---|---|---|---|---|---|
| **[Geekworm X1001-Max](https://wiki.geekworm.com/X1001-Max)** (wiki 2026-09-09) | top; 2230–2280 | "3.3V ±5% Max 8A" | "9-20Vdc via DC jack" or "27W-120W USB-C PD"; feeds the Pi "5.1V / 8A" via GPIO | NVMe boot yes | $32, 141 in stock | new, no field reports; "Connect only ONE power source at a time" |
| [Geekworm X1011](https://wiki.geekworm.com/X1011) | bottom; 4 slots, ASM1184e switch | "3.3 V, max 10A" | Pi USB-C 5 V ≥5 A, or its own 5 V/10 A jack | EEPROM 2024/05/17+ | $45, 18 in stock | a switch in the boot path |
| [Geekworm X1015](https://wiki.geekworm.com/X1015) | top; 2230–2280 | page says "max 6A" and "max 3A" | GPIO + ribbon cable | `PCIE_PROBE=1` | $16 | spec contradicts itself |
| [Geekworm X1002](https://wiki.geekworm.com/X1002) | bottom; 2230–2280 | "3.3V, max 3.5A" | ribbon cable + GPIO | `PCIE_PROBE=1` | $16 | — |
| [Geekworm X1001](https://wiki.geekworm.com/X1001) | top; 2230–2280 | "3.3V, max 3.5A" | ribbon cable + XH2.54 aux | — | $13 | aux source undocumented |
| [Geekworm X1012](https://wiki.geekworm.com/X1012) (PoE) | top; 2230–2280 | "up to 5A of power for your SSD" (table: "5V, 5A") | 802.3af/at, or 40–57 V aux jack | `PSU_MAX_CURRENT=5000` | $32 | fails on some PoE switches ([forum t=378425](https://forums.raspberrypi.com/viewtopic.php?t=378425)) |
| [52Pi EP-0241 / P33](https://wiki.52pi.com/index.php?title=EP-0241) (PoE) | top; 2230–2280 | not published | 802.3at, "5.1V/4.5A"; "Do not connect power supply to USB-C port when PoE+ Hat is in use" | `PCIE_PROBE=1`, `BOOT_ORDER=0xf416`, `dtparam=pciex1` | $29.99 | Geerling: "the PoE HAT seemed to reset its power line, causing the Pi to immediately power back on"; users: "it reboots every 60–90 seconds", Samsung 990 Pro "requires too much power and doen't boot" ([#664](https://github.com/geerlingguy/raspberry-pi-pcie-devices/issues/664)) |
| [Waveshare PoE M.2 HAT+ (B)](https://www.waveshare.com/poe-m.2-hat-plus-b.htm) | top; 2230–2280 | not published | 802.3af/at; "25W for 12V+5V total" | `BOOT_ORDER=0xf416` | on sale | — |
| MCUzone MPS2280P / MPS2280-POE | top; 2230/2242/2280 | P: aux "5V/3A"; POE: "5V4.5A output" | aux or PoE | — | Amazon | the plain MPS2280 has holes to zip-tie a 22110 ([CNX](https://www.cnx-software.com/2024/01/31/this-mcuzone-mps2280-m-2-nvme-hat-for-raspberry-pi-5-2280-22110-gen3-ssd/)) |
| [Pironman 5 NVMe board](https://docs.sunfounder.com/projects/pironman5/en/latest/pironman5/hardware/nvme_pip.html) | in case; 2230–2280 | "up to 3A" | ribbon cable + J3 5 V aux | — | on sale | — |
| [Seeed PCIe3 dual](https://thepihut.com/products/seeed-pcie-3-0-dual-m-2-hat-for-raspberry-pi-5) | bottom; ASM2806 switch | not published | pogo (2 A) + ribbon cable (1 A) | — | in stock | — |

- Cable-only boards (~5 W input) cannot run an 8 W drive [I]: 52Pi N04/N07 (N04 discontinued at
  The Pi Hut), MCUzone MPS2280, Pimoroni NVMe Base, Geekworm X1003 (2230/2242).
- Argon ONE V3: "up to 2280" via "POGO PINS", no rating.
- Pineboards has closed.
- HackerGadgets PoE+NVMe is 2230/2242 only.
- The official Pi 5 PoE+ HAT+ was "missing in action" (RPi, 2025-03-24) and is still unreleased.
- **22110 overhang:** no board documents it except MCUzone. On a top HAT the extra 30 mm hangs
  past the Pi's edge.

## PoE+ budget

- Pi 5: "Typical bare-board active current consumption 800mA" (RPi docs). Geerling (2024-08-29):
  idle 2.4/3.3/3.2 W and stress-ng 8.9/9.8/9.8 W on the 2/4/8 GB models.
- An 802.3at powered device gets 25.5 W.
- [I] Worst case ≈ 20 W: Pi 9.8 W + an 8.25 W drive through a ~90 % converter (~9.2 W) + fan/USB
  (~1 W).
  - EP-0241 outputs 22.95 W (5.1 V × 4.5 A).
  - The "25 W" X1012/Waveshare claims need ~98 % efficiency; plan on 22–23 W real.
  - Typical DNS/NUT load is ~6–7 W.
- **No PoE+ board clearly publishes enough for an enterprise drive.** The X1012's figure is
  ambiguous about voltage.

## Single-module Compute Module carriers

| Carrier | Module | M.2 | Power | M.2 3.3 V | Availability |
|---|---|---|---|---|---|
| [Geekworm X1502](https://geekworm.com/products/x1502) | CM5 | 4× 2230–2280 behind a PCIe 2.0 switch | "DC 12V 5A" jack, "9-17V"; PoE HAT support | "3.3V/4A for each SSD" | $72 |
| Official CM5 IO Board | CM5 | 2230–2280, Gen 2 ×1 | USB-C 5 V 5 A; 5 V via J8; PoE HAT | not published | on sale ([datasheet 2026-09-11](https://pip-assets.raspberrypi.com/categories/1097-raspberry-pi-compute-module-5-io-board/documents/RP-008182-DS-3-cm5io-datasheet.pdf)) |
| Official CM4 IO Board | CM4 | PCIe x1 slot + adapter | 12 V barrel; PoE disables PCIe | "+3.3v@3A" | — |
| [Waveshare CM5-PoE-BASE-A](https://www.waveshare.com/wiki/CM5_PoE_BASE_A) | CM5 | 2230–2280 | 802.3af/at or USB-C 5 V 5 A | not published | on sale |
| [Geekworm X1501](https://geekworm.com/products/x1501) | CM5 | 2× 2230–2280 | USB-C 5.1 V | not published | $55 |
| [Seeed reComputer R1000](https://wiki.seeedstudio.com/recomputer_r/) | CM4 | 2280 | 9–36 V DC terminal; PoE option "12.95W", which Seeed says is not enough for an SSD | not published | on sale |
| [Waveshare CM4-IO-BASE-A](https://www.waveshare.com/wiki/CM4-IO-BASE-A) | CM4 | M key | 5 V | "limited to 1.5A" | on sale |
| Uptime Compute Blade | CM4 (CM4/5 retail) | "2230 to 22110" | PoE+ only ("up to 30W @5.1V") | not published | sold out; "not been validated without… Fan Unit, BladeRunner™️, and Heat Sink" |

## Best-fit combinations for an enterprise 22110 PLP drive [I]

1. **Pi 5 + Geekworm X1001-Max, on its own supply** (27 W+ USB-C PD or 9–20 V DC). It has the
   most 3.3 V headroom of any single-drive HAT (8 A ≈ 3× a 2.5 A drive), the Pi gets its own
   5.1 V/8 A rail, and it's in stock. Unknowns: brand new; the Pi is powered through GPIO (set
   `PSU_MAX_CURRENT=5000`); the overhang geometry.
2. **Pi 5 + Geekworm X1002** (3.5 A, from the Pi's 27 W supply): less headroom (1.4×), simpler.
3. **PoE only if required: Geekworm X1012.** ~20 W worst case against ~22–23 W, and there's a
   switch-dependent failure report. **Avoid the EP-0241.**
- Drive side: a Synology SNV3510-400G halves the power (4 W typical) and is the only one with a
  Pi-family compatibility listing. A 2280 PLP drive (Micron 7400/7300) removes the extender.
- **Test that the chosen drive boots on the chosen board before relying on it.** If it won't, the
  fallback is the boot files on a microSD with root on the NVMe.
