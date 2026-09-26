# pi-rack failure (2026-09-24): evidence and cause analysis

All data was read on 2026-09-25 from Prometheus, Scrutiny, the UniFi and UPS notes in
`tasks/pikvm-hid-beszel-flapping.md`, and the Mac's IORegistry. Times are CDT.

## The hardware that failed

| Part | Identity |
|---|---|
| Host | Raspberry Pi 4B Rev 1.4, 8 GB; official PoE+ HAT; Ubuntu 24.04 |
| SSD | Intel DC S3520 M.2 SATA 150 GB, `SSDSCKJB150G7`, serial `PHDW805500QD150A`, firmware `N2010112`, 512e (4096 physical), PLP |
| Enclosure | ASMedia bridge, USB `174c:55aa`, USB product string `ASMT1051`, SCSI identity `ASMT 2235`, USB serial `123456792B8C`. Links at **10 Gb/s** on the Mac, so it is a USB 3.2 Gen 2 part (ASM2235/235CM class), not the 5 Gb/s ASM1051 its string claims. Linux bound `uas` to it |

## SMART history (Scrutiny, drive `PHDW805500QD150A`)

| Result date | Power-on hours | **199 CRC** | 12 power cycles | 174 unsafe shutdowns | 183 downshift | Temp °C | 241 host writes |
|---|---|---|---|---|---|---|---|
| 2025-10-02 | 31425 | 0 | 69 | 66 | 0 | 47 | 331169 |
| 2025-12-02 | 32578 | 0 | 73 | 70 | 0 | 49 | 332269 |
| 2026-03-02 | 35122 | 0 | 78 | 75 | 0 | 48 | 334560 |
| 2026-04-01 | 35793 | 0 | 79 | 76 | 0 | 45 | 335232 |
| 2026-05-02 | 36561 | 0 | 82 | 79 | 0 | 42 | 336035 |
| 2026-06-01 | 37301 | 0 | 88 | 85 | 0 | 52 | 337309 |
| 2026-07-02 | 37972 | 0 | 91 | 88 | 0 | 46 | 338339 |
| **2026-08-02** | 38644 | **4** | 94 | 91 | 0 | 46 | 339418 |
| **2026-08-28** | 39280 | **44** | 103 | 100 | 0 | 45 | 340289 |
| 2026-08-31 | 39352 | 44 | 103 | 100 | 0 | 47 | 340393 |
| 2026-09-04 | 39448 | 44 | 103 | 100 | 0 | 46 | 340520 |
| 2026-09-07 | 39520 | 44 | 103 | 100 | 0 | 49 | 340649 |
| 2026-09-11 | 39616 | 44 | 103 | 100 | 0 | 43 | 340807 |
| 2026-09-14 | 39688 | 44 | 103 | 100 | 0 | 46 | 340929 |

Media health at the newest result:
- 5 reallocated: 0
- 197 pending: 0
- 187 reported uncorrectable: 0
- 184 end-to-end: 0
- 170/232 reserve: 100
- 233 wearout: normalized 98
- **175 power-loss capacitor test: normalized 100** (threshold 10)

Scrutiny flagged 199 as status 2. Nothing alerted on it.

**Comparison: same model, native SATA.** The spares `PHDW7420007J150A` (ex vm-host-01) and
`PHDW736503MP150A` (ex vm-host-02) read **199 = 0 in every result** (2026-06-01 → 2026-09-11),
with all media attributes clean.

**174 moving with 12 is not a fault signal.** Almost every power cycle counts as "unsafe" on all
three drives, including the spares in Proxmox hosts. The PLP capacitors cover in-flight data.

## Collector and data gaps

- `scrutiny-collector.service` on pi-rack was **failed on every run from 2026-09-16 01:00**. It was
  inactive (succeeding) before that. Source: Prometheus `node_systemd_unit_state`. Its logs are
  on the dead drive.
- The last Scrutiny data from pi-rack is 2026-09-15 05:01.
- Prometheus holds pi-rack series only from 2026-09-10 onward, so there is no Prometheus view of
  July or August.

## 2026-09-24 timeline (Prometheus, 15 s scrapes)

| Time | Load1 | Temp °C | Procs blocked | Procs running | I/O full stall | Under-voltage alarm | Uptime |
|---|---|---|---|---|---|---|---|
| 15:50–16:04 | 1.9–2.8 | 71.1–73.0 | **0** | 3–8 | ~0 | 0 | 3.74e6 s (up since 08-12 08:06) |
| **16:04:50** | — | — | — | — | — | — | **reboot** (`node_boot_time_seconds` changed) |
| 16:07 | **20.2** | 67.2 | **30** | 2 | **0.475** | 0 | 130 s |
| 16:08 | 10.1 | 66.7 | 0 | 2 | 0.502 | 0 | 190 s |
| ~16:09 | — | — | — | — | — | — | gone; no further scrapes |

- `node_disk_io_now{device="sda"}` was **14** at 16:07.
- `up`: node 1 → 0 at 16:05, back to 1 at 16:07, 0 from 16:09. nut 1 → 0 at 16:05, 1 at 16:06,
  0 from 16:07. keepalived 0 from 16:05.
- Root never went read-only (`node_filesystem_readonly` = 0), and `node_filesystem_device_error` =
  0 up to 16:08.
- No OOM kills. MemAvailable 7.1–7.5 GB.
- Daily max temperature (09-10 → 09-24): 70.6–76.0 °C.
- UniFi logged "Rack - 24 Port 2.5GbE POE Switch power-cycled Port 7 connected to pi-rack" at
  16:26, 16:57 and 17:28 — an auto power-cycle of an already-dead host. It did not revive it.
- **Mains and UPS are ruled out.** The UPS NMC log showed input 120.9–122.4 V at 16:05 and only
  the OL flag ever. See `tasks/pikvm-hid-beszel-flapping.md:55-56`.

## What the under-voltage metric can and cannot show

- The kernel driver `raspberrypi-hwmon` polls the firmware's **sticky** under-voltage bit (bit 16)
  every 2 s (`drivers/hwmon/raspberrypi-hwmon.c:65`, `schedule_delayed_work(..., 2 * HZ)`).
- It logs `dev_crit(... "Undervoltage detected!")` / `dev_info(... "Voltage normalised")`
  (`:48-52`), and journald forces crit messages to disk immediately.
- The hwmon `in0_lcrit_alarm` that node_exporter scrapes is only held for about one poll interval.
  So "0 in every 15 s scrape" does **not** exclude brief sags. The dead drive's kernel journal
  would.

## Cause analysis

**Most likely: the enclosure's SATA link (moderate confidence).**
- SMART 199 counts CRC errors that the drive sees on frames arriving over the SATA link from the
  bridge. Intel defines it as "the total number of encountered SATA interface cyclic redundancy
  check (CRC) errors" (S3520 spec 334826-001US).
- The errors began in service in July (0 → 4), in this enclosure only.
- The +40 jump (08-02 → 08-28) spans two things: the early-August handling, when the drive was
  pulled and macOS `dd` failed every read through this enclosure with ~8 s SCSI timeouts (on the
  Mac's healthy USB power), and pi-rack's in-service days from 08-12. How the 40 split between
  them is unknown.
- The ASM225CM/235CM family on `174c:55aa` is exactly the chip in raspberrypi/linux #5060 and
  #5076. The known chain there is: link or UAS errors → `uas_eh_abort_handler` → "xHCI host
  controller not responding, assume dead" → ext4 "Aborting journal" → hang.
- The boot-2 I/O stall (30 blocked, 14 in flight) and the resulting filesystem corruption fit that
  chain. Writes discarded during a UAS reset explain ext4 damage without any power-loss event.
- *Inference:* the collector failing from 09-16 fits a bridge whose SMART passthrough was
  degrading.

**Contributing, not separable with current data: power.**
- The Pi 4 caps downstream USB at 1.2 A total, whatever feeds the Pi (RPi docs), and the PoE+ HAT
  does not raise that.
- The S3520 M.2's 3.3 V inrush is 1.5 A typical peak for under 1 s (M.2 240–960 GB table). The
  estimate at 5 V is ~1.1–1.2 A, plus the bridge — at the cap.
- Marginal supply to the enclosure produces the same SATA CRC errors.
- *Inference:* a transient sag on the Pi's rail could explain the abrupt 16:04:50 reset, which
  had no storage precursor at all.

**Unlikely: the SSD itself.** Media is clean and PLP passes, and it ran in this enclosure with 0
CRC errors for at least 9 months before July.

## Forensics on nas-01, 2026-09-25 16:36–16:56 (read-only, native SATA via the 9305-24i HBA)

Addressed only as `/dev/disk/by-id/scsi-SATA_INTEL_SSDSCKJB15_PHDW805500QD150A`. The by-id name
truncates the model to `SSDSCKJB15`. Nothing was mounted or written, and the temp extracts in
nas-01's `/tmp` were deleted afterwards.

**The drive is healthy on a good link.**
- `smartctl`: PASSED, 6.0 Gb/s, 0 realloc/pending/uncorrectable/E2E, PLP test 100, wearout 98.
  **199 = 45** (44 on 09-14). Power cycles 110.
- **A full-surface read over native SATA** (150 GB in 351 s, ~427 MB/s) gave **zero errors**:
  - 199 stayed 45
  - hardware resets stayed 3,989
  - every SATA PHY event counter read 0 afterwards (no ICRC, no R_ERR)
  - no kernel errors
- The same drive that logged CRC errors and link resets in the enclosure is clean here. **The
  drive is exonerated.**

**What the drive recorded while it lived in the enclosure:**
- ATA device statistics:
  - **Number of Hardware Resets: 3,989** (link resets) against only 110 power-on resets
  - **Resets Between Cmd Acceptance and Completion: 85** — resets that hit commands in flight,
    the mechanism that discards writes
  - Number of Interface CRC Errors: 45
- The extended error log: **6 errors, all `ICRC, ABRT`** (interface CRC error, command aborted).

| # | Power-on hours | When in that power-on | Commands | Note |
|---|---|---|---|---|
| 1 | 38177 | 00:00:35 (booting) | READ FPDMA | LBA **13581312** |
| 2 | 38738 | 00:00:31 (booting) | READ FPDMA | LBA **10864672** |
| 3 | 38738 | 00:00:41 (booting) | READ FPDMA | LBA 15414640 |
| 4 | 38753 | 15:03:11 | READ/WRITE FPDMA | LBA 5435656 |
| 5 | 38753 | 15:03:13 | 1024-sector sequential WRITE FPDMA | LBA 32254976 |
| 6 | 39995 | 01:00:50, right after an IDENTIFY + SET FEATURES re-init (a link reset) | WRITE DMA EXT | after the 09-24 crash |

- Three of the six hit during the first 31–41 s after power-up, when the Pi boots.
- **The host saw them.** pi-rack's own boot logs on the drive show
  `I/O error, dev sda, sector 13581312 … (READ)` at 20.9 s into a boot (`/var/log/dmesg.4.gz`) and
  `I/O error, dev sda, sector 10864672 … (READ)` at 14.5 s (`dmesg.3.gz`). **Those are the exact
  LBAs** of errors 1 and 2.

**The filesystem is not damaged.** `e2fsck -fn` passes all five passes. The only complaints are
the free block and inode summary counts, which are normal with an unreplayed journal. The
superblock:
- `needs_recovery`
- **`Errors behavior: Continue`**, so ext4 does not remount read-only on errors unless fstab says
  so
- last write time stamped 09-15 04:53:26

The journal holds only ~145 transactions (sequence 1991854–1991998, ~15 MB). The Pi's
"filesystem errors" at boot were I/O failures through the enclosure, not on-disk corruption.

**Nothing written from 09-15 04:53 to the crash survived.**
- The on-disk syslog shows normal logging (~35 lines/h) up to **09-15 04:52:25** (PackageKit
  starting: the daily apt run).
- The next lines are a boot stamped 04:53:22. That boot cannot really be on 09-15: Prometheus shows
  continuous uptime from 08-12 to 09-24.
- The timesync clock file's on-disk mtime is **09-15 04:53:16**. At boot, a Pi with no RTC sets
  its clock from that file. So the boot stamped 04:53:22 is the **post-crash boot of 09-24**,
  starting from a disk frozen at 09-15 04:53.
- There are no sysstat daily files after the one created 09-15 00:07, and the node_exporter
  textfile was last written 09-15 04:15.
- The ~145 journal transactions fit a boot that ran only minutes.
- Meanwhile, from 09-15 to 09-24 the running system looked healthy: root mounted rw, 0 blocked
  processes, no I/O stall. It was living on page cache while ~9.5 days of writes never became
  durable, or were discarded at the post-crash journal replay.
- `beszel-agent` logged `smartctl failed device=/dev/sda err="exit status 2"` 52 times from
  09-13 00:09 on (the earliest syslog on disk). SMART passthrough through the bridge was already
  failing.

**No under-voltage in any log that persisted.** There are zero `Undervoltage detected` lines in
the July boot logs, kern.log 08-25 → 09-01, or syslog 09-13 → 09-15 04:52. The 09-15 → 09-24
window is lost.

**Verdict (high confidence on the component, moderate on the exact mechanism):**
- The storage path between the Pi and a healthy drive failed: the USB-SATA enclosure.
- It produced SATA-link CRC errors that surfaced as host I/O errors during boots from July, and
  thousands of link resets (85 with commands in flight). SMART passthrough failed from at least
  09-13. From 09-15 04:53, right after a package-manager write burst, **writes silently stopped
  persisting for 9.5 days**. That matches jdb's warning that these devices "may in rare cases
  throw write data away".
- The trigger for the 16:04:50 reset itself is still unexplained (power or kernel). PoE/USB
  power can't be excluded as a contributor to the link errors, but no persisted log shows
  under-voltage.
- The drive itself is fine to reuse.

## Tests that would settle it

1. **Done 2026-09-25** (results above): the dead drive in a nas-01 SATA bay, read-only, via an
   M.2→2.5" adapter. Address it as
   `/dev/disk/by-id/scsi-SATA_INTEL_SSDSCKJB15_PHDW805500QD150A`. The journald files are a newer
   format than nas-01's `journalctl` reads ("unsupported feature"); the text syslog, kern.log and
   dmesg files were used instead. The original steps:
   - `smartctl -x`: 199 staying at 44 on native SATA clears the drive's link.
   - `e2fsck -fn` on part2.
   - `debugfs -R 'rdump /var/log/journal /tmp/pr-journal'` (no mount; `-c` if it won't open).
   - `journalctl -D /tmp/pr-journal -k` from 07-01 to 09-24 for `Undervoltage detected` vs
     `uas_eh`, `reset SuperSpeed`, `I/O error`, `EXT4-fs error`.
   - `-u scrutiny-collector` from 09-15 to 09-17 for why it started failing.
2. **Spare S3520 in the old enclosure on a non-Pi Linux host**, under sustained read/write while
   watching 199. If 199 climbs with the Pi's power out of the loop, the enclosure is confirmed.

## How the data was pulled (for next time)

- Prometheus `https://prometheus.<domain_name>/api/v1/query_range`, e.g.
  `node_boot_time_seconds{instance=~".*pi-rack.*"}`, `node_procs_blocked`, `node_disk_io_now`,
  `rate(node_pressure_io_stalled_seconds_total[3m])`, `node_hwmon_in_lcrit_alarm_volts`,
  `node_systemd_unit_state{name=~"scrutiny.*"}`.
- Scrutiny `https://scrutiny.<domain_name>/api/summary` (device WWN + host_id), then
  `/api/device/<wwn>/details` for SMART history (`smart_results[].attrs`).
