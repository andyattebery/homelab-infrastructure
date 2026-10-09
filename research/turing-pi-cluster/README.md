# Turing Pi 2 cluster research (2026-09-26)

**Goal.** A new lab Kubernetes cluster on the Turing Pi 2 (board v2.5), with **new** shared storage on the nodes' own drives. That rules out the Proxmox Ceph cluster and nas-01.
- Lab means the cluster is rebuilt at will and has no backup target.
- Every host and the API VIP get fixed IPs from the existing Turing Pi block in `network-inventory/network_hosts_inventory.yaml.tpl`.

The work started as a Talos plan. This folder is the research behind it.

**Bottom line: Talos does not support the RK1's or the Orin's most compelling hardware.**
- **RK1:** no video encode or decode and no HDMI. The NPU runs only through a TFLite-only path, about 10× slower than Rockchip's RKNN.
- **Orin:** no GPU, no video decoder and no Super mode. Under Talos it is a CPU-only node at best.
- **Everything else works on the RK1 and CM4:** CPU, storage and network.
- Getting those features means vendor stacks: Rockchip's BSP kernel and NVIDIA's JetPack.

**Status: undecided.** Storage (Longhorn v1) and the Talos configuration are researched. The open decision is the OS. Nothing is built.

**Superseded (2026-09-26):** the cluster is being built on the DeskPi Super6C (6× CM4 Lite) instead. See [../super6c-cluster/](../super6c-cluster/README.md).

## The CM4's OS (2026-10-08)

`turingpi-cm4-01` runs stock Armbian `rpi4b` 26.8.1, installed to match the RK1s. That match no longer holds: the RK1s run a custom build on Rockchip's vendor kernel. Details: [cm4-os.md](cm4-os.md).

**Decided (owner, 2026-10-08): Ubuntu 26.04 on the RK1s and the CM4; the Jetson stays on Ubuntu 24.04,** which is what NVIDIA's L4T supports. That is Ubuntu on all four nodes, in two releases.

**Recommendation for the CM4: Canonical's Ubuntu Server 26.04 for Raspberry Pi.**
- **Why:** Canonical certifies the CM4. Its A/B boot falls back by itself when a kernel update fails. Its first boot is cloud-init, like the Jetson's card.
- **What it needs:** an EEPROM dated 2022-11-25 or later, and a small script that puts the `user-data` seed onto the image the BMC writes.
- **On the kernel-update reports:** the two CM4 reports are single-user and unconfirmed, and the widespread `piboot-try` failure is a low-RAM problem.
- **The fallback is Armbian's `rpi4b` 26.04 image,** if the EEPROM or the seeding doesn't work out. Armbian doesn't test the CM4, its first boot is a manual wizard, and its boot-partition packaging has no fallback.

**For the RK1s,** 26.04 means building a minimal image Armbian doesn't publish. Armbian ships 26.04 for this board only as desktops. `rk1-armbian-minimal` then needs reworking from Debian 13, and the image must pass its hardware checks again.

## Kubernetes on the vendor OSes (2026-10-07)

Since 2026-10-03 the RK1s run Debian 13 on Rockchip's vendor kernel and the Orin runs L4T R39.2.1 ([turingpi/nodes.md](../../turingpi/nodes.md)). The Talos answer above therefore no longer says what the boards could do. Details: [kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md).

**Bottom line: under Kubernetes on these OSes, the Orin's GPU and the CM4's H.264 reach pods the standard way. The RK1's accelerators reach them only partly: its full video and most NPU front ends need privileged pods.** Nothing here has been run on the boards.
- **Orin:**
  - CUDA and TensorRT work through NVIDIA's device plugin and CDI. That is reported working on R39.2.1 with k3s 1.36.
  - NVDEC comes with the GPU allocation, unverified.
  - NVIDIA calls Kubernetes on Jetson community support, and its GPU Operator excludes Jetson.
  - Its stock kernel runs k3s's defaults (Flannel VXLAN, iptables kube-proxy). It can't run nftables or IPVS kube-proxy or Cilium, and has no iSCSI for Longhorn.
- **RK1:**
  - GPU (OpenCL, Vulkan) and RGA: unprivileged [I].
  - NPU through the C runtimes: unprivileged [I, untested]. Python RKNN, Frigate and Immich need privileged pods.
  - MPP video: the full codec set only in privileged pods.
- **CM4:**
  - Raspberry Pi OS: H.264 decode and encode and the V3D GPU, yes. The HEVC hardware is stateless, and most apps miss it.
  - Canonical's Ubuntu 26.04, the recommended OS: the same, with the HEVC decoder in its 7.0 kernel.
  - Talos: no codecs.
- **No maintained device plugin exists for the Rockchip or Pi blocks.** `squat/generic-device-plugin` is the generic route.
- **The boards shouldn't join the Super6C Talos cluster.** Sidero won't support mixed clusters, and the Orin's kernel can't run that cluster's nftables kube-proxy [I].

**Kubernetes is a consistent layer for the workloads, not for the OSes.** Each board's kernel and firmware come from its own vendor (the RK1 build, NVIDIA's L4T, the Pi kernel tree), and those upgrades stay three separate jobs with or without it. Docker CE is already the same version on Debian and Ubuntu.

**Recommendation:** run the boards as Docker hosts managed by Ansible. Choose k3s for its operating model, or to keep RK1 services up during RK1 upgrades, not to reduce OS maintenance. The work that does reduce OS maintenance is automating RK1 kernel updates and keeping every node on Ubuntu ([cm4-os.md](cm4-os.md)). The argument is in [kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md#decision-kubernetes-on-the-turing-pi-or-not).

## Storage for a self-contained board (2026-10-08)

**The goal:** the board is self-contained. Its primary data is local, except data that lives only on nas-01, and it may serve other systems, such as the Wyoming whisper stack for Home Assistant. Details: [node-storage.md](node-storage.md).

**Bottom line: each node's NVMe is good enough for its own data. Two S3610s in a ZFS mirror on slot 3, with the CM4 as the other nodes' file server, doesn't fit.**
- The apps' own docs require local disk for the data worth protecting: databases, SQLite, Docker's root. What may go on NFS, mostly models, can be downloaded again.
- The CM4 serves it through its single 1 GbE port: about 110 MB/s shared, against about 3 GB/s from local NVMe.
- It makes the slowest node a single point of failure. The S3610s' power-loss protection doesn't help when the whole board shares one power supply.
- What the NVMe drives lack is redundancy. Back up the small irreplaceable part to backup-01, which is off the board and already feeds the offsite copy.
- Keep the S3610s shelved until something writes a lot locally, such as camera recordings. Then put them on the node that writes the data, not behind NFS.

## Hardware

| Slot | Module | Data disk (from `hardware/ssd-inventory.md`, "Unused / shelved") |
|---|---|---|
| 1 | Turing RK1 16 GB (RK3588, 32 GB eMMC) | Samsung 960 PRO 512 GB NVMe, M.2 T1 |
| 2 | Turing RK1 16 GB | Samsung 970 EVO 500 GB NVMe, M.2 T2 |
| 3 | Raspberry Pi CM4 8 GB / 32 GB eMMC, on the Turing Pi CM4 adapter | Samsung 860 EVO 1 TB SATA, on slot 3's ASMedia controller |
| 4 | Jetson Orin Nano 8 GB, P3767-0005 (from the Orin Nano Super dev kit) | — |

- The two NVMe drives were picked to match in size. Raw capacity is about 2 TB, roughly 1 TB of volumes at 2 replicas [I].
- The three Intel S3610s stay unassigned. At least one is the Proxmox Ceph cold spare.
- The Orin is `jetson-01` today. It sits on its own carrier and serves Wyoming faster-whisper and piper to Home Assistant ([ops-findings.md](ops-findings.md)).

**Update (2026-10-03):** what is installed now is in [turingpi/nodes.md](../../turingpi/nodes.md). It differs from the table: slot 3's SATA ports are empty, the Orin is in slot 4 as `turingpi-jetson-01` with an HP EX950 1 TB NVMe, and slots 1 and 2 carry Realtek RTL8125 2.5 GbE cards in their mini-PCIe slots.

## Conclusions

### Talos runs every board's core hardware, not its accelerators

Details: [hardware-support.md](hardware-support.md).

- **Core blocks work under every OS researched.** On the RK1 and CM4 that means CPU and cpufreq, thermal, fan, eMMC, NVMe, SATA, Ethernet and USB. Two exceptions:
  - CM4 USB 2.0 on mainline kernels (Talos, and NixOS without nixos-hardware) needs a dwc2 host-mode overlay. Talos adds it through `configTxtAppend`.
  - The Orin under Talos gets no power modes, no thermal zones and no fan control.
- **What Talos 1.14.1 lacks:**
  - **RK1:** no video decode or encode, no HDMI, no RGA. The GPU and NPU work only through system extensions. The NPU path (Mesa Teflon) is TFLite-only and about 10× slower than Rockchip's RKNN.
  - **CM4:** no H.264 or HEVC codecs. The GPU works through the `vc4` extension.
  - **Orin:** boots in ACPI mode with working Ethernet. CPU, USB and NVMe are expected but not verified on this board. No GPU, no NVDEC.
- **Only vendor stacks expose all the accelerators:**
  - Rockchip's BSP kernel: Armbian vendor 6.1, or Turing's Ubuntu 22.04.
  - The Raspberry Pi kernel: RPi OS, or NixOS with nixos-hardware.
  - NVIDIA's stack: JetPack 6.2 / 7.2.1, or jetpack-nixos.
- The Orin Nano has **no DLA and no NVENC** under any OS.

### The Orin's GPU needs NVIDIA's stack, which is NVIDIA's constraint, not Talos's

Details: [os-alternatives.md](os-alternatives.md).

- Mainline Linux has no driver or firmware for its GPU (GA10B). Even JetPack 7.2 still uses NVIDIA's out-of-tree `nvgpu`.
- The only Talos port needs Device Tree boot, which reboot-loops on P3767-0005 (talos-jetson-orin#57, open). ACPI boot works but exposes no GPU.
- **Moving it into a Turing Pi slot needs a QSPI reflash from an x86 Ubuntu host with `cvb_eeprom_read_size = 0`, whatever the OS**, because the board has no carrier EEPROM. On its dev-kit carrier it can join a cluster over Ethernet unchanged.
- Wherever it runs NVIDIA's L4T kernel (options 2–4 below), it can't hold Longhorn volumes: that kernel is built without `iscsi_tcp`.

### Storage: Longhorn v1

Details: [storage.md](storage.md).

- **Longhorn 1.12.1, v1 engine.** It needs:
  - two Talos extensions (`iscsi-tools`, `util-linux-tools`)
  - a `UserVolumeConfig` per data disk, mounted at `/var/mnt/longhorn`
  - a privileged namespace

  RWX goes through share-manager (NFSv4). Replica count 2 is Longhorn's best practice. On 1 GbE it means at most two network copies per write instead of three [I].
- **Piraeus/LINSTOR** is viable but tied to Talos's `drbd` extension version.
- **Rook-Ceph** requests about 5.5 GiB per node before CephFS.
- **Mayastor's** docs are x86-64 only.
- **Longhorn's v2 engine** has a stuck-I/O bug on arm64 NVMe.

### OS options

| Option | Gets | Gives up |
|---|---|---|
| **1. Talos on RK1, RK1, CM4; Orin stays `jetson-01`** | A supported, immutable, API-driven cluster. Full core hardware, Longhorn on all three nodes, RK1 NPU/GPU possible through extensions. The Orin keeps full JetPack as a standalone GPU host that pods call over the network. | RK1 video, HDMI and RKNN speed; CM4 codecs; GPU scheduling in Kubernetes |
| 2. Talos + Orin as a JetPack worker | Option 1 plus the Orin GPU in pods | Sidero says mixed clusters are "not going to be supported". `talosctl upgrade-k8s` fails on the Orin. The kubelet and join files are hand-maintained, and KubePrism needs HAProxy or disabling. |
| 3. NixOS + k3s everywhere (jetpack-nixos on the Orin) | One declarative toolchain like the rest of the repo; full CM4 and Orin hardware; RK1 at mainline level | The most unknowns: Longhorn on NixOS needs path workarounds (longhorn#2166, open since 2021), k3s with the jetpack-nixos GPU is undocumented, and the RK1 runs on community flakes. |
| 4. k3s on vendor OSes, managed by Ansible | Every accelerator on every board | Three mutable distros. The RK1 vendor images are unmaintained: the Armbian board has no maintainer and Turing's image has been frozen since Feb 2024. NVIDIA calls Kubernetes on JetPack "community support". |

Kairos is out: it has no RK3588 support and no Orin Nano model.

**Update (2026-10-01):** option 4's RK1 premise has partly changed. The vendor-kernel images are still unmaintained. But Ubuntu 26.04's own generic 7.0 kernel ships the RK1 DTB with GPU, NPU and rkvdec enabled, and builds `iscsi_tcp`. Booting it needs a hand-built EFI/GRUB path. See [rk1-os-releases.md](rk1-os-releases.md), and [rk1-gpu-npu.md](rk1-gpu-npu.md) for the GPU/NPU stacks and the boot procedure.

**Recommendation: option 1, if in-cluster accelerators are not a goal of the lab.** If they are, no option gets them all while keeping a supported Kubernetes platform. Option 4 is the only one with every accelerator, and it rests on an unmaintained RK1 OS image.

## Open questions

- **Which accelerators, if any, should pods use?** That decides the OS.
- **If Talos:** build on 1.14.1 and live with the mmc boot race (#14359), re-applying the config when a node lands in maintenance mode? Or wait for a 1.14.x that carries fix #14370? Its backport was only "Proposed" on 2026-09-26.
- **If the Orin moves into slot 4, under any OS:** the per-node power budget for 25 W and the fan header wiring are undocumented.
- **Untested here: Canonical's Ubuntu 26.04 on the CM4** (its EEPROM date, the seeding route, whether the first kernel update applies) **and a 26.04 minimal RK1 image.** See [cm4-os.md](cm4-os.md#open).
- **Kubernetes on the Turing Pi, or Docker hosts?** See [kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md#decision-kubernetes-on-the-turing-pi-or-not); its unverified items are listed there under "Open".
- **Before relying on the NVMe drives:** read their SMART wear. They came out of Proxmox hosts. See [node-storage.md](node-storage.md#open).

## Repo-level findings

- NIM writes DHCP reservations to **UniFi**. `ansible/roles/docker_compose_network_inventory_manager/README.md` says AdGuard, and is stale ([ops-findings.md](ops-findings.md)).
- The DNS VIP and MACs are vaulted, so a Talos patch with static addresses and nameservers can't be committed. Fixed IPs therefore come from UniFi reservations.
- Local `kubectl` is 1.33.9, outside the version skew for Kubernetes 1.37.

## Files

| File | What's in it |
|---|---|
| [hardware-support.md](hardware-support.md) | Per-feature support for RK1, CM4 and Orin across Talos, Armbian, Turing's Ubuntu, NixOS, RPi OS, JetPack and jetpack-nixos. Also: whether a pod can use each feature, the Turing Pi 2 slot map, and what the Orin loses in a slot. |
| [storage.md](storage.md) | Longhorn v1/v2, Piraeus/LINSTOR, Rook-Ceph, OpenEBS and Talos local storage on this hardware |
| [talos.md](talos.md) | Talos 1.14.1: board support, known issues, the multi-document config, Image Factory and upgrades, networking and VIP, etcd, secrets, tooling. Also the build outline for option 1. |
| [os-alternatives.md](os-alternatives.md) | Why the Orin GPU needs NVIDIA's stack, Kubernetes GPU on Jetson, and options A–E in detail |
| [rk1-gpu-npu.md](rk1-gpu-npu.md) | 2026-10-01: getting the RK1's GPU and NPU working. Ubuntu 26.04 generic (firmware, Mesa/rocket gaps, Teflon, booting via U-Boot v2026.07 → shim → GRUB, DT and console) vs Armbian vendor (kbase/libmali or panthor, RKNN/RKLLM, install) |
| [rk1-custom-image.md](rk1-custom-image.md) | 2026-10-01: building a custom RK1 vendor-kernel image. Base (Armbian framework vs stock rootfs vs defcom5/Radxa/BredOS), distro (Ubuntu 24.04 vs Debian 13; Rockchip targets Debian), Armbian framework internals (hosts, OrbStack, userpatches, pins, apt/version traps, first boot), libmali/RKNN/RKLLM/video userspace, vendor-tree maintenance, `tpi flash` |
| [orin-nano-install.md](orin-nano-install.md) | 2026-10-02: installing the Orin Nano in a Turing Pi slot. One x86 QSPI flash (not SDK Manager or the JetPack ISO), the EEPROM fix, the OS on microSD from a `jetson-disk-image-creator.sh` image with the NVMe for data, headless minimal/basic rootfs, locking QSPI against apt, distros on NVIDIA's kernel, Turing's steps |
| [orin-nano-qspi-updates.md](orin-nano-qspi-updates.md) | 2026-10-03: QSPI updates through apt. How NVIDIA's bootloader package reaches QSPI; rebuilding it around a patched capsule with NVIDIA's tools; a private apt repo that carries the release and gates it; checks |
| [cm4-os.md](cm4-os.md) | 2026-10-08: which OS `turingpi-cm4-01` should run. Armbian `rpi4b`, Ubuntu 24.04 and 26.04, and Raspberry Pi OS Lite, compared on kernel and update cadence, codecs, boot firmware and EEPROM, first boot after `tpi flash`, memory cgroup, and support dates. Records the decision (Ubuntu 26.04 on the RK1s and the CM4) and the RK1 image rework it needs |
| [kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md) | 2026-10-07: what a Kubernetes pod can use on the vendor OSes the boards now run (RK1 on Armbian vendor 6.1, Orin on L4T R39.2.1, CM4 on Raspberry Pi OS or Talos); how device nodes reach pods; each kernel's Kubernetes readiness; joining the Talos cluster vs a separate k3s cluster vs Docker hosts |
| [node-storage.md](node-storage.md) | 2026-10-08: each node's NVMe vs a CM4 file server on two S3610s in slot 3. Slot-3 SATA and power, the 1 GbE ceiling, ZFS on each OS, the three NVMe drives' specs and quirks, what each app allows on NFS, and backups to backup-01 |
| [rk1-os-releases.md](rk1-os-releases.md) | 2026-10-01 follow-up: current RK1 releases (Turing, Armbian Ubuntu 26.04 / Debian 13 on vendor 6.1.172, kurochan's builds), and Ubuntu 26.04's generic 7.0 kernel on the RK1 with its EFI boot path |
| [ops-findings.md](ops-findings.md) | The fixed-IP block, NIM behaviour, vaulted values, jetson-01's role, earlier attempts in the repo, local tooling |
