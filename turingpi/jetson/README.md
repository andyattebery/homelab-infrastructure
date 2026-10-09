# Jetson Orin Nano: turingpi-jetson-01

The Orin Nano module (P3767-0005) in Turing Pi 2 node 4, `turingpi-jetson-01`, runs the generic
image from [jetson-orin-nano-l4t-minimal](https://github.com/andyattebery/jetson-orin-nano-l4t-minimal)
on its own microSD card. That image is NVIDIA's minimal Jetson Linux plus cloud-init, fwupd and
udisks2, with nothing of this homelab in it.

This directory holds what makes a card this homelab's: the cloud-init files written onto the card's
`CIDATA` volume, which apply at first boot. The NVMe holds data only: Ansible moves write-heavy
paths there (`ansible/roles/data_disk_offload`). So the OS is reinstalled by rewriting the card.
The research behind the image is in
[research/turing-pi-cluster/orin-nano-install.md](../../research/turing-pi-cluster/orin-nano-install.md).

## Files

| Path | What |
|---|---|
| `cloud-init/user-data.tpl` | The first-boot settings every Jetson card here gets. A 1Password template, rendered onto the card with `op inject`. |
| `cloud-init/<hostname>/meta-data` | One per node: `instance-id` and `local-hostname`. |
| `qspi-flash.md` | The module's first QSPI flash, with the EEPROM fix, from an x86-64 host. |
| `images/` | Gitignored. Downloaded release images. |

`tpi`, the Turing Pi BMC's CLI, comes from `turingpi/mise.toml` ([../README.md](../README.md)).

## Making a card

This needs the module's QSPI already at the image's L4T release and board config (R39.2.1,
`jetson-orin-nano-devkit-super`), with the Turing Pi EEPROM fix. The first flash is done once per
module, from an x86-64 host ([qspi-flash.md](qspi-flash.md)). After that, QSPI moves to each new
L4T release through apt on the running card ("Updating"). The image repo builds new L4T releases
automatically, but a card for one is written only after QSPI has that release.

Run the commands from the repo root.

1. Download the newest build of the node's QSPI release, R39.2.1. The newest release overall can
   be a newer L4T.
   ```
   gh release download "$(gh release list -R andyattebery/jetson-orin-nano-l4t-minimal --limit 1000 --json tagName --jq '[.[].tagName | select(startswith("R39.2.1-")) | ltrimstr("R39.2.1-") | select(test("^[0-9]+$")) | tonumber] | max | "R39.2.1-\(.)"')" \
     -R andyattebery/jetson-orin-nano-l4t-minimal --pattern '*.img.xz*' --dir turingpi/jetson/images
   ```
2. Check it: `(cd turingpi/jetson/images && shasum -a 256 -c <name>.img.xz.sha256)`.
3. Write the `.img.xz` to the card with balenaEtcher or your usual tool. In Raspberry Pi Imager,
   pick no OS customisation.
4. Re-insert the card. `CIDATA` mounts.
5. Render `user-data` onto it, which prompts 1Password once:
   `op inject -i turingpi/jetson/cloud-init/user-data.tpl -o /Volumes/CIDATA/user-data`.
6. Copy the node's `meta-data` onto it:
   `cp -X turingpi/jetson/cloud-init/turingpi-jetson-01/meta-data /Volumes/CIDATA/`.
7. Eject the card.
8. Put the card in the module, then power on: `mise -C turingpi exec -- tpi power on -n 4`.

**A new node:** add `cloud-init/<hostname>/meta-data` with its `instance-id` and `local-hostname`,
then make a card.

## What user-data does

- **Access:** as on the NixOS hosts (`nix/modules/base.nix`), except for the password.
  - User `services`, uid 1000, groups `sudo video render`.
  - Passwordless sudo that keeps `SSH_AUTH_SOCK`.
  - The keys from `nix/modules/ssh-keys.nix`, and no password logins.
  - No password at all, so there's no console login over the BMC UART. Recovery is rewriting the
    card.
- **Not fish, and no packages.** Ansible provisions the node: it installs fish and switches the
  shell.
- **Settings:** `America/Chicago`, `en_US.UTF-8`, and a `127.0.1.1` entry for the hostname.
- **NVIDIA's packages come from a private apt repo.** The module's QSPI has NVIDIA's firmware with
  the carrier-board EEPROM read turned off; NVIDIA's stock firmware hangs in MB2 on this board.
  Installing any `nvidia-l4t-bootloader` stages its capsule for QSPI, so the node takes that
  package, and the rest of each L4T release, from a repo whose bootloader carries the fixed
  firmware ([orin-nano-qspi-updates.md](../../research/turing-pi-cluster/orin-nano-qspi-updates.md)).
  - The repo is Forgejo's Debian registry (org `homelab`), built and published by the
    `jetson-orin-nano-l4t-bootloader` repo's workflow. Its URL contains the domain, which is why
    `user-data` is a 1Password template.
  - `write_files` adds the repo's source, its signing key and a pin. Everything the repo carries
    wins at 990, against NVIDIA's 600, and NVIDIA's own `nvidia-l4t-bootloader` never installs
    (-1).
  - `runcmd`'s last item is a check, `/usr/local/sbin/l4t-private-repo-check`. It runs
    `apt-get update`, then holds every installed `nvidia-l4t-*` package unless
    `nvidia-l4t-bootloader`'s candidate is the rebuild, whose version contains `+`. So a card that
    can't reach the repo stays locked.
  - The check runs near the end of the first boot, after NTP syncs. Until then nothing may run apt
    (Traps).
  - `bootcmd` sets `ENABLE_AUTO_QSPI_UPDATE="0"`. Until the first `apt upgrade`, the card has
    NVIDIA's own bootloader package, and the switch stops `nv-l4t-bootloader-config.service`
    installing its stock capsule when that package is newer than QSPI. `bootcmd` runs before
    `sysinit.target`, so the switch is off before that service first runs.
  - The pin and the check are tested with fixture repos in
    `ansible/tests/apt-sources/verify-l4t-pin.yml`.
- **No swap on the card.** `runcmd` removes the 2 GB `/swapfile` that NVIDIA's first-boot
  `nvfb-swapfile.service` makes. `data_disk_offload` puts swap on the NVMe.
- **cloud-init runs once.** The last `write_files` entry disables it after the first boot. Left
  enabled, it would read `CIDATA` on every boot:
  - edits there would do nothing unless `instance-id` changed;
  - deleting the files would make it treat the node as new and regenerate its SSH host keys.

## First-boot checks

Over ssh as `services`:

| Check | Expect |
|---|---|
| `cloud-init status --long` | `status: disabled`, from the marker. After a reboot it shows no errors, whatever the first boot did |
| `sudo cat /var/lib/cloud/data/result.json` | `"errors": []`, for the whole first boot |
| `cat /var/lib/cloud/instance/datasource` | `DataSourceNoCloud [seed=/dev/mmcblk0pN]` |
| `sudo grep -m1 'modules:final' /var/log/cloud-init.log` | The day's date, not 1970: the final stage waited for NTP |
| `hostname` | `turingpi-jetson-01` |
| `getent passwd services; id services` | uid 1000, shell `/bin/bash` until Ansible runs, groups `sudo video render` |
| `findmnt -no SOURCE,SIZE /` | `/dev/mmcblk0p1`, about the card's size |
| `apt-mark showhold` | nothing. A list of `nvidia-l4t-*` means the check didn't find the rebuild; its reason is in `/var/log/cloud-init-output.log` (Traps) |
| `apt-cache policy nvidia-l4t-bootloader` | Candidate `…+tp1` at 990; NVIDIA's versions at -1 |
| `sudo fwupdmgr get-devices` | lists "System Firmware" with no "Update Error". The bootloader package's install script exits 1 without the device. "Not updatable as UEFI ESP partition not detected" means udisks2 is missing, and staging would fail without a message |
| `grep ENABLE_AUTO_QSPI_UPDATE /opt/nvidia/l4t-bootloader-config/nv-l4t-bootloader-config.conf` | `"0"` |
| `swapon --show; ls /swapfile` | no swap, no file |
| `test -e /etc/cloud/cloud-init.disabled && echo yes` | `yes` |
| `cat /etc/nv_tegra_release /sys/class/dmi/id/bios_version` | R39.2.1 for both: card and QSPI match |

## Updating

QSPI and the rest of each L4T release arrive through apt. `jetson-orin-nano-l4t-bootloader`'s
workflow publishes each new NVIDIA release with the same major version by itself, from a daily
check at 04:41 Central time. After that, any `apt upgrade` on the node installs it and stages its
QSPI capsule, and the next reboot writes it.
1. Wait until the workflow has finished publishing the release (Traps).
2. `sudo apt update && sudo apt upgrade`.
3. Reboot. UEFI writes the new firmware to the non-current QSPI slot, switches to it and resets.
   If the node doesn't answer within about five minutes, it hangs on that reset: power-cycle it
   (`mise -C turingpi exec -- tpi power off -n 4`, then `tpi power on -n 4`). The new slot is
   already written, and it boots from a cold start.
4. `sudo nvbootctrl dump-slots-info` shows capsule update status 1 and the other slot current, and
   `sudo cat /etc/nv_tegra_release /sys/firmware/efi/esrt/entries/entry0/fw_version` shows the
   same release in both. `fw_version` is readable by root only, and is
   `(major<<16)|(minor<<8)|patch`: 2556417 is 39.2.1.

A new card's first `apt upgrade` installs the rebuild of the release QSPI already runs. Reboot
after it, as after any bootloader update.

## Traps

- **Until the first `apt upgrade`, never reinstall or reconfigure `nvidia-l4t-bootloader`.** The
  card then has NVIDIA's own package. Its install script stages the stock QSPI capsule with no
  version check, and `dpkg-reconfigure` re-runs it whatever apt's pins and holds say. Once the
  rebuild is installed, a reinstall or reconfigure re-stages the fixed capsule.
- **The card and QSPI must be the same release.** QSPI moves forward through `apt upgrade` on the
  running card ("Updating"), so update it before writing a card for a newer release.
- **Nothing may run apt on a new card until its first boot has finished**, because the check
  decides only at its end whether to hold NVIDIA's packages.
  - The finish is `/var/lib/cloud/data/result.json`, which cloud-init's final stage writes when it
    ends, after `runcmd`.
  - The marker `/etc/cloud/cloud-init.disabled` doesn't show it: it's written earlier in the same
    stage (`write_files_deferred` runs before `scripts_user`).
- **Run apt only after the workflow has finished, and never `dist-upgrade` while it runs.** The
  workflow publishes one package at a time. It runs every day at 04:41 Central time, and a run that
  finds a new release publishes it.
  - Mid-publish, `apt upgrade` keeps back everything tied to the bootloader by exact versions.
  - `apt dist-upgrade`, `full-upgrade` and the `system_upgrade` role remove `nvidia-l4t-bootloader`
    and `nvidia-l4t-bsp` instead, to move the rest. Later upgrades don't reinstall them, so QSPI
    would stop getting updates.
  - `ansible/tests/apt-sources/verify-l4t-pin.yml` shows both.
- **If the check held the packages,** its reason is in `/var/log/cloud-init-output.log`. Fix the
  cause (the network, the repo's URL or its key), then run
  `sudo apt-mark unhold '?and(?installed,?name(^nvidia-l4t-))'`.
- **No dollar signs in `user-data.tpl`.** `op inject` replaces a dollar sign followed by a name
  with that environment variable.
- **Edits to `CIDATA` after the first boot do nothing**, because cloud-init is disabled.
  Re-provisioning is rewriting the card.
- **`network-config` on `CIDATA` is ignored.** NVIDIA turns off cloud-init's networking, and
  NetworkManager runs DHCP. The address comes from the DHCP reservation for the node's MAC.
- **The keys are a copy.** `user-data.tpl` holds the keys from `nix/modules/ssh-keys.nix`; a key
  changed there must be changed here too. Nothing enforces it.
- **The BMC's UART doesn't show this module's boot.** `tpi uart -n 4 get` returns only a few bytes
  through a complete boot. A node that doesn't come back can only be judged by ssh, ping and
  `tpi power status`.
- **Cooling and power.** The module needs its heatsink and fan. Whether a slot holds 25 W isn't
  verified; if the module throttles or browns out, use a lower `nvpmodel` mode.
