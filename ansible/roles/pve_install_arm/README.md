# pve_install_arm

Installs Proxmox VE on ARM64 from the PXVIRT port.

## Status: Production

## Inputs

All optional.

- `pve_install_arm_apt_source_name` — default `pxvirt`. **This is the filename**:
  `deb822_repository` derives both `/etc/apt/sources.list.d/<slug>.sources` and
  `/etc/apt/keyrings/<slug>.<asc|gpg>` from it.
- `pve_install_arm_apt_repo_url` — default
  `https://mirrors.lierfang.com/pxcloud/pxvirt`.
- `pve_install_arm_apt_gpg_key_url` — default
  `https://mirrors.lierfang.com/pxcloud/lierfang.gpg`. This URL 301-redirects to
  a regional mirror; `deb822_repository` follows it.
- `pve_install_arm_apt_suite` — default `{{ ansible_distribution_release }}`,
  matching the vendor's own `$VERSION_CODENAME` instruction.
- `pve_install_arm_apt_components` — default `[main]`. The repository also
  publishes `ceph-quincy`, `ceph-reef` and `ceph-squid`.
- `pve_install_arm_packages` — default
  `[proxmox-ve, pve-manager, qemu-server, pve-cluster]`, the vendor's documented
  set. `ifupdown2` is deliberately **not** in it; it is installed as its own
  earlier step, for the ordering reason below.

## The old mirror is dead

This role used to point at `mirrors.apqa.cn`, pinned to `bookworm`. That host now
returns **HTTP 521 site-wide**, and `global.mirrors.apqa.cn` does not connect at
all — so the role could not have worked.

It now uses [PXVIRT](https://docs.pxvirt.lierfang.com/en/installfromdebian.html),
which is live and, unlike the old mirror, publishes for more than one release, so
the suite follows the host instead of being pinned:

```
Origin: Lierfang
Architectures: arm64 amd64 loong64      (trixie adds riscv64)
Components: main ceph-quincy ceph-reef ceph-squid
```

Verified in `ansible/tests/apt-sources/verify-tail.yml` on **both** bookworm and
trixie arm64: `apt-get update` returns 0 with the signature verifying, and
`proxmox-ve` is offered (candidate `8.3.1`).

## What it cleans up

Two generations of predecessor, removed **before** the new source is written so
the host is never left with two definitions of one repository and a `Signed-By`
conflict that blocks all apt:

- `pveport.list` and `trusted.gpg.d/pveport.gpg`, from this role's own earlier
  version;
- `pxvirt-sources.list` and `trusted.gpg.d/lierfang.gpg`, which is what following
  the vendor's install page by hand produces.

Both of those put their key in `trusted.gpg.d`, where it is trusted for **every**
repository on the host. The key now lives in `/etc/apt/keyrings/` and signs only
this one.

## It follows PXVIRT's documented procedure, not just its repository

The install steps come from the vendor's page, in its order:

| Step | Where |
| --- | --- |
| repository + key | `tasks/apt_repo.yaml` |
| `/etc/hosts` gets the host's own IP and name | `tasks/main.yaml` (pre-existing) |
| stop and disable NetworkManager | `tasks/main.yaml` |
| install `ifupdown2`, then delete `/etc/network/interfaces.new` | `tasks/main.yaml` |
| install `proxmox-ve pve-manager qemu-server pve-cluster` | `pve_install_arm_packages` |

`ifupdown2` is installed **before** the PVE packages and **after** NetworkManager
is stopped, which is the vendor's order and not incidental: `ifupdown2` takes
over `/etc/network/interfaces`, and leaving NetworkManager running means two
things manage the same interfaces. The NetworkManager task is conditional on the
service actually existing, so it is a no-op on an image that never had it.

Static addressing and the reboot that follows it are **not** automated — the
vendor's steps 4, 5 and 7 are manual, and the web UI still has to be used
afterwards to drop the original interface IP and create the bridge.

### Packages dropped

`postfix` and `open-iscsi` were installed by the previous version of this role,
inherited from the upstream x86 "Proxmox on Debian" guide. PXVIRT's page lists
neither, and neither is published by this repository, so they are no longer
installed. Add them in the calling playbook if a particular host needs them.

### The package set was checked, not copied

Every package was confirmed present for **arm64** in the repository's own
`Packages` index, on both suites:

```
bookworm  proxmox-ve 8.3.1  pve-manager 8.4.18-pxvirt2  qemu-server 8.4.8+pxvirt1  pve-cluster 8.1.2-1
trixie    proxmox-ve 9.0.0  pve-manager 9.0.10-2        qemu-server 9.0.22         pve-cluster 9.0.6
```

Note trixie gets **Proxmox 9**, which is why the suite follows the host's release
rather than staying pinned to bookworm as the old role was.

A trap when re-checking this: `dists/<suite>/main/binary-arm64/Packages.gz`
**404s** — only the uncompressed `Packages` is published. Fetching the `.gz` and
finding nothing reads exactly like an empty repository, and briefly did.
