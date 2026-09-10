# nas-host-01

## Hardware

- Case
    - [Innovision S45624 with the 12G MiniSAS HD Backplane](https://iovstech.com/4u-server-case/s45624.html) [[AliExpress]](https://www.aliexpress.us/item/3256804052792939.html?spm=a2g0o.order_list.order_list_main.11.39d11802Y8aRJw&gatewayAdapt=glo2usa)
- Motherboard
    - [Asrock Rack ROMED8-2T](https://www.asrockrack.com/general/productdetail.asp?Model=ROMED8-2T#Specifications)
- CPU
    - [AMD Epyc Rome 7282 (16 Core)](https://en.wikipedia.org/wiki/Epyc#Second_generation_Epyc_(Rome))
- RAM
    - 4x 16 GB DDR4-3200
    - 4x 32 GB DDR4-3200
- [Broadcom 9305-24i](https://www.broadcom.com/products/storage/host-bus-adapters/sas-9305-24i)
- 2x [Asus Hyper M.2 x16 Gen 4](https://www.asus.com/us/motherboards-components/motherboards/accessories/hyper-m-2-x16-gen-4-card/)
- [Linkreal 4x U.2 to PCIe x16 Adapter](http://www.linkreal.com.cn/en/products/LRNV94NF.html) [[AliExpress]](https://www.aliexpress.us/item/3256803285836696.html?spm=a2g0o.order_list.order_list_main.41.39d11802Y8aRJw&gatewayAdapt=glo2usa)
- [Nvidia RTX A4000](https://www.nvidia.com/en-us/products/workstations/rtx-a4000/)
- [Intel Arc B580](https://www.intel.com/content/www/us/en/products/sku/241598/intel-arc-b580-graphics/specifications.html)
- [Mellenox ConnectX-4 Lx](https://www.nvidia.com/en-in/networking/ethernet/connectx-4-lx/)
- [PCIe X16 To X8+X4+X4 Splitter Card Adaptor with X8 PCIe slot and 2x M.2 Slots](https://www.aliexpress.us/item/3256805673456043.html?spm=a2g0o.order_list.order_list_main.234.24de1802IAFUoi&gatewayAdapt=glo2usa)
- U.2 Drives
    - [Intel Optane 905P - 960 GB](https://www.intel.com/content/www/us/en/products/sku/147529/intel-optane-ssd-905p-series-960gb-2-5in-pcie-x4-3d-xpoint/specifications.html) [[Newegg]](https://www.newegg.com/intel-optane-905p-1-5tb/p/N82E16820167505)
    - [Intel Optane 905P - 1.5 TB](https://www.intel.com/content/www/us/en/products/sku/147526/intel-optane-ssd-905p-series-1-5tb-2-5in-pcie-x4-3d-xpoint/specifications.html) [[Newegg]](https://www.newegg.com/intel-optane-ssd-905p-series-960gb/p/N82E16820167463)
    - [HPE VK003840KWWFP (Rebranded SK Hynix PE6011) - 3.84 TB](https://www.techpowerup.com/ssd-specs/sk-hynix-pe6011-3-8-tb.d1490)
- M.2 Drives
    - 4x [Intel Optane P1600X - 118 GB](https://ark.intel.com/content/www/us/en/ark/products/211867/intel-optane-ssd-p1600x-series-118gb-m-2-80mm-pcie-3-0-x4-3d-xpoint.html) [[Newegg]](https://www.newegg.com/intel-optane-ssd-p1600x-118gb/p/1Z4-009F-00621?Item=1Z4-009F-00621)
    - 2x [Solidigm P44 Pro - 2 TB](https://www.solidigm.com/products/client/pro-series/p44.html#form=M.2%202280&cap=2%20TB)
    - 2x [Samsung 980 Pro - 2 TB](https://semiconductor.samsung.com/consumer-storage/internal-ssd/980pro/)
- Hard Drives — 18 total, in 18 of the 24 bays (6 bays empty)
    - 1x Seagate BarraCuda - 24 TB — `ST24000DM001`
    - 1x Seagate Exos (Refurbished) - 22 TB — `ST22000NM000C`
    - 3x WD Easystore shucked - 18 TB — `WD180EDGZ`
    - 2x Seagate Exos X20 (Refurbished) - 18 TB — `ST18000NM003D`
    - 1x Seagate Exos X18 (Refurbished) - 18 TB — `ST18000NM000J`
    - 3x WD Easystore shucked - 14 TB — `WD140EDFZ`
    - 1x WD Easystore shucked - 14 TB — `WD140EDGZ`
    - 1x Seagate Exos X18 (Refurbished) - 14 TB — `ST14000NM000J`
    - 1x Seagate Exos X16 (Refurbished) - 14 TB — `ST14000NM001G`
    - 2x WD shucked white-label - 8 TB — `WD80EMAZ`
    - 2x WD shucked white-label - 8 TB — `WD80EZAZ`

Model numbers are recorded because the family names alone are ambiguous — `ST18000NM003D`
(X20) and `ST18000NM000J` (X18) are both 18 TB, as are `ST14000NM000J` (X18) and
`ST14000NM001G` (X16) at 14 TB. The 8 TB drives are Easystore/Elements shucks, not retail
WD Red; a genuine 8 TB Red would be `WD80EFAX`/`WD80EFZX` (both CMR — the 2020 SMR
change affected only the 2/3/4/6 TB Reds).

### Motherboard

I initially had a [Supermicro H12SSL-i](https://www.supermicro.com/en/products/motherboard/H12SSL-i). [However, it has exposed surface mount components for the BMC next to the middle PCIe slots that I damaged with a PCIe bracket when inserting a card.](https://forums.servethehome.com/index.php?threads/h12ssl-i-stuck-at-bmc-initiating.38043/) This kills the BMC, and the BIOS by default won’t boot if the BMC isn’t online. **If you do get this motherboard, immediately disable the option in the BIOS to wait for the BMC before booting and be careful when inserting cards.** *Please learn from my mistake.*

**That applies to this board too, not just the one it replaced.** The ROMED8-2T has the same
setting at `Server Mgmt → Wait For BMC`, and the manual documents it as Enabled by default. Leave
it alone. This board's BMC restarts itself every couple of days and hung for a full hour on
2026-09-09, so enabling it would turn each of those into a machine that will not come up. It has
been proposed twice as a fix for the PCI enumeration flip; it is not one, and re-enabling Onboard
LAN solves that properly — see [Why the enumeration changes](#why-the-enumeration-changes).

### CPU

I chose the 7282 because it has a 120 W TDP vs the comparable 16 core 7302P that has a 155W TDP. It achieves this by only having 2 active CCDs vs the 7302P's 4 CCDs. [However this limits it to 4 memory channels vs the full 8 memory channels](https://www.servethehome.com/amd-epyc-7002-rome-cpus-with-half-memory-bandwidth/). I value lower power consumption over raw performance, so the trade-off was worth it. Additionally, I chose DDR4-3200 RAM (the fastest supported) to try to make up some of the performance.

## Cooling

Established 2026-09-04 by measurement, not from vendor docs — most of it is undocumented.

### Fan headers

The ROMED8-2T has **7 fan headers, all 6-pin**, rated 5 A / 60 W each. Each header carries
**two tachometer inputs and one PWM control**:

| pin | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| | GND | FAN_VOLTAGE | FAN_SPEED_SENSOR1 | FAN_SPEED_CONTROL | FAN_SPEED_SENSOR2 | NC |

Pins 1-4 are the standard 4-pin PWM order, so an ordinary fan plugs straight in. That
second tach on pin 5 is why the BMC exposes `FANn` **and** `FANn_2` sensors — 14 sensors
for 7 headers. `FANn_2` is not a separate fan, it is the second rotor of the fan on
header *n*.

### Header to fan mapping

Derived from maximum RPM at 100% duty and PWM response, since nothing labels them:

| header | RPM @100% | responds to PWM | fan |
|---|---|---|---|
| FAN1 | 3700 | yes | Noctua NF-A4x20 PWM (5000 rated) |
| FAN2 | 2300 | yes | **3x EK-Vardar F4-120ER on a splitter — front intake** |
| FAN3 | 4900 | **no — flat at 35% and 100%** | Supermicro SP3 cooler fan |
| FAN4 | 1900 | yes | Noctua NF-A14 industrialPPC-2000 |
| FAN5 | — | — | *empty* |
| FAN6 | 1700 (see below) | yes | **2x Noctua NF-A8 PWM on a splitter** |
| FAN7 | — | — | *empty* |

Eight fans on five headers. FAN2 was identified by elimination: 2300 RPM exceeds the
NF-A14's 2000 rating even at +10% tolerance, so FAN2 cannot be the NF-A14.

### Known issues

- **FAN6's tachometer is intermittent.** Both NF-A8s spin, confirmed visually, but the
  header reports `0 RPM` / `lnc`. It read a steady 1700 earlier the same day and briefly
  returned to 1700 after a duty change, so it is a flaky contact rather than a dead fan or
  a severed wire (a severed tach reads `ns`, like FAN5/FAN7). Reseat the splitter. Until
  then FAN6 sits in permanent alarm and **cannot report a real failure on that header**.
- **FAN3 ignores PWM** — 4900 RPM at both 35% and 100% duty. Most likely a 3-pin fan on a
  PWM header seeing a constant 12 V, meaning the CPU cooler has no thermal response.
  Unconfirmed.
- **A splitter discards tach.** FAN2 carries three fans but reports one; two of the three
  front intakes are unmonitored. A 6-pin header has only two tach inputs, so no cable fixes
  all three — but FAN5 and FAN7 are empty, so splitting them 2+1 across two headers would
  cover all of them. A dual-tach adapter (e.g. modDIY `2PWM4-ASRR`) wires the second fan's
  tach to pin 5; a generic splitter does not.

### Control

netfn `0x3a`, per ASRock Rack [TSDQA-72](https://download.asrock.com/Rack/TSD/FAQ/TSDQA-72.pdf).
**AST2500-only** — AST2600 boards use entirely different commands and `0x02` for manual mode.

| purpose | command |
|---|---|
| set mode (16 bytes) | `0x3a 0xd8` — `00` auto, `01` manual, `02` custom |
| set duty (16 bytes) | `0x3a 0xd6` — hex of the percentage |
| get mode | `0x3a 0xd9` |
| get saved setpoint | `0x3a 0xd7` |
| get current duty | `0x3a 0xda` |
| reset to defaults | `0x3a 0xd8` with all sixteen bytes `0x00` |

Managed with [ipmitool-asrock-fan-control](https://github.com/andyattebery/ipmitool-asrock-fan-control)
(`~/projects/ipmitool-asrock-fan-control` on the host).

Things that cost time to work out and are not written down anywhere else:

- **The arrays are always 16 bytes** even though the board has 7 headers. Slot 8 is
  firmware-live but has no physical header; 9-16 are unpopulated. Every write rewrites all
  16 slots — there is no per-slot command — so setting one fan re-applies a duty to every
  fan on the board.
- **Minimum duty is 20%.** The BMC accepts 20 and *rejects* 19 and below outright with
  `rsp=0xcc: Invalid data field in request`, discarding the whole write. It does not clamp.
  Fans cannot be stopped through this interface.
- **`0xd7` is the saved setpoint, `0xda` is the live duty.** They diverge whenever a fan is
  in auto mode. Rebuilding a write from `0xda` overwrites every other fan's stored setpoint
  with a live sample of the BMC curve. TSDQA-72 calls `0xd7` "fan setting mode", which is
  wrong for this board.
- **The BMC sometimes reports failure for a write it applied** — `rsp=0xff` with
  ipmitool's "Received a response with unexpected ID". Verify by reading back; neither
  trusting nor ignoring the exit status is correct.

### Backplane

**The backplane is a black box and the fans are wired direct to the motherboard on
purpose.** Its own fan headers are driven by an onboard temperature controller keyed to
drive temperature, which is the wrong input when the thing overheating is a GPU.

There is no software path to it, confirmed rather than assumed:

- No SES device. The SCSI bus shows only disks and cd/dvd, no `enclosu` type, and
  `/sys/class/enclosure` is empty. Checked independently of the `ses` driver, which is not
  even available in the nas-01 kernel.
- No expander — `sas_expander` count is 0, consistent with 6x SFF-8643 direct-attach into
  a 24-port HBA.
- The `enclosure logical id` the drives report (`0x500062b203e59c80`) is derived from the
  HBA's own SAS address (`...c87`), as are the drive addresses (`0x3000_62b203e59c8X`).
  That is mpt3sas synthesising an enclosure for direct-attach SATA, not a real one.

So no HBA configuration, jumper or cable change would expose SES — there is nothing there
to expose. A genuine Supermicro BPN-SAS-846A carries an MG9072 SES-2 chip; this does not,
which suggests it is a clone rather than a rebadge.

## Motherboard Layout

The PCIE2 Selection Jumpers are set to PE8_SEL = 1_2 and PE16_SEL = 2_3 which configures:

- PCIE2 runs at x8
- M2_1/SATA_4_7 Enabled
- OCU1/OCU2 Disabled

### M.2 Slots

#### M2_1

- Intel Optane P1600X - 118 GB

#### M2_2

- Intel Optane P1600X - 118 GB

### PCIe Slots

Order is descending from PCIE7 which is closest to the CPU.

#### PCIE7

##### Linkreal 4x U.2 to PCIe x16 Adapter

The end of this had to be trimmed ~0.5 cm to make it fit. I _think_ no traces were cut, but I haven't populated the last U.2 slot to verify...

- Intel Optane 905P - 960 GB
- Intel Optane 905P - 1.5 TB
- HPE VK003840KWWFP (Rebranded SK Hynix PE6011) - 3.84 TB

#### PCIE6

##### Asus Hyper M.2 x16 Gen 4

- 2x Solidigm P44 Pro - 2 TB
- 2x Samsung 980 Pro - 2 TB

#### PCIE5

##### Nvidia RTX A4000

#### PCIE4

Uses PCIe X16 To X8+X4+X4 Splitter Card Adaptor with X8 PCIe slot and 2x M.2 Slots with:

##### Mellenox ConnectX-4 Lx

Port 1 is `vmbr0`'s uplink, port 2 is the Ceph cluster network. Both are pinned by
MAC to `cx4p0` and `cx4p1` so a slot change can't rename them — see
[host-inventory.md](host-inventory.md#network-interface-names).

##### 2x Intel Optane P1600X - 118 GB

#### PCIE3

##### Intel Arc B580

#### PCIE2

Configured to be x8.

Empty

#### PCIE1

##### Broadcom 9305-24i

Connected to the case backplane that all of the hard drives are connected to.

## Summary

- **CPU**: AMD EPYC 7282 — 16 cores / 32 threads
- **RAM**: 192 GB DDR4-3200 as 4× 32 GB + 4× 16 GB, all running at 3200 MT/s
- **BIOS**: P3.90
- **Hypervisor**: PVE 9.2.18, running kernel 7.0.14-15-pve, Ceph 20.2.4 tentacle (2026-09-10)
    - **7.0.14-16-pve is installed and on both ESPs**, so the next boot changes the kernel as
      well as applying the `memmap=` reservations below. Two variables, one reboot.

### VMs (as of 2026-09-10)

| VMID | VM | Status | vCPUs | RAM Allocated | Boot disk |
| --- | --- | --- | --- | --- | --- |
| 200 | nas-01 | running | 14 | 80 GB | 128 GB |
| 201 | media-01 | stopped | 24 | 64 GB | 192 GB (+ 640 GB scsi1) |
| 203 | network-03 | running | 2 | 4 GB | 64 GB (Ceph) |

**Totals when all three run**: 40 vCPUs allocated against 32 threads, 148 GB RAM of 188 GiB
usable.

The vCPU figure is **overcommitted on purpose and temporarily** — media-01 was widened from
16 to 24 for a one-time job and gets narrowed again. Do not treat 40/32 as the steady state.

**The headroom is thin.** 80 + 64 + 4 leaves about 40 GiB for the host. That is enough for PVE
and a healthy `ceph-mon`, but not for a monitor that has grown during a cluster rebuild — one
reached 46 GB on 2026-09-09 and the OOM killer took both guests. Watch monitor memory whenever
the cluster is degraded, and do not raise guest memory further.

media-01 holds one snapshot, `pre-26-04`, from before the Ubuntu 26.04 upgrade (2026-08-29).

## Use

### Host

- Proxmox boot drives - ZFS RAID 1
    - 2x Intel Optane P1600X - 118 GB
- Proxmox storage
    - Intel Optane 905P - 1.5 TB
- Proxmox Ceph storage
    - Intel Optane 905P - 960 GB

### nas-01 VM Passthrough

All conventional PCI passthrough — no `pcie=1`.

| `hostpciN` | Mapping | Device | Serial | Role |
| --- | --- | --- | --- | --- |
| `hostpci0` | `broadcom_9305_24i` (`rombar=0`) | Broadcom/LSI SAS3224 (9305-24i HBA) | — | All SATA HDDs — ZFS tank data + snapraid/mergerfs pool |
| `hostpci1` | `solidigm_p44_pro_1` | Solidigm P44 Pro 2 TB | `SDC1N403710501322` | ZFS sink pool |
| `hostpci2` | `solidigm_p44_pro_2` | Solidigm P44 Pro 2 TB | `SJC1N5037101A1H3A` | ZFS sink pool |
| `hostpci3` | `samsung_980_pro_1` | Samsung 980 Pro 2 TB | `S6B0NU0W400960M` | ZFS sink pool |
| `hostpci4` | `samsung_980_pro_2` | Samsung 980 Pro 2 TB | `S6B0NU0W402398J` | ZFS sink pool |
| `hostpci5` | `skhynix_pe6011` | SK hynix PE6011 / HPE VK003840KWWFP 3.84 TB | `KIB4T0001I0204T31` | Staging/temp |
| `hostpci6` | `intel_p1600x_1` | Intel Optane P1600X 118 GB | `PHOC150200LL118B` | ZFS tank metadata special device |
| `hostpci7` | `intel_p1600x_2` | Intel Optane P1600X 118 GB | `PHOC150201CU118B` | ZFS tank metadata special device |

`rombar=0` hides the HBA's SAS boot BIOS from the guest. nas-01 boots from a virtual
disk, never from the HBA.

- ZFS Mirror Pool (tank) - 16 TB
    - 4x WD shucked white-label 8 TB (`WD80EMAZ` x2, `WD80EZAZ` x2)
    - 2x Intel Optane P1600X - 118 GB as [ZFS mirrored metadata special device](https://forum.level1techs.com/t/zfs-metadata-special-device-z/159954)
- ZFS Mirror Pool (sink) - 4 TB
    - 2x Solidigm P44 Pro - 2 TB
    - 2x Samsung 980 Pro - 2 TB
- Staging/Temp data
    - HPE VK003840KWWFP (Rebranded SK Hynix PE6011) - 3.84 TB
- Snapraid/mergerfs Pool
    - Data Disks — 12
        - 3x WD Easystore shucked - 18 TB
        - 2x Seagate Exos X20 (Refurbished) - 18 TB
        - 1x Seagate Exos X18 (Refurbished) - 18 TB
        - 4x WD Easystore shucked - 14 TB
        - 1x Seagate Exos X18 (Refurbished) - 14 TB
        - 1x Seagate Exos X16 (Refurbished) - 14 TB
    - Parity Disks
        - 1x Seagate BarraCuda - 24 TB
        - 1x Seagate Exos (Refurbished) - 22 TB

### media-01 VM Passthrough

All use `pcie=1` (the VM is `q35`).

| `hostpciN` | Mapping | Device | Role |
| --- | --- | --- | --- |
| `hostpci0` | `nvidia_rtx_a4000` | Nvidia RTX A4000 + HDA | Transcoding, AI inference (CUDA) |
| `hostpci1` | `intel_arc_b580` | Intel Arc B580 | Transcoding (QSV/VA-API) |
| `hostpci2` | `intel_arc_b580_audio` | Intel Arc B580 HDA | Rides along with the B580 |

**The A4000 passes as GPU only.** Its mapping path is `0000:01:00.0` — function-scoped, not
function-less — so the card's HDA at `0000:01:00.1` is *not* attached and sits unmapped on the
host. `lspci` inside media-01 shows the A4000 with no NVIDIA audio device.

The B580's GPU and HDA are on different buses with different device IDs, so they cannot share
one mapping — hence the two separate entries above.

### Resource mappings

Every passed-through device on this node goes through a named PCI resource mapping
in `/etc/pve/mapping/pci.cfg` rather than a raw `hostpci` address. Naming is
`<manufacturer>_<model>`, lowercased, non-alphanumerics folded to `_`, with a
numeric suffix only where the chassis holds more than one of a model.

A mapping records the device's `id`, `subsystem-id` and `iommugroup` and refuses to
start the VM if any stops matching. A raw address gets no identity check — it fails
only if the address is empty, and otherwise passes whatever now sits there.

| Mapping | Topology | ID | Subsystem-ID | Consumer |
| --- | --- | --- | --- | --- |
| `nvidia_rtx_a4000` | `0000:00/01.1/00.0` | `10de:24b0` | `1028:14ad` | media-01 |
| `intel_arc_b580` | `0000:c0/01.1/00.0/01.0/00.0` | `8086:e20b` | `1849:6021` | media-01 |
| `intel_arc_b580_audio` | `0000:c0/01.1/00.0/02.0/00.0` | `8086:e2f7` | `1849:6021` | media-01 |
| `broadcom_9305_24i` | `0000:80/03.1/00.0` | `1000:00c4` | `1000:31a0` | nas-01 |
| `skhynix_pe6011` | `0000:80/01.4/00.0` | `1c5c:2429` | `1590:02d0` | nas-01 |
| `solidigm_p44_pro_1` | `0000:c0/03.1/00.0` | `025e:f1ac` | `025e:f1ac` | nas-01 |
| `solidigm_p44_pro_2` | `0000:c0/03.2/00.0` | `025e:f1ac` | `025e:f1ac` | nas-01 |
| `samsung_980_pro_1` | `0000:c0/03.3/00.0` | `144d:a80a` | `144d:a801` | nas-01 |
| `samsung_980_pro_2` | `0000:c0/03.4/00.0` | `144d:a80a` | `144d:a801` | nas-01 |
| `intel_p1600x_1` | `0000:40/03.3/00.0` | `8086:2525` | `8086:380a` | nas-01 |
| `intel_p1600x_2` | `0000:40/03.4/00.0` | `8086:2525` | `8086:380a` | nas-01 |

The PCI address and IOMMU group are deliberately not tabulated: they are what changes, and the
`pve_pci_mapping` role writes them from the topology on every run. Read the live values with
`pvesh get /cluster/mapping/pci --output-format json`. "Topology" is the position in the PCIe
tree with bus numbers dropped — `readlink -f /sys/bus/pci/devices/<addr>`, keep the
`device.function` of each hop. Root-port numbers are fixed by the silicon; bus numbers are not.

**A mapping does not establish instance identity for the Optanes.** All four P1600X
report the same `id` and `subsystem-id`; only `iommugroup` differs, and group numbers
are renumbered by any topology change. Two of the four are the host's `rpool` boot
mirror, under root ports `00:03.5` and `40:01.1`; the two passed-through ones sit on the PCIE4
splitter under `40:03.3` and `40:03.4`, so the topology cannot reach an `rpool` drive. Serials
read by address on 2026-09-09 (drives on the `nvme` driver, VMs stopped): `intel_p1600x_1` =
`PHOC150200LL118B`, `intel_p1600x_2` = `PHOC150201CU118B`; the Solidigm, Samsung and SK hynix
serials in the table above also matched.

Working with mappings:

- Create via `pvesh create /cluster/mapping/pci` or the GUI, passing `id`,
  `subsystem-id` and `iommugroup` explicitly. `pvesh` does not read them from sysfs
  and they are optional in the schema, so a mapping created without them is accepted
  and then dies at every `qm start` with `missing expected property 'iommugroup'`.
- There is no rename API — renaming means create-new, re-point the VM, delete the old.
- `delete` has no in-use guard; deleting a mapping a VM still references leaves it
  unbootable.

**Mappings and the VMs' `hostpci` lines are managed by Ansible** since 2026-09-09:
`pve_pci_mapping` owns this node's entries in `pci.cfg`, `pve_vm_hostpci` owns the `hostpciN`
lines on VMs 200 and 201, and `textfile_collector_pve_pci_mapping` exports
`pve_pci_mapping_check_ok{mapping}` for Grafana (`rules-pve-pci-mapping.yaml`). The declaration
is in `ansible/host_vars/nas-host-01/vars.yaml`; the playbook is
`playbook-prod-proxmox-cluster.yaml --tags pci_passthrough --limit nas-host-01`. Each role's
README has the traps. The old `broadcom_9305_24e` name was deleted the same day, after VM 200
was re-pointed to `broadcom_9305_24i`.

### Why the enumeration changes

The mechanism, consistent across every boot on record:

> "Onboard LAN1/LAN2 Disabled" is applied at POST on a **cold power-on**, and only if the BMC
> is ready at that moment. On a warm reset the previous hide state persists. A cold power-on
> that starts while the BMC is still initialising leaves the X550 at its hardware default,
> enabled, under root port `40:01.3` at bus 42: every bus below it on root bus 40 shifts by two
> (the Optanes `46/47` → `48/49`, the BMC's VGA lands on `46:00.0`) and every IOMMU group after
> it shifts by three (`nvidia_rtx_a4000` 97 → 100).

The POST-time marker is the BIOS's own SEL entry `System Firmwares | Unrecoverable video
controller failure`: the VGA is inside the same AST2500 as the BMC. The kernel-side marker is
`ipmi_si … BMC returned incorrect response` instead of `Found new BMC` at boot; the collector
exports it as `pve_pci_mapping_bmc_kcs_ok`.

What makes that boot happen, in order: a spurious `CPU_THERMTRIP` (asserted 2026-09-09 18:17 with
the CPU at 34 °C by both the BMC and k10temp — a hardware fault on the THERMTRIP path, socket
first suspect given the May-11 contamination) powers the host off; the BMC (fw 2.02) hangs or
restarts — six self-restarts in the twelve days to 09-09 and one hour-long hang; and
`Restore AC Power Loss = always-on` powers the host back on the instant the BMC comes up, before
its host interface does. The 2026-08-28 event had the same shape (host off 16:19, BMC reboot
16:26, power-on at BMC boot 16:28, kernel's first IPMI exchange failed).

Open follow-ups, none of them Ansible: re-enable Onboard LAN1/LAN2 at the next setup visit
(Enabled is the hardware default, so a BIOS that skips the setting lands on the same enumeration
as one that applies it, and the flip stops mattering); update the BMC (2.08 public, 3.04 via
ASRock support); reseat/inspect the CPU for the THERMTRIP.

A reboot here stalls every Ceph-backed guest unless the cluster has three monitors in quorum, so
check `ceph -s` before taking the host down.

Two settings that must be left as they are:

- **Restore AC Power Loss stays `always-on`.** Last State would stop the BMC's own restart from
  powering the host on, but this host is a NUT client of the rack UPS, so a sustained outage ends
  in a clean shutdown — and Last State would then leave it powered off when mains returned,
  needing a walk to the rack.
- **Do not enable `Server Mgmt → Wait For BMC`.** See the warning under [Motherboard](#motherboard):
  this board's predecessor would not boot at all once its BMC died with that setting on. This
  BMC restarts itself every couple of days, so enabling it would trade a rare enumeration flip
  that one playbook run fixes for a regular hard-down.

**Keeping the SEL usable.** The BIOS writes a `PCI PERR` entry and rasdaemon writes an OEM record
for **the same** corrected PCIe event — roughly 190 each per day from `c8:00.0` and the A4000's
root port, which together with correctable ECC filled the ~3,600-entry log in a week.

rasdaemon's half is blocked by `rasdaemon_block_ipmitool_sel`, which sandboxes `ipmitool` away
from that one service — **not** by a `PATH` override, which would break the uncorrectable-error
trigger script that inherits only `PATH`. The log now fills at about 100 entries a day and lasts
roughly five weeks, of which ~90% is correctable ECC.

Lowering PCIe link speed to stop the errors is available for the A4000's slot, which holds nothing
else, but **not** for the Hyper M.2 slot: all four drives there are sink-pool mirror legs, so
slowing any of them caps the mirror it belongs to.

### Corrected memory errors

`DDR4_A1` and `DDR4_B1` log corrected single-bit ECC errors continuously — a small set of stuck
cells, stable since May and not spreading. There has never been an uncorrected, uncorrectable or
deferred error, and these are **not** the cause of the shutdowns below.

The `Over` flag in `MC17_STATUS[Over|CE|…]` looks like "errors arriving faster than they can be
corrected" and is not: it means the logging undercounts, because firmware reports only every
tenth corrected error (`mce: HEST corrected error threshold limit: 10`). ECC corrects a
single-bit error however fast the next one arrives.

The failing pages are three 32 KiB aligned blocks plus two single pages rather than scattered
cells, so whole blocks are reserved — 104 KiB of 188 GiB:

    memmap=32K$0x17fcb0000 memmap=32K$0xa40fa8000 memmap=32K$0xa6a890000
    memmap=4K$0x6ad451000  memmap=4K$0x2961ceb000

Declared in `ansible/host_vars/nas-host-01/vars.yaml`, written to `/etc/kernel/cmdline` by
`kernel_parameters`, effective at boot.

**Do not replace this with rasdaemon's soft-offline.** The kernel refuses it on this host —
`thp split failed` for pages inside a transparent huge page, `unhandlable page` for others.

Check it with `grep -c memmap /proc/cmdline` = 5 and the ranges absent from `/proc/iomem` as
`System RAM`. Neither `ras-mc-ctl --summary` nor `HardwareCorrupted` reports anything here:
rasdaemon cannot subscribe to `ras:memory_failure_event` on this kernel, and a `memmap=`
reservation is never handed to the allocator so nothing is poisoned.

### Shutdowns

The host has powered itself off three times — 2026-06-29, 2026-08-28, 2026-09-09. Each time the
journal stops mid-stream with no shutdown, the host stays off, the front-panel power button does
nothing, and only an AC cycle recovers it.

That is `THERMTRIP` cutting the rails, which is what the BMC logged on 09-09 — with the CPU at
34 °C and every voltage rail flat, so a spurious trip rather than heat. Suspects in order: CPU
socket contact (channel G was dead until the 2026-05-11 reseat), BMC firmware 2.02, then the VRM.

## PVE storages

| Name | Type | Backing |
| --- | --- | --- |
| `local` | dir | rpool |
| `local-zfs` | zfspool | rpool |
| `local-zfs_pve-optane-01` | zfspool | `pve-optane-01` — the 1.5 TB 905P. VM root disks for nas-01 and media-01 |
| `pve_pool` | rbd | Ceph, across all three OSDs. network-03 and every vm-host-0x guest |
| `pve_cephfs` | cephfs | Ceph |
| `nas-01_proxmox` | cifs | An SMB share back from nas-01 |
| `backup-01_pbs_nas-host-01` | pbs | backup-01, active |
| `backup-01_pbs_vm-host-01`, `backup-01_pbs_vm-host-02` | pbs | Restricted to their own node via `nodes=`, so `pvesm status` here reports them disabled |
