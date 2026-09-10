# pve_pci_mapping

Owns a Proxmox node's PCI resource mappings (`/etc/pve/mapping/pci.cfg`, the cluster-wide
mappings that `hostpciN: mapping=<id>` refers to). Each mapping is declared by where the device
sits in the PCIe tree rather than by its bus address, and the role resolves that position to the
current address and IOMMU group on every run.

## Status: Production

## Why topology

A PCI address (`0000:46:00.0`) is a bus number, and bus numbers are assigned at POST in
enumeration order. When a device appears or disappears upstream — an onboard NIC that a BIOS
setting hides on some boots and not others did this on the node this role was written for; see
the node's file under `hardware/` — every bus behind it renumbers and every IOMMU group
after it shifts. A mapping records address, ids and group, and PVE refuses to start the VM when any
of them stops matching. That refusal is the right behaviour (the address may now hold the host's
own NIC or its BMC's VGA); what was missing was anything that re-points the mapping.

Root-port and downstream-port `device.function` numbers are fixed by the silicon and the card, so
the chain of them from the root bus down names a physical position that survives renumbering.
That chain is the `topology`:

    0000:40/03.3/00.0             root bus 40 → root port 03.3 → endpoint 00.0
    0000:c0/01.1/00.0/01.0/00.0   root bus c0 → root port 01.1 → switch upstream 00.0
                                  → switch downstream 01.0 → endpoint 00.0

Read it from the host with `readlink -f /sys/bus/pci/devices/<addr>` and drop the bus numbers.

Serials were considered and rejected: a passed-through NVMe is bound to `vfio-pci`, which exposes
no `nvme/*/serial`, and PVE never rebinds it after the VM stops. The topology is readable in every
state.

## Inputs

### `pve_pci_mapping_mappings` (required, no default)

```yaml
pve_pci_mapping_mappings:
  - { id: intel_p1600x_1, topology: "0000:40/03.3/00.0", pci_id: "8086:2525", subsystem_id: "8086:380a" }
  - { id: nvidia_rtx_a4000, topology: "0000:00/01.1/00.0", pci_id: "10de:24b0", subsystem_id: "1028:14ad" }
  - { id: broadcom_9305_24e, topology: "0000:80/03.1/00.0", pci_id: "1000:00c4", subsystem_id: "1000:31a0", state: absent }
```

| key | meaning | if wrong |
| --- | --- | --- |
| `id` | PVE mapping id, `^[a-zA-Z][a-zA-Z0-9_-]+$` | validation fails before anything runs |
| `topology` | position as above | the resolver fails naming the hop that did not match exactly one device |
| `pci_id` | `vendor:device` the device at that position must report | the run fails before any write, naming what is actually there |
| `subsystem_id` | `subvendor:subdevice` it must report | same |
| `state` | `present` (default) or `absent` | — |

The list is deliberately not defaulted in `defaults/main.yaml`: an imported role's defaults are
visible to the task-level `when`, so a playbook gate of `when: pve_pci_mapping_mappings is
defined` would never skip (verified against ansible-core 2.21.3). Gate with
`when: pve_pci_mapping_mappings | default([]) | length > 0`; the role asserts the list is
non-empty.

### `pve_pci_mapping_node`

Default `{{ ansible_facts['hostname'] }}`. The node whose entries the role owns; only mappings
with a `map` element naming it are touched.

### `pve_pci_mapping_pvesh_command`, `pve_pci_mapping_sysfs_root`, `pve_pci_mapping_resolver_path`, `pve_pci_mapping_vm_config_root`

Defaults `/usr/bin/pvesh`, `/sys`, `/usr/local/sbin/resolve-pci-topology`, `/etc/pve/nodes`.
Overridable so the fixture test can run against a stub and a fake tree.

## What a run does

1. Validates the declaration, deploys `files/resolve_pci_topology.py`, resolves every `present`
   topology in one call.
2. **Asserts `pci_id`/`subsystem_id` against the device found.** PVE's start-time identity check,
   moved to before the write. A mismatch stops the play for this host with nothing written.
3. Reads `pvesh get /cluster/mapping/pci`. A mapping on this node that the declaration does not
   mention **fails the run** — the role owns every entry on the node; declare it, with
   `state: absent` if it should go. A mapping whose `map` names more than one node is out of
   scope and also fails.
4. `pvesh create` for a declared mapping that does not exist, `pvesh set --map` for one whose
   `node/path/id/subsystem-id/iommugroup` differ (compared as parsed key/value pairs, not as
   strings).
5. `pvesh delete` for `state: absent`, **guarded**: every `*.conf` under
   `pve_pci_mapping_vm_config_root` is searched line by line for `hostpciN: … mapping=<id>`.
   A hit anywhere — the main section, `[PENDING]`, or a snapshot section — refuses the delete and
   names the file. A snapshot rollback would otherwise resurrect a reference to a mapping that no
   longer exists. The pattern is anchored, so `intel_arc_b580` does not match
   `intel_arc_b580_audio`.
6. Runs PVE's own validator, `pvesh get /cluster/mapping/pci --check-node <node>`, and fails if
   any declared mapping carries a `checks` entry.

The role never starts or stops a VM and never edits `pci.cfg` directly. Every refusal above is a
failed task: the play stops for the host and nothing after it in the playbook runs.

## Renaming a mapping

There is no rename API. Declare the new id (same topology), re-point the VM's `hostpciN` to it
(`pve_vm_hostpci` does that; on a stopped VM it is immediate, on a running one it lands at the
next stop/start), then flip the old id to `state: absent`. The guard refuses the delete until
no config section references the old name any more.

## Playbook

```yaml
- name: Configure PCI resource mappings for this node
  when: pve_pci_mapping_mappings | default([]) | length > 0
  tags: pci_passthrough
  ansible.builtin.import_role:
    name: pve_pci_mapping
```

## Tests

```sh
cd ansible
.venv/bin/pytest roles/pve_pci_mapping/tests/ -q
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_pci_mapping/tests/inventory roles/pve_pci_mapping/tests/test.yml
```

The pytest covers the resolver against two fake sysfs trees recorded from a real node's kernel
log (`tests/fake_sysfs.py`): the 2026-08-31 layout with the X550 hidden and the 2026-08-28 layout
with it present. The fixture playbook runs the real role against a stub `pvesh` that applies
writes to a JSON state file and reproduces PVE's `--check-node` validation against the tree.
Cases: create the missing mapping; re-point the three that moved after the flip; second run is
a no-op; wrong `pci_id` refuses before writing; unlisted mapping fails; absent-but-referenced
refuses for a main-section, `[PENDING]`-only and snapshot-only reference; absent-unreferenced
deletes; a prefix id is not a reference; a multi-node mapping fails. Localhost only, nothing
left behind.
