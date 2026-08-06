# SSD inventory

Cross-host snapshot of every SSD in the Proxmox cluster and the nas-01 VM. See [nas-host-01.md](nas-host-01.md) for the full nas-host-01 build including chassis, motherboard, and HDDs.

Refresh source: `lsblk`, `zpool status`, `pvesm status`, `/etc/pve/qemu-server/*.conf`, `lspci`, `smartctl` on each host.

## nas-host-01 (Proxmox bare-metal)

| Device | Model | Cap | Class | Use |
|---|---|---|---|---|
| nvme9n1 | [Intel Optane P1600X](https://ark.intel.com/content/www/us/en/ark/products/211867/intel-optane-ssd-p1600x-series-118gb-m-2-80mm-pcie-3-0-x4-3d-xpoint.html) | 118 GB | Optane / 3D XPoint, PLP | `rpool` mirror — PVE boot (14 GB used) |
| nvme10n1 | Intel Optane P1600X | 118 GB | Optane | `rpool` mirror |
| nvme6n1 | [Intel Optane 905P](https://www.intel.com/content/www/us/en/products/sku/147529/intel-optane-ssd-905p-series-960gb-2-5in-pcie-x4-3d-xpoint/specifications.html) (`SSDPE21D960GA`) | 960 GB | Optane | Ceph OSD for `pve_pool` (single OSD on this node) |
| nvme7n1 | [Intel Optane 905P](https://www.intel.com/content/www/us/en/products/sku/147526/intel-optane-ssd-905p-series-1-5tb-2-5in-pcie-x4-3d-xpoint/specifications.html) (`SSDPE21D015TA`) | 1.5 TB | Optane | `pve-optane-01` single-vdev ZFS — VM root disks for nas-01, media-01, network-03 (566 GB used) |

### Passthrough into nas-01

Defined as `hostpci*` in `/etc/pve/qemu-server/200.conf`, verified against `lspci`.

| `hostpci` | PCI ID | Device |
|---|---|---|
| 0 | 01:00 | [Broadcom 9305-24e](https://docs.broadcom.com/doc/BC00-0392EN) SAS HBA (all SATA HDDs + SATADOM) |
| 1, 2 | c4:00, c5:00 | 2× [Solidigm P44 Pro](https://www.solidigm.com/products/client/pro-series/p44.html#form=M.2%202280&cap=2%20TB) |
| 3, 4 | c6:00, c7:00 | 2× [Samsung 980 PRO 2TB](https://semiconductor.samsung.com/consumer-storage/internal-ssd/980pro/) |
| 5 | 83:00 | [HPE VK003840KWWFP](https://www.techpowerup.com/ssd-specs/sk-hynix-pe6011-3-8-tb.d1490) (SK hynix PE6011 OEM) |
| 6, 7 | c2:00, c3:00 | 2× Intel Optane P1600X 118 GB |

## nas-01 (Proxmox VM on nas-host-01)

All NVMe devices and the SAS HBA are PCIe-passed-through from nas-host-01.

| Device | Model | Cap | Class | Use |
|---|---|---|---|---|
| nvme0n1, nvme1n1 | Solidigm P44 Pro (`SSDPFKKW020X7`) | 2 TB each | Consumer TLC NVMe | `sink` zpool — mirror-0 |
| nvme2n1, nvme3n1 | Samsung 980 PRO 2TB | 2 TB each | Consumer TLC NVMe | `sink` zpool — mirror-1 |
| nvme5n1, nvme6n1 | Intel Optane P1600X | 118 GB each | Optane | [`tank` special vdev mirror](https://forum.level1techs.com/t/zfs-metadata-special-device-z/159954) (metadata for the 4× 8TB HDDs) |
| nvme4n1 | HPE VK003840KWWFP | 3.84 TB | Enterprise TLC NVMe | `/mnt/depot` ext4 — snapraid content + scratch (158 GB used) |
| sdr | Innodisk DEMSM-A28M41BW1DC-27 (3ME4) | 128 GB | Industrial SATA M.2 (SLC-mode MLC) | **Unused** — holds Ubuntu Live leftovers |
| sda, sdb, sdc | QEMU virtual disks on `pve-optane-01` | 128 / 64 / 32 GB | Virtual | rootfs / `/mnt/docker` / `/mnt/content/snapraid` |
| sdd..sdv | WD / Seagate SATA HDDs | 8–24 TB | HDD | snapraid data + parity (12 disks) and `tank` zpool (4× 8TB mirror-of-mirrors). Full list in [nas-host-01.md](nas-host-01.md). |

Note: `tank` carries Immich, Nextcloud, Paperless, Forgejo, Linkwarden, Minio, Syncthing, Frigate, Shinobi, and all their postgres DBs. It has a P1600X metadata special vdev but **no SLOG** — sync writes land on the 8TB HDDs.

## vm-host-01 (Proxmox — Dell OptiPlex SFF)

| Device | Model | Cap | Class | Use |
|---|---|---|---|---|
| sda | Intel SSDSCKJB150G7 (DC S3520 M.2) | 150 GB | Enterprise SATA M.2 | PVE boot (LVM) |
| nvme0n1 | Samsung 960 PRO 512GB | 512 GB | Consumer MLC NVMe (no PLP) | Ceph OSD |
| sdb | SanDisk USB stick | 14 GB | USB | (irrelevant) |

M.2 slots reported via DMI: 1× Socket 3 NVMe (x4, used), 1× Socket 1-SD (x1, WLAN). Length "Long" — practical assumption is 2280 only.

## vm-host-02 (Proxmox — Dell OptiPlex SFF)

| Device | Model | Cap | Class | Use |
|---|---|---|---|---|
| sda | Intel SSDSCKJB150G7 (DC S3520 M.2) | 150 GB | Enterprise SATA M.2 | PVE boot (LVM) |
| nvme0n1 | Samsung 970 EVO 500GB | 500 GB | Consumer TLC NVMe (no PLP) | Ceph OSD |

Same chassis class and slot constraints as vm-host-01.

## Unused / shelved

| Item | Class | Plausible role |
|---|---|---|
| 2× Intel Optane P1600X 118 GB | Optane (PLP) | Mirrored SLOG (tank's special vdev is already filled) |
| 4× Intel Optane Memory M10 16 GB | Optane "cache" SKU, small, M.2 single-namespace | Marginal — too small for special vdev; SLOG-only and P1600X is a better SLOG |
| Samsung 860 EVO 1 TB | Consumer SATA TLC | General bulk SATA SSD |
| HP EX950 1 TB | Consumer NVMe TLC (SMI controller) | Drop-in consumer NVMe OSD candidate |

Plus M.2-to-PCIe carrier adapters available for slotting M.2 22110 enterprise NVMe into PCIe x4 lanes.

## Refresh commands

```sh
ssh nas-host-01 'sudo lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN && sudo zpool list -v && sudo /usr/sbin/pvesm status'
ssh vm-host-01  'sudo lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN'
ssh vm-host-02  'sudo lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN'
ssh nas-01      'lsblk -d -o NAME,SIZE,MODEL,SERIAL,ROTA,TRAN && sudo zpool status tank sink'

# Passthrough map on nas-host-01
ssh nas-host-01 'sudo grep -E "hostpci|name" /etc/pve/qemu-server/200.conf'
ssh nas-host-01 'sudo lspci -nn | grep -E "01:00|c[2-7]:00|83:00"'
```
