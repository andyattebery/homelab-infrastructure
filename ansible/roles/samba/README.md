# samba

Installs Samba and renders `/etc/samba/smb.conf` from a list of share definitions, creating
the Unix users the shares authenticate against.

## Status: Production

## Inputs

- `samba_shares` — list of share dicts. See below.
- `samba_users` — list of `{ username, password }` created as Samba users.
- `samba_server_name` — value for `server string`.
- `samba_workgroup` — default `WORKGROUP`.
- `samba_homes_enabled` — default `false`. Adds a `[homes]` section.
- `samba_homes_browseable` / `_guest_ok` / `_read_only` — defaults `false`.
- `samba_global_browseable` / `_guest_ok` — defaults `true`.
- `samba_global_read_only` — default `false`.
- `samba_timemachine` — when defined, adds a Time Machine share.

### Share dict

| Key | Required | Notes |
| --- | --- | --- |
| `name` | yes | Share name, i.e. the `[section]` header. |
| `path` | yes | Host path exported. |
| `browseable` | no | Falls back to `samba_global_browseable`. Set `false` for shares reached by explicit path only. |
| `guest_ok` | no | Falls back to `samba_global_guest_ok`. |
| `read_only` | no | Falls back to `samba_global_read_only`. |
| `vfs_objects` | no | Space-separated VFS modules, e.g. `streams_xattr`. |
| `veto_files` | no | Slash-delimited glob list the server hides and refuses to open. |

## Example

```yaml
- role: samba
  vars:
    samba_users:
      - username: "{{ smb_username }}"
        password: "{{ smb_password }}"
    samba_homes_enabled: true
    samba_shares:
      - name: storage
        path: /mnt/storage
      - name: data01
        path: /mnt/data/data01
        browseable: false
        vfs_objects: streams_xattr
        veto_files: /.snapshots/
```

## Per-disk shares alongside a pooled one

Exporting the individual disks *and* the merged pool is how a client can address a specific
filesystem — which is what hardlink-aware tooling needs, since hardlinks cannot cross
filesystems and a pooled view hides which disk a file is on.

Mark the per-disk shares `browseable: false` so they do not clutter network browsing; they
still work when addressed directly.

## `veto_files` and snapshots

`veto_files: /.snapshots/` hides btrfs or ZFS snapshot directories. Without it, a client
walking the share descends into every snapshot and sees each file once per snapshot —
which looks like enormous duplication and makes any recursive scan effectively never finish.

Vetoed paths are hidden *and* unopenable, unlike `hide files`, which only removes them from
listings.

## `vfs_objects` is not additive

The value replaces any global `vfs objects` for that share rather than appending to it. A
share that needs both a global module and its own must list both.
