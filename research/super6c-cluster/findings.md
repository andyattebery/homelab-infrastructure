# Findings: Talos on the Super6C (CM4 Lite + PM991)

Researched 2026-09-26. Quotes are verbatim. **[I]** marks inference. Kernel-config and source lines were grepped from the raw files; they are not summaries.

## Talos on the CM4

- **Support statement.** The Talos v1.14 `rpi_generic` page: "only been officialy tested on the Raspberry Pi 4 and community tested on one variant of the Compute Module 4 using Super 6C boards" ([page](https://docs.siderolabs.com/talos/v1.14/platform-specific-installations/single-board-computers/rpi_generic)).
- **Kernel.** Talos v1.14.1 pins `siderolabs/pkgs@f694e1b`, identical to `release-1.14` (Linux 6.18.51). From [`kernel/build/config-arm64`](https://github.com/siderolabs/pkgs/blob/release-1.14/kernel/build/config-arm64):

  | Symbol | Value | Line | What it is |
  |---|---|---|---|
  | `CONFIG_PCIE_BRCMSTB` | `y` | 2007 | BCM2711 PCIe controller, the CM4's single lane |
  | `CONFIG_RASPBERRYPI_FIRMWARE` | `y` | 2233 | firmware mailbox |
  | `CONFIG_NVME_CORE` | `y` | 2457 | NVMe core |
  | `CONFIG_BLK_DEV_NVME` | `m` | 2458 | NVMe block driver |
  | `CONFIG_BCMGENET` | `y` | 2951 | CM4 Ethernet MAC |
  | `CONFIG_BROADCOM_PHY` | `y` | 3307 | CM4 Ethernet PHY |
  | `CONFIG_MMC_SDHCI_IPROC` | `m` | 7037 | SD controller |

- **Base image modules.** From [`talos@v1.14.1` `hack/modules-arm64.txt`](https://github.com/siderolabs/talos/blob/v1.14.1/hack/modules-arm64.txt): `sdhci-iproc.ko` (L110, the `MMC_SDHCI_IPROC` SD driver) and `nvme.ko` (L210). Both drivers are therefore available without an extension.
- **Not needed here:** the Pi's H.264/HEVC codecs are absent under Talos, and the GPU needs the `vc4` extension. Per-feature detail: [../turing-pi-cluster/hardware-support.md](../turing-pi-cluster/hardware-support.md).

## NVMe boot: possible, not used

- **Talos patches U-Boot for NVMe.** [`siderolabs/sbc-raspberrypi@v0.2.2`](https://github.com/siderolabs/sbc-raspberrypi/tree/v0.2.2/artifacts/u-boot) builds U-Boot from `rpi_arm64_defconfig` (`pkg.yaml` L22, L32) and patches it:
  - `0002-rpi-add-NVMe-to-boot-order.patch` (Stefan Agner, 2020-12-29): `boot_targets=mmc nvme usb pxe dhcp`
  - `0008-enable-nvme-and-fixup-efi-boot.patch` (Tom Plant, 2023-12-03): `CONFIG_NVME=y`, `CONFIG_NVME_PCI=y`, `CONFIG_CMD_NVME=y`, `CONFIG_BOOTMETH_EFILOADER=y`
  - `0003` and `0005`–`0007`: NVMe PRP and bus-address fixes
- **Stock U-Boot doesn't.** Stock `rpi_arm64_defconfig` "has no NVMe" ([../pi-rack-boot-drive/cm4-path.md](../pi-rack-boot-drive/cm4-path.md), L90).
- **What NVMe boot would need.** An EEPROM new enough for NVMe boot mode 6 (stable for CM4 since 2021-07-07), with NVMe in `BOOT_ORDER`, e.g. `0xf6` or `0xf46` ([../pi-rack-boot-drive/cm4-path.md](../pi-rack-boot-drive/cm4-path.md), L44–47).
- **U-Boot's `boot_targets` lists `mmc` before `nvme`** (patch 0002). So once U-Boot runs, an SD card in the slot is tried before NVMe [I].

## Super6C

From the [DeskPi-Team/super6c README](https://github.com/DeskPi-Team/super6c) (line numbers from that file):

| Item | Quote / fact | Line |
|---|---|---|
| Switch | "interconnected through the gigabit switch chip RTL8370N" | 37 |
| Uplinks | "Full-speed gigabit external network interface*2" | 39 |
| USB | main module micro USB 2.0 (42); "Slave module MICRO USB2.0 master-slave device interface*5" (45) | 42, 45 |
| Fans | "DC12V fan interface *3"; per-module "5V FAN Header" | 51, 70 |
| Power / reset | "The total power switch button of the whole board"; "Total reset button for all modules" | 52, 53 |
| microSD | "Full module Micro SD card slot, used to support non-eMMC version of CM4 *6" | 55 |
| M.2 | "Full module M.2 2280 M-KEY interface socket *6"; "M.2 2280 slot (PCIe Gen 2 x1)" | 56, 68 |
| Input | "DC 19v~24V or ATX 12V"; "Max. 24V/6.15A" | 64, 203 |

- **No per-node power control** [I, from 52–53]. A node shut down with `talosctl shutdown` comes back only with a board reset.
- The README's "Fit for CM4 Lite version" section (from L181) covers booting Lite modules from the TF card.
- Per-CM4 jumper functions are in the image `assets/CM4_Jumpers.png` (L109). Not read.

## Talos volumes

From the Talos v1.14 docs.

- **Capping EPHEMERAL** ([system volumes](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/storage-and-disk-management/disk-management/system)):
  - example: `kind: VolumeConfig`, `name: EPHEMERAL`, `provisioning: maxSize: 40GiB`
  - "The volume configuration in the machine configuration is only applied when the volume has not been provisioned yet. So applying changes after the initial provisioning will not have any effect."
- **Moving EPHEMERAL off the boot disk** uses `diskSelector: match: disk.transport == 'nvme' && !system_disk`. The 2026-09-26 research agent reported this from the same page; it was not re-fetched verbatim.
- **User volumes** ([user volumes](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/storage-and-disk-management/disk-management/user)):
  - mounted at `/var/mnt/<volume-name>`, with the label `u-<volume-name>`
  - `minSize` is the free space required before provisioning, and `maxSize` caps the volume. This is paraphrased from the page, via a summarizing fetch; not verbatim.
  - partition is the default type
  - after the config is removed, the data stays on the disk until it is wiped with `talosctl wipe disk`. Also paraphrased.
- **Upgrade path** ([upgrading](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/lifecycle-management/upgrading-talos)): "The recommended upgrade path is to always upgrade to the latest patch release of all intermediate minor releases". So 1.8 → 1.14 would be 1.9, 1.10, 1.11, 1.12, 1.13, then 1.14.

## Secrets bundle and 1Password

- **Bundle schema.** `talosctl gen secrets` writes the bundle defined in [`talos@v1.14.1` `pkg/machinery/config/generate/secrets/secrets.go`](https://github.com/siderolabs/talos/blob/v1.14.1/pkg/machinery/config/generate/secrets/secrets.go) (L21–60). YAML keys are the lowercased Go field names [I: the go-yaml default; the structs carry no yaml name tags, only `yaml:",omitempty"` on the two encryption secrets].
  - The structs: `Cluster{ID, Secret}`, `Secrets{BootstrapToken, AESCBCEncryptionSecret (omitempty), SecretboxEncryptionSecret (omitempty)}`, `TrustdInfo{Token}`, and `Certs{Etcd, K8s, K8sAggregator, OS}` (each a cert and key) plus `K8sServiceAccount` (key only).
  - The code comment: "Certs holds the base64 encoded keys and certificates."
- **Bundle → `pi-cluster` item** (vault `Home Lab`, section `talos`):

  | Bundle path | Item field |
  |---|---|
  | `cluster.id`, `cluster.secret` | `cluster id`, `cluster secret` |
  | `secrets.bootstraptoken` | `bootstrap token` |
  | `secrets.secretboxencryptionsecret` | `secretbox encryption secret` |
  | `trustdinfo.token` | `trustd token` |
  | `certs.etcd.crt`, `certs.etcd.key` | `etcd crt`, `etcd key` |
  | `certs.k8s.crt`, `certs.k8s.key` | `k8s crt`, `k8s key` |
  | `certs.k8saggregator.crt`, `certs.k8saggregator.key` | `k8s aggregator crt`, `k8s aggregator key` |
  | `certs.k8sserviceaccount.key` | `k8s service account key` |
  | `certs.os.crt`, `certs.os.key` | `os crt`, `os key` |

  The same item's `mac address` section holds `pi-cluster-01` … `pi-cluster-06`. The owner filled these in on 2026-09-26.
- **Only the MAC is per-host.** Machine configs are generated from the bundle plus committed patches. Node certificates are issued by Talos from the cluster CAs. Talos has no SSH or host passwords.
- **op CLI 2.39.0** (local `op --help`): `op item create [ - ]` reads an item JSON from stdin, and `op item edit … --template` updates an item from a JSON file. So secret values never need to go on the command line.

## Known issues

- **[siderolabs/talos#14359](https://github.com/siderolabs/talos/issues/14359):** "nodes booting from an SD card (SDHCI/mmc) intermittently land in maintenance mode". The reporter measured 4 of 20 boots on a Pi 5 and 0 of 20 on a Pi 4; the CM4 is the Pi 4's SoC.
  - Workaround: `talosctl apply-config --insecure`.
  - The fix, [#14370](https://github.com/siderolabs/talos/pull/14370), merged to `main` on 2026-09-16, after v1.14.1 (2026-09-15). Its 1.14 backport was "Proposed".
- **[sbc-raspberrypi#72](https://github.com/siderolabs/sbc-raspberrypi/issues/72):** bcmgenet "NETDEV WATCHDOG … transmit queue 1 timed out" on a Pi 4 with Talos 1.12.2 (2026-01-25). Open. It uses the same driver as the CM4. A 2026-05-24 comment says the kernel fix "is included in 6.18.33"; Talos 1.14.1 runs `6.18.51-talos`.
- **PM991 hangs with APST on (found building this cluster, 2026-09-26).**
  - Node 1's drive hung about 30 s after etcd bootstrap and the node boot-looped. Its console: `[   36.228167] nvme nvme0: Device not ready; aborting reset, CSTS=0x1`. Node 4's drive hung with only the kubelet running; after the node rebooted, its kernel log showed `brcm-pcie fd500000.pcie: link down`, so no NVMe.
  - The drives' PCI ID is `144d:a809`. Linux v6.18 `drivers/nvme/host/pci.c` L3874 has a quirk for it (`/* Samsung MZALQ256HBJD 256G */`), but only `NVME_QUIRK_DISABLE_WRITE_ZEROES`, no APST quirk. On the healthy nodes `pm_qos_latency_tolerance_us` was 100000 (APST on), and the link exposes no `l0s_aspm`/`l1_aspm` controls, so ASPM is not in play.
  - The Arch wiki, "Controller failure due to broken APST support" ([page](https://wiki.archlinux.org/title/Solid_state_drive/NVMe#Controller_failure_due_to_broken_APST_support)), quotes the same `Device not ready; aborting reset, CSTS=0x1` and says a failure "renders the device unusable until system reset"; its workaround is `nvme_core.default_ps_max_latency_us=0`.
  - That argument is now in the schematic. With it, bootstrap, the Longhorn install, the smoke test and two node reboots ran with 0 NVMe error lines on all six (watched every 30 s for 15 min).
  - A hung drive stayed hung through CM4 reboots and came back after a board power cycle: the M.2 slot's power comes from the carrier [I]. Drive temperatures: 36–41 °C idle without a fan; 23–47 °C with a fan through the install. The hung drive was the hottest by touch, most likely from hanging rather than as its cause [I].
- **Upgrade can revert to the old slot.** Upgrading to the new schematic, node 3 came back on its old boot slot twice (META key 6, the previous slot, gone) and took on the third attempt; the other five took first time. The failed boots left no log [I: possibly the mmc race above].

## Network inventory manager

- **Reservations.** NIM writes a UniFi DHCP reservation only for inventory entries with a `mac` and no `skip_dhcp` (`network-inventory-manager/network_inventory_manager/sync.py` L92–96; user guide L48: "A DHCP reservation in UniFi (if `mac` is present and `skip_dhcp` is not `true`)"). Entries without a MAC get only a DNS rewrite and a client entry.
- **Where it reads the inventory.** From GitHub (`nix/hosts/network-01/default.nix` L127), every 1800 s. A change applies only after it is pushed.
- **Forcing a sync.** `POST /sync` on port 8090 forces one (owner). Use network-01's IP, `http://192.168.1.224:8090/sync`, so the command carries no domain name.
- **No deletions.** The UniFi output "only creates and updates reservations and never deletes" (NIM user guide).
- **Stale README.** `ansible/roles/docker_compose_network_inventory_manager/README.md` still says reservations go to AdGuard.

## Repo leftovers

These came from the old Ubuntu/k3s version of this cluster. They were removed on 2026-09-27 (owner's call):
- `ansible/playbook-pi-cluster.yaml`: k3s install; mounted an existing `/dev/nvme0n1p1` as the k3s data dir. That fits the 8.6 GB ext4 partition labelled `k3s` found on five of the six PM991s when the build started [I].
- `ansible/files/pi-cluster/manifests/traefik-config.yaml`: a k3s `HelmChartConfig` for its bundled Traefik; nothing referenced it.
- `ansible/host_vars/pi-cluster-0[1-6].yaml`: `ansible_become_password` per host.
- The six password variables and their vault references in `ansible/group_vars/all/vars.yaml` and `ansible/group_vars/all/vault.yaml.tpl`. The 1Password items they pointed at (`pi-cluster-01` … `pi-cluster-06`) are no longer referenced by the repo.
- The commented `[pi_cluster]` group in `ansible/inventory.ini`.
