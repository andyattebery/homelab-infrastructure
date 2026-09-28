# NixOS findings for pi-rack on a Raspberry Pi

Verified 2026-09-25 against this repo (nixos-raspberrypi pinned at
`7e39508bcf9c1da82cf11c1e22f74f9d9fd0fe10`, nixpkgs nixos-26.05, working-tree `flake.lock` at
nixpkgs `c508844`). **[E]** means read-only `nix eval` / `build --dry-run` output via
`nix/scripts/nix-shell.sh`, **[S]** means source at the pinned revs, and **[I]** marks inference.

## Existing defect: keepalived binds a nonexistent `eth0`

- [E] pi-rack evaluates `networking.usePredictableInterfaceNames = true`, and `boot.kernelParams`
  has no `net.ifnames=0`: `console=serial0,115200n8 console=tty1 root=fstab loglevel=7
  lsm=landlock,yama,bpf`.
- [S] The Pi DTs alias the NIC:
  - Pi 4: `ethernet0 = &genet;` in `bcm2711-rpi.dtsi:15` (raspberrypi/linux rpi-6.18.y).
  - Pi 5: the RP1 `cdns,macb` controller (rp1.dtsi:1001) aliased `ethernet0`
    (`bcm2712-rpi.dtsi:127`).
- [S] systemd v252+ names platform devices with a DT alias as `<prefix>d<index>`
  (systemd.net-naming-scheme, v252 entry). nixos-26.05 ships systemd 260.4.
- [I] So the NIC comes up **`end0`**, and `homelab.network.keepalived.interface = "eth0"`
  (`nix/hosts/pi-rack/default.nix:52`) binds nothing. pi-rack would never join VRRP, on any Pi.
- Ubuntu kept `eth0` via `net.ifnames=0` on its cmdline.
- **Fix options:**
  - `networking.usePredictableInterfaceNames = false;`. [E] It adds `net.ifnames=0` to
    `boot.kernelParams` (udev.nix:441).
  - **Implemented 2026-09-25 instead:** a MAC pin, `systemd.network.links."10-genetp0"`
    (`MACAddress=` → `Name=genetp0`), as `pve_pin_network_interface` does on the Proxmox nodes,
    with keepalived on `genetp0`. The MAC comes from `vars.network-02.nicMacAddress` =
    `op://Home Lab/pi-rack/hardware/mac address`.

## config.txt as evaluated (pi-rack, Pi 4 board module)

- `[all]` options: `arm_64bit=1`, `arm_boost=1`, `avoid_warnings=1`, `camera_auto_detect=1`,
  `disable_fw_kms_setup=1`, `disable_overscan=1`, `display_auto_detect=1`, **`enable_uart=1`**,
  `kernel=kernel.img`, `max_framebuffers=2`, `os_prefix=nixos/default/`. Overlay `vc4-kms-v3d`.
- dt-params: `audio` + `poe_fan_temp0..3`.
- `[cm4]`: `otg_mode=1`. `[cm5]`: overlay `dwc2`.
- `arm_64bit=1` means `kernel=kernel.img` boots 64-bit. The `poe_fan_temp*` params belong only to
  the `rpi-poe-plus` overlay (overlays README 4583-4603) and do nothing without that HAT.

## Building a flashable image from pi-rack's own config

- [S] `nixosModules.sd-image` = `modules/installer/sd-card/sd-image-raspberrypi.nix`
  (flake.nix:106):
  - imports nixpkgs `profiles/base.nix` and `sd-image.nix`
  - `firmwareSize = 1024`
  - populates FIRMWARE with the configured bootloader's builder
  - sets `/boot/firmware` to `noauto` + `x-systemd.automount` + idle-timeout 1 min
  - forces bootloader `kernel` only for variant "5"
- Labels come from nixpkgs defaults: FIRMWARE / NIXOS_SD. MBR layout, 8 MiB offset, zstd,
  `expandOnBoot = true`.
- [E] `nixosConfigurations.pi-rack.extendModules { modules = [ sd-image ]; }` **fails**: "The kernel
  module and the userspace tooling versions are not matching" (zfs.nix:670-671).
  `profiles/base.nix` enables ZFS; the kernel's zfs is 2.4.3 (nixos-raspberrypi's nixpkgs) and the
  userland is 2.4.4 (ours).
- [E] Adding `{ boot.supportedFilesystems.zfs = lib.mkForce false; }` makes it evaluate:
  - dry-run 482 built / 708 fetched, 1.7 GiB; kernel fetched
  - image names `nixos-image-rpi4-kernel.img.zst` / `nixos-image-rpi5-kernel.img.zst`
- [S] With `bootloader = "kernel"`, FIRMWARE gets `start*.elf`, `fixup*.dat`, `config.txt` and
  `nixos/default/{kernel.img,initrd,cmdline.txt,*.dtb,overlays}`, with `kernel=kernel.img` and
  `os_prefix=nixos/default/`. There is no U-Boot in that chain.
- [I] The image's system is not the deploy target (automount, base profile, expand service), so
  the first `deploy-host.sh` replaces it.
- [I] The image embeds values rendered from `vars.nix` (domain, AdGuard hash, UPS SNMP community).
  Treat the `.img.zst` as sensitive.

## First boot without the sops age key

- [E] userborn and sysusers are both false, so users come from `update-users-groups.pl`.
- [S] A missing password file only warns, and new shadow entries get `"!"` (:241-247, :307-315).
  Activation has no `set -e` (activation-script.nix:17-24), so boot continues.
- [S] SSH key login still works: `UsePAM` true (sshd.nix:522-525), and OpenSSH 10.5p1 `auth.c:108`
  checks locked accounts only `if (!options.use_pam && …)`. PAM `pam_unix` checks expiry, not the
  hash. Authorized keys live in `/etc/ssh/authorized_keys.d/%u`, outside sops.
- [I] Passwordless sudo also works. All 13 secrets are missing until the key is installed and
  activation re-runs.
- Today `.sops.yaml` has 3 recipients (`operator`, `network-01`, `network-03`). An image built
  before `add-sops-recipient.sh pi-rack` cannot decrypt even once the key is installed.
- [S] Install the key as `services@…`, not `root@…`: a system built from this flake's
  `base.nix` sets `PermitRootLogin = "no"` (base.nix:54). `host-age-key.sh` escalates with
  sudo, which wheel gets without a password (base.nix:45).

## The upstream `rpi4-installer` is not a headless path

- [S] The `nixos` user and root have empty passwords. nixos-images sets `PermitRootLogin = "yes"`
  plus a random xkcdpass root password on every activation, shown only on the console / QR.
  Hostname `nixos-installer`, mDNS.
- [E] bootloader `uboot`, mutableUsers true, no keys. Its toplevel is **built**, not cached (274
  built / 566 fetched) at `7e39508`. No `services` user, so `deploy-host.sh` can't target it.

## Remote build on the Pi (`remoteBuild = true`)

- [E] The pi-rack toplevel is 447 built / 628 fetched (1.7 GiB download, 3.4 GiB unpacked).
  - Fetched: the kernel `linux_rpi-bcm2711-6.18.34-unstable_20260604` and its `-modules`.
  - Built: the `-modules.drv` buildEnv, `-modules-shrunk`, and the initrd.
- Real compiles on the Pi: `sops-install-secrets` (Go 1.26.7) and `raspberrypi-utils` (cmake).
- The host's caches (`nixosModules.trusted-nix-caches`): nixos-raspberrypi.cachix.org +
  cache.nixos.org.

## Pi 5 variant of pi-rack (evaluated without editing repo files)

- Method: rebuilt `mkHost` via `builtins.getFlake`, swapping import 2 of the host file for
  `raspberry-pi-5.base`. Positive control: the unmodified host built this way gives the same
  drvPath as `nixosConfigurations.pi-rack`.
- [E] Results:
  - variant "5"; bootloader `kernel` (explicit in the host), `warnings: []`
  - `useGenerationDeviceTree` true; `configurationLimit` 4
  - kernel `linux_rpi-bcm2712-6.18.34-unstable_20260604`, **fetched** from cachix
  - initrd includes `nvme`, `pcie_brcmstb`, `reset-raspberrypi`, `usb_storage`, `xhci_pci`
- [E] Closure: 447 built / 634 fetched from an empty store, **3.41 GiB** NarSize total. The largest
  items: `linux-firmware-zstd` 810 MiB, gcc 248, go 212, python3 131, kernel modules 117. About
  603 MiB is build tools that land because of `remoteBuild`.
- Minimal source diff:
  - `default.nix:12` → `raspberry-pi-5.base`
  - the `:24-28` comment goes stale (the Pi 5 default is the deprecated `kernelboot`, loader
    default.nix:338, 437-452)
  - delete PoE `:31-42`
  - add `pciex1` + `usePredictableInterfaceNames = false`
  - the combined change evaluates with `warnings: []`; config.txt gains `dtparam=pciex1`
- `page-size-16k` isn't needed (nixpkgs 26.05 builds jemalloc for 64 KiB pages on aarch64).
  `display-*` modules only add Xorg config.
- `pciex1` is off by default on Pi 5 (overlays README:379-380), `nvme` is an alias, and
  `pciex1_gen` defaults to 2.
- [S] nixpkgs `raspberrypi-eeprom` 2026.05.11-2712 (not unfree) wraps flashrom, pciutils and
  binutils on PATH (package.nix:51-62). It finds `/boot/firmware/config.txt` and flashes via
  flashrom on Pi 5. The flake itself doesn't ship it or manage the EEPROM (#239, request #91 open).

## Disk-size note (only if a 16 GB drive were used)

- An Optane M10 16 GB reports 13.41 GiB.
- [I] Three generations plus an in-flight remote build plus the journal come to ≈ 10 GiB. It fits
  without the 4 GiB swapfile (`rpi4.nix:30`), not reliably with it.
- FIRMWARE: 4 generations × ~53 MB + 21 MB shared.

## nixos-raspberrypi issues relevant to Pi NVMe

| Issue | State | Summary |
|---|---|---|
| #159 | open | No supported NVMe install flow. Users ran `nixos-install --no-bootloader` + the sd-image populate commands; one needed `dtparam=nvme` |
| #121 | closed 2025-12-14 | Pi 5 with a 2023 EEPROM failed to boot with `kernel`; `rpi-eeprom-update -a` fixed it |
| #117 | closed | error 45 = a drive on RPi's unsupported list |
| #83 | — | RPi4 image flashed to a USB-SATA SSD, booted and SSH'd |
| #60 | open | `kernel` is "the only fully-supported option for RPi5" |
| #181 | open, no replies | CM4 on the IO Board with the U-Boot installer image: crashes, no Ethernet |

- [I] sd-image.nix:403 takes the root partition number from `lsblk` MAJ:MIN, which is only right
  on the first disk. Keep one disk attached for the first boot.
