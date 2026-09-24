# SSD inventory

Cross-host snapshot of every SSD in the Proxmox cluster, the nas-01 VM and htpc-01. See [nas-host-01.md](nas-host-01.md) for the full nas-host-01 build including chassis, motherboard, and HDDs.

Refresh source: `lsblk`, `zpool status`, `pvesm status`, `/etc/pve/qemu-server/*.conf`, `lspci`, `smartctl` on each host.

Last verified: nas-host-01 and nas-01 2026-09-06; vm-host-01 2026-09-09; vm-host-02 2026-09-07;
htpc-01 2026-09-10.

## nas-host-01 (Proxmox bare-metal)

`nvmeN` numbers are not stable across boots or changes to what is passed through —
a passed-through drive has no host node at all. The serial is the identity. Names
below are from 2026-09-06 with both passthrough VMs running.

They have already moved once: the two `rpool` P1600X were `nvme7n1`/`nvme10n1` on
2026-08-08 and are `nvme10n1`/`nvme9n1` today, with no hardware change. Match on the
serial, never the node name.

| Device | Serial | Model | Cap | Class | Use |
|---|---|---|---|---|---|
| nvme10n1 | `PHOC1456007B118B` | [Intel Optane P1600X](https://ark.intel.com/content/www/us/en/ark/products/211867/intel-optane-ssd-p1600x-series-118gb-m-2-80mm-pcie-3-0-x4-3d-xpoint.html) | 118 GB | Optane / 3D XPoint, PLP | `rpool` mirror — PVE boot |
| nvme9n1 | `PHOC14550050118B` | Intel Optane P1600X | 118 GB | Optane | `rpool` mirror |
| nvme4n1 | `PHM2911300BM960CGN` | [Intel Optane 905P](https://www.intel.com/content/www/us/en/products/sku/147529/intel-optane-ssd-905p-series-960gb-2-5in-pcie-x4-3d-xpoint/specifications.html) (`SSDPE21D960GA`) | 960 GB | Optane | Ceph OSD for `pve_pool` (single OSD on this node) |
| nvme5n1 | `PHKE336300RL1P5CGN` | [Intel Optane 905P](https://www.intel.com/content/www/us/en/products/sku/147526/intel-optane-ssd-905p-series-1-5tb-2-5in-pcie-x4-3d-xpoint/specifications.html) (`SSDPE21D015TA`) | 1.5 TB | Optane | `pve-optane-01` single-vdev ZFS — VM root disks for nas-01 and media-01 (network-03 is on Ceph) |

The two `rpool` P1600X are in the onboard M.2 slots. The other two are on the PCIE4
splitter and belong to nas-01 — same model, same IDs, so only the serial
distinguishes them.

### Passthrough into nas-01

Defined as `hostpci*` on VM 200, all via named resource mappings. Full table with
IOMMU groups in [nas-host-01.md](nas-host-01.md#resource-mappings).

| `hostpci` | Mapping | Device |
|---|---|---|
| 0 | `broadcom_9305_24e` | [Broadcom 9305-24i](https://www.broadcom.com/products/storage/host-bus-adapters/sas-9305-24i) SAS HBA (all SATA HDDs) |
| 1, 2 | `solidigm_p44_pro_1/_2` | 2× [Solidigm P44 Pro](https://www.solidigm.com/products/client/pro-series/p44.html#form=M.2%202280&cap=2%20TB) |
| 3, 4 | `samsung_980_pro_1/_2` | 2× [Samsung 980 PRO 2TB](https://semiconductor.samsung.com/consumer-storage/internal-ssd/980pro/) |
| 5 | `skhynix_pe6011` | [HPE VK003840KWWFP](https://www.techpowerup.com/ssd-specs/sk-hynix-pe6011-3-8-tb.d1490) (SK hynix PE6011 OEM) |
| 6, 7 | `intel_p1600x_1/_2` | 2× Intel Optane P1600X 118 GB |

**The mapping is named `broadcom_9305_24e`; the card is a 9305-24i.** The name is wrong and
is kept verbatim here because that is the string PVE matches on. PCI resource mappings are not
managed by Ansible — see [nas-host-01.md](nas-host-01.md#resource-mappings) for why the rename
is a followup rather than a one-liner.

## nas-01 (Proxmox VM on nas-host-01)

All NVMe devices and the SAS HBA are PCIe-passed-through from nas-host-01.

| Device | Model | Cap | Class | Use |
|---|---|---|---|---|
| nvme0n1, nvme1n1 | Solidigm P44 Pro (`SSDPFKKW020X7`) | 2 TB each | Consumer TLC NVMe | `sink` zpool — mirror-0 |
| nvme2n1, nvme3n1 | Samsung 980 PRO 2TB | 2 TB each | Consumer TLC NVMe | `sink` zpool — mirror-1 |
| nvme5n1, nvme6n1 | Intel Optane P1600X | 118 GB each | Optane | [`tank` special vdev mirror](https://forum.level1techs.com/t/zfs-metadata-special-device-z/159954) (metadata for the 4× 8TB HDDs) |
| nvme4n1 | HPE VK003840KWWFP | 3.84 TB | Enterprise TLC NVMe | `/mnt/depot` ext4 — snapraid content + scratch (**1.4 TB used of 3.5 TB**) |
| sda, sdb, sdc | QEMU virtual disks on `pve-optane-01` | 128 / 64 / 32 GB | Virtual | rootfs / `/mnt/docker` (btrfs) / `/mnt/content/snapraid` (btrfs) |
| sdd..sdu | WD / Seagate SATA HDDs | 8–24 TB | HDD | snapraid data + parity (14 disks) and `tank` zpool (4× 8TB mirror-of-mirrors). Full list in [nas-host-01.md](nas-host-01.md). |

**Filesystems on the bulk disks:** the 12 snapraid data disks are **btrfs**, mounted at
`/mnt/data/data01`–`data12` and pooled by mergerfs at `/mnt/storage`. The 2 parity disks are
**ext4** at `/mnt/parity01` (ST24000DM001, 24 TB) and `/mnt/parity02` (ST22000NM000C, 22 TB).

**Gone since 2026-08-08:** the Innodisk DEMSM-A28M41BW1DC-27 (3ME4) 128 GB industrial SATA
M.2, previously `sdr` and unused. It is absent from both `lsblk` and `/dev/disk/by-id`. `sdr`
is now a WD80EMAZ — another reason not to trust a device node across time.

Note: `tank` carries Immich, Nextcloud, Paperless, Forgejo, Linkwarden, Silo, Syncthing, Frigate, Shinobi, and all their postgres DBs. It has a P1600X metadata special vdev but **no SLOG** — sync writes land on the 8TB HDDs.

## vm-host-01 (Proxmox — Dell OptiPlex Micro 5070)

| Device | Model | Cap | Class | Use |
|---|---|---|---|---|
| nvme0n1 | Intel Optane P1600X 58 GB | 58 GB | Optane, PLP | PVE boot (LVM) |
| sda | Intel DC S3610 1.6 TB `BTHC637404T21P6PGN` | 1.6 TB | Enterprise SATA MLC, PLP | Ceph OSD (osd.0, class `ssd`; CRUSH weight 1.45549) |

M.2 slots reported via DMI: 1× Socket 3 NVMe (x4, used), 1× Socket 1-SD (x1, WLAN). Length "Long" — practical assumption is 2280 only.

## vm-host-02 (Proxmox — Dell OptiPlex Micro 3070)

| Device | Model | Cap | Class | Use |
|---|---|---|---|---|
| sda | Intel SSDSC2BX016T4 (DC S3610) `BTHC6306000V1P6PGN` | 1.6 TB | Enterprise SATA MLC, PLP | Ceph OSD (osd.1, class `ssd`) |
| nvme0n1 | Intel Optane P1600X 58GB | 58 GB | Optane (PLP) | PVE boot (LVM: root 24.6 GB, swap 4 GB, 25.8 GB free in the VG — `maxvz 0`, no `local-lvm`) |

Same chassis class and slot constraints as vm-host-01.

The node is idle by design. Guest placement moves and is recorded in
[host-inventory.md](host-inventory.md); it does not change the table above, because no guest disk
is local — every one is on `pve_pool`, the Ceph RBD pool that spans all three OSDs.

## htpc-01 (Bazzite — AMD Ryzen 5 5600GE)

Not a cluster node: a workstation with four SSDs and no shared storage. All four are btrfs.

| Device | Model | Serial | Cap | Class | Use |
|---|---|---|---|---|---|
| nvme0n1 | SK hynix `BC711` (OEM) | `CDACN71971370CP2X` | 256 GB | OEM consumer TLC NVMe, no PLP | Bazzite boot: `/boot/efi` (vfat), `/boot` (ext4) and the `bazzite-deck_fedora` btrfs root that carries `/var`, `/etc`, `/var/home`, the ostree deployment and the **rootful podman overlay store** (139 GB of 237 GB used) |
| nvme1n1 | SK hynix Platinum P41 (`SHPP41-2000GM`) | `ASDAN54041200B15X` | 2 TB | Consumer TLC NVMe, no PLP | btrfs `Games` at `/run/media/system/Games` (1.0 TB of 1.8 TB used) |
| sda | Samsung 850 EVO 500GB | `S2RANXAH130042A` | 500 GB | Consumer SATA TLC, no PLP | btrfs `data` at `/run/media/system/data` — `htpc_data_mount_path`, the data root every podman quadlet binds into (191 GB of 466 GB used) |
| sdb | Intel DC S3500 (`SSDSC2BB016T4`) | `BTWD5362016W1P6HGN` | 1.6 TB | Enterprise SATA MLC, PLP | btrfs `sata_2tb` at `/run/media/system/sata_2tb` (930 GB of 1.5 TB used) |

**The btrfs labels do not describe the hardware.** `sata_2tb` is a 1.6 TB drive, `data` is the
500 GB consumer SATA one and the models are only distinguishable by serial. Swap is `zram0`
(14.6 GB), not a partition — nothing on these disks is swap.

The container store is on the boot drive, so podman images and volumes eat the same 237 GB as the
OS; `htpc_data_mount_path` on `sda` is what keeps quadlet *data* off it. The other directories
under `/run/media/system/` — `tdarr_media`, `tdarr_media_raw`, `nas_01_ai_images` — are CIFS
mount points onto nas-01 shares, not local storage.

## Unused / shelved

| Item | Class | Plausible role |
|---|---|---|
| **3× Intel DC S3610 1.6 TB** (of five; the other two are the cluster's osd.0 and osd.1) | Enterprise SATA MLC, PLP, 3 DWPD (10.7 PBW) | Unassigned. At least one is the cluster's only cold spare — a failed OSD cannot heal without it. Per-drive detail below. |
| Intel DC S3520 150 GB M.2 (`SSDSCKJB150G7`; pulled from vm-host-01, 2026-09-09) | Enterprise SATA M.2 | vm-host-01's old boot drive; spare |
| Samsung 960 PRO 512 GB (pulled from vm-host-01, 2026-09-09) | Consumer MLC NVMe (no PLP) | vm-host-01's old osd.0, zapped by `pveceph osd destroy --cleanup`; shelf |
| Intel DC S3520 150 GB M.2 (`SSDSCKJB150G7`; pulled from vm-host-02, 2026-09-07) | Enterprise SATA M.2 | vm-host-02's old boot drive; spare |
| Samsung 970 EVO 500 GB (pulled from vm-host-02, 2026-09-07) | Consumer TLC NVMe (no PLP) | vm-host-02's old osd.1, zapped by `pveceph osd destroy --cleanup`; shelf |
| 4× Intel Optane Memory M10 16 GB | Optane "cache" SKU, small, M.2 single-namespace | None. Too small for a special vdev, and a SLOG is the only other role — no pool has one and no P1600X is spare to build one with |
| Samsung 860 EVO 1 TB | Consumer SATA TLC | General bulk SATA SSD |
| HP EX950 1 TB | Consumer NVMe TLC (SMI controller) | Drop-in consumer NVMe OSD candidate |

Plus M.2-to-PCIe carrier adapters available for slotting M.2 22110 enterprise NVMe into PCIe x4 lanes.

### The five Intel DC S3610 1.6 TB

Verified 2026-09-07 over read-only `smartctl`, four attached to nas-01 and one on the bench.
**Keyed on serial, never on device node** — during this check alone, `sdv` was two different
drives twenty minutes apart.

Listed in serial order, which is build order: serial sequence and power-on-hours rank match
exactly across all five.

| Serial | Badge / model | Firmware | SMART attrs | Used | Host TB | POH | Wearout | Peak °C (limit) | Notable |
|---|---|---|---|---|---|---|---|---|---|
| `BTHC6306000V1P6PGN` | Intel `SSDSC2BX016T4` | `G2010170` | 26, named | 6 % | 893.4 | 55,607 | 94 | 43 (70) | by far the most-worked; WAF 2.9. Flashed `G2010150`→`G2010170` on 2026-09-07 |
| `BTHC637404T21P6PGN` | Intel `SSDSC2BX016T4` | `G2010170` | 26, named | 1 % | 61.6 | 48,540 | 99 | 50 (70) | **143 SATA downshifts** 6→3 Gb/s, but 0 CRC errors |
| `BTHC646101YB1P6PGN` | HPE `LK1600GEYMV` | `4IWTHPG1` | **8** | 0 % | 25.2 | 46,913 | hidden | 42 (55) | least-written of the five |
| `BTHC722408RR1P6PGN` | Intel `SSDSC2BX016T4K` | `G201CS01` | 26, part unnamed | 1 % | 58.0 | 42,566 | 99 | 43 (70) | **Cisco UCS** OEM SKU; 179 unsafe shutdowns |
| `BTHC72640DGK1P6PGN` | HPE `LK1600GEYMV` | `4IWTHPG2` | **8** | 1 % | 112.7 | 41,624 | hidden | 55 (60) | — |

All five: power-loss-capacitor test passing, **0** interface-CRC errors, **0** reported
uncorrectables, **0** reallocated sectors, **0** time over temperature. There is no bad drive
in this set; every meaningful difference below is about *visibility*, not health.

#### Where they are

Two fitted as the cluster's OSDs, three shelved and unassigned. The split is driven by **SMART
visibility**, not by health, because the health numbers barely differ.

| Role | Serial | Why this one |
|---|---|---|
| Ceph OSD, vm-host-02 | `BTHC6306000V1P6PGN` | Retail Intel firmware ⇒ 26 named attributes for `scrutiny_collector`. 893 TB written is still only 6 % of rating |
| Ceph OSD, vm-host-01 | `BTHC637404T21P6PGN` | same reasoning; the two are interchangeable for this role. Retail Intel firmware, so `scrutiny_collector` gets 26 named SMART attributes — the reason this drive rather than the Cisco-SKU `BTHC722408RR1P6PGN`, whose SMART is partly unnamed |
| Shelf | `BTHC646101YB1P6PGN` | HPE firmware hides wear, so it belongs where `devstat` is run by hand rather than in a monitored host. Least-written of the five |
| Shelf | `BTHC72640DGK1P6PGN` | the other HPE drive. 113 TB against the other's 25 TB, so if the two are ever paired the **wear-out is staggered** and the halves do not reach end-of-life together |
| Shelf | `BTHC722408RR1P6PGN` | Cisco SKU. 26 attributes with wear readable, the lowest power-on hours of the five, a 70 °C limit and a build lot the two fitted drives do not share |

Two reasons the Ceph pair are the retail Intel drives rather than the HPE ones: they go into
hosts nobody has hands on, where `scrutiny_collector` is the only thing watching, and the HPE
firmware would leave Scrutiny with no wear trend, no CRC count and no reallocation trend at all.

**The spare matters more here than in most designs.** With three hosts, `size=3` and a
`chooseleaf … type host` rule, a dead OSD **cannot** be healed — there is no fourth host for the
third replica and no second OSD on any host to take it, so `pve_pool` sits degraded until a disk
is physically fitted.

Unresolved by choice: `BTHC6306000V1P6PGN` and `BTHC637404T21P6PGN` are the same 63xx build lot.
Splitting them would mean promoting the Cisco drive into an OSD slot and accepting one OSD whose
SMART Scrutiny can only partly read. Judged not worth it — these drives are five years past
infant mortality, so same-lot correlation is largely theoretical, and the legibility loss is
continuous.

#### `smartctl -a` lies by omission on the HPE-badged pair

`4IWTHPG1`/`4IWTHPG2` expose **8** SMART attributes and none of the wear ones — no
`233 Media_Wearout_Indicator`, no `241 Host_Writes`, no `232 Available_Reservd_Space`, no
`199 UDMA_CRC_Error_Count`. Judged on the attribute table alone, those two drives look like
they have no wear data rather than hidden wear data. Get it from the standard ATA device
statistics log instead, which every one of the five populates correctly:

```sh
smartctl -l devstat /dev/sdX     # Percentage Used Endurance, Logical Sectors Written
```

This is why the two HPE drives are the wrong ones to put where `scrutiny_collector` is the only
thing watching them.

#### Attribute 175 is the power-loss capacitor, whatever smartctl calls it

On the Intel stock firmware smartctl names ID 175 `Power_Loss_Cap_Test` with a sane raw (13030,
13890). On `G201CS01` and both HPE revisions the drive is not in smartctl's database, so the
same ID is mislabelled `Program_Fail_Count_Chip` with a 12-digit raw — nonsense as a fail count,
which is the tell. **Trust the normalized value** (100, threshold 10), not the name or the raw.
This is the check the whole PLP rationale for these drives rests on.

#### The declared temperature limit varies by firmware

`4IWTHPG1` reports a 55 °C maximum, `4IWTHPG2` reports 60 °C, and all three Intel revisions
report 70 °C. Comparing one drive's peak against another's limit is an easy way to invent a
problem that isn't there.

#### Firmware currency, and which can actually be updated

| Firmware | Newest available | Updatable? |
|---|---|---|
| `G2010170` | current | both retail Intel drives are on it as of 2026-09-07 |
| `G201CS01` | **current for its branch** | No, and it does not need to be — Cisco UCS 4.0(1)–4.0(4) list `G201CS01` for `SSDSC2BX016T4K` and 4.1 shows nothing newer |
| `4IWTHPG1`, `4IWTHPG2` | `HPG6` | HPE tooling only, and HPG6 exists partly to fix drives failing *during* a firmware update |

S3610 firmware was dropped from Solidigm Storage Tool at 1.15 (EOL), but **`1.11.268` carries
the whole ladder through `G2010170`** in `firmware_module_dc.so`. It applies it **one step at a
time**: a drive on `G2010150` is offered `G2010160`, and only after that is `G2010170` offered.
Confirmed by doing it on 2026-09-07 — `G2010150`→`G2010160`→`G2010170`, two `load` calls, no
reboot needed and no SMART attribute moved. Procedure:
[intel-s3610-firmware-update.md](../docs/intel-s3610-firmware-update.md).

**The model-number suffix is the OEM code.** No suffix = retail Intel, `P` = HPE
(`LK1600GEYMV`), `R` = Dell, **`K` = Cisco UCS**. Each badge carries its own firmware lineage —
`G20101xx` retail, `4IWTHPGn` HPE, `G201CS01` Cisco — and a tool only ever holds one of them.

**The three shelved drives still carry ZFS labels from a pool named `basin`** (2× mirror vdevs,
`hostname: 'vm-host-03'` — a host that no longer exists). Disposable, per the owner, but
`pveceph osd create` refuses a non-empty disk, so they need zapping before use — on a node rebuild
that is `pve_node_ceph_osd_zap: true` (see the role's README), which is what cleared
`BTHC637404T21P6PGN` on 2026-09-09.

## Refresh commands

```sh
ssh nas-host-01 'sudo lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN && sudo zpool list -v && sudo /usr/sbin/pvesm status'
ssh vm-host-01  'sudo lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN'
ssh vm-host-02  'sudo lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN'
ssh nas-01      'lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN && sudo zpool status tank sink'

# htpc-01 is Bazzite: ssh as `bazzite`, TERM=dumb, and the interesting part is which btrfs
# label sits on which serial -- the labels are misleading (see its section above).
ssh -o SetEnv=TERM=dumb htpc-01 'bash -lc "lsblk -o NAME,SIZE,MODEL,SERIAL,TRAN,FSTYPE,LABEL,MOUNTPOINTS"'
ssh -o SetEnv=TERM=dumb htpc-01 'bash -lc "findmnt -no SOURCE,TARGET,FSTYPE,SIZE,USED -t btrfs,ext4,vfat"'

# Passthrough map on nas-host-01. Read the mappings rather than filtering on
# hardcoded addresses — a card move changes every bus number under it.
ssh nas-host-01 'sudo cat /etc/pve/mapping/pci.cfg'
ssh nas-host-01 'sudo lspci -nnD | grep -E "Non-Volatile|Serial Attached SCSI|VGA|Ethernet controller"'

# Grep the VM configs, never `cat` them: 200.conf carries a cipassword.
ssh nas-host-01 'sudo grep -E "hostpci|name" /etc/pve/qemu-server/200.conf /etc/pve/qemu-server/201.conf'

# Which VMIDs actually exist. Settles the class of drift where a doc keeps describing a
# guest that was deleted — 101 and 202 both outlived their VMs in these files.
for h in vm-host-01 vm-host-02 nas-host-01; do ssh $h 'sudo qm list'; done

# The shelved S3610s, whichever host they are hanging off. Enumerate by model, and read wear
# from devstat -- `smartctl -A` shows no wear at all on the two HPE-badged drives. The model
# pattern is the TRUNCATED one: lsblk caps MODEL at 16 chars, so `SSDSC2BX016T4` never matches.
ssh <host> bash -s <<'EOF'
for n in $(lsblk -dno NAME,MODEL | awk '/LK1600GEYMV|SSDSC2BX01/{print $1}'); do
  sudo smartctl -i /dev/$n | grep -E 'Device Model|Serial Number|Firmware'
  sudo smartctl -l devstat /dev/$n | grep -E 'Percentage Used|Logical Sectors Written|CRC'
  sudo smartctl -A /dev/$n | awk '$1==175{print "  PLP(175) normalized:",$4,"threshold:",$6}'
done
EOF
```
