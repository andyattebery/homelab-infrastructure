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
- [Broadcom 9305-24e](https://docs.broadcom.com/doc/BC00-0392EN)
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
- Hard Drives
    - 1x Seagate BarraCuda - 24 TB
    - 1x Seagate Exos (Refurbished) - 22 TB
    - 3x WD Easystore shucked - 18 TB
    - 1x Seagate Exos X20 (Refurbished) - 18 TB
    - 1x Seagate Exos X18 (Refurbished) - 18 TB
    - 4x WD Easystore shucked - 14 TB
    - 1x Seagate Exos X18 (Refurbished) - 14 TB
    - 2x Seagate Exos X16 (Refurbished) - 14 TB
    - 4x WD Red - 8 TB

### Motherboard

I initially had a [Supermicro H12SSL-i](https://www.supermicro.com/en/products/motherboard/H12SSL-i). [However, it has exposed surface mount components for the BMC next to the middle PCIe slots that I damaged with a PCIe bracket when inserting a card.](https://forums.servethehome.com/index.php?threads/h12ssl-i-stuck-at-bmc-initiating.38043/) This kills the BMC, and the BIOS by default won’t boot if the BMC isn’t online. **If you do get this motherboard, immediately disable the option in the BIOS to wait for the BMC before booting and be careful when inserting cards.** *Please learn from my mistake.*

### CPU

I chose the 7282 because it has a 120 W TDP vs the comparable 16 core 7302P that has a 155W TDP. It achieves this by only having 2 active CCDs vs the 7302P's 4 CCDs. [However this limits it to 4 memory channels vs the full 8 memory channels](https://www.servethehome.com/amd-epyc-7002-rome-cpus-with-half-memory-bandwidth/). I value lower power consumption over raw performance, so the trade-off was worth it. Additionally, I chose DDR4-3200 RAM (the fastest supported) to try to make up some of the performance.

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

##### Broadcom 9305-24e

Connected to the case backplane that all of the hard drives are connected to.

## Summary

- **CPU**: AMD EPYC 7282 — 16 cores / 32 threads
- **RAM**: 192 GB DDR4-3200 (154 GB used, 34 GB available at host level)

### VMs (as of 2026-08-08)

| VMID | VM | Status | vCPUs | RAM Allocated |
| --- | --- | --- | --- | --- |
| 200 | nas-01 | running | 14 | 48 GB |
| 201 | media-01 | running | 16 | 96 GB |
| 203 | network-03 | running | 2 | 4 GB |

**Running totals**: 32 vCPUs allocated against 32 threads (no overcommit), 148 GB
RAM allocated of 192 GB.

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
| `hostpci0` | `broadcom_9305_24e` (`rombar=0`) | Broadcom/LSI SAS3224 (9305-24e HBA) | — | All SATA HDDs — ZFS tank data + snapraid/mergerfs pool |
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
    - 4x WD Red 8 TB
    - 2x Intel Optane P1600X - 118 GB as [ZFS mirrored metadata special device](https://forum.level1techs.com/t/zfs-metadata-special-device-z/159954)
- ZFS Mirror Pool (sink) - 4 TB
    - 2x Solidigm P44 Pro - 2 TB
    - 2x Samsung 980 Pro - 2 TB
- Staging/Temp data
    - HPE VK003840KWWFP (Rebranded SK Hynix PE6011) - 3.84 TB
- Snapraid/mergerfs Pool
    - Data Disks
        - 3x WD Easystore shucked - 18 TB
        - 1x Seagate Exos X20 (Refurbished) - 18 TB
        - 1x Seagate Exos X18 (Refurbished) - 18 TB
        - 4x WD Easystore shucked - 14 TB
        - 1x Seagate Exos X18 (Refurbished) - 14 TB
        - 2x Seagate Exos X16 (Refurbished) - 14 TB
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

The A4000's mapping path is function-less, so it attaches the GPU and its HDA
together. The B580's GPU and HDA are on different buses with different device IDs,
so they cannot share one mapping.

### Resource mappings

Every passed-through device on this node goes through a named PCI resource mapping
in `/etc/pve/mapping/pci.cfg` rather than a raw `hostpci` address. Naming is
`<manufacturer>_<model>`, lowercased, non-alphanumerics folded to `_`, with a
numeric suffix only where the chassis holds more than one of a model.

A mapping records the device's `id`, `subsystem-id` and `iommugroup` and refuses to
start the VM if any stops matching. A raw address gets no identity check — it fails
only if the address is empty, and otherwise passes whatever now sits there.

| Mapping | Path | ID | Subsystem-ID | IOMMU grp | Consumer |
| --- | --- | --- | --- | --- | --- |
| `nvidia_rtx_a4000` | `0000:01:00` | `10de:24b0` | `1028:14ad` | 97 | media-01 |
| `intel_arc_b580` | `0000:c3:00.0` | `8086:e20b` | `1849:6021` | 17 | media-01 |
| `intel_arc_b580_audio` | `0000:c4:00.0` | `8086:e2f7` | `1849:6021` | 18 | media-01 |
| `broadcom_9305_24e` | `0000:84:00.0` | `1000:00c4` | `1000:31a0` | 45 | nas-01 |
| `skhynix_pe6011` | `0000:83:00.0` | `1c5c:2429` | `1590:02d0` | 44 | nas-01 |
| `solidigm_p44_pro_1` | `0000:c5:00.0` | `025e:f1ac` | `025e:f1ac` | 19 | nas-01 |
| `solidigm_p44_pro_2` | `0000:c6:00.0` | `025e:f1ac` | `025e:f1ac` | 20 | nas-01 |
| `samsung_980_pro_1` | `0000:c7:00.0` | `144d:a80a` | `144d:a801` | 21 | nas-01 |
| `samsung_980_pro_2` | `0000:c8:00.0` | `144d:a80a` | `144d:a801` | 22 | nas-01 |
| `intel_p1600x_1` | `0000:46:00.0` | `8086:2525` | `8086:380a` | 74 | nas-01 |
| `intel_p1600x_2` | `0000:47:00.0` | `8086:2525` | `8086:380a` | 75 | nas-01 |

**A mapping does not establish instance identity for the Optanes.** All four P1600X
report the same `id` and `subsystem-id`; only `iommugroup` differs, and group numbers
are renumbered by any topology change. Two of the four are the host's `rpool` boot
mirror. When re-pointing `intel_p1600x_*`, confirm the serial first — the mapping
will not catch it if you aim at an `rpool` drive.

Working with mappings:

- Create via `pvesh create /cluster/mapping/pci` or the GUI, passing `id`,
  `subsystem-id` and `iommugroup` explicitly. `pvesh` does not read them from sysfs
  and they are optional in the schema, so a mapping created without them is accepted
  and then dies at every `qm start` with `missing expected property 'iommugroup'`.
- There is no rename API — renaming means create-new, re-point the VM, delete the old.
- `delete` has no in-use guard; deleting a mapping a VM still references leaves it
  unbootable.
