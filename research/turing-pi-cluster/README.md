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

**Recommendation: option 1, if in-cluster accelerators are not a goal of the lab.** If they are, no option gets them all while keeping a supported Kubernetes platform. Option 4 is the only one with every accelerator, and it rests on an unmaintained RK1 OS image.

## Open questions

- **Which accelerators, if any, should pods use?** That decides the OS.
- **If Talos:** build on 1.14.1 and live with the mmc boot race (#14359), re-applying the config when a node lands in maintenance mode? Or wait for a 1.14.x that carries fix #14370? Its backport was only "Proposed" on 2026-09-26.
- **If the Orin moves into slot 4, under any OS:** the per-node power budget for 25 W and the fan header wiring are undocumented.

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
| [ops-findings.md](ops-findings.md) | The fixed-IP block, NIM behaviour, vaulted values, jetson-01's role, earlier attempts in the repo, local tooling |
