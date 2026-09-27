# In-cluster shared storage for Talos on the Turing Pi 2

Researched 2026-09-26. Quotes are verbatim. **[I]** marks inference.

Scope: new storage on the cluster nodes' own drives. The owner excluded the Proxmox Ceph cluster and anything NAS-backed (NFS, democratic-csi).

## Versions

| Component | Version |
|---|---|
| Talos | v1.14.1: Linux 6.18.51, Kubernetes 1.37.0 |
| Longhorn | v1.12.1 (2026-08-14) |
| Piraeus Operator | v2.12.0 (2026-09-17): LINSTOR 1.35.2, Kubernetes ≥ 1.30 |
| Talos `drbd` extension | `ghcr.io/siderolabs/drbd:9.3.3-v1.14.1` |
| Rook | v1.20.7 (2026-09-02), Ceph v20.2.4 by default |
| OpenEBS | v4.6.1 (2026-09-10), Mayastor 2.12.1 |
| local-path-provisioner | v0.0.37 |

## What this hardware imposes

- **RK1.** Talos boots from the 32 GB eMMC 5.1, so the whole NVMe (PCIe 3.0 x4) is free for storage ([RK1 specs](https://docs.turingpi.com/docs/turing-rk1-specs-and-io-ports), [Talos RK1 page](https://docs.siderolabs.com/talos/v1.14/platform-specific-installations/single-board-computers/turing_rk1)).
- **CM4.** It "does not support connections via an M.2 (NVMe) port". SATA exists only in slot 3, USB3 only in slot 4 ([Turing Pi 2 specs](https://docs.turingpi.com/docs/turing-pi2-specs-and-io-ports)). Board v2.5 fixes the slot-3 "unconnected #clkreq signal (mostly a case with Talos running on Raspberry Pi CM4)" ([v2.5 changelog](https://docs.turingpi.com/changelog/turing-pi2-v25-list-of-improvements)).
- **Three nodes means three control planes,** so storage pods run on control planes. In 1.14 the NoSchedule taint lives in `KubeNodeConfig`, and `.cluster.allowSchedulingOnControlPlanes` is deprecated ([v1.14.0 release](https://github.com/siderolabs/talos/releases/tag/v1.14.0)).
- **Pod Security.** Talos "applies a `baseline` pod security profile across namespaces, except for the kube-system namespace". Every option below needs `pod-security.kubernetes.io/enforce=privileged` on its namespace.
- **1 GbE [I].** A writer's network card carries one copy per remote replica. That caps writes at about 110 MB/s with one remote copy, and about 55 MB/s with two. The SATA and NVMe disks are faster than the network.

## Longhorn, v1 data engine: best fit

- **Talos setup** ([Sidero's Longhorn guide](https://docs.siderolabs.com/kubernetes-guides/csi/longhorn)):
  - Extensions `siderolabs/iscsi-tools` and `siderolabs/util-linux-tools`.
  - A `UserVolumeConfig` named `longhorn`, mounted at `/var/mnt/longhorn`:
    ```yaml
    apiVersion: v1alpha1
    kind: UserVolumeConfig
    name: longhorn
    provisioning:
      diskSelector:
        match: disk.transport == 'nvme' && !system_disk
      grow: false
    ```
  - Helm `--set defaultSettings.defaultDataPath=/var/mnt/longhorn`.
  - No kernel modules for v1: `CONFIG_ISCSI_TCP=y` is built in.
  - [Longhorn's own Talos page](https://longhorn.io/docs/1.12.1/advanced-resources/os-distro-specific/talos-linux-support/) still adds a kubelet `extraMounts` bind (`rshared`). Talos says user volumes are "automatically propagated into the `kubelet` container" ([user volumes](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/storage-and-disk-management/disk-management/user)), so the bind is likely redundant [I].
- **Upgrades.**
  - Since Talos 1.8, `--preserve` "is now automatically set".
  - The v1.14 betas mounted `/var` noexec ("Longhorn v1 and vCluster are known to be affected", [discussion #13868](https://github.com/siderolabs/talos/discussions/13868)). This was reverted before release: "Only keep `noexec` for ETCD and LOG" ([commit 6fa811a0d](https://github.com/siderolabs/talos/commit/6fa811a0d)). Blog posts that repeat the beta warning are stale.
- **Requirements** ([best practices](https://longhorn.io/docs/1.12.1/best-practices/)): "3 nodes", "4 vCPUs per node", "4 GiB per node", ARM64 supported, and "10 Gbps network bandwidth between nodes". The instance manager reserves `{"v1":"12"}` percent of CPU ([settings](https://longhorn.io/docs/1.12.1/references/settings/)).
- **Replication.** Synchronous. Best practice is "Set the default replica count to "2""; the shipped default is 3. Replica node-level soft anti-affinity defaults to `false`, so every replica needs its own node.
- **RWX.**
  - "RWX volumes are exposed via NFSv4 servers that reside in share-manager pods", one per volume. If that pod dies there is a 90 s grace period, or 30 s with fast failover ([RWX](https://longhorn.io/docs/1.12.1/nodes-and-volumes/volumes/rwx-volumes/)).
  - Talos's NFS client "is part of the kubelet image" ([Talos storage guide](https://docs.siderolabs.com/kubernetes-guides/csi/storage)).
  - Longhorn 1.7.1 broke RWX on Talos through its environment check. It was fixed in 1.8.0 and backported to 1.7.3 ([#9558](https://github.com/longhorn/longhorn/issues/9558)).
- **Node down.**
  - StatefulSet pods need a manual force-delete ("Kubernetes won't force delete the pod for the user", [node failure](https://longhorn.io/docs/1.12.1/high-availability/node-failure/)), unless "Pod Deletion Policy When Node is Down" is moved off its default `do-nothing`.
  - Draining the node that holds a volume's last healthy replica is blocked by default (`block-if-contains-last-replica`).
- **Chart keys** (verified in [v1.12.1 `values.yaml`](https://raw.githubusercontent.com/longhorn/longhorn/v1.12.1/chart/values.yaml)):
  - `persistence.defaultClassReplicaCount` (default 3)
  - `defaultSettings.defaultDataPath`
  - `defaultSettings.defaultReplicaCount`, a per-engine JSON string such as `{"v1":"2"}`
  - `defaultSettings.createDefaultDiskLabeledNodes`
- **A node without a data disk [I].** By default Longhorn creates a default disk on every node. A node without the user volume would therefore hold replicas on its eMMC. `createDefaultDiskLabeledNodes` plus the `node.longhorn.io/create-default-disk` label limits disks to labelled nodes. In the planned layout every node has a data disk; the other safeguard is to install Longhorn only after every `u-longhorn` volume reports ready.
- **v2 (SPDK) engine: not on this hardware.**
  - It is GA ([v1.12.0](https://github.com/longhorn/longhorn/releases/tag/v1.12.0)).
  - Talos needs a `RawVolumeConfig`, `vm.nr_hugepages: "1024"`, and the modules `nvme_tcp`, `vfio_pci`, `uio_pci_generic` and `ublk_drv`.
  - Cost: "Additional 2 GiB memory per node", plus a poller that "consumes 100% of a dedicated CPU core". v1.12.0 made the default mask `0x3`, two cores.
  - On ARM64 with NVMe: "V2 volumes may experience stuck I/O when SPDK is configured with two or more CPU cores and node disks use the NVMe driver".

## Piraeus Operator / LINSTOR (DRBD): viable

- **Talos setup** ([Piraeus Talos how-to](https://piraeus.io/docs/v2.12.0/how-to/talos/)):
  - Image Factory extension `drbd`.
  - Modules `drbd` (with `usermode_helper=disabled`) and `drbd_transport_tcp`.
  - A `LinstorSatelliteConfiguration` that deletes `drbd-module-loader` and `drbd-shutdown-guard` and moves the LVM paths to `/var/etc/lvm/...`.
- **Version coupling.** The extension is "built against a specific Talos version" ([extensions README](https://github.com/siderolabs/extensions/blob/v1.14.1/README.md)). Upgrade using the installer built from the same schematic.
- **Pools.** LVM, thin LVM, file-backed (for example on a user volume), or ZFS. "source.hostDevices takes a list of raw block devices".
- **arm64.** piraeus-server 1.35.2 has a `linux/arm64` image. The Talos drbd extension on arm64 was not verified [I: likely].
- **Memory.** No defaults are published for the v2 operator. An old v1 example gives the satellite a 300Mi request and a 1Gi limit.
- **Quorum.**
  - "DRBD quorum requires at least three nodes but a third node which acts as an arbitrator can be diskless" ([DRBD guide](https://linbit.com/drbd-user-guide/drbd-guide-9_0-en/)).
  - With `placementCount: "2"`, a third node automatically gets a "TieBreaker".
  - The HA Controller "will speed up the fail-over process for stateful workloads".
- **RWX (v2.10+).**
  - Runs an NFS-Ganesha instance per volume. It needs "`autoPlace` value greater than or equal to `2`, in a LINSTOR cluster with three or more nodes".
  - The project's own advice: "rely on RWO volumes for performance, only using RWX where it is absolutely necessary".
- **Known issues.**
  - DRBD 9.3.1 with kernel TLS on Talos 1.13 caused a "cluster-wide bad_page kernel taint". Still open; no fix status found for 9.3.3 ([#13316](https://github.com/siderolabs/talos/issues/13316)).
  - LINSTOR once refused an evacuate because Talos's DRBD was too old: "has DRBD version 9.2.6, but version 9.2.7 (or higher) is required" ([piraeus-operator#626](https://github.com/piraeusdatastore/piraeus-operator/issues/626)). The DRBD version is fixed by the Talos release.

## Rook-Ceph in-cluster: marginal

- **Talos setup** ([Sidero's Rook guide](https://docs.siderolabs.com/kubernetes-guides/csi/ceph-with-rook)):
  - Privileged namespace.
  - "Only nodes with a spare disk can host an OSD", and the disk must have no partitions.
  - `allowMultiplePerNode` for small clusters.
  - Upgrade one node at a time and wait for `HEALTH_OK`.
  - `CONFIG_BLK_DEV_RBD=y` is built in.
  - A CephFS slowdown on Talos was patched ([#11129](https://github.com/siderolabs/talos/issues/11129); "Talos now drops the IMA ... support").
- **Kubernetes version conflict.** The Talos guide says Rook v1.20 supports "`v1.31` through `v1.36`"; [Rook](https://rook.io/docs/rook/v1.20/Getting-Started/Prerequisites/prerequisites/) says "v1.31 through v1.37". Talos 1.14 runs 1.37.
- **Memory.**
  - Chart defaults ([values](https://raw.githubusercontent.com/rook/rook/release-1.20/deploy/charts/rook-ceph-cluster/values.yaml)), request / limit: mon 1Gi/2Gi, mgr 512Mi/1Gi, OSD 4Gi/4Gi, MDS 4Gi/4Gi.
  - [Ceph Tentacle guidance](https://docs.ceph.com/en/tentacle/start/hardware-recommendations/): OSD "4GB+ per daemon" ("2-4GB may function but will be slow"), mon "5GB+", MDS "8+ GiB".
  - A node running mon + mgr + OSD requests about 5.5 GiB before any workloads. Adding CephFS's MDS brings it to about 9.5 GiB, more than an 8 GB node has [I].
- **Network.** Ceph asks for "1x 1Gb/s (bonded 25+ Gb/s recommended)". Talos warns "Ceph can be rather slow for small clusters".
- **Replication.** 3 mons, which can run on nodes without OSDs. Size 3 with failure domain `host` needs three OSD hosts, so the CM4 must host an OSD, or you accept size 2. With exactly 3 hosts, a lost host cannot be re-replicated anywhere [I].

## OpenEBS: Mayastor not viable; LocalPV is the baseline

- **Mayastor** ([prerequisites](https://openebs.io/docs/quickstart-guide/prerequisites)):
  - "x86-64 CPU cores with SSE4.2"
  - "Two CPU cores" and "1GiB RAM" per io-engine
  - "A minimum of 2GiB of 2MiB-sized pages"
  - at least three worker nodes

  The [Talos page](https://openebs.io/docs/Solutioning/openebs-on-kubernetes-platforms/talos) says nothing about architecture. arm64 images only started building in CI on 2026-09-04 ([mayastor-extensions#1035](https://github.com/openebs/mayastor-extensions/pull/1035)). A 2023 arm64 install bug on Talos is still open ([mayastor#1568](https://github.com/openebs/mayastor/issues/1568)).
- **LocalPV** (Hostpath / LVM / ZFS): node-local storage, the same as the Talos baseline. LocalPV-ZFS needs the `zfs` extension.

## Talos local storage: the non-shared baseline

- A `UserVolumeConfig` (partition, whole disk or directory; "Default is `xfs`") mounted at `/var/mnt/<name>`. Point local-path-provisioner at `/var/mnt/local-path-provisioner` and label its namespace privileged ([local storage](https://docs.siderolabs.com/kubernetes-guides/csi/local-storage)).
- "Local storage is not replicated, so in case of a machine failure contents of the local storage will be lost."
- Removing the volume config keeps the data; `talosctl wipe disk … --drop-partition` erases it.

## Comparison

| Option | Minimum nodes | RAM per node | RWX | Verdict |
|---|---|---|---|---|
| Longhorn v1 | 3 recommended; 2 storage nodes at replica 2 [I] | 4 GiB node minimum; 12 % CPU reserved | yes (share-manager NFSv4) | **best fit** |
| Piraeus / LINSTOR | 3 (2 data + a diskless tiebreaker) | not published (about 0.3–1 GiB per satellite in an old example) | yes (v2.10+, ≥ 3 nodes) | viable; strongest quorum; DRBD tied to the Talos release |
| Talos local / LocalPV | 1 | about 0 | no | baseline, for apps that replicate themselves [I] |
| Rook-Ceph | 3 mons; 3 OSD hosts for size 3 | about 5.5 GiB, +4 GiB for MDS | yes (CephFS) | marginal |
| Longhorn v2 | 3 | +2 GiB huge pages, 1–2 busy cores | yes | no: stuck I/O on arm64 NVMe |
| OpenEBS Mayastor | 3 workers | 1 GiB + 2 GiB huge pages + 2 cores | through NFS | no: x86-64 only in the docs |
