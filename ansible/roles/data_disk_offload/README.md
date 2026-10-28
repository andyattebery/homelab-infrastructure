# data_disk_offload

Puts a host's write-heavy directories and its swap on a second disk, as a ZFS pool. It partitions
the disk once, makes the pool, gives each listed directory its own dataset, copies the directory in
and bind-mounts that copy over the original. It can add a swap partition too.

## Status: Production

Its callers are the Turing Pi 2 nodes:
- the Jetson (L4T on Ubuntu 24.04);
- the RK1s (Armbian minimal on Ubuntu 26.04);
- the CM4 (Ubuntu Server 26.04).

## Why it exists

Every Turing Pi 2 node boots from flash:
- the Jetson from a microSD card (`turingpi/jetson/README.md`), chosen so that reinstalling is just
  rewriting the card;
- the RK1s and the CM4 from their eMMC.

Flash write endurance is limited, and a card's is unspecified. Logging, swap and container state
are steady writers, so they live on the node's NVMe or SATA disk instead, while the OS stays on the
flash. The disk is ZFS so that each directory's data can be snapshotted and replicated.

## Inputs

### `data_disk_offload_device` (required, no default)

The data disk as its `/dev/disk/by-id/` path. For example:
- `/dev/disk/by-id/nvme-Samsung_SSD_980_1TB_S649NL0T123456X` for an NVMe drive;
- `/dev/disk/by-id/ata-Samsung_SSD_860_EVO_1TB_S3Z9NB0K123456X` for a SATA disk.

The path names the drive by model and serial, so the role cannot be aimed at whichever disk happens
to be `nvme0n1` today. Its partitions are the `-part1` and `-part2` links next to it.

Unset, outside `/dev/disk/by-id/`, a `-partN` link or not a block device on the host: the role fails
before it changes anything.

Read it on the host with `ls -l /dev/disk/by-id/`. NVMe drives also get an `nvme-eui.…` link, but
the model-and-serial one is the readable one.

### `data_disk_offload_mount_path` (default `/mnt/data`)

Where the pool is mounted, and the parent of every directory's dataset: `/var/log`'s dataset
`data/var/log` is mounted at `/mnt/data/var/log`. It must be absolute, without a trailing slash or
whitespace.

Set it before the first run. A pool mounted anywhere else is refused, and the role never moves
one.

### `data_disk_offload_fs_label` (default `data`)

The GPT name of partition 1 and the name of the pool on it. It must be a name zpool accepts (a
letter, then letters, digits and `_.:-`), not one zpool reserves (`log`, or a name beginning with
`mirror`, `raidz`, `draid` or `spare`), and not `APP` or `swap`.

Changed after the first run, the role refuses the disk, whose partition and pool still have the old
name.

### `data_disk_offload_bind_dirs` (default `[]`)

The directories to move, each as `{path, services, zfs_properties}`:

- **`path`**: an absolute directory, with no trailing slash and only letters, digits and `_.:-`
  between its slashes, since it names the dataset `<fs_label><path>`. It must not be inside or
  above the mount path or another entry. A path that does not exist yet is created empty (root,
  0755), so that a program installed later starts on the data disk. On Armbian, `/var/log` is a
  RAM-logging mount that the role turns off to move it (Traps).
- **`services`**: the units stopped while the directory is copied and bind-mounted, in list
  order. Only those that were running are started again afterwards. Units that are not installed
  are skipped.
- **`zfs_properties`** (optional, default `{}`): ZFS properties set on the directory's dataset, for
  example `{recordsize: 32K}` for a PostgreSQL data directory. A changed `recordsize` applies only
  to files written after it.

Empty means the role only partitions the disk and makes the pool. Each wrong shape fails
`validate.yaml` before anything changes.

### `data_disk_offload_swap_mib` (default `0`)

A swap partition of this many MiB: partition 2, named `swap`, at the end of the disk. It is enabled
at once and in fstab by its by-id link, with `nofail`. `0` means none. A whole number only.

Set it before the first run. Only wiping the disk changes the partition's size, so a partition 2
of another size is refused, and so is one made with `0` and then asked for (Traps).

### `data_disk_offload_zfs_root_properties` (default `{}`)

ZFS properties of the pool's root dataset, which every dataset inherits. They are set on every run,
so a changed value reaches an existing pool. For example `org.debian:periodic-trim: enable`,
without which Ubuntu's monthly trim skips a pool that isn't all NVMe (Traps). Not a mapping: the
input check refuses it.

## Playbook

`playbook-turingpi.yaml` applies the role to the `turingpi` group:
- after `configure_server` and `zfs_install`, which loads the module the pool needs;
- with `become: true`;
- tagged `data_disk_offload`, so a run can leave it out (`--skip-tags data_disk_offload`).

The directories are group-wide, in `group_vars/turingpi`:

```yaml
data_disk_offload_bind_dirs:
  - path: /var/log
    services:
      - syslog.socket
      - rsyslog.service
      - fail2ban.service
      - unattended-upgrades.service
      - auditd.service
  - path: /var/tmp
    services: []
```

Each node's host_vars set `data_disk_offload_device` and `data_disk_offload_swap_mib: 8192`; a node
without the device fails at the input check. Two nodes' host_vars set more:
- the Jetson's replace the list with one that adds `/var/lib/docker` and `/var/lib/containerd`;
- the CM4's set `data_disk_offload_zfs_root_properties: {org.debian:periodic-trim: enable}`, since
  its disk is SATA.

A disk that still holds the role's old ext4 layout (one GPT partition named `data`, ext4) is refused
at the pool check. `playbook-turingpi-data-disk-zfs-migration.yaml` wipes it once, on a node where
nothing uses the disk any more, and then runs this role.

## What it does, in order

1. Checks the inputs (`validate.yaml`), that ZFS is loaded (`/dev/zfs` is a character device) and
   that the device is a block device.
2. Installs `parted` and `rsync`.
3. Reads the partition table and the disk's signatures (`wipefs`). It refuses any disk that is
   neither:
   - blank: no partitions, and no signature or an empty GPT;
   - nor holding its own partitions: GPT partition 1 named `data_disk_offload_fs_label`, alone or
     followed by partition 2 named `swap` when `data_disk_offload_swap_mib` asks for it
     (`check_table.yaml`).
4. Creates partition 1 if it is missing. It starts at 1 MiB. With `swap_mib` set, it ends at a
   whole MiB, `swap_mib` before the disk's last whole MiB, where partition 2 will start.
5. Reads partition 1 (`blkid -p`) and whether the pool is imported, then (`pool_state.yaml`):
   - imported already: nothing;
   - the pool's own member, not imported, as after an OS reinstall: `zpool import -f`;
   - empty: creates the pool, with `ashift=12`, `acltype=posix`, `xattr=sa` and the mount path;
   - anything else, such as the old layout's ext4: refuses.

   With `swap_mib` set, partition 2 is created between this check and the pool. It comes after the
   check, so a disk with another layout gets the check's refusal rather than parted's. It comes
   before the pool, so the table changes while partition 1 is idle.
6. Checks that the pool is partition 1 alone and is mounted at the mount path, then sets
   `data_disk_offload_zfs_root_properties` on it.
7. Creates each directory's dataset with its `zfs_properties` and checks it is mounted at
   `<mount_path><path>`.
8. Writes a drop-in for each bind's mount unit:
   `/etc/systemd/system/<unit>.d/data_disk_offload.conf`, with
   `ConditionPathIsMountPoint=<mount_path><path>`, so the bind is skipped at a boot without its
   dataset (Traps).
9. For each directory that is not already bound from its dataset (`bind_state.yaml`):
   1. Stops its running services. For the directory holding `/var/log/journal`, it also runs
      `journalctl --relinquish-var`.
   2. Fails if any process still has a regular file open in it. Under Armbian's RAM logging,
      `/var/log.hdd` is checked too.
   3. On Armbian, for a `/var/log` that RAM logging holds:
      - stops `armbian-ramlog.service`;
      - checks `/var/log` is a plain directory again;
      - sets `ENABLED=false` in `/etc/default/armbian-ramlog`.
   4. Copies it into the dataset with `rsync -aHAX --numeric-ids --ignore-existing`.
   5. Bind-mounts the copy over it
      (`bind,nofail,x-systemd.requires=zfs-mount.service,x-systemd.before=local-fs.target`).
   6. Always, even after a failure: runs `journalctl --flush` and starts the services that were
      running.

   A directory that is already bound keeps its bind, and only its fstab entry is rewritten to the
   current options. Then each directory is checked to be mounted from its dataset.
10. With `swap_mib` set, checks partition 2's size, formats it if it is empty (`swap_state.yaml`),
    adds it to fstab and enables it.

## Traps

- **It never wipes or repartitions.**
  - `community.general.parted` with `state: present` runs `mklabel` whenever the disk's table
    differs from the one asked for, which wipes the disk.
  - So the role reads the table and the disk's signatures first, and refuses anything it did not
    make. parted alone isn't enough: it recognises partition tables and filesystems only, so it
    reports a whole-disk LVM PV, LUKS, md or BlueStore volume as `table: unknown` with no
    partitions, the same as a blank disk. `wipefs` sees their signatures.
  - A partition with any other name is refused too, even an empty one.
  - Partition 1 holding a filesystem or another pool is refused, and so is partition 2 holding
    anything but swap.

  To reuse a disk with data on it, the decision and the wipe are yours.
- **Never name a partition `APP` on a Jetson.** L4TLauncher boots any disk with an `APP`
  partition, so a data disk named that could take over the boot. The role refuses the label.
- **`community.general.zpool` only creates the pool.** On an existing pool, its layout check
  compares `zpool status -P -L`'s real path, with the partition suffix stripped (`/dev/nvme0n1`),
  against the by-id `-part1` path as given. It finds them different and runs `zpool add`, then
  `zpool remove` (13.3.0, `zpool.py:307-326, 408-500`). So the role runs it only when there is no
  pool, and checks an existing pool's device itself.
- **The binds wait for `zfs-mount.service`, not for a mount unit.**
  - ZFS mounts its datasets from `zfs-mount.service` (`zfs mount -a`, `Before=local-fs.target`),
    which Ubuntu's `zfsutils-linux` enables.
  - Per-dataset mount units exist only when zed's `history_event-zfs-list-cacher.sh` keeps
    `/etc/zfs/zfs-list.cache/<pool>` (zfs-mount-generator(8)), and `zfs_install` leaves zed out.
  - So `x-systemd.requires-mounts-for=<mount_path>` would order the bind against no unit, and
    `/var/log` could be bound before its dataset mounts.
  - `x-systemd.requires=zfs-mount.service` "Configures a Requires= and an After= dependency"
    (systemd.mount(5)). `systemd-journal-flush.service`'s `RequiresMountsFor=/var/log/journal` then
    waits for the `/var/log` bind.
  - With `nofail`, "the mount unit is not ordered before" `local-fs.target`, so a service such as
    Docker could start before its directory is bound, and write into the hidden copy.
    `x-systemd.before=local-fs.target` puts the ordering back: it is "particularly useful for mount
    point declarations with nofail option" (systemd.mount(5)). Every regular service starts after
    the binds.
- **Without its dataset, a bind is skipped, not made over an empty directory.**
  - At boot, systemd creates a bind's missing source directory and mounts it: "Create the source
    directory for bind-mounts if needed" (mount.c, v255 and v259).
  - `zfs-mount.service` succeeds with no pool to mount, and is skipped by its own condition when
    the module isn't loaded. Either way the bind would go ahead, over an empty directory on the
    root filesystem.
  - So each bind's mount unit has a drop-in with `ConditionPathIsMountPoint=<mount_path><path>`.
    systemd.unit(5): a failed condition skips the unit "at the time the queued start job is to be
    executed". It isn't failed, and "other units are still pulled in and ordered as if this unit
    was successfully activated".
- **No swap file on ZFS.**
  - ZFS has no `bmap` or `swap_activate` (`zpl_file.c`), and the kernel's swapon then fails with
    "swapfile has holes".
  - OpenZFS's FAQ warns that "swap on zvol may lead to deadlock".
  - So swap is its own partition.
- **The partitions' positions are explicit.** With parted's default start, `0%`, parted put
  partition 1 at sector 34 of an image file, and 17408 bytes isn't 4K-aligned. Positions measured
  from the end of the disk landed off the MiB grid too. With partition 1 at `1MiB`, and partition 2
  at the disk's whole MiB minus `swap_mib`, both are MiB-aligned, and partition 2 is exactly
  `swap_mib` (parted 3.6, 2026-10-26).
- **`swap_mib` is fixed at the first run.** A partition 1 made with `swap_mib: 0` fills the disk,
  so a later swap partition doesn't fit, and parted fails.
- **`ashift=12`, set at creation and immutable.**
  - All four Turing Pi data disks report 512-byte logical and physical sectors, and OpenZFS's
    exception list has none of them, so auto-detect would pick 9.
  - OpenZFS's Hardware page: SSDs "incorrectly report 512-byte sectors", and "ashift=12 is usually
    the correct choice".
- **Check a new NVMe disk's LBA formats before its first run.** OpenZFS's Hardware page says to
  format an NVMe namespace to 4096-byte sectors before giving it to ZFS, unless 512 performs as
  well. `nvme id-ns -H` lists them. The role makes the pool on whatever format is in use, and the
  three NVMe drives here offer only 512 ("0 Best").
- **`acltype=posix` and `xattr=sa`.** The copy is `rsync -A`, and systemd's tmpfiles puts ACLs on
  `/var/log/journal`. ZFS's `acltype` defaults to off on Linux. zfsprops(7) encourages `xattr=sa`
  with POSIX ACLs; in 2.2.2 `xattr`'s default is directory-based. Compression and atime stay at
  their defaults: lz4, and relatime.
- **A reinstall imports the pool with `-f`.** A pool that was never exported "appears as
  potentially active", and importing it takes `-f` (zpool-import(8)). After the import, each
  directory is plain again, so it is copied in with `--ignore-existing`: what is already in the
  dataset wins, and only what it lacks is added. This path is untested.
- **Ubuntu's monthly trim covers only NVMe-only pools.** `/usr/lib/zfs-linux/trim` trims a pool
  whose `org.debian:periodic-trim` is `enable`, or unset and every device is NVMe. fstrim can't
  stand in, because ZFS has no FITRIM ioctl (`zpl_ioctl`, zpl_file.c). So a SATA pool needs
  `data_disk_offload_zfs_root_properties: {org.debian:periodic-trim: enable}`, once `lsblk
  --discard` shows TRIM reaches the drive. Ubuntu's monthly scrub covers every pool.
- **`/var/log` moves under a running journald.** journald holds its journal files open, and
  without `--relinquish-var` it would go on writing into the old copy, hidden under the bind. The
  role switches it to `/run` for the copy and back with `--flush`.
- **Armbian keeps `/var/log` in RAM.**
  - armbian-ramlog is on by default (`ENABLED=true` in `/etc/default/armbian-ramlog`). It:
    - mounts a zram device on `/var/log`;
    - binds the root filesystem's `/var/log` to `/var/log.hdd`;
    - links `/var/log/journal` to `/var/log.hdd/journal`.
  - With `/var/log` listed, the role turns it off once the entry's services are stopped and nothing
    has a file open there:
    - it stops `armbian-ramlog.service`, whose stop writes the RAM copy back to the root filesystem
      and unmounts both;
    - it checks `/var/log` is a plain directory;
    - only then does it set `ENABLED=false`.
  - The order matters, because the stop does nothing once `ENABLED` is false.
  - The role recognises only a zram device on exactly `/var/log`, with `ENABLED=true`. These are
    refused as foreign mounts:
    - ramlog's tmpfs fallback;
    - a zram still mounted after someone set `ENABLED=false` without rebooting.
  - Left alone:
    - Armbian's zram swap, at priority 5, which fills before the swap partition;
    - the `SystemMaxUse=20M` that armbian-zram-config writes into `journald.conf`, which still caps
      the journal on the data disk.
- **Any other process holding a file in a directory has to be listed in its `services`.**
  - rsyslog is socket-activated, so `syslog.socket` comes before `rsyslog.service`; otherwise the
    socket restarts rsyslog mid-copy.
  - Readers count too. fail2ban holds journal files open, and left running it would miss every new
    entry once the journal moves.
  - Under Armbian's RAM logging, those journal files are under `/var/log.hdd`, through the
    `/var/log/journal` link. So the check looks there as well.
  - The open-file check fails the run, after restarting what it stopped, rather than leave a writer
    or reader behind.
- **The old contents stay on the original filesystem**, hidden under the bind mount, and keep
  their space. Nothing is deleted. Unmount the bind to see them.
- **`nofail` everywhere.** Without the data disk, or without the pool, the host still boots.
  - The binds are skipped by their condition. The swap partition isn't ZFS, so it still comes up
    while the disk is there, and without the disk `nofail` lets the boot go on without it.
  - So the directories show their old contents on the root filesystem, which then takes the writes.
  - A skipped bind counts as done for what waits on it, such as `systemd-journal-flush.service` or
    a unit with `PrivateTmp=yes` and `/var/tmp`, so those still start.

  That is from systemd's documentation; no degraded boot has been tried.
- **A directory that is already a mount point is refused,** apart from Armbian's RAM-logging
  `/var/log`. `ansible.posix.mount` would remount that mount with these options, not bind over it.

## Tests

`tests/test.yml` is a role fixture test (`ansible/tests/README.md`). It runs the role's decision
files through `tasks_from` on localhost, and touches no host:

- **The input checks (`validate.yaml`):** 31 cases.
  - Accepted: a typical configuration, a SATA disk's by-id path, a pool name with zpool's other
    characters, a dataset's properties and the pool's own.
  - Refused, each by the task meant to refuse it: a missing device, and 25 malformed devices,
    labels and pool names, mount paths, directory lists, dataset and pool properties, and swap
    sizes.
- **The partition-table guard (`check_table.yaml`):** 16 cases. Most come from real `parted` and
  `wipefs` output.
  - Accepted:
    - a blank disk;
    - an empty GPT;
    - the role's partition 1 alone, with and without a swap partition to come;
    - both of its partitions.
  - Refused:
    - an empty GPT with an LVM signature;
    - the role's partitions when no swap is asked for;
    - the swap partition first;
    - an unnamed GPT partition;
    - msdos;
    - ext4 on the whole disk;
    - a second partition not named swap;
    - a Mac map;
    - a configured label that differs;
    - an LVM PV on the whole disk;
    - an empty partition someone else made (an RK1's NVMe as found).
- **The pool decision (`pool_state.yaml`):** 6 cases: imported; a reinstall's import; another
  pool's member; the old layout's ext4; and an empty partition, with and without its partition
  entry.
- **The relocation decision (`bind_state.yaml`):** 13 cases. They cover:
  - already-bound from its dataset;
  - bound from another dataset or from the old ext4 partition;
  - foreign mounts;
  - which paths hold the journal;
  - which RAM-logging mounts the role turns off.
- **The swap decision (`swap_state.yaml`):** 4 cases: empty, in use, formatted but off, and ext4.

Where the fixtures come from is in the test's header. The ZFS `findmnt` source and the `blkid -p`
lines are built from util-linux's and libblkid's formats, until a node gives the real ones.

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/data_disk_offload/tests/inventory \
  roles/data_disk_offload/tests/test.yml
```

Positive controls. Each mutation turned exactly its case red, and was reverted.

2026-10-02:
- Dropping the `-partN` check failed "a by-id partition link".

2026-10-09:
- Dropping the signature check failed "an LVM PV on the whole disk".
- Dropping the `ENABLED` check failed "a zram still mounted after RAM logging was switched off".
- Dropping the `/var/log` path check failed "/var/tmp on a zram while RAM logging is on".
- Dropping the zram match failed "RAM logging's tmpfs fallback".

2026-10-26:
- Accepting any empty GPT failed "an empty GPT on an LVM PV's disk".
- Dropping the `swap_mib` condition failed "the role's partitions with swap, and no swap asked
  for".
- Dropping the pool-name comparison failed "another pool's member on partition 1".
- Creating on any type but `zfs_member` failed "the old layout's ext4 on partition 1".
- Comparing against the ext4 source failed "/var/log, already bound from its dataset".
- Formatting anything but swap failed "ext4 on partition 2".
- The old path rule failed "a character a dataset name can't hold".
- Dropping the reserved-name check failed "a pool name beginning with raidz".
- Dropping the mapping check on the pool's own properties failed "the pool's own properties as a
  list".

One condition is not exercised on its own: `check_table.yaml`'s `table == 'gpt'` for the role's own
partitions.
- Every other table parted makes fails another condition first, and deleting the condition leaves
  the test green.
- It is kept for a PC98 table, which can name partition 1 but could not be read on a loop device.

Not here: everything that needs a real disk, a pool, mounts and services, which is all of
`main.yaml`, `relocate.yaml` and `swap.yaml` outside those decision files.
- That includes stopping armbian-ramlog, handing the journal over, creating and importing the
  pool, the bind conditions, and the swap partition.
- They are checked on the host:
  - by the run itself, which re-reads and asserts the pool, each dataset, each directory's mount
    and the swap;
  - by a second run reporting no changes;
  - by a reboot.
