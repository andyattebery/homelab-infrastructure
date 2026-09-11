# systemd_cifs_mount

Mounts CIFS/SMB shares with systemd `.mount` units and a single 0600 credentials file per
server.

The role supplies the mechanism. **What gets mounted is entirely the caller's**, as a list of
`{path, share}` entries. It mounts; it has no opinion about what consumes the result.

## Status: Production

## Inputs

Required — all asserted, because every wrong value here fails quietly rather than loudly:

- `systemd_cifs_mount_server` — the server as it appears in `What=//<server>/<share>`, e.g.
  `<storage_host>.{{ domain_name }}`. The role does **not** compose a host and a domain for
  you: a
  caller mounting from an IP or a short name has no domain to give.
- `systemd_cifs_mount_username` / `_password` — SMB credentials. Written `no_log`.
- `systemd_cifs_mount_uid` / `_gid` — become `uid=`/`gid=` on every mount. No default on
  purpose: a CIFS mount's ownership is fixed by these, and a wrong value is not a mount
  failure, it is a service that can read the share and cannot write to it.
- `systemd_cifs_mount_mounts` — list of entries:

  | Key | When | Meaning |
  | --- | --- | --- |
  | `path` | required | Where it mounts locally. Also the unit's name, after `systemd-escape`. |
  | `share` | required | Everything after `//<server>/`. See "shares are not validated". |
  | `options` | optional | Extra CIFS options, appended after the ones this role sets. |
  | `description` | optional | The unit's `Description=`. Defaults to naming share and server. |

Optional:

- `systemd_cifs_mount_credentials_path` — default `/etc/cifs-credentials-<server>`. One file
  for every mount from that server, which is the point: two callers mounting the same server
  converge on one credential instead of each keeping a copy.
- `systemd_cifs_mount_timeout_sec` — default `15`. `TimeoutSec=` on each unit. Low on purpose:
  a mount that cannot reach the server should fail and be retried, not hang the boot.
- `systemd_cifs_mount_unit_directory_path` — default `/etc/systemd/system`.
- `systemd_cifs_mount_file_owner` / `_file_group` — default `root`. The only correct values on
  a real host; they are inputs so a fixture test can render as an unprivileged user.
- `systemd_cifs_mount_systemd_escape` / `_mountpoint` — CLI paths, default `/usr/bin/…`. Both
  are inputs so the fixture test can point them at stubs. A wrong path here makes every unit
  name wrong, so it fails loudly.

## Example

Lifted from the calling playbook:

```yaml
- name: Mount the storage shares
  tags: [mounts]
  ansible.builtin.include_role:
    name: systemd_cifs_mount
    apply:
      tags: [mounts]
  vars:
    systemd_cifs_mount_server: "<storage_host>.{{ domain_name }}"
    systemd_cifs_mount_username: "{{ smb_storage_username }}"
    systemd_cifs_mount_password: "{{ smb_storage_password }}"
    systemd_cifs_mount_uid: "{{ smb_storage_uid }}"
    systemd_cifs_mount_gid: "{{ smb_storage_gid }}"
    systemd_cifs_mount_mounts:
      - {path: /mnt/pool, share: storage, options: noserverino}
      - {path: /mnt/raw/disk1, share: disk1}
```

`apply:` is required when tagging an `include_role` — a tag on the include gates only the
include itself, not the tasks inside the role.

## Shares are not validated, because some of them have sub-paths

`share` is interpolated whole into `What=//<server>/<share>`. It is a bare share name for most
callers and a share with a sub-path (`storage/AI/images`) for some, and this role deliberately
cannot tell the difference. Splitting or validating it would break the sub-path case and buy
nothing — the server rejects a bad path far more reliably than a regex would.

## Why `.mount` units and not Quadlet `.volume` units

The `podman_quadlet` role writes every unit at mode `0644`. A Quadlet `.volume` unit carrying
CIFS `Options=` would therefore put the SMB password in a world-readable file, and
`credentials=` cannot rescue it: `mount.cifs(8)` documents that option as read by the
`mount.cifs` userspace helper, which Podman's local volume driver does not invoke. A systemd
`.mount` unit runs `/bin/mount`, so `credentials=<0600 file>` works.

## No `nofail`, no `_netdev`

They are inert in a unit file. systemd.mount(5) is explicit that both "can only be used in
`/etc/fstab`, and will be ignored when part of the `Options=` setting in a unit file". The
ordering they stand for is stated directly by `After=network-online.target nss-lookup.target`.

`serverino` is not set either way. `mount.cifs(8)` says server inode numbers are "enabled by
default"; a caller that needs them off passes `noserverino` through `options`.

## Rewriting a unit does not remount it

`state: started` is a no-op on an already-mounted path, so a changed `Options=` line does
**not** take effect — systemd will not remount in place. The role reports which units it
rewrote for exactly this reason; acting on it means stopping whatever consumes the path,
`systemctl restart`ing the `.mount`, then starting the consumer again. Remounting under a
running container is an operator decision, not something a playbook should do unprompted.

## A failed `.mount` has no way back

`Restart=` is not a mount-unit option, and a consumer whose `RequiresMountsFor=` dependency
failed never runs its own `Restart=` either. If the server is unavailable at boot, the unit
fails and stays failed until something starts it. This role does not solve that — see
`systemd_unit_watchdog`.

## Mount points are only created when not already mounted

A mounted CIFS root has its ownership and permissions fixed by the mount's `uid=`/`gid=`, so
applying a mode to it does not stick: it reports *changed* on every run and a chmod can fail
outright. The role pre-tests each path with `mountpoint -q` and creates only the ones that are
not mounted, which is what makes an explicit `0755` safe — it is only ever applied to a
directory the role is about to create.

## No handlers

Deliberate. A handler fires at end of play, which in a fixture test means a `systemd` call on a
controller that has none. `tasks/configure.yaml` renders and registers; `tasks/main.yaml` is
the only place that talks to systemd. That split is what makes `tasks_from: configure.yaml`
testable — see `tests/test.yml`.
