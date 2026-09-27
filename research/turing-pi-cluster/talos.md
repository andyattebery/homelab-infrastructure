# Talos 1.14.1 on the Turing Pi 2: findings and build outline

Researched 2026-09-26. **[I]** marks inference.

Pinned to Talos **v1.14.1** (2026-09-15, [release](https://github.com/siderolabs/talos/releases/tag/v1.14.1)):
- talosctl 1.14.1
- Kubernetes 1.37.0 by default (the support matrix lists 1.33–1.37)
- Linux 6.18.51

Docs are pinned to `docs.siderolabs.com/talos/v1.14/`. The Kubernetes guides under `docs.siderolabs.com/kubernetes-guides/` are unversioned.

## Board support

| Module | Status | Notes |
|---|---|---|
| Turing RK1 | Official: overlay `turingrk1` (`siderolabs/sbc-rockchip` v0.2.1, u-boot 2026.01), listed in the [support matrix](https://docs.siderolabs.com/talos/v1.14/getting-started/support-matrix) | Flash to eMMC with `tpi flash -n <N> -i metal-arm64.raw`, then `tpi power on -n <N>` ([RK1 page](https://docs.siderolabs.com/talos/v1.14/platform-specific-installations/single-board-computers/turing_rk1)). NVMe/USB boot needs the u-boot SPI image on eMMC; Turing: "the bootloader must still be flashed to eMMC because RK3588 SoM does not boot off devices like this" ([Turing RK1 flashing](https://docs.turingpi.com/docs/turing-rk1-flashing-os)). No kernel args are needed. |
| CM4 | `rpi_generic` (`siderolabs/sbc-raspberrypi` v0.2.2), listed in the support matrix | "only been officialy tested on the Raspberry Pi 4 and community tested on one variant of the Compute Module 4 using Super 6C boards". "Changing config.txt on a running system is not supported." ([rpi_generic page](https://docs.siderolabs.com/talos/v1.14/platform-specific-installations/single-board-computers/rpi_generic)) |
| Orin Nano | None | `sbc-jetson` has only `jetson_nano`. The PR "add support for Jetson Orin Nano and AGX Orin SBCs" has been on hold since 2026-02-02; the maintainer leans towards native UEFI ([sbc-jetson#23](https://github.com/siderolabs/sbc-jetson/pull/23)). See [os-alternatives.md](os-alternatives.md). |

### Known issues that apply here

- **v1.14.0 SBC boot.** v1.14.0 broke boot for GRUB-based SBC images ([#14226](https://github.com/siderolabs/talos/issues/14226)); fixed in 1.14.1. Use 1.14.1 or later.
- **mmc boot race** ([#14359](https://github.com/siderolabs/talos/issues/14359)). Nodes booting from mmc intermittently land in maintenance mode: 4/20 boots on a Pi 5, 0/20 on a Pi 4.
  - Workaround: re-run `talosctl apply-config --insecure`.
  - The fix, [#14370](https://github.com/siderolabs/talos/pull/14370), merged to main on 2026-09-16, after 1.14.1. The 1.14 backport is only "Proposed".
  - Impact on RK1/CM4 eMMC is unknown [I].
- **RK1 issue history:**
  - `tpi uart` broke after a patch was dropped; restored on 2025-11-08 (sbc-rockchip #87/#88).
  - v1.10.x upgrades "failed to probe bootloader on upgrade"; closed May 2025.
  - "networking issue on upgrade 1.12.1 => 1.12.2" was closed as not planned, with no root cause found ([sbc-rockchip#105](https://github.com/siderolabs/sbc-rockchip/issues/105), 2026-01-29).
  - SBC overlays ignore `extraKernelArgs` from schematics ([sbc-rockchip#101](https://github.com/siderolabs/sbc-rockchip/issues/101), closed as not planned).
  - u-boot memory holes above 16 GB RAM were fixed upstream in 2024; a 32 GB RK1 cluster ran v1.13.5.
- **CM4:**
  - An open report on a Pi 4 with the same driver: bcmgenet "NETDEV WATCHDOG … transmit queue 1 timed out" (Talos 1.12.2, [sbc-raspberrypi#72](https://github.com/siderolabs/sbc-raspberrypi/issues/72)).
  - On pre-v2.5 boards, Talos on a CM4 in slot 3 failed to boot. v2.5 fixes this.

## Configuration model: 1.14 is multi-document

- **What gen config writes.** `talosctl gen config` writes multi-document config (contract > 1.13, [`contract.go`](https://github.com/siderolabs/talos/blob/v1.14.1/pkg/machinery/config/contract.go)):
  - on every node: `KubeClusterConfig`, `KubeNodeConfig`, `KubeletConfig`, `KubeNetworkConfig`, `KubeAPIServerCAConfig`, `KubePrismConfig`
  - on control planes: also `KubeFlannelCNIConfig`, `KubeProxyConfig`, `KubeAPIServerConfig` and others
  - `HostnameConfig` with `auto: stable`
  - an `UnattendedInstallConfig` when an install disk is given
- **Which document replaces which field** ([document map](https://docs.siderolabs.com/talos/v1.14/reference/configuration/document-map)):

| Document (since) | Replaces |
|---|---|
| HostnameConfig (1.12) | `.machine.network.hostname`, `.machine.features.stableHostname` |
| LinkConfig, ResolverConfig, StaticHostConfig (1.12) | `.machine.network` |
| Layer2VIPConfig, VLAN, Bond, Bridge, DHCPv4 (1.12) | new capability |
| TimeSyncConfig (1.12) | `.machine.time` |
| UserVolumeConfig (1.10) | `.machine.disks` |
| VolumeConfig (1.8 or earlier) | `.machine.systemDiskEncryption` |
| UnattendedInstallConfig (1.14) | `.machine.install` |
| KubeNodeConfig (1.14) | `.cluster.allowSchedulingOnControlPlanes`, node labels, taints, nodeIP |
| KubeProxyConfig (1.14) | `.cluster.proxy` |
| KubeFlannelCNIConfig + KubeNetworkConfig (1.14) | `.cluster.network` |
| KubeAdmissionControlConfig (1.14) | `.cluster.apiServer.admissionControl` |
| DiscoveryIdentityConfig (1.14) | `.cluster.id`, `.cluster.secret` |
| KernelModuleConfig | `machine.kernel.modules` |

- **Still in v1alpha1:** `.machine.type`, `.machine.token`, `.machine.ca`, `.machine.features`, `.cluster.token`, `.cluster.etcd`.

### Traps

- **Legacy plus new fails validation.** Setting a legacy field next to its new document errors, e.g. `".cluster.allowSchedulingOnControlPlanes is already set in v1alpha1 config"`.
- **Hostname.** `HostnameConfig.hostname` and `auto` are mutually exclusive ([reference](https://docs.siderolabs.com/talos/v1.14/reference/configuration/network/hostnameconfig)), so a per-node hostname patch must delete `auto`.
- **Patching** ([patching](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/system-configuration/patching)):
  - To delete a field, write `field:` followed by `$patch: delete`; this works for scalars and maps.
  - `$patch: delete` at document level removes a named document, but not the main v1alpha1 document.
  - "A single patch file cannot modify the same document more than once."
  - Multi-document patches match "by `kind`, `apiVersion` and `name`".
- **`UnattendedInstallConfig`** ([reference](https://docs.siderolabs.com/talos/v1.14/reference/configuration/runtime/unattendedinstallconfig)):
  - `diskSelector.match` is CEL over `disk.dev_path`, `disk.transport` and `disk.serial`.
  - `wipe` "Defaults to `true`".
  - It applies "exclusively to initial installations, not upgrades".
  - gen config's default `--install-disk` is `/dev/sda`, which on a CM4 in slot 3 would be the SATA data disk [I].
- **`KubeNodeConfig`** ([reference](https://docs.siderolabs.com/talos/v1.14/reference/configuration/kubernetes/kubenodeconfig)):
  - Control planes get `node-role.kubernetes.io/control-plane: NoSchedule` unless scheduling is allowed.
  - `taints` is a map.
  - `nodeIP.validSubnets` accepts `!` exclusions, e.g. `'!10.0.0.3/32'`.

### Secret vs committable

- **All four generated files stay secret:**
  - `secrets.yaml` holds everything.
  - `controlplane.yaml` holds the machine CA certificate and key, the Kubernetes CA key, and the tokens.
  - `worker.yaml` holds CA certificates only, but also `MachineToken` and `BootstrapToken`, which makes it a join credential.
  - `talosconfig` holds an admin client certificate.
- **Committable:** patches and schematic YAML. Note that `GET /schematics/:id` returns a schematic to anyone who has the ID.

### Tools around the config

- **talhelper:** archived 2026-08-26. The last release, v3.1.17, is built against `machinery v1.14.0-alpha.2`; its maintainer points to topf or talstomize ([repo](https://github.com/budimanjojo/talhelper)).
- **Omni:** BSL 1.1. "personal use in a home lab environment" counts as non-production ([docs](https://docs.siderolabs.com/omni/self-hosted/production-vs-non-production)). The hosted Hobby plan is $10/month for up to 10 nodes.
- **Terraform** `siderolabs/talos` v0.12.0 (Talos SDK 1.14.0): its state file holds the secrets.

## Image Factory and upgrades

- **IDs for v1.14.1:**
  - overlays: `turingrk1` (`siderolabs/sbc-rockchip`), `rpi_generic` (`siderolabs/sbc-raspberrypi`)
  - extensions: `siderolabs/iscsi-tools`, `siderolabs/util-linux-tools`
  - also listed: `siderolabs/panfrost`, `rockchip-rknn`, `vc4`, `drbd`
- **Create a schematic:** `curl -X POST --data-binary @schematic.yaml https://factory.talos.dev/schematics` returns `{"id":…}`.
- **Disk image:** `https://factory.talos.dev/image/<id>/v1.14.1/metal-arm64.raw.xz`. `tpi flash` needs it decompressed.
- **Installer:** `factory.talos.dev/metal-installer/<id>:v1.14.1`, the "Current form (preferred)"; `factory.talos.dev/installer/…` is the legacy form. "Starting with Talos 1.14, the `ghcr.io/siderolabs/installer` image is no longer published" ([upgrading](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/lifecycle-management/upgrading-talos)).
- **Upgrade trap.** "The `--image` flag defaults to the installer image of the `talosctl` version in use". That default is the empty schematic (`376567988ad…`, [`images.go`](https://github.com/siderolabs/talos/blob/v1.14.1/pkg/images/images.go)), with no overlay and no extensions. Always pass the node's own schematic: `talosctl -n <node> upgrade --image=factory.talos.dev/metal-installer/<id>:<ver>`.
- **Per-node schematics** in one cluster are fine [I]. The docs say "Use the schematic ID of the image the node was installed from", and upgrades run per node.

## Networking

- **DHCP** ([dynamic addressing](https://docs.siderolabs.com/talos/v1.14/networking/configuration/dynamic)).
  - By default Talos runs "a DHCP client on all physical network interfaces".
  - "Once any explicit link configuration is applied, the default DHCP behavior is disabled, and DHCP must be explicitly enabled on the desired link(s)". That means a `DHCPv4Config` with `name: <link>`.
  - The docs don't say whether `Layer2VIPConfig` counts as explicit link configuration, so declare `DHCPv4Config` explicitly.
- **Link selection.** `LinkConfig` selects by `name` only. `LinkAliasConfig` aliases a link by a CEL expression over `mac(link.permanent_addr)` or `link.driver` ([reference](https://docs.siderolabs.com/talos/v1.14/reference/configuration/network/linkaliasconfig)). Whether other documents accept an alias is not documented.
- **VIP** ([VIP](https://docs.siderolabs.com/talos/v1.14/networking/advanced/vip); [reference](https://docs.siderolabs.com/talos/v1.14/reference/configuration/network/layer2vipconfig)): `kind: Layer2VIPConfig`, `name: <ip>`, `link: <link>`.
  - "The controlplane nodes must share a layer 2 network".
  - The election rides on etcd, so "the shared IP will not come alive until after you have bootstrapped Kubernetes".
  - "Don't use the VIP as the `endpoint` in the `talosconfig`".
  - Failover takes "typically up to a minute". Control planes only.
  - The docs don't say whether kubelet node-IP selection skips the VIP. Exclude it with `KubeNodeConfig.nodeIP.validSubnets` [I].
- **Alternative endpoint:** "multiple A or AAAA records, one for each control plane"; "You cannot use a HTTP load balancer" ([production notes](https://docs.siderolabs.com/talos/v1.14/getting-started/prodnotes)). kube-vip is not in the v1.14 docs.
- **KubePrism** "is enabled by default on port 7445", so clients inside the cluster don't depend on the VIP.

## etcd and control planes

- **Disk speed.** "Fast disks are the most critical factor"; slow writes mean "heartbeats may time out and trigger an election" ([etcd 3.7 hardware](https://etcd.io/docs/v3.7/op-guide/hardware/); Talos ships etcd 3.7.1). The Talos docs say nothing about eMMC.
- **Minimum control plane:** 2 GiB RAM, 2 cores, 10 GiB disk.
- **Member count.** 3 members tolerate 1 failure, and 4 still tolerate only 1. So: 3 schedulable control planes on 3 nodes [I].
- **Where etcd lives.** In EPHEMERAL on the system disk. A `VolumeConfig` for `ETCD` (e.g. `disk.transport == 'nvme' && !system_disk`) can move it, but "The backing type is permanent — it is chosen when the volume is first provisioned" ([system disk](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/storage-and-disk-management/disk-management/system)).
- **etcd peer URLs are fixed when a member joins** [I]. So node IPs must be final before bootstrap.

## Pod Security, CNI

- **Pod Security defaults:** `enforce: baseline`, `audit` and `warn: restricted`, `kube-system` exempt (a `KubeAdmissionControlConfig` named `PodSecurity`). Longhorn and Rook namespaces need `enforce=privileged`.
- **Flannel** is the default. `kubeNetworkPoliciesEnabled` adds kube-network-policies.
- **Cilium** ([guide](https://docs.siderolabs.com/kubernetes-guides/cni/deploying-cilium)):
  - delete `KubeFlannelCNIConfig`, and set `KubeProxyConfig` `enabled: false`
  - Helm: `k8sServiceHost=localhost`, `k8sServicePort=7445`, `cgroup.autoMount.enabled=false`, `cgroup.hostRoot=/sys/fs/cgroup`
  - Bootstrap stalls at phase 18/19 until a CNI exists.

## Wiping and rebuilding

- **`talosctl reset`** flags ([`reset.go`](https://github.com/siderolabs/talos/blob/v1.14.1/cmd/talosctl/cmd/talos/reset.go)):
  - `--graceful`, default true: cordon, drain, leave etcd
  - `--reboot`
  - `--system-labels-to-wipe`
  - `--wipe-mode all|system-disk|user-disks`
  - `--user-disks-to-wipe`
- **The default wipes the whole system disk.** On an eMMC-booted board that means re-flashing [I].
- **User volumes on other disks** survive a default reset, and re-provision on the same disk when the config is re-applied [I]. Erase them with `talosctl wipe disk <partition> --drop-partition`.
- **Old installs.** An old install can't rejoin a cluster built from fresh secrets. Wipe any disk that might still hold an old STATE partition [I].

## Tooling (macOS)

| Tool | Homebrew | mise | Note |
|---|---|---|---|
| talosctl | `talosctl` (core), or `siderolabs/tap/talosctl` after `brew trust siderolabs/tap` (tap trust arrived in Homebrew 6.0.0) | `talosctl` → `aqua:siderolabs/talos` | must match the Talos version |
| kubectl | `kubernetes-cli` (1.37.1) | `aqua:kubernetes/kubernetes/kubectl` | the local 1.33.9 is out of skew |
| helm | `helm` (4.3.0) | `aqua:helm/helm` | |
| tpi | — | `github:turing-machines/tpi`; release `1.0.7` ships `tpi-aarch64-apple-darwin.tar.gz` | reads `TPI_HOSTNAME`, `TPI_USERNAME`, `TPI_PASSWORD`; otherwise prompts or uses a cached token |

- **`tpi` commands** ([`cli.rs`](https://github.com/turing-machines/tpi)):
  - `flash` takes `--node 1-4`, `--image-path`, `--local`, `--sha256`, `--skip-crc`.
  - `power` takes `on|off|reset|status`.
  - `usb flash` puts a module into flashing mode.
  - Flashing an RK1 takes "about 8 minutes for each 1 GB of the image file".
- **BMC firmware:** GitHub marks v2.1.0 as latest (2025-02-05, "breaking change of network configuration"). firmware.turingpi.com lists up to v2.0.5.

## Build outline for option 1 (not started; pending the OS decision)

| Slot | Host | IP | Role | Data disk |
|---|---|---|---|---|
| 1 | `turingpi-rk1-01` | 192.168.1.216 | control plane | 960 PRO 512 GB NVMe |
| 2 | `turingpi-rk1-02` | 192.168.1.217 | control plane | 970 EVO 500 GB NVMe |
| 3 | `turingpi-cm4-01` | 192.168.1.218 | control plane | 860 EVO 1 TB SATA |
| — | `turingpi-k8s` | 192.168.1.220 | API VIP | — |
| BMC | `turingpi` | 192.168.1.215 | — | — |

Addresses: see [ops-findings.md](ops-findings.md).

**Design.**
- **Config generation.** Plain talosctl.
  - `gen secrets` once; the bundle is kept as a 1Password Document.
  - `gen config --with-secrets` with an all-nodes patch and a control-plane patch.
  - `machineconfig patch` per node.
  - Everything generated stays in a gitignored directory.
- **All nodes:** `UnattendedInstallConfig` pinned to the eMMC by CEL, so the `/dev/sda` default can never target the CM4's SATA disk. Confirm the transport string first with `talosctl get disks --insecure`.
- **Control planes:**
  - delete the `KubeNodeConfig` taint
  - `nodeIP.validSubnets: [192.168.1.0/24, "!192.168.1.220/32"]`
- **Per node:**
  - `HostnameConfig`: delete `auto`, set the inventory name.
  - `DHCPv4Config` + `Layer2VIPConfig` on the link name read in maintenance mode.
  - `UserVolumeConfig` `longhorn`, selected by the data disk's serial.
- **Fixed IPs** come from UniFi reservations through NIM. Set them while the nodes sit in maintenance mode, before bootstrap.
- **Platform choices:** etcd stays on the eMMC; Flannel; Longhorn 1.12.1 v1 at replica count 2. Install Longhorn only after all three `u-longhorn` volumes report ready.
- **Tools** are pinned per directory with mise. `TALOSCONFIG`, `KUBECONFIG` and helm's homes point inside the repo.

**Order:**
1. Flash.
2. Set the reservations.
3. Read link names and disk serials.
4. Generate.
5. Apply.
6. Bootstrap one node.
7. Wipe the data disks by serial.
8. Install Longhorn.
9. Verify:
   - health checks
   - VIP failover, by powering off the VIP holder
   - an RWO/RWX smoke test
   - a node-down test, which must show the volume degraded before it recovers
