# zfs_install

Installs ZFS on Debian from `<release>-backports`, pinned so backports wins.

## Status: Production

Not currently enabled by any playbook.

## Inputs

All optional.

- `zfs_install_backports_name` — default `<release>-backports`. **This is the
  filename**: `deb822_repository` derives both
  `/etc/apt/sources.list.d/<slug>.sources` and `/etc/apt/keyrings/<slug>.asc`
  from it.
- `zfs_install_backports_uri` — default `http://deb.debian.org/debian`.
- `zfs_install_keyring_base` — default
  `/usr/share/keyrings/debian-archive-keyring`, **without extension**. See below.

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
per-release keyring explicitly and that `zfs-dkms` resolves from backports:
`2.3.2-2~bpo12+2` on bookworm, `2.4.3-2~bpo13+1` on trixie.

## deb and deb-src

Both types are configured, because `zfs-dkms` builds from source on the target
and the one-line entries this replaced carried both.

## Pinning

`templates/apt_preferences_zfs.j2` is written to `/etc/apt/preferences.d/90_zfs`
so the backports build outranks the release's own. That is unchanged by the
deb822 migration.
