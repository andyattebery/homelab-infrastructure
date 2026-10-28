# zfs_install

Installs ZFS: on Debian from `<release>-backports`, pinned so backports wins; on Ubuntu from
Ubuntu's own archive, with the module loaded and checked.

## Status: In use — `playbook-turingpi.yaml` runs the Ubuntu path, tagged `zfs`.

No playbook runs the Debian path.

## Which path

`ansible_facts['distribution']` decides: `Debian` takes the backports path, `Ubuntu` its own
archive, and anything else is refused. Not `os_family`: Ubuntu's is `Debian` too, and the
backports path adds a `<codename>-backports` source that deb.debian.org doesn't serve for
Ubuntu's codenames. Ansible finds the distribution by looking for `Debian`, then `Ubuntu`, in
`/etc/os-release`, so an Armbian image built on Ubuntu takes the Ubuntu path.

## Inputs

All optional.

Debian path:

- `zfs_install_backports_name` — default `<release>-backports`. **This is the
  filename**: `deb822_repository` derives both
  `/etc/apt/sources.list.d/<slug>.sources` and `/etc/apt/keyrings/<slug>.asc`
  from it.
- `zfs_install_backports_uri` — default `http://deb.debian.org/debian`.
- `zfs_install_keyring_base` — default
  `/usr/share/keyrings/debian-archive-keyring`, **without extension**. See below.

Ubuntu path:

- `zfs_install_packages` — default `[zfs-dkms, zfsutils-linux]`, installed without recommends.
  A kernel that ships the module prebuilt lists `zfsutils-linux` alone. Wrong: a build
  dependency left out fails the DKMS build (see gcc below).
- `zfs_install_apt_preferences` — default empty. Written as given to
  `/etc/apt/preferences.d/90_zfs` before the install; empty removes that file. Wrong: a pin that
  matches nothing leaves apt's candidate where it was, which on Armbian is a pair apt can't
  install (see below).
- `zfs_install_state` — `present` (default) or `absent`. Wrong: anything else is refused.

## Example

From `playbook-turingpi.yaml`:

```yaml
- name: Configure all nodes
  hosts: turingpi
  become: true
  roles:
    - configure_server
    - role: zfs_install
      tags: [zfs]
    - role: data_disk_offload
      tags: [data_disk_offload]
```

`data_disk_offload` builds a ZFS pool, so `zfs_install` comes first.

The Armbian nodes keep the default packages and set the pin:

```yaml
zfs_install_apt_preferences: |
  Package: src:zfs-linux
  Pin: origin apt.armbian.com
  Pin-Priority: -1
```

## What the Ubuntu path does

`present`:

1. With `zfs-dkms` listed, refuses unless `/lib/modules/<kernel>/build` exists. dkms builds
   against it, and without it the install would leave the packages in and no module.
2. Writes or removes the preferences file.
3. Installs `zfs_install_packages`, without recommends.
4. Loads the module (`community.general.modprobe`).
5. Fails unless `zpool version` prints a `zfs-` and a `zfs-kmod-` line, `/dev/zfs` is a
   character device, and, with `zfs-dkms` listed, `dkms status -m zfs` shows `installed` for the
   running kernel. The two `zpool` lines aren't compared: a module prebuilt with the kernel
   follows the kernel's release, not `zfsutils-linux`'s. On success it prints them and the
   installed versions.

`absent` unloads the module, purges `zfs_install_packages` and removes the preferences file. The
unload is refused while anything holds the module, an imported pool included, so nothing is
purged under one. Every listed package is purged, `gcc` too where a host lists it, along with
anything installed since that depends on one. What apt pulled in for them (dkms, the ZFS
libraries) stays, marked automatic, for `apt-get autoremove`, and so does the `/etc/hostid` that
`zfsutils-linux`'s postinst writes.

## The role loads the module, not the install

`zfsutils-linux`'s postinst enables `zfs.target` and starts `zfs-load-module.service`, which runs
`modprobe zfs` and ignores its failure (`ExecStart=-`). `zfsutils-linux` doesn't depend on
`zfs-dkms`, so in one apt transaction dpkg may configure it before the build, as it does on noble:
the install then succeeds with no module loaded. Hence step 4.

At boot, `zfs.target` loads the module through that unit; the package's `modules-load.d/zfs.conf`
is all comments. If step 4 fails, `zfs.target` is already enabled and tries again at every boot:
run `absent` before rebooting.

## No recommends

Ubuntu's `zfs-dkms` and `zfsutils-linux` recommend `zfs-zed`, and Ubuntu's `dkms` recommends
`linux-headers-generic | … | linux-headers`, a generic kernel's headers wherever nothing installed
provides `linux-headers`. So nothing recommended is installed. `zfs-zed`, the event daemon pools
use, goes in `zfs_install_packages` when a host wants it.

## gcc with NVIDIA's dkms

NVIDIA's L4T repository carries its own `dkms`, which only recommends `gcc | c-compiler`, where
Ubuntu's depends on `gcc`. Without recommends, a Jetson lists `gcc` in `zfs_install_packages`, or
the build has no compiler.

## Armbian's ZFS pair

apt.armbian.com's `resolute-utils` has `zfs-dkms` only at `2.4.4-2arter97` and `zfsutils-linux`
only at `2.4.4-1arter97`, and that `zfsutils-linux` Breaks every `zfs-dkms` but `-1`, so apt
can't install the two together ("Reached two conflicting assignments"). Being newer than
Ubuntu's, they are apt's candidates. The pin in the example blocks every binary built from
`zfs-linux` at that origin, the libraries included under whatever soname they have, so Ubuntu's
ZFS is installed and keeps its updates.

On Armbian, installing or purging `zfs-dkms` also regenerates the initrd, and Armbian's
`99-uboot` hook rewrites `/boot/uInitrd` from it. ZFS isn't added to it: `zfs-initramfs` isn't
installed.

## The archive keyring extension is not derivable from the release

The role stats `<base>.pgp` and `<base>.gpg` and uses whichever exists,
preferring `.pgp`. That is not fussiness:

| Release | ships | `debian.sources` signs with |
| --- | --- | --- |
| bookworm | `.gpg` only | `.gpg` |
| trixie | **both** `.pgp` and `.gpg` | `.pgp` |

apt compares the `Signed-By` **strings**, not the keys they contain. Naming
`.gpg` on trixie is therefore a fatal `E:Conflicting values set for option
Signed-By` wherever the same archive is already configured — `apt-get update`
exits 100 and nothing on the host can install a package. Hardcoding either
spelling gets one of the two releases wrong.

Verified in `ansible/tests/apt-sources/verify-tail.yml`, which asserts the
per-release keyring explicitly and that `zfs-dkms` resolves from backports.

## deb and deb-src

Both types are configured, because `zfs-dkms` builds from source on the target
and the one-line entries this replaced carried both.

## Pinning

On Debian, `templates/apt_preferences_zfs.j2` is written to
`/etc/apt/preferences.d/90_zfs` so the backports build outranks the release's
own. That is unchanged by the deb822 migration. On Ubuntu the same file holds
`zfs_install_apt_preferences`.
