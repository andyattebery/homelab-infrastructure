# pve_pin_network_interface

Pins Proxmox network interface names to MAC addresses, so a NIC keeps its name when a card
moves to a different PCIe slot — and re-pins a NIC the installer (or an earlier scheme) named
differently. Wraps `pve-network-interface-pinning generate` and adds the idempotency and the
re-pin the tool itself doesn't have.

## Status: Production

## Contract

- **Owns:** `50-pmx-<name>.link` (and the legacy `50-pve-` form) in the link directory, for
  every MAC in `pve_pin_network_interface_pins`; and, through the tool, the references to
  those interfaces in `/etc/network/interfaces` (staged as `interfaces.new`), `host.fw` and
  the SDN config.
- **Requires:** each listed MAC resolves to exactly one physical interface. Nothing else — no
  particular current name, no prior pin.
- **Guarantees on exit:** every listed MAC has a `.link` naming it as requested, re-pinned if
  it was pinned to something else; `pve_pin_network_interface_reboot_required` is true iff any
  `.link` was created or replaced. **Live names match the pins only after a reboot.**
- **Never:** reboots; touches an interface it was not given, or anything under
  `interfaces.d/`; swaps names between two NICs in one run (see "Re-pinning").

The ordering follows from this: run it **first** in the play, reboot if it asks, and only
then run anything that resolves a name — `debian_add_network_interface`,
`e1000e_disable_offloads`, Ceph. `playbook-prod-proxmox-cluster.yaml` does exactly that.

## Why

Default interface names are PCI-path-derived (`enp69s0f0np0`), and the bus number comes from the
slot. Move the card and every name under it changes, which breaks `vmbr0`'s `bridge-ports` at
boot — the host comes up with no management network and needs a console to fix.

Resolving a NIC by MAC in Ansible (as `debian_add_network_interface` does) is not a substitute.
That runs at playbook time and writes a static file, so it buys convergence on the *next run*,
not survival across a boot. Pinning acts before any of that config is read.

## Inputs

### `pve_pin_network_interface_pins`

List of `{ mac, name }`. Default `[]`, which makes the role a no-op.

```yaml
pve_pin_network_interface_pins:
  - mac: "{{ vault_mgmt_nic_mac }}"
    name: cx4p0
  - mac: "{{ vault_ceph_cluster_nic_mac }}"
    name: cx4p1
```

`mac` is matched case-insensitively against the interface's MAC. If nothing matches, the role
fails rather than pinning the wrong card — and it fails *before* touching any existing pin.

`name` must match `^[a-zA-Z][a-zA-Z0-9_]{1,14}$` — PVE's own `pve-iface` format
(`^[a-z][a-z0-9_]{1,20}$`, from `PVE/JSONSchema.pm`) capped at the kernel's 15-character
`IFNAMSIZ` limit. It must also not begin with `eth`, `eno`, `ens`, `enp`, `enx` or `em`;
[systemd warns](https://www.freedesktop.org/software/systemd/man/latest/systemd.link.html) that
a custom name inside the kernel's own namespace races with the kernel's assignment, and only one
of the two wins.

**Interfaces not listed are left alone.** That is deliberate — see "Never let it auto-number".

### `pve_pin_network_interface_link_directory`

Default `/usr/local/lib/systemd/network`. Where PVE keeps pinning, for both the installer and
the CLI. Note this is *not* `/etc/systemd/network`, which is empty on a pinned host.

### `pve_pin_network_interface_command`

Default `/usr/bin/pve-network-interface-pinning`. Overridable so the tests can run the role
against a stub.

## Sets

### `pve_pin_network_interface_reboot_required`

`true` when a pin was created or replaced. The rename only happens at boot — `.link` files are
read by udev at device-add, and `pvenetcommit.service` moves `interfaces.new` into place before
networking starts. The role never reboots; the caller does, immediately, before anything
references a name:

```yaml
- name: Pin network interface names
  ansible.builtin.import_role:
    name: pve_pin_network_interface

- name: Reboot to apply pinned interface names
  when: pve_pin_network_interface_reboot_required | default(false)
  ansible.builtin.reboot:
    reboot_timeout: 600
```

That pair is the first two tasks of `playbook-prod-proxmox-cluster.yaml` (tagged `network`,
`pin_nics`), and `docs/proxmox_node_reinstall.md` Phase 5 counts on it: a node installed with
`nicN` names converges without a console.

## Never let it auto-number

Run without `--interface`, `pve-network-interface-pinning` names every physical interface
`nic0`, `nic1`, … in **`ifindex` order** — kernel registration order at boot. That ordering is
not stable, and it counts things you would not expect:

- A BMC USB gadget (`cdc_ether`) qualifies as physical — `ip_link_is_physical` only checks
  `link_type == 'ether'` with no `info_kind`. It can land between two ports of the same card and
  take a name you wanted for a real NIC.
- Registration order changes between boots. A host pinned as `nic0`=onboard can later enumerate
  the add-in card first, so a re-run would produce swapped names.

This role therefore always passes `--interface <current> --target-name <name>`, one interface at
a time. Anything you don't list is never touched.

## Re-pinning

Two scenarios reach this role, and they used to be treated as one:

- an **existing, provisioned node**: NICs unpinned, or already pinned to the wanted names —
  the role stages what is missing, or does nothing;
- a **fresh install**: the PVE installer pinned every NIC as `nic0`, `nic1`, … (unless the
  names were set in its Options dialog), and `/etc/network/interfaces` says
  `bridge-ports nic0`.

The tool (`PVE/CLI/pve_network_interface_pinning.pm`, pve-manager 9.2.11) has no unpin
subcommand: `generate` aborts with `There already exists a pin for NIC` while any `.link`
names the MAC, and with `target-name already exists as link or pin` if the wanted name is
taken. So a re-pin means the old `.link` goes first — and the two facts that make that safe:

1. **Removing a `.link` does not rename the running interface.** The tool still finds the
   NIC under its current name and rewrites `interfaces.new`, `host.fw` and SDN to the new one.
2. **The rename happens at the next boot**, together with the `interfaces.new` commit.

The role sets the old file aside as `<file>.replaced` (a name neither systemd nor the tool
reads), runs `generate`, then deletes the set-aside copy. If `generate` fails, the rescue puts
the old file back for every MAC that failed and stops the play: a MAC that is *unpinned* when
the node reboots gets a kernel name, and `bridge-ports` stops matching anything. That is the
console-only outage of 2026-09-07, caused by deleting the installer's pins by hand and letting
the playbook's own kernel reboot land before this role ran. Set-aside and generate happen in the
same run, and the playbook reboots straight after — that sequence is the fix.

**Swapping names between two NICs is not possible in one run**: the wanted name is still a
live interface, and the tool refuses it. The role fails with that reason before touching
anything. Pin the other NIC to its final name first, reboot, then re-run.

## It does not touch `/etc/network/interfaces.d/`

The tool rewrites `/etc/network/interfaces` (as a staged `.new` file), `host.fw`, and the SDN
configs. It does **not** rewrite drop-ins under `interfaces.d/`, and this role does not either.

That is a safety property, not an oversight. A drop-in naming an interface that will not exist
until reboot would be torn down by the next `ifreload -a` from any source — and
`debian_add_network_interface` runs exactly that in a handler it flushes immediately. Writing
the pinned name early would take a working interface down *before* the reboot, which is the one
thing the staged approach exists to prevent.

With the playbook order above, the drop-ins are regenerated in the **same run**, right after
the reboot, against the new names. What still happens in between: an interface configured only
by a drop-in comes up with no address for the few seconds until that task runs, and any daemon
that binds to it fails at boot. `pve_node_ceph` converges the Ceph daemons afterwards —
`reset-failed` and start for `ceph-mon`/`ceph-mgr`, a restart for an MDS that started bound to
nothing — and waits for each to appear in Ceph's own view. The 18-hour version of that failure,
found by `ceph -s` reporting `insufficient standby MDS daemons available` while
`systemctl is-active` said `active`, is why the role checks with Ceph and not with systemd.

**Before rebooting a Ceph node, confirm the cluster can lose it:** `ceph -s` must show
`HEALTH_OK` and all mons in quorum. If another node is already out, rebooting this one can drop
mon quorum below half and take all Ceph storage offline cluster-wide.

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_pin_network_interface/tests/inventory \
  roles/pve_pin_network_interface/tests/test.yml
```

Runs the role against a stubbed pinning CLI and a throwaway `tempfile` directory —
localhost only, no host contacted, nothing left behind. Covers: staging on an unpinned
host (including a missing link directory), idempotency on re-run, re-pinning a MAC that the
installer named differently (both `50-pmx-` and `50-pve-` files replaced, the tool called with
the live name, reboot flagged), a MAC that no longer resolves failing *before* its pin is set
aside, a name that is live on another NIC being refused, a failed `generate` restoring the
set-aside pin, failing before the CLI runs on an unknown MAC, rejecting a name in the kernel's
namespace, and the bridge-MAC regression below.

The bridge and ambiguity cases assert against the same filter chain as `vars/main.yaml`
rather than through the role, because injecting fake facts would be overwritten by the
role's own `setup` task. Keep them in step if you change that chain.

Cluster-wide invariants (pins declared on every node, the Ceph MAC appearing among them)
live in `ansible/tests/test-network-interface-pinning.yml`.

## Not updated automatically

`/etc/pve/firewall/cluster.fw` — the tool warns about interface references there and skips them,
because the mapping is node-local. Check it by hand before pinning a node.
