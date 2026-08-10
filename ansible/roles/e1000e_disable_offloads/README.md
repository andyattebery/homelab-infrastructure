# e1000e_disable_offloads

Turns off TCP/generic segmentation offload on a NIC, both at boot (via an
`/etc/network/interfaces.d` drop-in) and immediately (`ethtool -K`).

## Status: Production

## Why

Intel e1000e onboard NICs hit `Detected Hardware Unit Hang` every ~16–19 hours and trigger a
watchdog reset. Disabling TSO/GSO is the long-standing workaround.

## Inputs

### `e1000e_disable_offloads_nics`

List of `{ mac, offloads }`. Default `[]`, which makes the role a no-op except for pruning
(see below).

```yaml
e1000e_disable_offloads_nics:
  - mac: "{{ vault_mgmt_nic_mac }}"
    offloads:
      - tso
      - gso
```

`mac` is required and must be colon-separated (`8c:04:ba:a0:fd:3d`), matched
case-insensitively. The interface name is resolved from it at run time, so the NIC keeps
working through a rename — a new PCIe slot, or name pinning. **A literal interface name is no
longer accepted**; an entry with `nic:` instead of `mac:` fails the assert with a message
saying so.

If a MAC matches no interface, the role fails rather than silently configuring nothing.

`offloads` is optional and overrides `e1000e_disable_offloads_offloads` for that NIC.

### `e1000e_disable_offloads_offloads`

Default `[tso, gso]`. Used for entries that don't carry their own list.

## The drop-in filename is MAC-derived

Files are written as `<mac-without-colons>-disable-offloads.cfg`, e.g.
`8c04baa0fd3d-disable-offloads.cfg`.

This is less readable than naming it after the interface, and that is the trade. A
name-derived filename is *not* rewritten when the interface is renamed — the role would write a
second file and leave the first behind, still declaring `iface <old-name> inet manual` for an
interface that no longer exists. Rewriting file contents doesn't fix a stale filename. A
MAC-derived name never has to change.

## The role owns every `*-disable-offloads.cfg`

After writing its drop-ins it removes any other `*-disable-offloads.cfg` in
`/etc/network/interfaces.d`. That prunes files from the old name-derived scheme, and files for
NICs dropped from the list, instead of leaving them to accumulate as dead `iface` stanzas.

The corollary: don't hand-place a file matching that pattern, and take the whole list in one
invocation. The playbook calls this role **once**, unlooped — a per-item loop would make each
invocation delete the previous one's output.

## Example

From `playbook-prod-proxmox-cluster.yaml`:

```yaml
- name: Disable e1000e NIC offloads
  when: e1000e_disable_offloads_nics is defined
  ansible.builtin.import_role:
    name: e1000e_disable_offloads
```

with `e1000e_disable_offloads_nics` set in `host_vars/<host>/vars.yaml`.

## Tests

```sh
cd ansible
.venv/bin/ansible-playbook -i roles/e1000e_disable_offloads/tests/inventory \
  roles/e1000e_disable_offloads/tests/test.yml
```

localhost only, throwaway `tempfile` directory, nothing left behind. Covers: pruning a
legacy name-derived snippet while leaving an unrelated drop-in alone, MAC-derived filename
computation, the rendered ifupdown stanza, rejecting the old `nic:` key, and the bridge-MAC
regression.

Pruning is exercised through the real role with an empty NIC list — that skips the
`template` task, which is what lets the suite run unprivileged (the template writes
`owner: root`). The keep-the-expected-file half is asserted against the filename expression
directly.

## Notes

- `ethtool -K` targets the *running* interface. Before a staged rename takes effect that is the
  old name; after the reboot the role re-resolves and targets the new one. No special handling.
- The generated stanza is `iface <name> inet manual`, which may duplicate a declaration in the
  installer-owned `/etc/network/interfaces`. Harmless under ifupdown2, and pre-existing.
