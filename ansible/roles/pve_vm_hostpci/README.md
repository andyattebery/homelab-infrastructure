# pve_vm_hostpci

Owns the `hostpciN` lines of declared Proxmox VMs, mapping-based only (`hostpciN: mapping=<id>`).
Companion to `pve_pci_mapping`, which owns the mappings those ids refer to; run it after that role.

## Status: Production

## Inputs

### `pve_vm_hostpci_vms` (required, no default)

```yaml
pve_vm_hostpci_vms:
  - vmid: 200
    hostpci:
      - { index: 0, mapping: broadcom_9305_24i, rombar: 0 }
      - { index: 1, mapping: solidigm_p44_pro_1 }
      - { index: 6, mapping: intel_p1600x_1, state: absent }
  - vmid: 201
    hostpci:
      - { index: 0, mapping: nvidia_rtx_a4000, pcie: 1 }
```

| key | meaning | if wrong |
| --- | --- | --- |
| `vmid` | the VM, on this node | `qm config` fails and so does the run |
| `index` | the N in `hostpciN`, 0–15, unique per VM | validation fails before anything runs |
| `mapping` | id of a PCI resource mapping | must exist, name this node, and pass PVE's `--check-node`; otherwise the run fails naming it, before any write |
| `pcie`, `rombar` | `0`/`1`, optional | — |
| `state` | `present` (default) or `absent` | — |

**The desired line is exactly the keys given.** An option present on the VM but not declared
(`rombar=0` when the declaration has none) is a difference and is removed by the `qm set`. PVE's
defaults are `pcie=0`, `rombar=1` (`qm.conf.5`). Option order on the VM does not matter; lines
are compared as parsed key/value pairs.

Not defaulted in `defaults/main.yaml` for the reason given in `pve_pci_mapping/README.md`; gate
with `when: pve_vm_hostpci_vms | default([]) | length > 0`.

### `pve_vm_hostpci_node`, `pve_vm_hostpci_qm_command`, `pve_vm_hostpci_pvesh_command`

Defaults `{{ ansible_facts['hostname'] }}`, `/usr/sbin/qm`, `/usr/bin/pvesh`. Overridable for the
fixture test.

## What a run does

1. Validates the declaration.
2. `pvesh get /cluster/mapping/pci --check-node <node>`: every mapping a present line refers to
   must exist, carry a `map` entry for this node, and have no `checks`. Any other case **fails the
   run before any write**, naming the mapping and why. This is the ordering dependency on
   `pve_pci_mapping`.
3. Per VM, `qm config <vmid>` — PVE's default output, which has pending changes applied, so a
   change queued by an earlier run compares as current and is not re-issued.
   - A `hostpciN` line whose value names a PCI address rather than a mapping fails the run: the
     role manages mapping-based lines only.
   - A `hostpciN` line on a declared VM that the declaration does not mention **fails the run**.
     Declare it, with `state: absent` if it should go.
4. `qm set <vmid> --hostpciN mapping=<id>[,pcie=..][,rombar=..]` where missing or different;
   `qm set <vmid> --delete hostpciN` for `state: absent`.
5. `qm pending <vmid>`: a `new hostpci…` or `del hostpci…` line means the VM is running and the
   change lands at the next stop/start. Those vmids are collected in
   `pve_vm_hostpci_restart_required` and reported. **The role never restarts a VM.**

A VM locked by a running backup makes `qm set` fail; the role reports that and does not retry.

## Sets

### `pve_vm_hostpci_restart_required`

List of vmids with a pending hostpci change. Always defined after the role runs (`[]` when none).

## Playbook

```yaml
- name: Configure VM hostpci lines
  when: pve_vm_hostpci_vms | default([]) | length > 0
  tags: pci_passthrough
  ansible.builtin.import_role:
    name: pve_vm_hostpci
```

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_vm_hostpci/tests/inventory roles/pve_vm_hostpci/tests/test.yml
```

Runs the real role against a stub `qm` (`tests/stub-qm.py`, which applies writes to a per-VM
config file, or queues them as pending when the VM is marked running, and prints `qm config`
and `qm pending` the way PVE does) plus the sibling role's stub `pvesh` and fake sysfs tree.
Cases: converge two stopped VMs (re-point, add, strip an undeclared option, leave a reordered
line alone); second run is a no-op; a running VM's change is pending and reported, and a re-run
stays quiet but still reports it; `state: absent` deletes; an undeclared line fails; a missing,
foreign or PVE-rejected mapping fails before any write; a raw-address line fails. Localhost only,
nothing left behind.
