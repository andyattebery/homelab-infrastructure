# debian_add_network_interface

Configures one NIC on an ifupdown host through a drop-in under
`/etc/network/interfaces.d/`, resolving the interface by MAC so the playbook never hardcodes
a name, and applies it immediately with `ifreload -a`. One invocation per interface.

## Status: Production

## Contract

- **Requires:** the NIC's **final** name is live — `pve_pin_network_interface` has run and any
  reboot it asked for has happened. Structural check: the role refuses to run while
  `/etc/network/interfaces.new` exists (a staged rename, or an unapplied GUI edit — it cannot
  know what that file says). Also requires `/etc/network/interfaces` to exist (ifupdown, not
  netplan/NetworkManager).
- **Owns:** `interfaces.d/<filename>.cfg`; the `source /etc/network/interfaces.d/*` line in the
  main file; and the removal of the bare `iface <nic> inet manual` stanza the installer wrote
  for this NIC, which the drop-in shadows.
- **Guarantees:** when the role returns, the interface is configured as declared and
  `ifreload -a` has run, so later tasks in the same play can use it.
- **Never:** touches an interface it was not given; rewrites a stanza that has options (it
  fails and says so); removes a stanza that another interface names as its `bridge-ports`,
  `bond-slaves` or `vlan-raw-device`.

In `playbook-prod-proxmox-cluster.yaml` it runs after the pinning role and its reboot, and
before anything that binds to the address it configures (Ceph).

## Required inputs

### `debian_add_network_interface_filename`

Drop-in name, without `.cfg` — e.g. `ceph-cluster` → `interfaces.d/ceph-cluster.cfg`. Two
invocations with the same name overwrite each other.

### `debian_add_network_interface_mac`

MAC of the NIC, case-insensitive. Resolved against the host's physical (`type == ether`)
interfaces; a bridge sharing its port's MAC is never selected. No match fails the role before
anything is written.

### `debian_add_network_interface_method`

`static` or `dhcp`. Default `dhcp`.

### `debian_add_network_interface_address_cidr`

Required when `method` is `static`: `10.1.40.12/24`. The prefix length is mandatory — the
template emits no `netmask` line. No `gateway` is emitted on purpose: a second default route
under ifupdown2 leaves the host with none.

## Optional inputs

### `debian_add_network_interface_wol`

`ethtool` wake-on-LAN flags (`g`, `pumbg`). Default empty → no `ethernet-wol` line.

### `debian_add_network_interface_interfaces_file`, `…_interfaces_d`, `…_ifreload`

Defaults `/etc/network/interfaces`, `/etc/network/interfaces.d`, `/usr/sbin/ifreload`.
Overridable so `tests/test.yml` can run the real role against a tempdir and a stub reload.

## Example

From `playbook-prod-proxmox-cluster.yaml`:

```yaml
- name: Configure Ceph cluster network NIC
  tags: network
  vars:
    debian_add_network_interface_filename: ceph-cluster
    debian_add_network_interface_mac: "{{ ceph_cluster_nic_mac }}"
    debian_add_network_interface_method: static
    debian_add_network_interface_address_cidr: "{{ ceph_cluster_nic_address_cidr }}"
    debian_add_network_interface_wol: pumbg
  ansible.builtin.import_role:
    name: debian_add_network_interface
```

## The installer's bare stanza

The PVE installer writes `iface <nic> inet manual` for every NIC it does not configure. Once
this role's drop-in declares the same interface, ifupdown has two definitions of it — the
state every node in this cluster ran in until 2026-09-08. The role removes the bare stanza
(and an `auto <nic>` line directly above it) when it has no options and no other interface
names the NIC as a port, slave or parent; the vmbr0 uplink's stanza therefore stays. A stanza
*with* options is a real configuration and fails the role: two configurations of one
interface is a decision, not something to merge silently.

The first run on an already-provisioned node reports `changed` for this and runs
`ifreload -a`. The effective configuration is unchanged, so the interface is not expected to
flap — but run it one node at a time with `ceph -s` open.

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/debian_add_network_interface/tests/inventory \
  roles/debian_add_network_interface/tests/test.yml
```

Runs the real role against a tempdir seeded with `interfaces` exactly as the PVE 9 installer
writes it, and a stub `ifreload` that logs its calls — localhost only, nothing contacted.
Covers: the drop-in and its content, the bare stanza removed while the vmbr0 block and the
bridge-port stanza stay byte-identical, `ifreload -a` called once, a second run changing
nothing and calling nothing, a bridge-port NIC's stanza kept when it is the target, a stanza
with options refused, `interfaces.new` refused before any write, and the `source` line added
exactly once when missing.
