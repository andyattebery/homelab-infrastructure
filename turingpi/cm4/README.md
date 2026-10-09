# Raspberry Pi CM4: turingpi-cm4-01

The CM4 (8 GB RAM, 32 GB eMMC) in Turing Pi 2 node 3, `turingpi-cm4-01`, runs Canonical's Ubuntu
Server for Raspberry Pi. This directory holds what makes that image this homelab's:
- the cloud-init seed;
- the script that writes the seed into the image before the BMC flashes it.

The research behind the choice is in
[research/turing-pi-cluster/cm4-os.md](../../research/turing-pi-cluster/cm4-os.md).

## Files

| Path | What |
|---|---|
| `cloud-init/user-data` | The first-boot settings every CM4 here gets. |
| `cloud-init/<hostname>/meta-data` | One per node: `instance-id` and `local-hostname`. |
| `scripts/seed-image.sh` | Writes both into a copy of Ubuntu's image, with `turingpi/scripts/write-seed.sh`. Prints its usage with `-h`. |
| `images/` | Gitignored. Seeded images, one directory per host. |

## Installing

Run the commands from the repo root.

1. **Check the EEPROM** on whatever OS the node runs. It must be dated 2022-11-25 or later, which
   Ubuntu's A/B boot (`piboot-try`) needs:
   `date -u -d @$(printf %d 0x$(od /proc/device-tree/chosen/bootloader/build-timestamp -v -An -t x1 | tr -d ' \n'))`
2. **Download** `ubuntu-<version>-preinstalled-server-arm64+raspi.img.xz` from
   `cdimage.ubuntu.com/releases/<version>/release/`.
3. **Seed it:** `turingpi/cm4/scripts/seed-image.sh turingpi-cm4-01 <the .img.xz>`. It needs mtools
   (`brew install mtools`).
   - It checks the download against Ubuntu's `SHA256SUMS`.
   - It writes `turingpi/cm4/images/turingpi-cm4-01/<name>.img.xz`, recompressed, and its `.sha`.
4. **Flash it:** `turingpi/scripts/flash-node.sh 3 turingpi/cm4/images/turingpi-cm4-01/<name>.img.xz`
   shows the nodes' power state. Add `--yes` to flash.
5. **Log in:** `ssh-keygen -R 192.168.1.218`, then `ssh services@192.168.1.218`.

**A new node:** add `cloud-init/<hostname>/meta-data`, then seed an image for it.

## What the seed does

- **Access:** the Jetson's ([../jetson/README.md](../jetson/README.md)).
  - User `services`, uid 1000, groups `sudo video render`.
  - Passwordless sudo that keeps `SSH_AUTH_SOCK`.
  - The keys from `nix/modules/ssh-keys.nix`, and no password.
  - Ubuntu's `ubuntu` user isn't created.
- **Settings:** `America/Chicago`, `en_US.UTF-8`, and a `127.0.1.1` entry for the hostname.
- **Network:** Ubuntu's own `network-config`, DHCP on `eth0`.
  - `runcmd` runs `netplan apply`. Without it the first boot never starts `systemd-networkd`,
    because the backend is chosen before cloud-init writes the netplan config. The node would then
    stay off the network until a reboot.
- **cloud-init runs once.** The last `write_files` entry disables it after the first boot.

## First-boot checks

Over ssh as `services`:

| Check | Expect |
|---|---|
| `cloud-init status --long` | `status: disabled` |
| `sudo cat /var/lib/cloud/data/result.json` | `"errors": []` |
| `hostname` | `turingpi-cm4-01` |
| `id services` | uid 1000, groups `sudo video render` |
| `getent passwd ubuntu` | nothing |
| `findmnt -no SIZE /` | about 29 G: the root grew to fill the eMMC |

## Traps

- **The keys are a copy** of `nix/modules/ssh-keys.nix`, as are the Jetson's `user-data.tpl` and
  `turingpi/rk1/cloud-init/user-data`. Nothing keeps them in step.
- **No password, so no console login** over `tpi uart`. Recovery is reflashing.
- **Edits to `/boot/firmware/user-data` after the first boot do nothing,** because cloud-init is
  disabled. Re-provisioning is reflashing.
- **An EEPROM older than 2022-11-25** leaves A/B kernel updates unapplied. CM4s disable in-OS EEPROM
  updates; the supported update is rpiboot (`cm4-os.md`, "EEPROM, whichever OS").
