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

- The `enable_apt_component.yaml` step writes a `.sources` file pointing
  at `deb.debian.org` / `archive.ubuntu.com`. Hosts using a private mirror
  will end up with an extra source talking to upstream — functional but
  suboptimal.
- The `github_deb` and `ppa` paths only support amd64 (awesometic only
  ships an `_amd64.deb` and the PPA is amd64). Non-amd64 hosts fall
  through to the source build.
