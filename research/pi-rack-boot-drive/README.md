# pi-rack boot drive research (2026-09-25)

pi-rack is a Pi 4B with the official PoE+ HAT, booting from an Intel DC S3520 M.2 SATA SSD in a
USB enclosure. It died at 16:04:50 CDT on 2026-09-24 with a corrupted root filesystem. The
question was: is there a more stable boot drive option? This folder is the full record.

**Outcome:** pi-rack was rebuilt as NixOS on a CM4 with its 32 GB eMMC, deployed 2026-09-25. See
`nix/docs/raspberry-pi.md`.

## Cause (updated after forensics, 2026-09-25)

**The USB-SATA enclosure. The drive is exonerated.**
- **Clean on native SATA:** on nas-01 the drive read 150 GB with zero errors (CRC count unchanged,
  all PHY counters 0).
- **Errors logged in the enclosure:** 6 interface-CRC aborted commands, 3,989 link resets, and 85
  resets that hit in-flight commands. pi-rack's own boot logs show `I/O error` at the exact LBAs
  of those CRC errors.
- **SMART passthrough:** it failed through the bridge from at least 09-13.
- **Writes stopped persisting on 09-15 04:53**, right after a package-manager write burst. The Pi
  ran 9.5 more days on page cache, and nothing it wrote survived. The post-crash boot came up on a
  disk frozen at 09-15.
- **Filesystem:** structurally fine (`e2fsck -fn` clean apart from free counts).
- **Still unexplained:** the 16:04:50 reset itself.
- **Power:** no persisted log shows under-voltage.

Full detail: [failure-evidence.md](failure-evidence.md) → "Forensics on nas-01".

### Pre-forensics reasoning (kept for the record)

**The USB-SATA enclosure's SATA link (moderate confidence).**
- SMART 199 counts CRC errors on the cable-free link between the enclosure's bridge chip and the
  drive. It went 0 → 4 → 44 from July to August, in this enclosure only. Two identical spare
  S3520s read 0 in native SATA hosts.
- The chip reports 10 Gb/s, so it's an ASM2235/235CM-class part under a shared `174c:55aa` ID.
  Linux runs it under UAS with no quirks.
- That chip family is in raspberrypi/linux #5060 and #5076. The chain there: link or UAS errors →
  UAS aborts → the Pi 4's xHCI "not responding, assume dead" → ext4 journal abort. It matches the
  post-reboot I/O stall (30 processes blocked) and the corruption.
- 40 of the 44 errors appeared in an August window that includes Mac attempts, where every read
  through this enclosure timed out on the Mac's healthy power. That points at the enclosure, not
  only the Pi's power.

**Contributing, not separable yet:** the Pi 4's 1.2 A USB cap against the S3520's ~1.1–1.2 A
inrush, and the PoE HAT. Marginal power causes the same CRC errors and could explain the abrupt
16:04:50 reset.

**Unlikely:** the SSD itself (clean media, PLP test passing).

**Settled by (not yet run):**
- the dead drive's kernel journal, read-only on a nas-01 SATA bay: `uas_eh_abort`/CRC lines vs
  `Undervoltage detected`
- a spare S3520 in the old enclosure on a non-Pi Linux host under sustained I/O while watching
  199

Details: [failure-evidence.md](failure-evidence.md).

## Hardware conclusions

**Update 2026-09-25: the owner has a Dell Wyse 5070 with an M.2 SATA slot, and it beats every Pi
option for this host.**
- **Native SATA** for the already-proven-healthy S3520 M.2 (PLP): no USB bridge, no HAT, no
  enterprise-NVMe Pi-bootloader gamble, and nothing to buy.
- **x86 NixOS** like network-01/03: cached kernels, standard UEFI boot with rollback, no
  nixos-raspberrypi (bus factor 1), no Pi firmware partition or EEPROM.
- **A battery RTC**, so no stale-clock boots.
- Fanless, with plenty of CPU.
- **Caveats:**
  - its own 19 V brick on a UPS-backed outlet (no PoE, so no switch auto power-cycle)
  - set BIOS **AC Recovery = On**
  - Realtek NIC: set `keepalived.interface` to its name or disable predictable names
  - **check that the M.2 slot takes 2280** (the S3520 is 2280; not verified)
- **Single drive: use the S3520 for boot and data. No Optane boot + SATA data split.**
  - A split doubles the points of failure without adding redundancy.
  - Wear is a non-issue: this S3520 wrote ~10.4 TiB in 4.5 years (~6 GiB/day) and is at 2% used
    (SMART 233 = 98).
  - pi-rack's state is small, and the 16 GB Optane (13.4 GiB usable) is tight for NixOS
    generations.
  - The S3520 has certified PLP.
  - Recovery is a spare S3520 plus a re-image, since the config is declarative and AdGuard
    re-syncs from network-01.

**CM4 with eMMC (owner has some):** viable at **32 GB**, marginal at 16 GB (no swapfile, 2–3
generations), not at 8 GB.
- **Pros:**
  - default boot mode, with a U-Boot fallback that can read eMMC (unlike NVMe)
  - flashed via `rpiboot` from the Mac
  - no PCIe needed
- **Cons:**
  - no PLP (the UPS host shuts down cleanly in real outages; abrupt cuts remain)
  - unpublished endurance: pi-rack wrote ~6 GiB/day on Ubuntu with Docker; watch `mmc extcsd
    read` wear estimates
  - no SMART, so drop `services.scrutiny.collector` on that host
- The last three digits of the CM4 part number are the eMMC size in GB (`…032` = 32 GB).
- It ranks below the Wyse + S3520.
- **The owner has an 8 GB RAM / 32 GB eMMC CM4, which qualifies.** Deltas from today's
  `nix/hosts/pi-rack`:
  - keep `raspberry-pi-4.base`
  - pin the NIC's name (implemented as a MAC pin to `genetp0`, not
    `usePredictableInterfaceNames = false`)
  - drop the PoE fan dtparams
  - drop the 4 GB swapfile (8 GB RAM; eMMC wear)
  - drop `services.scrutiny.collector` (no SMART)
  - add `mmc-utils` for wear estimates
- The IO Board's RTC (`dtoverlay=i2c-rtc,pcf85063a` + coin cell) would avoid stale-clock boots.
  That is from memory and not verified.
- **Carrier would be the owner's Waveshare CM4-IO-BASE** (2230 M.2 slot), not the official IO
  Board:
  - Leave the M.2 slot empty at first. No 2230 drive has capacitor PLP, and a second device adds a
    failure point.
  - The owner's idea is to **move logging to a 2230 NVMe to spare the eMMC.** Do it only if
    measurements say so:
    - Cut **bytes written** first. Size caps (`SystemMaxUse`, AdGuard's 7-day `querylog.interval`)
      only limit stored history, not write volume, so they are **not** wear mitigations. Real
      levers:
      - one logger: NixOS runs only journald, while Ubuntu also wrote everything to rsyslog
      - no swap on eMMC
      - `/tmp` on tmpfs
      - AdGuard `querylog.file_enabled = false` on this backup node (needs a per-host override of
        the shared `network.nix`)
      - where the system is built barely matters: the closure lands on the Pi either way, and
        on-host builds add only build-time deps (~600 MiB) on the occasional deploy that rebuilds
        them
      - `Storage=volatile` would remove journal writes but loses logs across reboots; not
        recommended after these forensics relied on persisted logs
    - Measure writes per day via `node_disk_written_bytes_total{device="mmcblk0"}` (already
      scraped) and the eMMC wear estimate via `mmc extcsd read`.
    - The ~6 GiB/day seen on Ubuntu included Docker churn; NixOS without Docker should write less.
    - If it's needed: journald (+ the AdGuard work dir) on the NVMe, with a **`nofail`** mount so a
      dead log drive can't block boot.
  - Power is 5 V USB-C (Waveshare: 2.5 A); use a good 5 V/3 A supply on a UPS outlet.
  - Flash via `rpiboot` over its USB-C with its boot switch (see Waveshare's wiki for A/B).
  - Whether this board has an RTC is unknown; check.

The Pi analysis below stands as the fallback.

**More stable = get storage off USB.** For a single self-contained host with an enterprise PLP
drive:
1. **Pi 5 + Geekworm X1001-Max** + a used enterprise **M.2 22110 NVMe with capacitor PLP** on a
   22110→2280 extender.
   - The HAT gives the M.2 3.3 V at 8 A (~3× an 8.25 W drive) from its own 9–20 V DC or 27–120 W
     USB-C PD input, and powers the Pi over GPIO. No USB bridge, no PoE HAT.
   - Caveats: the HAT is new (Sep 2026) with no field reports, and the 22110 overhang is
     unverified.
2. **Pi 5 + Geekworm X1002**: 3.5 A, fed from the Pi's 27 W supply; less headroom.
3. **PoE:** Geekworm X1012 has a thin budget (~20 W worst case vs ~22–23 W real) and a
   switch-dependent failure report. **Avoid the 52Pi EP-0241** (reboot loops; a 990 Pro won't boot
   on it).
4. **CM4 + official IO Board:** the slot's 3.3 V @ 3 A puts an 8 W drive at ~80 %, x4 adapters
   need a riser, it needs 12 V (PoE disables PCIe), and `kernel` on BCM2711 is unproven.

**Drives** (22110, PLP): PM983 8.0 W, PM963 7.5–9 W, PM9A3 8.25 W, Micron 7300 PRO / 7400 PRO
8.25 W (the 7400 can be capped to 4 W after boot), P4511 8.25 W (discontinued). **Synology
SNV3510-400G** runs 4.0 W typical and is the only one on any Pi-family compatibility list (Compute
Blade, CM4).

**The real risk:** no public report shows an enterprise NVMe booting under the Pi bootloader.
CAP.TO is 20–30 s, and how long the bootloader waits is undocumented. Test before relying on it.
The fallback is the boot files on a microSD with root on the NVMe.

**Staying on USB?** No chipset has real reliability evidence. The best-reported is an ASM1153E on
firmware 141126 (or an RTL9210B), behind a powered USB 3 hub (works around the Pi 4 VL805 bug and
the 1.2 A cap), with UAS off and SMART 199 watched. See
[usb-sata-bridges.md](usb-sata-bridges.md).

**Ruled out:**
- Optane as the boot drive: the Pi bootloader can't boot it (CM4 or Pi 5); it works as a data
  disk.
- The on-hand USB adapters: all ASMedia `174c:55aa`.
- Consumer NVMe, SD and eMMC: no PLP.
- Network boot: a dependency on the cluster pi-rack must outlive.

## Repo-level traps found along the way

- **The committed NixOS config would bring the NIC up as `end0`**, so
  `keepalived.interface = "eth0"` binds nothing. It is now fixed with a MAC pin to `genetp0`
  (`systemd.network.links`), like the Proxmox nodes ([nixos-findings.md](nixos-findings.md)).
- **NIM never removes UniFi reservations.** A new board's MAC needs the old fixed IP cleared by
  hand ([ops-findings.md](ops-findings.md)).

## Files

| File | What's in it |
|---|---|
| [failure-evidence.md](failure-evidence.md) | SMART history, Prometheus timeline, UPS/mains ruled out, cause analysis, the tests to run |
| [usb-sata-bridges.md](usb-sata-bridges.md) | `uas-detect.h` for `174c:55aa`, Pi 4 USB-SATA issues, quirks, power budget, flush/FUA, known-good chipsets, the on-hand adapter IDs |
| [boot-media-alternatives.md](boot-media-alternatives.md) | SD / USB flash / eMMC / netboot / NVMe / N100 comparison, write reduction, Innodisk 3ME2, 2230 PLP |
| [optane-and-pi5-hats.md](optane-and-pi5-hats.md) | Optane M10 facts and the no-boot evidence, Pi 5 2280 single/dual HATs, Pi 5 EEPROM |
| [enterprise-nvme-and-power-hats.md](enterprise-nvme-and-power-hats.md) | 22110 PLP drive power table, Pi evidence (none), power-capable HATs, PoE+ budget, CM carriers |
| [cm4-path.md](cm4-path.md) | CM4 IO Board slot/power, Waveshare boards, usbboot on macOS, nixos-raspberrypi CM4 coverage |
| [nixos-findings.md](nixos-findings.md) | the `eth0`/`end0` defect, config.txt, building an image from pi-rack's config, first boot without the sops key, the Pi 5 variant eval |
| [ops-findings.md](ops-findings.md) | NIM/MAC procedure, NUT refs, secrets state, `deploy-host.sh` specifics, monitoring gaps |
