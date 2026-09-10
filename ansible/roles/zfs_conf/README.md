# zfs_conf

Sets the ZFS ARC maximum on a host, or removes the setting so ZFS uses its own default. Writes
`options zfs zfs_arc_max=<bytes>` into `/etc/modprobe.d/zfs.conf`, regenerates the initramfs, and
raises the live value where that is possible.

Manages nothing else about ZFS — the pool, datasets and packages belong to `zfs_install` and to the
roles that own the data.

## Status: Production

## Inputs

- `zfs_arc_max_gb` — default `0`. The cap in GiB.

  **`0` means no cap**, and the role then *removes* its block from `/etc/modprobe.d/zfs.conf` rather
  than writing `zfs_arc_max=0`. Both would work at boot; absence is what "this role does not manage
  the cap" should look like on disk.

  Any value above 0 writes the cap. A value below 64 MiB is rejected by ZFS itself
  (`zfs_arc_max` "must be at least 67108864B"), so a fractional GiB value is not usable here.

`vars/main.yaml` derives `zfs_arc_max_bytes` from it. That is internal — it sits above role defaults
in precedence and is not a caller override.

## Example

From `playbook-media-01.yaml`:

```yaml
- role: zfs_conf
  vars:
    zfs_arc_max_gb: 8
```

## The default is not 50% of RAM any more

Worth knowing before setting `0`, because the number it falls back to changed under this repo's feet
when hosts moved to 26.04.

Through OpenZFS **2.2** the man page read *"Under Linux, half of system memory will be used as the
limit"*. From **2.4** the Linux/FreeBSD split is gone and the default is *"the larger of
all_system_memory − 1 GiB and 5/8 × all_system_memory"* — so on anything above ~2.7 GiB of RAM,
effectively **RAM minus 1 GiB**.

On a host that also runs containers, "no cap" on 2.4 means ARC will claim nearly all memory and
release it only under pressure. Check which ZFS the host runs before assuming what `0` gives you.

## Raising the cap applies immediately; removing it does not

The module reads `/etc/modprobe.d` at load time, so the file only decides the cap after the next
boot. The role's runtime write to `/sys/module/zfs/parameters/zfs_arc_max` is what makes a change
apply now — and it only works in one direction.

From the OpenZFS man page, `zfs_arc_max`:

> This value can be changed dynamically, with some caveats. It cannot be set back to **0** while
> running, and reducing it below the current ARC size will not cause the ARC to shrink without
> memory pressure to induce shrinking.

Three consequences:

- **Raising a cap takes effect at once.** No reboot needed.
- **Removing a cap (`0`) needs a reboot.** The role skips the runtime write in that case rather than
  issuing one the kernel rejects. An earlier version of this role always wrote, with
  `failed_when: false` swallowing the rejection — which looked like it had applied and had not.
- **Lowering a cap is weaker than it looks.** The parameter changes, but a already-large ARC does not
  give memory back until something else demands it.

## Removing the block leaves the file

`state: absent` on the `blockinfile` removes the managed block and leaves `/etc/modprobe.d/zfs.conf`
in place, empty. That is deliberate: this role created the file but does not own everything that
might later be written to it, so it removes its own block rather than the file.

An empty file in `modprobe.d` is inert.

## The initramfs handler is not optional

`/etc/modprobe.d` is copied into the initramfs, so a stale copy there can set the cap before the
on-disk file is ever read. Both writing and removing the block notify `Regenerate initramfs` for
that reason. If the handler is skipped — a `--tags` run that excludes it, or a failure after the
file is written — the host can boot with the previous value still in force.
