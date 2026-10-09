# Turing Pi storage: each node's NVMe, or a CM4 file server

Researched 2026-10-08. **[I]** marks inference. Nothing here was run on the boards, and the drives' SMART wear wasn't read. Sources are listed at the end.

**The question (owner, 2026-10-08):** put two of the shelved Intel DC S3610 1.6 TB SSDs on slot 3's SATA ports as a ZFS mirror and make that node the file server for the other nodes, or are the NVMe drives already in the nodes good enough?

**The goal behind it:** the board is self-contained. Its primary data is local, except data that lives only on nas-01, and it may serve other systems, such as the Wyoming whisper stack for Home Assistant.

**The board** ([turingpi/nodes.md](../../turingpi/nodes.md)):

| Slot | Node | Disk now |
|---|---|---|
| 1 | `turingpi-rk1-01`: RK1 16 GB, Debian 13 on vendor 6.1.172 | Samsung 960 PRO 512 GB NVMe |
| 2 | `turingpi-rk1-02`: the same | Samsung 970 EVO 500 GB NVMe |
| 3 | `turingpi-cm4-01`: CM4 8 GB | 32 GB eMMC only; both SATA ports empty |
| 4 | `turingpi-jetson-01`: Orin Nano 8 GB, L4T R39.2.1 | OS on microSD; HP EX950 1 TB NVMe for data (`data_disk_offload`) |

## Bottom line

**Each node's NVMe is good enough for its own data. A CM4 file server on two S3610s doesn't fit this board.**
- **The data worth protecting can't go on the file server.**
  - The apps' own docs require local disk for databases (Immich's Postgres, Frigate's and every other SQLite database) and for Docker's own storage.
  - What NFS may hold is models, recordings and media. That is mostly re-downloadable, or nas-01's data anyway.
- **The file server would be about 30× slower than local disk.**
  - The CM4 has one 1 GbE port: about 110 MB/s, shared by every client, and about 35 MB/s for many small files.
  - The RK1s and the Orin read their NVMe at about 3 GB/s.
  - A 1.6 GB whisper model loads in about 15 s instead of 0.5 s [I].
- **It adds a single point of failure without removing the common one.**
  - Every client hangs while the CM4 reboots.
  - The S3610s' power-loss protection guards only the server's own disks, and the whole board shares one power supply.
- **What the NVMe drives lack is redundancy, not speed or endurance.**
  - Their rated endurance covers this kind of workload many times over. The exception is heavy camera recording on the 970 EVO.
  - Cover the missing redundancy with backups to backup-01. It is off the board, and it already sends its pool offsite.
- **Keep the S3610s on the shelf until something writes a lot locally,** such as camera recordings. Then give them to the node that writes, in slot 3, not to an NFS server.

## Option A: the CM4 with two S3610s, serving NFS

### The drives

- **Three S3610s are shelved, and one must stay as the Proxmox Ceph cluster's only cold spare** ([hardware/ssd-inventory.md](../../hardware/ssd-inventory.md), "The five Intel DC S3610 1.6 TB"). This option uses every drive that can be spared.
- **The pair to use is the two HPE `LK1600GEYMV` drives** (`BTHC646101YB1P6PGN`, `BTHC72640DGK1P6PGN`).
  - The inventory already notes that pairing them staggers their wear (25 TB vs 113 TB written).
  - Their firmware hides wear from Scrutiny anyway.
  - That leaves the Cisco-SKU drive, whose SMART Scrutiny can read, as the Ceph spare [I].
- **All three carry ZFS labels** from an old pool, `basin`, and need clearing first.

### Hardware

**The controller:**
- An ASMedia ASM1061 on the CM4's single PCIe 2.0 x1 lane (talos#7358; Geerling 2021). That lane tops out around 400 MB/s.
- On a CM4, two SSDs in an mdadm RAID1 measured 253.6 MB/s read and 125.7 MB/s write, on a different controller (Marvell 9215; pcie-devices#1). A mirror writes every block over the lane twice.

**No SATA power on the board.**
- The specs list only "Standard ATX 24 Pin socket" for power, and the board diagram shows no power header by the SATA ports.
- So the drives take power from the PSU's own SATA or Molex leads [I, strongly implied]. Turing's Pico PSU has "3 x SATA" at "up to 160W".
- Each S3610 1.6 TB draws 6.8 W writing (RMS, 5 V only) and 0.62 W idle, with 1.2 A inrush per rail. Its 3.3 V pins are "Not connected", so a Molex-to-SATA adapter works (Intel spec 331342-007US, tables 8, 9 and 17).

**Turing's SATA note:** "you should not hot-plug the disk… shut down the node… plug in the disk, and then restart the node."

**The slot-3 CLKREQ# problem** is fixed in the v2.5 board's hardware, and Linux 6.8+ carries the kernel fix (e2596dcf1e9d).

### The network

- **Every port on the board's switch is 1 GbE.** The RTL8370MB-CG connects nodes 1–4, the BMC and two external ports (BMC firmware `sun8i-t113s-turing-pi2.dtsi:227-277`).
  - BMC v2.1.0 offloads the bridge to the switch chip, so node-to-node traffic doesn't touch the BMC's CPU.
- **Measured:** an RK1 in a Turing Pi 2 reached 942 Mbps out and 927 Mbps in (sbc-reviews#38).
- **NFS from a CM4** (Geerling, pcie-devices#1, 2020, async export):
  - 106.2 MB/s for one large file;
  - 36.5 MB/s for 1,478 files totalling 1.93 GB;
  - one nfsd thread used 75–100% of a core.
- **The RK1s' 2.5 GbE cards don't help.**
  - They connect to the house switch, so RK1-to-CM4 traffic over them would leave the board and come back through its 1 GbE uplink. That is no faster, and depends on the house network [I].
  - With both NICs on one subnet, NFS would also need pinning to the onboard interface.

### ZFS on the CM4

- **On Canonical's Ubuntu 26.04, the CM4's recommended OS** ([cm4-os.md](cm4-os.md)), the ZFS modules ship prebuilt: `linux-main-modules-zfs-7.0.0-1020-raspi`, pulled in by the kernel's modules package. The Raspberry Pi OS route below is the other one researched.
- **Works from Raspberry Pi OS's default repos [I: from apt's rules, not run].**
  - RPi's archive carries `zfs-dkms` 2.4.4-1~bpo13+0~rpt1, which apt prefers over Debian's 2.3.9. Both support Linux up to 7.2 (OpenZFS `META`), so the 6.18.50 kernel is covered.
  - The repo's `zfs_install` role pins trixie-backports, which would give Debian's 2.4.4-1~bpo13+1 instead.
  - `linux-headers-rpi-v8` must be installed explicitly. Without it, a kernel update leaves "Module zfs not found".
- **No AES instructions on the CM4** (Pi 4 `/proc/cpuinfo`: "fp asimd evtstrm crc32 cpuid").
  - ZFS native encryption would run in generic C. OpenSSL's aes-256-gcm on a Pi 4 does 24 MB/s, so encrypted datasets would fall below line rate [I].
  - SSH defaults to chacha20-poly1305, about 226 MB/s, so replication over ssh is fine.
- **Checksums (fletcher4, NEON) and lz4 aren't a bottleneck [I].**
- **The ARC** defaults to about 7 GiB of the 8 GB.

### What the apps allow on NFS

| Data | On NFS? | The source says |
|---|---|---|
| SQLite (Frigate's database, many apps' state) | **no** | "have been known to operate incorrectly for some network filesystems. This has led to database corruption"; "WAL does not work over a network filesystem" (sqlite.org) |
| Immich's Postgres | **no** | "should ideally use local SSD storage, and never a network share of any kind" (Immich docs, requirements) |
| PostgreSQL generally | possible | "It is possible to use an NFS file system", mounted `hard`, where "processes can 'hang' indefinitely" (PostgreSQL 18, §18.2.2.1) |
| Docker's root, `/var/lib/docker` | **no** | overlay2 needs "xfs with ftype=1, ext4, btrfs"; the kernel says "NFS is not suitable" as an overlay upper layer (`overlayfs.rst:104`) |
| Frigate recordings | yes | NAS is "supported", but "it is generally recommended to have local storage for your Frigate recordings" |
| Models (faster-whisper, piper, LLMs) | yes | read-mostly and re-downloadable |
| Immich originals | yes | the FAQ's CIFS example; these are nas-01's data anyway |

**Mount options:**
- **Never mount `soft`:** "A so-called 'soft' timeout can cause silent data corruption" (nfs-utils 2.8.3, `nfs.man`).
- **Keep the server's default `sync`:** `async` "can cause data to be lost or corrupted" on a crash.
- **The cost:** with `hard` mounts, every client stalls while the CM4 is down [I].

**So the file server could hold only models, recordings and media, and models load far slower over it:**

| Model | Size | Over the CM4's NFS (~110 MB/s) [I] | Local NVMe (~3 GB/s) [I] |
|---|---|---|---|
| faster-whisper `turbo` (the `docker_compose_wyoming_faster_whisper` default) | 1.62 GB | ~15 s | ~0.5 s |
| faster-whisper large-v3 | 3.09 GB | ~28 s | ~1 s |
| an 8 GB LLM | 8 GB | ~73 s | ~2.7 s |

Two nodes loading at once each get about half the NFS rate.

## Option B: each node's NVMe holds its own data

### The drives

| | Samsung 960 PRO 512 GB (rk1-01) | Samsung 970 EVO 500 GB (rk1-02) | HP EX950 1 TB (jetson-01) |
|---|---|---|---|
| Controller, NAND, DRAM | Polaris, MLC, 512 MB | Phoenix, TLC, 512 MB | SMI SM2262EN, 64-layer TLC, 1 GB |
| Rated endurance | 400 TB | 300 TB | 650 TB |
| That, per day over 5 years [I] | ~219 GB | ~164 GB | ~356 GB |
| Power-loss protection | none | none | none |
| Power states on Linux | Probably never enters APST: 960 PROs report APSTA=0 (LKML 2017) [I for this 512 GB drive] | APST on, down to PS4 (5 mW, 8 ms exit) [I] | Deepest state disabled by a kernel quirk naming "HP SSD EX950 1TB" (commit e89086c43f05). It's in the RK1's vendor 6.1 `pci.c:3548`, and in 6.8.12, which L4T R39.2.1 is based on [I] |

Sources: Samsung datasheets (960 PRO Rev 1.0, 970 EVO Rev 1.0); the HP/BIWIN EX950 sheet; AnandTech.

**Enough for this workload, with caveats:**
- **Endurance:**
  - The planned services (Wyoming whisper and piper, Immich machine learning, LLMs) write little: models once, then logs and small state [I].
  - Continuous camera recording is the exception. Each 4 Mbit/s camera writes about 43 GB a day [I], so a few cameras would eat the 970 EVO's budget.
- **Warranty and wear:**
  - The warranties have almost certainly run out.
  - The drives came out of Proxmox hosts, so their remaining wear is unknown until SMART is read.
- **APST on the 970 EVO:**
  - The Super6C's PM991s hung with APST on. The fix was `nvme_core.default_ps_max_latency_us=0` ([../super6c-cluster/findings.md](../super6c-cluster/findings.md)).
  - The PM991 is a different controller, and nothing found says the 970 EVO hangs on an RK3588. The remedy is known if it does.
- **The RK1's PCIe 3 clock issue,** which mainline fixed in 6.13, is already handled in the vendor 6.1 device tree: CLKREQ# is held low (`rk3588-turing-rk1.dtsi:509-516`).

**No power-loss protection, on a board with one PSU:**
- **The kernel** flushes a drive's volatile write cache on `fsync`: "the operating system needs to force data out to the non-volatile storage when it performs a data integrity operation like fsync" (`writeback_cache_control.rst`).
- **OpenZFS:** firmware that honours flushes protects "flushed data and the drives' own metadata, which is all that filesystems such as ZFS need."
- **So fsync'd data survives a board-wide power cut, if the drive honours flushes.**
  - PostgreSQL warns that some consumer SSDs don't.
  - One 2022 test caught two other consumer drives losing flushed data.
  - None of these three models has been tested [I].
  - ZFS would detect such a loss; ext4 would not.

### Filesystem per node

- **Jetson:**
  - `data_disk_offload` already puts ext4 on the EX950 and moves Docker, containerd, logs and swap onto it.
  - ZFS would probably build there. Ubuntu noble's `zfs-dkms` 2.2.2-0ubuntu9.5 carries Linux 6.8 support, and NVIDIA's `nvidia-l4t-kernel-headers` ships a native build tree [I].
  - Nobody has reported ZFS on JetPack 6 or 7.
- **RK1: ZFS on the vendor kernel has a poor record.** That kernel can't be dropped, because RKNN and RKLLM need it ([rk1-gpu-npu.md](rk1-gpu-npu.md)). Armbian forum reports on Rockchip's vendor kernels:
  - 5.10 with ZFS 2.1.11 failed to build;
  - 6.1.84 with 2.2.6 oopsed on module load;
  - 6.1.115 with 2.3.5 loaded, but `/dev/zfs` failed.
  
  An Armbian admin, January 2026: "It is not recommended to match ZFS with vendor kernel(s)." The 6.1.172 headers also exist only on beta.armbian.com.
- **btrfs is the in-kernel alternative on the RK1.** `BTRFS_FS=m` is set in the vendor config, so it gives checksums and snapshots with no DKMS.
- **ext4 is the plain default everywhere.**

### Backups instead of a mirror

**The homelab already backs up with ZFS.** nas-01 syncoids to backup-01 (a pool of two mirrors), which forwards to offsite-nas (`ansible/playbook-nas-01.yaml`, `playbook-backup-01.yaml`). backup-01 is off the board and on other power, which an S3610 mirror in slot 3 would not be.
- **Where ZFS runs** (probably the Jetson): sanoid, plus syncoid to backup-01. The roles `zfs_install`, `sanoid`, `syncoid_source` and `syncoid_destination` exist.
- **Where it doesn't** (the RK1s): a file-level tool such as restic, writing into a dataset on backup-01 that sanoid snapshots and syncoid carries offsite [I]. The repo has no restic role yet.
- **What to back up is small.** Configs come from Ansible, and models and images can be downloaded again. What's left is each app's state: databases, and recordings if any.

**Under Kubernetes** ([kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md)): Longhorn could replicate volumes between the two RK1s' NVMe drives. The Orin's kernel has no iSCSI, so its data stays local only.

## Variants considered

**The CM4 and mirror as an in-box backup target.** It would use syncoid with raw sends, so the CM4 never runs AES.
- It needs ZFS on the sources, which the RK1s lack.
- It shares the board's power supply.
- Over backup-01, it adds only a fast local restore [I].

**An RK1 in slot 3, with the mirror local to it.**
- **What it gets:** slot 3 carries M.2 T3 and both SATA ports, and Turing's table lists the RK1 for both. So an RK1 there should get its NVMe and the SATA pair [I]. RK1 SATA hasn't been confirmed in practice.
- **Throughput:** the SATA would sit on the RK1's PCIe 2.0 x1 into the same ASM1061, so the same ~400 MB/s class [I].
- **What it loses:** slot 3 has no mini-PCIe, so the module moved there gives up its 2.5 GbE card [I].
- **Filesystem:** on the vendor kernel the mirror would be btrfs RAID1 rather than ZFS (above).
- **When to use it:** if a node ever writes a lot locally, for example Frigate recording onto the mirror on its own node, with no NFS hop.

## Decision: S3610 mirror and CM4 file server, or each node's NVMe

**The question:** should slot 3 hold two S3610s in a ZFS mirror, with the CM4 serving the other nodes' data, or should each node keep its data on its own NVMe?

**CM4 file server on the mirror.**
- **For:**
  - Redundancy and checksums for whatever lives on it.
  - Enterprise drives with power-loss protection and high endurance (10.7 PB rated).
  - One place to snapshot and replicate.
  - ZFS works on the CM4: prebuilt in Canonical's Ubuntu 26.04 kernel, its recommended OS, or from Raspberry Pi OS's default repos.
- **Against:**
  - The apps' own docs keep their databases and Docker's storage off NFS, so the data that most needs the mirror can't use it.
  - What can use it (models, recordings, media) is mostly re-downloadable. It would be served about 30× slower than local NVMe, over one shared 1 GbE port, from the slowest node.
  - Every client hangs when the CM4 restarts.
  - The board has one power supply, so the drives' PLP doesn't change how it fails.
  - It uses the last two S3610s not reserved for Ceph, and needs SATA power leads from the PSU.

**Each node's NVMe.**
- **For:**
  - Every app gets local disk, which their docs ask for.
  - PCIe 3.0 x4 speed.
  - No cross-node dependency: a node going down affects only its own services.
  - Endurance is ample for inference services.
  - Nothing to buy or cable.
- **Against:**
  - No redundancy: a dead drive loses that node's data until it's restored.
  - No power-loss protection.
  - Unknown wear, and out of warranty.
  - ZFS is a poor fit on the RK1s' vendor kernel, so their backups need a file-level tool the repo doesn't have yet.

**Recommendation: each node's NVMe, with backups to backup-01.**
- The data that matters on this board is small, and the apps require it on local disk.
- A mirror protects against one drive failing. A backup off the board protects against that and against losing the board, and the homelab's backup chain already exists.
- Keep the two S3610s shelved for now.

**What would change it:**
- **A workload that writes a lot and must stay on the board,** such as several Frigate cameras recording continuously. Then put the S3610s in slot 3 under the node that runs it (an RK1 there, btrfs RAID1), still not behind NFS.
- **SMART wear on an NVMe close to its limit.** Then replace that drive rather than centralise storage.

## Open

- **SMART on the three NVMe drives:** percentage used, data written, media errors and unsafe shutdowns; also the 960 PRO's APSTA bit and each drive's firmware version.
- **Which services will run, and how much state they keep:** especially whether Frigate (cameras, retention) is planned.
- **The PSU model,** if the S3610s are ever fitted: whether it has spare SATA or Molex leads.
- **Untested here:**
  - ZFS on the Jetson (noble `zfs-dkms` against `6.8.12-1021-tegra`);
  - btrfs RAID1 on the RK1 vendor kernel;
  - RK1 SATA in slot 3;
  - a node-to-node iperf through the board's switch.
- **The backup tool for non-ZFS nodes.** No restic role exists. Not checked: whether `proxmox-backup-client` has arm64 builds (backup-01 runs Proxmox Backup Server).

## Sources

**Turing Pi 2 and the CM4**
- **Turing Pi docs:**
  - [Turing Pi 2 specs and I/O](https://docs.turingpi.com/docs/turing-pi2-specs-and-io-ports) (updated 2025-11-12), and the board interconnection diagram linked from it
  - [Turing Pi 2 cluster storage](https://docs.turingpi.com/docs/turing-pi2-kubernetes-cluster-storage)
  - [v2.5 changelog](https://docs.turingpi.com/changelog/turing-pi2-v25-list-of-improvements)
  - [Pico PSU](https://turingpi.com/product/pico-psu/)
- **BMC firmware**, turing-machines/BMC-Firmware v2.1.0: `tp2bmc/board/tp2bmc/sun8i-t113s-turing-pi2.dtsi:227-277`, `patches/linux/realtek-switch.patch`, `overlay/etc/network/interfaces`.
- **CLKREQ#:** [siderolabs/talos#7358](https://github.com/siderolabs/talos/issues/7358); Linux `e2596dcf1e9d`.
- **Jeff Geerling:**
  - [Turing Pi 2 (2021)](https://www.jeffgeerling.com/blog/2021/turing-pi-2-4-raspberry-pi-nodes-on-mini-itx-board/)
  - [Wiretrustee SATA](https://www.jeffgeerling.com/blog/2021/wiretrustee-sata-pi-board-true-sata-nas/)
  - geerlingguy/raspberry-pi-pcie-devices #1, #268, #314
  - geerlingguy/sbc-reviews#38
  - geerlingguy/turing-pi-2-cluster#3
- **The S3610:** Intel DC S3610 product specification 331342-007US (Sept 2016).
- **Raspberry Pi:**
  - [Raspberry Pi OS release notes](https://downloads.raspberrypi.com/raspios_arm64/release_notes.txt)
  - raspberrypi/documentation `linux_kernel/headers.adoc`, `processors/bcm2711.adoc`
  - meta-raspberrypi#964 (no AES)
- **ZFS:** OpenZFS 2.3.9 and 2.4.4 `META`, `module/icp/algs/aes/aes_impl.c`, `man4/zfs.4`; the Debian and archive.raspberrypi.com package indexes for trixie (2026-10-08).
- **Crypto speed:** [OpenSSL on a Pi 4](https://www.tuxed.net/fkooman/blog/openvpn_modern_crypto_part_iii.html).

**The NVMe drives**
- **Datasheets:**
  - [Samsung 960 PRO](https://cdn.inet.se/pdf/4300298_0.pdf)
  - [Samsung 970 EVO](https://download.semiconductor.samsung.com/resources/data-sheet/Samsung-NVMe-SSD-970-EVO-Data-Sheet_Rev.1.0.pdf)
  - [HP EX950](https://hp.biwintech.com/u_file/photo/20260123/HP%20EX950%20Specifications.pdf)
  - AnandTech: the EX950 at CES 2019, and the power states in its 970 EVO review
- **Power states and quirks:**
  - [LKML 2017, 960 PRO APSTA=0](https://lkml.iu.edu/hypermail/linux/kernel/1705.0/01924.html)
  - Linux commit e89086c43f05 (quirks for 126f:2262)
  - armbian/linux-rockchip `rk-6.1-rkr7.2`: `drivers/nvme/host/pci.c`, `core.c`, `arch/arm64/boot/dts/rockchip/rk3588-turing-rk1.dtsi`
- **Flushes and power loss:** Linux `Documentation/block/writeback_cache_control.rst`; [OpenZFS hardware](https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Hardware.html); PostgreSQL 18 "WAL reliability".
- **ZFS on these kernels:** Armbian forum topics 30555, 49378 and 57323; NVIDIA forum 269858 (ZFS on JetPack 5); Ubuntu `zfs-linux` 2.2.2-0ubuntu9.5 changelog; `nvidia-l4t-kernel-headers` 6.8.12-tegra-39.2.1.

**The apps**
- **SQLite:** [useovernet](https://www.sqlite.org/useovernet.html) and [wal](https://www.sqlite.org/wal.html).
- **Immich:** docs.immich.app (requirements, FAQ).
- **Frigate:** docs (installation, FAQ, planning).
- **PostgreSQL 18:** §18.2.2.1.
- **Docker:** docs (volumes, storage drivers).
- **Linux:** `Documentation/filesystems/overlayfs.rst`.
- **NFS:** nfs-utils 2.8.3 `nfs.man` and `exports.man`.
- **Model sizes:** Hugging Face (Systran faster-whisper, rhasspy piper voices); `ansible/roles/docker_compose_wyoming_faster_whisper/defaults/main.yaml`.
