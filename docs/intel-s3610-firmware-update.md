# Intel DC S3610 firmware update

Runbook for updating the firmware on the Intel DC S3610 1.6 TB drives before they are put into
service. **Executed once, on `BTHC6306000V1P6PGN` (`G2010150` → `G2010170`) on 2026-09-07** —
the phases below record what was actually done, not what was planned.

Per-drive inventory, health and firmware currency: [ssd-inventory.md](../hardware/ssd-inventory.md),
"Unused / shelved" → "The five Intel DC S3610 1.6 TB".

## Only one of the five had an update to apply

The suffix on the model number is the OEM code, and each badge is a separate firmware lineage:
no suffix = retail Intel, `P` = HPE, `R` = Dell, **`K` = Cisco UCS**. A tool only ever ships one
lineage's images.

| Serial | Model reported | Firmware | Newest for its branch | Action |
|---|---|---|---|---|
| `BTHC6306000V1P6PGN` | `INTEL SSDSC2BX016T4` | `G2010170` | `G2010170` | **updated 2026-09-07**, `G2010150`→`G2010160`→`G2010170` |
| `BTHC637404T21P6PGN` | `INTEL SSDSC2BX016T4` | `G2010170` | `G2010170` | none — already current |
| `BTHC722408RR1P6PGN` | `INTEL SSDSC2BX016T4K` | `G201CS01` | `G201CS01` | none — Cisco UCS SKU, already newest for that branch |
| `BTHC646101YB1P6PGN` | `LK1600GEYMV` | `4IWTHPG1` | `HPG6` | **behind, but unreachable** — HPE tooling on HPE hardware |
| `BTHC72640DGK1P6PGN` | `LK1600GEYMV` | `4IWTHPG2` | `HPG6` | **behind, but unreachable** — same |

Only the two HPE-badged drives are genuinely behind. The Cisco drive looks stranded on an
unfamiliar version but is not: `SSDSC2BX016T4K` is listed at `G201CS01` across Cisco UCS
C-Series 4.0(1)–4.0(4), with nothing newer in 4.1.

Intel's position on the OEM drives is explicit: *"Original equipment manufacturer (OEM) drives
have specific firmware built for their purposes/system designs. Therefore it is not possible to
update the firmware of these drives using the Intel® SSD Management tools"*, with HP named as an
example.

The reason `BTHC6306000V1P6PGN` was different was not a guess: `BTHC637404T21P6PGN` reports the
**identical model string** and was already running `G2010170`, so the target firmware was proven
to run on that exact model before anything was written.

## Prerequisites

- The drive is **carrying nothing you need**. Do this before it is an OSD or a live ZFS vdev
  member; if the update bricks it, the cost should be one spare drive and nothing else.
  **Check, do not assume** — on 2026-09-07 all four attached S3610s turned out to still carry
  ZFS labels from a pool (`basin`, 2× mirrors, from a host that no longer exists), which was
  only found because the pre-flight looked:

  ```sh
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT /dev/sdX   # want: no filesystem, no mountpoint
  zpool import                                    # read-only scan; imports nothing
  ```

  A firmware update does not destroy data, so a label is not itself a blocker — but "this disk
  is blank" should be something you verified, not something you assumed.
- Mains power that will not be interrupted. The write takes 30 s – 2 min and an interruption
  can leave the drive non-functional.
- The allocation has slack: if this drive dies here, `BTHC722408RR1P6PGN` (the planned spare)
  becomes the second Ceph OSD and nothing else changes.

## Phase 0 — Identify the drive by serial

**Device letters are not identities.** During the inspection that produced this runbook, `sdv`
was two different drives twenty minutes apart. Resolve the serial first and use it for every
subsequent step:

```sh
lsblk -dno NAME,MODEL,SERIAL | awk '/LK1600GEYMV|SSDSC2BX01/'
```

`lsblk` truncates MODEL to 16 characters, which is why the pattern is `SSDSC2BX01` and not the
full `SSDSC2BX016T4`.

Confirm the target reads exactly `INTEL SSDSC2BX016T4` — no `K` suffix — and `G2010150`:

```sh
smartctl -i /dev/sdX | grep -E 'Device Model|Serial Number|Firmware Version'
```

**Required artifact:** the serial `BTHC6306000V1P6PGN` and firmware `G2010150` printed together
from the same device node, in the same command, before anything is written.

## Phase 1 — Where to run it

Preferred: **a direct SATA port on a bench machine, booted from a live Linux USB.** Nothing is
installed permanently, and no HBA sits in the command path.

The drives are currently attached to `nas-01` behind the Broadcom 9305-24i. That may work, but
whether the tool can issue a firmware download through that HBA is **unverified** — treat
Phase 2's "the tool lists the drive" check as the gate. It costs one command to find out. Do
not install the tool on `nas-01` permanently; it is a bench utility, not managed state.

## Phase 2 — Get a tool that actually carries the firmware

This is the step that decides whether the rest is possible. The S3610 is EOL (2017) and its
firmware has been **removed from Solidigm Storage Tool 1.15**.

**Measured 2026-09-07: Solidigm Storage Tool `1.11.268` carries `G2010160`, not `G2010170`.**
Asked about `BTHC6306000V1P6PGN` (on `G2010150`) it offers `G2010160`; asked about
`BTHC637404T21P6PGN` (already on `G2010170`) it reports "current firmware as of this tool
release". Secondary sources claiming 1.11 ships `G2010170` are wrong — the tool is the
authority, so read what it actually offers rather than trusting a version number.

**`G2010170` is present in the installed tool**, despite not being offered. The firmware images
live in the per-family modules, not the `sst` binary, and the data-centre module carries the
whole ladder:

```sh
strings /usr/lib/solidigm/FirmwareModules/firmware_module_dc.so | grep -oE 'G20[0-9]{5}' | sort -u
# G2010100 G2010110 G2010120 G2010130 G2010140 G2010150 G2010160 G2010170
```

(`firmware_module_client.so` stops at `G2010160`; the S3610 is a data-centre drive, so `dc` is
the applicable module.)

The tool applies that ladder **one step per `load`**, which is why a drive on `G2010150` is
offered only `G2010160`. **Confirmed by execution on 2026-09-07**: after the first `load` the
drive reported `G2010160` and `FirmwareUpdateAvailable : G2010170`; a second `load` took it to
`G2010170`, after which the tool reports it current. Budget **two** irreversible writes to get
from `G2010150` to `G2010170`.

Solidigm's current firmware page no longer lists the S3610 at all, so there is nothing
authoritative documenting this; the sequence above is what the tool actually did.

Both tools are Linux CLI binaries shipped as RPMs; `rpm2cpio … | cpio -idmv` extracts them on
Debian. `sst` is already installed on nas-01 at `/usr/bin/sst`.

List the drives. `isdct` syntax is confirmed; the Solidigm tool renamed `-intelssd` to `-ssd`,
so check `sst help` rather than assuming:

```sh
isdct show -intelssd          # or: sst show -ssd
```

**Required artifact — do not proceed without both:**

1. the target drive appears in the listing, matched by **serial**, with its index; and
2. the tool reports an available firmware update for it, and you have **read which version it
   names**. Do not infer it from the tool's version number — SST 1.11.268 offers `G2010160`
   here, while secondary sources claim it ships `G2010170`.

If the drive is listed but no update is offered, the tool does not carry the firmware. Get a
different version — do **not** run `load` and hope.

**Read the output with the record boundaries, not the field order.** `sst show -ssd` prints
each drive's fields alphabetically, so `Firmware` appears *before* `ModelNumber` and
`SerialNumber`. A filter that prints on the firmware line pairs it with the previous drive's
serial — during this runbook's own dry run that produced a table showing a WD hard disk running
Intel firmware and the target already up to date. Split on the `- <serial> -` header lines, and
cross-check against `smartctl -i` before believing anything:

```sh
sst show -ssd | awk '
  /^- .+ -$/ { if (ser!="") printf "%-20s %-22s fw=%-10s update=%s\n", ser, mod, fw, upd;
               ser=$2; mod=""; fw=""; upd=""; next }
  /^ModelNumber :/             { sub(/^ModelNumber : /,"");             mod=$0; next }
  /^Firmware :/                { sub(/^Firmware : /,"");                fw=$0;  next }
  /^FirmwareUpdateAvailable :/ { sub(/^FirmwareUpdateAvailable : /,""); upd=$0; next }
  END { if (ser!="") printf "%-20s %-22s fw=%-10s update=%s\n", ser, mod, fw, upd }'
```

If the drive does not appear at all and you are going through the HBA, move it to a direct SATA
port and retry before concluding anything. Measured 2026-09-07: `sst` on nas-01 **does**
enumerate all four S3610s through the Broadcom 9305-24i, so enumeration at least is not blocked
by the HBA. Whether a firmware *write* passes through it is still untested.

## Phase 3 — Update

**Target by serial number, never by index.** `sst load` accepts
`-ssd (Index|SerialNumber|PhysicalPath)`, and the index is positional — it renumbers as drives
come and go, exactly like a `sdX` letter. The serial cannot drift:

```sh
sst load -ssd BTHC6306000V1P6PGN            # correct: names the drive itself
sst load -ssd 24                            # avoid: index is positional and moves
```

It prompts `You have selected to update the drives firmware! Proceed with the update? (Y|N):`
and on success reports `Status : Firmware Updated Successfully.` **Do not pass `-f`** — the
prompt is the last chance to catch a mistake.

`load` also accepts `-source (path)` for an explicit firmware image. That is for a
vendor-supplied file; do **not** try to carve an image out of `firmware_module_dc.so` and feed
it in. The module's internal format is undocumented, and a malformed image is precisely how a
working drive becomes a paperweight.

Do not interrupt it, do not unplug anything, do not run it against more than one drive at a
time.

Then re-run the Phase 2 listing. If it now offers `G2010170`, repeat this phase once more; that
second step is what actually reaches the target.

The tool prints `Please reboot the system.` **Measured 2026-09-07: no reboot was needed** —
the drive reported the new firmware immediately, before any reset, on both steps. Verify with
Phase 4 rather than trusting either the message or this note; if the old version is still
reported, a per-device rescan (`echo 1 > /sys/block/<dev>/device/rescan`) is the least
disruptive next step, and a power cycle after that.

## Phase 4 — Verify

```sh
smartctl -i /dev/sdX | grep -E 'Serial Number|Firmware Version'   # expect G2010170
smartctl -l devstat /dev/sdX | grep -E 'Percentage Used|Logical Sectors Written'
smartctl -A /dev/sdX | awk '$1==175 || $1==233 || $1==5 || $1==187'
smartctl -H /dev/sdX
```

Expected, matched against the pre-update figures in
[ssd-inventory.md](../hardware/ssd-inventory.md):

- Firmware `G2010170`, **same serial**.
- `175 Power_Loss_Cap_Test` still normalized 100 — the capacitor test is why these drives were
  chosen over the consumer NVMe they replace.
- `233 Media_Wearout_Indicator` still 94, `241` host writes unchanged (~893 TB). A firmware
  update does not consume endurance; a jump here means something else happened.
- `5 Reallocated_Sector_Ct` and `187 Reported_Uncorrect` still 0.
- Overall health `PASSED`.

Observed on the 2026-09-07 run, `G2010150` → `G2010170`: every attribute above unchanged,
capacity byte-identical, health `PASSED`, error log clean, and the ZFS label on the disk intact
— a firmware update does not touch user data. Two things did move, both expected:

- **`ATA Version` now reads `ACS-3`**, which is exactly what `G2010160`'s release notes said it
  added.
- **Attribute 175's raw went 13030 → 11130** while its normalized value stayed 100 against a
  threshold of 10. That is the capacitor test re-running and returning a new measurement, not a
  degradation — the normalized value is the pass/fail signal. Worth re-reading once more later
  to confirm it is stable rather than trending, since PLP is why these drives were chosen.
- Logical sectors written moved by 8 (4 KiB). Noise.

Update the drive's firmware column in `hardware/ssd-inventory.md` in the same sitting.

## If the update fails

Intel's guidance for a failed or blank-screen update is to power down, reboot and retry. Beyond
that:

- **Drive still enumerates, firmware unchanged** — the tool did not carry the firmware, or the
  command path (HBA) did not pass it through. Go back to Phase 2; try a direct SATA port.
- **Drive still enumerates on the old firmware but SMART now shows new errors** — stop. Do not
  put it into service. It becomes the shelf spare and `BTHC722408RR1P6PGN` takes its slot.
- **Drive does not enumerate at all** — it is gone. Reallocate per the note in Prerequisites.
  There is no recovery path for a bricked SATA SSD without vendor tooling this drive is EOL for.

## Do not attempt this on the other four

The two HPE-badged drives and the `K`-SKU are not merely "not recommended". The reason is
concrete rather than a licence check: **the tool contains no firmware images for their
branches.** Grep every module and the binary and only the retail `G20101xx` ladder is present —
no `G201CS*`, no `4IWTHPG*`, no `HPG*`:

```sh
for f in /usr/lib/solidigm/FirmwareModules/*.so /usr/lib/solidigm/storelib.so /usr/bin/sst; do
  strings "$f" | grep -oE 'G201CS[0-9]{2}|4IWTHPG[0-9]|HPG[0-9]' | sort -u
done     # measured 2026-09-07: no output
```

`sst` says as much for both: *"No known update for SSD. If an update is expected, please contact
your SSD Vendor representative"* — which is literal. The images exist, at the OEM. Forcing the
issue by extracting a retail image and feeding it via `-source`, or with a raw
`hdparm --fwdownload`, is how a working drive becomes a paperweight: these drives validate
firmware against their own SKU, and if one did accept a mismatched image you would have retail
firmware on an OEM-configured drive. Specifically:

- `HPG6` for the HPE pair exists **partly to fix drives failing during a firmware update**,
  which makes updating *from* `HPG1`/`HPG2` the risky operation, and it needs HPE tooling on
  HPE hardware.
- `G201CS01` is **Cisco's** branch — the `K` suffix is the Cisco UCS OEM code — and it is
  already the newest firmware Cisco published for this model: `SSDSC2BX016T4K` is listed at
  `G201CS01` across Cisco UCS C-Series releases 4.0(1) through 4.0(4), with nothing newer in
  4.1. So unlike the HPE pair, this drive is not behind at all; it is current for its lineage
  and there is nothing to chase.

And one that is not blocked at all: `BTHC637404T21P6PGN` is a plain retail drive already on
`G2010170`, and `sst` reports it *"contains current firmware as of this tool release."* There is
simply nothing newer for it.

The HPE pair and the `K`-SKU are documented as deliberately left as-found. The SMART reporting
gap on the HPE pair is worked around with `smartctl -l devstat`, not with a firmware flash.

## Reference

- [hardware/ssd-inventory.md](../hardware/ssd-inventory.md) — per-drive serials, health, firmware
  currency table, and the three SMART reading traps for this drive family.
- [Intel: unable to update OEM SSD firmware](https://www.intel.com/content/www/us/en/support/articles/000030962/memory-and-storage/client-ssds.html)
- [Intel SSD Firmware Update Tool](https://www.intel.com/content/www/us/en/download/17903/intel-ssd-firmware-update-tool.html) — bootable ISO alternative; requires Legacy Boot.
