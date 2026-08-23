# realtek_dkms

Installs a Realtek DKMS driver (`r8125`, `r8126`, or `r8152`) via the best
available method for the host's distribution and architecture.

## Strategy

For the chosen `realtek_dkms_driver`:

1. **Official package** — if `<driver>-dkms` is in any enabled apt source
   (e.g. Debian non-free or Ubuntu multiverse), install via apt. For
   `r8125`, the role idempotently enables non-free / multiverse via a
   dedicated deb822 `.sources` file (never touches existing sources).
2. **github_deb** (Debian, amd64) — download `realtek-<driver>-dkms_<tag>_amd64.deb`
   from `awesometic/realtek-<driver>-dkms` releases and `apt install` it.
3. **PPA** (Ubuntu, amd64) — add `ppa:awesometic/ppa` and `apt install
   realtek-<driver>-dkms`.
4. **Source build** (any other arch) — fall back to the awesometic source
   tarball + `dkms-install.sh`.

Before installing, the role:

- Auto-detects the kernel / headers meta packages for the host (Proxmox VE,
  Raspberry Pi OS bookworm+, legacy Pi OS, vanilla Debian, vanilla Ubuntu)
  and bumps them to latest.
- Reboots into the newer kernel if one was installed but isn't running, so
  DKMS builds against the kernel it'll actually run on.
- Installs running-kernel headers as a safety net for vanilla Debian/Ubuntu.

After installing, for PCIe drivers (`r8125`, `r8126`) the role drops a
udev rule that re-binds matching cards from the kernel's `r8169` to the
DKMS driver and re-triggers udev so the swap takes effect without a
manual reboot.

## Required variables

| Var                     | Allowed values                  |
|-------------------------|---------------------------------|
| `realtek_dkms_driver`   | `r8125` \| `r8126` \| `r8152`   |

## Optional overrides

- `realtek_dkms_kernel_metas` — explicit list of kernel + headers meta
  packages, when auto-detection isn't right (e.g. Ubuntu HWE/cloud).
- `realtek_dkms_pci_vendor`, `realtek_dkms_pci_devices` — chip-level PCI
  IDs the udev rule matches. Defaults are taken from the awesometic source
  PCI tables; override per host for board-specific subsystem-level
  matching.

## Caveats

- The `enable_apt_component.yaml` step no longer writes a source
  unconditionally. It writes one **only when no other active apt source already
  enables the component**, and removes its own file when one does. See "Why the
  component drop-in is conditional" below — making it unconditional again breaks
  apt on Debian 13.
- The drop-in is the host's own archive source re-emitted with `Components:`
  swapped, so `URIs:`, `Suites:` and `Signed-By:` are copied rather than
  constructed. A host on a private mirror therefore gets a drop-in pointing at
  **its own mirror**, not at upstream. Only a host with no deb822 archive source
  to copy from falls back to constructed values.
- The `github_deb` and `ppa` paths only support amd64 (awesometic only
  ships an `_amd64.deb` and the PPA is amd64). Non-amd64 hosts fall
  through to the source build.

## Why the component drop-in is conditional

`enable_apt_component.yaml` used to write `realtek-dkms-<component>.sources`
every run, on the stated assumption that apt would deduplicate it against the
host's own sources. It does not, and the consequence depends on the release:

Which symptom you get depends on the keyring the host's own `debian.sources`
names — **not** on the Debian release, which is the trap:

| Host shape | Symptom |
| --- | --- |
| Debian 12, or **Proxmox VE 9** (trixie, but its installer writes `debian-archive-keyring.gpg`) | `Warning: Target Packages (non-free/binary-amd64/Packages) is configured multiple times in debian.sources and realtek-dkms-non-free.sources`. Noise on every apt run; apt still works. This is what the PVE fleet sees. |
| Stock Debian 13 (writes `debian-archive-keyring.pgp`) | `E:Conflicting values set for option Signed-By ... .pgp != .gpg` / `E:The list of sources could not be read`. **`apt-get update` exits 100** and nothing on the host can install a package until the file is removed. |
| Ubuntu | Stock Ubuntu already ships `multiverse` enabled, so the file was always redundant there. |

Both `.gpg` and `.pgp` exist on trixie and hold the same key. apt compares the
**strings**, so a host is fine or fatally broken purely on which spelling its
installer happened to choose.

All three shapes are reproduced in `ansible/tests/apt-sources/repro.yml` — including
an `apt-test-pve9` leg that matches the real fleet — and the fix is verified in both
directions on every leg by `verify-realtek.yml`.

Three values used to be hardcoded and each was wrong somewhere:

- **`Signed-By`** — stock Debian 13 signs with `debian-archive-keyring.pgp`;
  Debian 12 has only `.gpg`; Proxmox VE 9 is trixie but uses `.gpg`. No rule based
  on release gets all three right, which is why the value is copied from the host.
- **`URIs`** — Ubuntu on arm64 serves `ports.ubuntu.com/ubuntu-ports`, not
  `archive.ubuntu.com/ubuntu`, which 404s every index.
- **`Suites`** — differ per release, and security is a separate stanza with its
  own suite list.

Copying the host's stanzas removes all three as a class. The role now touches
apt only when it has something to add, and cleans up after itself when it does
not, so a host where the component is enabled by `debian_extra_components` (as
`playbook-prod-proxmox-cluster.yaml` does) self-heals on the next run.

**Known limitation:** detection is per *file*, not per *stanza*. A sources file
holding several stanzas where only some are `Enabled: no` is judged by the whole
file. No host in this repo is in that shape, and the failure mode is a redundant
drop-in rather than a missing one.
