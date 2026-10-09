# Turing RK1 nodes

Flashing the Turing RK1 nodes, in Turing Pi 2 slots 1 and 2, with a generic image from
[rk1-armbian-minimal](https://github.com/andyattebery/rk1-armbian-minimal): Debian 13 (`trixie`) or
Ubuntu 26.04 (`resolute`) on Rockchip's vendor kernel, with the most RK1 hardware support (GPU, NPU,
video). Each release carries both images. Nothing of this homelab is in them. First boot is
cloud-init, from the seed in `cloud-init/`, which the flash script writes into the image. Armbian's
first-login setup doesn't run.

## Files

| Path | What |
|---|---|
| `cloud-init/user-data` | The first-boot settings every RK1 here gets. |
| `cloud-init/<hostname>/meta-data` | One per node: `instance-id` and `local-hostname`. |
| `scripts/flash-latest-release.sh` | Downloads one image of the latest release, writes the node's seed into it, and flashes it to node 1 or 2. Prints its usage with `-h`. |
| `images/` | Gitignored. The script's downloads, in `<tag>/trixie/` or `<tag>/resolute/`; the seeded copies, in `<hostname>/` under those; and images from earlier downloads and local builds. |

## Flashing a node

From the repo root:
1. `turingpi/rk1/scripts/flash-latest-release.sh <node> <trixie|resolute>`:
   - downloads that image of the latest release into `turingpi/rk1/images/<tag>/<trixie|resolute>/`
     and checks it against its `.sha`. Each image of a release is downloaded only once.
   - writes the node's seed into a copy, recompressed, in `<hostname>/` under that directory, with
     [../scripts/write-seed.sh](../scripts/write-seed.sh). It needs mtools (`brew install mtools`).
     The copy is rewritten on every run, so it always holds the current seed.
   - shows the nodes' power state.
2. Run it again with `--yes` added to flash: it seeds again, powers the node off, writes the seeded
   image through [../scripts/flash-node.sh](../scripts/flash-node.sh), and powers the node on. About
   10 minutes in all.
3. Forget the node's old host key: `ssh-keygen -R <ip>`, with the node's IP from
   [../nodes.md](../nodes.md).
4. Log in: `ssh services@<ip>`.

**A new node:** add `cloud-init/<hostname>/meta-data`. The script seeds node N as `turingpi-rk1-0N`.

## What the seed does

- **Access:** the CM4's and the Jetson's ([../cm4/README.md](../cm4/README.md)).
  - User `services`, uid 1000, groups `sudo video render`.
  - Passwordless sudo that keeps `SSH_AUTH_SOCK`.
  - The keys from `nix/modules/ssh-keys.nix`, and no password.
  - The distro's default user (`ubuntu` or `debian`) isn't created.
  - Root has no password. The image gives it `1234`; `runcmd` replaces the hash with `*`.
- **Settings:** `America/Chicago`, `en_US.UTF-8`, and a `127.0.1.1` entry for the hostname.
- **Network:** the image's own, Armbian's DHCP on every Ethernet port. The image turns cloud-init's
  networking off.
- **cloud-init runs once.** The last `write_files` entry disables it after the first boot.

## First-boot checks

Over ssh as `services`:

| Check | Expect |
|---|---|
| `cloud-init status --long` | `status: disabled` |
| `sudo cat /var/lib/cloud/data/result.json` | `DataSourceNoCloud` from `/dev/mmcblk0p1`, `"errors": []` |
| `hostname` | `turingpi-rk1-0N` |
| `id services` | uid 1000, groups `sudo video render` |
| `getent passwd ubuntu debian` | nothing |
| `sudo passwd -S root` | `L`: no usable password |
| `sudo journalctl -b -t CRON` | `(root) CMD` lines, and no "Authentication token is no longer valid" |
| `findmnt -no SOURCE,FSTYPE /boot` | `/dev/mmcblk0p1 vfat` |
| `findmnt -no SIZE /` | about 28 G: the root grew to fill the eMMC |
| `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` | the same fingerprint after a reboot |

## Traps

- **The keys are a copy** of `nix/modules/ssh-keys.nix`, as are the Jetson's `user-data.tpl` and
  the CM4's `user-data`. Nothing keeps them in step.
- **The serial console logs root in by itself,** with no password (Armbian's autologin), over
  `tpi uart`. It's the way in when ssh isn't. Anyone with the BMC login has it, and could reflash the
  node anyway.
- **Root's password must not be expired.** cron then refuses every root job, including Armbian's log
  truncation (rk1-armbian-minimal's Traps).
- **`/boot` is FAT,** the image's `armbi_boot` partition, which cloud-init reads the seed from.
- **Edits to `/boot/user-data` after the first boot do nothing,** because cloud-init is disabled.
  Re-provisioning is reflashing.
