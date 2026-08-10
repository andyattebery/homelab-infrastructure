# pve_pin_network_interface

Pins Proxmox network interface names to MAC addresses, so a NIC keeps its name when a card
moves to a different PCIe slot. Wraps `pve-network-interface-pinning generate` and adds the
idempotency the tool itself doesn't have.

## Status: Production

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
fails rather than pinning the wrong card.

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

## Sets

### `pve_pin_network_interface_reboot_required`

`true` when a pin was staged. The rename only happens at boot; the role never reboots.

```yaml
- name: Pin NIC names
  ansible.builtin.import_role:
    name: pve_pin_network_interface

- name: Reboot if pinning was staged
  when: pve_pin_network_interface_reboot_required | default(false)
  ansible.builtin.reboot:
```

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

## It does not touch `/etc/network/interfaces.d/`

The tool rewrites `/etc/network/interfaces` (as a staged `.new` file), `host.fw`, and the SDN
configs. It does **not** rewrite drop-ins under `interfaces.d/`, and this role does not either.

That is a safety property, not an oversight. A drop-in naming an interface that will not exist
until reboot would be torn down by the next `ifreload -a` from any source — and
`debian_add_network_interface` runs exactly that in a handler it flushes immediately. Writing
the pinned name early would take a working interface down *before* the reboot, which is the one
thing the staged approach exists to prevent.

The consequence: after the reboot, drop-in-configured interfaces come up with no address until
the playbook runs again and regenerates them from their MACs. Check first that nothing critical
rides those interfaces — on this cluster corosync uses `vmbr0`, so quorum and SSH are
unaffected and the fix is always deliverable.

### Services bound to those addresses will not recover on their own

This is the part that actually costs you. Anything binding an address on a drop-in-configured
interface fails at boot, and systemd's restart limiter then gives up **permanently**:

```
ceph-mon: bind unable to bind to v2:10.1.40.13:3300/0: (99) Cannot assign requested address
ceph-mon@…: Start request repeated too quickly
```

Bringing the interface back later does not revive them — they stay `failed` until something
restarts them. On this cluster that took out `ceph-mon`, `ceph-mgr` and the node's OSD, and it
went unnoticed for 18 hours after a card swap.

**`ceph-mds` fails differently, and silently.** It does not exit — it starts anyway with no
address and never registers with the cluster:

```
ceph-mds: unable to find any IPv4 address in networks '10.1.40.0/24' interfaces ''
ceph-mds: starting mds.<host> at            <- note the empty address
```

`systemctl is-active` reports `active`, so a unit-state check passes on a daemon that is doing
nothing. Two nodes sat like this until caught by `ceph -s` reporting
`insufficient standby MDS daemons available`. **Verify MDS with `ceph mds stat` (expect
`N up:standby`), never with `systemctl is-active`.**

So the reboot procedure is three steps, not two:

```sh
ssh <host> 'bash -lc "sudo systemctl reboot"'
# once it is back on vmbr0:
ansible-playbook playbook-prod-proxmox-cluster.yaml --limit <host> --tags network
# then revive whatever died while the address was missing:
ssh <host> 'bash -lc "sudo systemctl reset-failed ceph-mon@<host> ceph-mgr@<host>; \
  sudo systemctl start ceph-mon@<host> ceph-mgr@<host>; \
  sudo systemctl restart ceph-mds@<host>; \
  sudo ceph-volume lvm activate --all"'
```

`restart` for the MDS, not `start` — it is already "running" and useless, so `start` is a no-op.
`ceph-volume lvm activate --all` is what brings the OSD back: its `/var/lib/ceph/osd/ceph-N` is
a tmpfs that boot leaves unpopulated, so `systemctl start ceph-osd@N` alone dies on `no keyring`.

Then confirm with Ceph's own view, not systemd's:

```sh
ssh <host> 'bash -lc "sudo ceph -s; sudo ceph mds stat"'
```

A full playbook run (no `--tags`) does the last step for you — `pve_node_ceph` reset-failes and
starts the OSD — but it also runs `apt dist-upgrade`. Pick deliberately.

**Before rebooting a Ceph node, confirm the cluster can lose it:** `ceph -s` must show
`HEALTH_OK` and all mons in quorum. If another node is already out, rebooting this one can drop
mon quorum below half and take all Ceph storage offline cluster-wide.

## No unpin

`generate` is the only subcommand. It aborts with `There already exists a pin for NIC` rather
than re-pinning, so the role fails with instructions instead of deleting anything: removing a
pin is irreversible from Ansible's point of view and should be a deliberate human act. To
rename an already-pinned interface, delete its `.link` file on the host and re-run.

## Tests

```sh
cd ansible
.venv/bin/ansible-playbook -i roles/pve_pin_network_interface/tests/inventory \
  roles/pve_pin_network_interface/tests/test.yml
```

Runs the role against a stubbed pinning CLI and a throwaway `tempfile` directory —
localhost only, no host contacted, nothing left behind. Covers: staging on an unpinned
host (including a missing link directory), idempotency on re-run, refusing to re-pin a MAC
that already has a different name, failing before the CLI runs on an unknown MAC, rejecting
a name in the kernel's namespace, and the bridge-MAC regression below.

The bridge and ambiguity cases assert against the same filter chain as `vars/main.yaml`
rather than through the role, because injecting fake facts would be overwritten by the
role's own `setup` task. Keep them in step if you change that chain.

Cluster-wide invariants (pins declared on every node, the Ceph MAC appearing among them)
live in `ansible/tests/test-network-interface-pinning.yml`.

## Not updated automatically

`/etc/pve/firewall/cluster.fw` — the tool warns about interface references there and skips them,
because the mapping is node-local. Check it by hand before pinning a node.
