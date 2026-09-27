# Super6C Talos cluster research (2026-09-26)

The DeskPi Super6C holds six Raspberry Pi CM4 8 GB **Lite** modules, which have no eMMC, and six Samsung PM991 256 GB NVMe drives. The questions:
- Can it run a Talos cluster that boots from microSD?
- Can the M.2 drives provide new shared cluster storage?
- Is there a hardware blocker?

This folder is the record. It supersedes the Turing Pi 2 plan in [../turing-pi-cluster/](../turing-pi-cluster/README.md), whose Talos 1.14 and Longhorn findings carry over.

**Bottom line: no hardware blocker.** Talos 1.14.1 runs everything this cluster needs on the CM4: CPU, SD boot, NVMe as a data disk, and Ethernet.
- What Talos lacks on the CM4 is the Pi's H.264/HEVC codecs, and a GPU without an extension. Neither matters for a compute and storage lab.
- Talos's own docs name this carrier: "community tested on one variant of the Compute Module 4 using Super 6C boards".

**Status: built 2026-09-27.** The design below was agreed on 2026-09-26; the runbook, verification and traps are in [talos/README.md](../../talos/README.md). The build found one thing the research missed: the PM991s hang with NVMe power saving (APST) on, so the schematic turns it off ([findings.md](findings.md#known-issues)).

## Hardware

| Part | Detail |
|---|---|
| Board | DeskPi Super6C: six CM4 slots, each with its own microSD slot, one M.2 2280 M-key slot at PCIe Gen2 x1, and a micro-USB port. RTL8370N gigabit switch with 2 external RJ45. 19–24 V DC or ATX 12 V. Power and reset for the whole board only [I]. |
| Modules | 6× CM4 8 GB Lite. They boot from the microSD in their slot. |
| Drives | 6× Samsung PM991 256 GB NVMe (256,060,514,304 bytes), one per node: "PM991a" / "PM991" on 01–03, `MZALQ256HAJD-000L1` on 04–06 (the 2242 part [I], on extenders). DRAM-less, no power-loss protection [I]. Previously data disks only; never had Talos (owner). |

## Conclusions

### Talos covers the CM4's core hardware

- The CM4 PCIe controller, NVMe, Ethernet PHY and SD controller are all in the Talos 1.14 kernel, and `nvme.ko` ships in the base image. Details: [findings.md](findings.md#talos-on-the-cm4).
- Codec and GPU gaps are covered in [../turing-pi-cluster/hardware-support.md](../turing-pi-cluster/hardware-support.md).

### Boot from microSD; the PM991 carries EPHEMERAL and the Longhorn volume

- **SD:** the card holds only Talos's system partitions (EFI, BOOT, META, STATE).
- **PM991:** EPHEMERAL (etcd, container images, logs) is capped at 40 GiB and moved onto the NVMe; a Longhorn user volume takes the rest (~198 GiB). On the SD, etcd's writes would wear the card out and be slow.
- **The cap only applies at first provisioning.** Talos applies a volume config "only … when the volume has not been provisioned yet" ([findings.md](findings.md#talos-volumes)).
- **NVMe boot would also work,** but it isn't used. Talos's Pi U-Boot is patched for NVMe, unlike stock U-Boot ([findings.md](findings.md#nvme-boot-possible-not-used)).

### Storage: Longhorn v1 over Ceph

- **Longhorn 1.12.1** (v1 engine, replica count 2) on all six nodes. A CM4 meets Longhorn's 4-core / 4 GiB node minimum.
- **Rook-Ceph** wants about 4 GiB per OSD plus 1–2 GiB per mon. Three of these 8 GB nodes also run etcd and the API server.
- **Rook's Kubernetes support is in doubt:** Talos's Rook guide lists Rook 1.20 as supporting Kubernetes only through 1.36.
- Figures and sources: [../turing-pi-cluster/storage.md](../turing-pi-cluster/storage.md).

### Cluster layout

- 3 control planes (`pi-cluster-01..03`) and 3 workers (`04..06`), all schedulable. Flannel.
- **Fixed IPs `192.168.1.181–186`** come from UniFi reservations written by the network inventory manager (NIM) from `network-inventory/network_hosts_inventory.yaml.tpl`. The API VIP is `192.168.1.187`.
- The DNS VIP and the MACs are vaulted, so a static-address Talos patch (which needs nameservers) can't be committed.
- NIM details: [findings.md](findings.md#network-inventory-manager).

### Secrets: one 1Password item

- The `pi-cluster` item in the `Home Lab` vault holds everything:
  - section `mac address`: one field per node
  - section `talos`: the 14 values of Talos's secrets bundle
- A committed template renders the bundle with one `op inject`.
- Schema and field map: [findings.md](findings.md#secrets-bundle-and-1password).

### Reinstall by re-flashing the SD cards

- The cards still carry a Talos 1.8 install from a Feb 2026 attempt on this board.
- Talos upgrades must step "to the latest patch release of all intermediate minor releases", so moving 1.8 → 1.14 in place would take six upgrades per node.
- Re-flashing each card on the Mac is simpler, and it removes the old install, and with it the old PKI, from the nodes.

## Open questions

- **mmc boot race** (siderolabs/talos#14359): SD-booted nodes can land in maintenance mode after a reboot. Is the fix (#14370) in a 1.14.x release yet? Its 1.14 backport was "Proposed" on 2026-09-26. Not seen on plain reboots during the build, but one node's upgrade reverted to the old boot slot twice, cause not captured ([findings.md](findings.md#known-issues)).

## Files

| File | What's in it |
|---|---|
| [findings.md](findings.md) | Sourced facts: Talos kernel and base-image modules for the CM4, the U-Boot NVMe patches, Super6C specs, Talos volume and upgrade rules, the secrets bundle schema and 1Password layout, known issues, NIM behaviour, repo leftovers |
