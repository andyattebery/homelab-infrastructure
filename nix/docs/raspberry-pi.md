# Raspberry Pi on NixOS

Research and decisions for running NixOS on Raspberry Pi hardware in this homelab. Written
2026-08-07 against nixpkgs `nixos-26.05`.

**Status.** Two hosts run this flake's config, both deployed with `deploy-host.sh`, both on
`bootloader = "kernel"`, and both with the kernel from the nixos-raspberrypi cache rather than
compiled. Each image comes from `nix/scripts/build-image.sh <host>`
(`packages.aarch64-linux.<host>-image`); the first deploy replaces the image's system.
- `pi-rack`, since 2026-09-25: a Compute Module 4 (8 GB RAM, 32 GB eMMC) on a Waveshare
  CM4-IO-BASE, with root on the eMMC. Its Pi 4 died on 2026-09-24 when its USB-SATA enclosure
  failed; see `research/pi-rack-boot-drive/`.
- `pi-turntable`, since 2026-10-20: a Raspberry Pi 4 Model B (4 GB) with root on a microSD, on
  Wi-Fi only. Its image carries the Wi-Fi password; see "Wi-Fi-only hosts".

## Decision

**Use [`nvmd/nixos-raspberrypi`](https://github.com/nvmd/nixos-raspberrypi), not `nixos-hardware`'s
Raspberry Pi module.**

| | |
|---|---|
| License | MIT |
| Activity | 621★ / 72 forks; 45 / 19 / 14 commits in Jun / Jul / Aug 2026 |
| nixpkgs | pins `nixos-26.05` — the same release this flake tracks |
| Bus factor | **1** — nvmd has 523 commits, the next contributor 13 |
| Kernel cache | `https://nixos-raspberrypi.cachix.org`, verified live |

The bus factor is real but the failure mode is mild: a flake input is pinned in `flake.lock`, so
upstream going quiet **freezes** you at a working revision rather than breaking anything. The risk is
staleness (eventually no kernel updates), not an outage.

## Why not `nixos-hardware`

It is actively maintained — commits through 2026-07-13, kernel 6.18.34, and `common/firmware.nix`
only landed 2026-05-29 — and its maintainers have diagnosed the design problem correctly. It is
simply not there yet:

- **No cached kernel, structurally.** `raspberry-pi/common/kernel.nix` is a `buildLinux` of
  `raspberrypi/linux` tag `stable_20260609` with `mkForce` config overrides (`NR_CPUS`,
  `CMA_SIZE_MBYTES`, `PREEMPT*`), making it a distinct derivation from anything nixpkgs ships.
  cache.nixos.org only carries Hydra's nixpkgs/nixos jobsets. PR
  [#1277](https://github.com/NixOS/nixos-hardware/pull/1277), which would add a Hydra jobset for
  these kernels, has been open since **2024-12-16**. Every kernel bump compiles locally — hours on a
  build host, far longer on the Pi itself.
- **`hardware.raspberry-pi."4".poe-plus-hat` is slated for removal.** Issue
  [#1946](https://github.com/NixOS/nixos-hardware/issues/1946): *"Migrate the Pi 4 modules to the new
  API, then remove the custom `dtmerge` backend and Pi-specific `hardware.deviceTree.overlays`
  usage."* That module is the main reason one would pick nixos-hardware for a PoE+ HAT host.
- **Its SD image does not boot as configured.** `raspberry-pi/common/firmware.nix` contains
  `sdImage.populateFirmwareCommands = lib.mkForce …` inside
  `lib.optionalAttrs (options ? sdImage)`, so importing any sd-image module replaces nixpkgs'
  firmware population — which copies `u-boot-rpi4.bin` and writes `[pi4] kernel=u-boot-rpi4.bin`.
  The replacement copies U-Boot only under `lib.mkIf cfg.uboot.enable`, and
  `hardware.raspberry-pi.firmware.uboot.enable` is a plain `mkEnableOption`, **off by default**.
  Result: a firmware partition with no `kernel=` line and no U-Boot binary, so the GPU firmware looks
  for a nonexistent `kernel8.img`.

### The two projects are converging

Same person driving both. JamieMagee is nixos-raspberrypi's #2 contributor and the author of
nixos-hardware [#1788](https://github.com/NixOS/nixos-hardware/pull/1788) (the `config.txt` module —
**merged**), #1839/#1840/#1841 (kernel package fixes), and #1946/#1947 (device-tree overlay
unification, in review). His stated goal, from nixos-raspberrypi issue
[#78](https://github.com/nvmd/nixos-raspberrypi/issues/78): *"I don't want to fragment the Raspberry
Pi NixOS userbase any further."*

**But the bootloader may never upstream.** From the same thread:

> "The actual bootloader module (`boot.loader.raspberry-pi`) is a different story, and yeah, that one
> would bump into samueldr's position on non-standard boot methods. I haven't tried to port that."

So "wait until nixos-hardware is sufficient" has an unresolved blocker, on top of the caching one.

### `tstat/raspberry-pi-nix` — rejected

Redirects to `nix-community/raspberry-pi-nix`, which reports `"archived": true`. Last commit
2025-03-17, pinning `nixos-24.11` — archived before 25.05 shipped. Its advertised
`nix-community.cachix.org` kernel cache was fed by nix-community's buildbot, whose current
`repoAllowlist` excludes it; issue #126 "Cachix not working" is open and unresolved. Its default
bootloader mode is also direct firmware kernel boot with no generations and no rollback.

## Integration rules

All four fail **silently** — nothing errors, you just quietly lose the benefit.

### 1. Do not add `inputs.nixpkgs.follows`

```nix
# Every other input in this flake follows nixpkgs. This one must not: kernel and firmware
# come from nixos-raspberrypi's own locked nixpkgs, so following ours produces different
# derivations, rebuilds the kernel from source, and misses the cache entirely.
nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi/main";
```

### 2. `specialArgs.nixos-raspberrypi` is mandatory

With a plain `nixpkgs.lib.nixosSystem`, the flake reference must be passed through `specialArgs` —
`modules/raspberry-pi-4.nix` reads `nixos-raspberrypi.packages.${pkgs.stdenv.hostPlatform.system}`
directly for its kernel and firmware. Also import `nixos-raspberrypi.lib.inject-overlays`, which adds
the `bootloader`, `vendor-kernel`, `vendor-firmware`, `kernel-and-firmware` and `vendor-pkgs`
overlays.

Their `lib.nixosSystem` wrapper does this for you; `lib.nixosSystemFull` additionally pulls
`inject-overlays-global`, which the upstream source marks *"causes _lots_ of rebuilds for graphical
stuff via ffmpeg, pipewire"* — not wanted for a headless server.

### 3. Remove `nixos-hardware.nixosModules.raspberry-pi-4` from the host

The two are mutually exclusive. Both set `boot.kernelPackages` with `mkDefault` to different values:

- nixos-hardware: `lib.mkDefault (pkgs.linuxPackagesFor (pkgs.callPackage ../common/kernel.nix { rpiVersion = 4; }))`
- nixos-raspberrypi: `lib.mkDefault nixos-raspberrypi.packages.${system}.linuxPackages_rpi4`

Equal priority, different values, so this is a **hard conflicting-definition error**, not a
last-one-wins override (see the merge semantics below). Confirmed independently upstream by
quentinmit in issue #78: *"If you try to use both, you get a conflict on `boot.kernelPackages`
because they both try to set it."*

`nixos-hardware` remains a flake input for the x86 hosts — only the Pi module is dropped.

### 4. Configure the binary cache explicitly

A flake's `nixConfig.extra-substituters` is **not** honoured automatically: `accept-flake-config`
defaults to `false`, and Nix prompts otherwise. `nix/scripts/nix-shell.sh` ends in a
non-interactive `sh -c "nix $ARGS"`, so the prompt cannot be answered and the substituter is silently
skipped — the kernel then builds from source anyway, defeating the reason for choosing this flake.

Add to `nix-shell.sh`'s `NIX_CONFIG`:

```
extra-substituters = https://nixos-raspberrypi.cachix.org
extra-trusted-public-keys = nixos-raspberrypi.cachix.org-1:4iMO9LXa8BqhU+Rpg6LQKiGa2lsNh/j2oiYLNOQ5sPI=
```

For the host side, the flake ships `nixosModules.trusted-nix-caches`.

**Verify it took** before building anything real:

```sh
nix/scripts/nix-shell.sh build --dry-run \
  .#nixosConfigurations.pi-rack.config.system.build.toplevel
```

The kernel must appear under *"will be fetched"*, not *"will be built"*. Read the two lists
carefully — `linux_rpi-bcm2711-<ver>` and `-modules` are fetched, while
`-modules-shrunk.drv` and `initrd-….drv` legitimately appear under *built*: those are host-specific
derivations that depend on the kernel, not the kernel compile. Confirmed on 2026-08-07: 441 built,
672 fetched (2.5 GiB), kernel among the fetched.

## How it boots

`boot.loader.raspberry-pi.bootloader` has three modes:

| Mode | What it does |
|---|---|
| `uboot` | **Pi 4 default** (`modules/raspberry-pi-4.nix:13`). `config.txt` gets `kernel=u-boot-rpi-arm64.bin`; the GPU firmware chainloads U-Boot, which reads `extlinux.conf`. Generations live on the ext4 root. |
| `kernel` | Generational direct firmware boot. Each generation gets its own directory on the firmware partition (`os_prefix`) with matched kernel, initrd, cmdline, DTBs and overlays. |
| `kernelboot` | Legacy direct boot, deprecated, emits a build warning. |

**Both Pi hosts use `kernel`, overriding the board default.** The reason is rollback. Upstream issue #60,
and the `useGenerationDeviceTree` option's own docs (`default.nix:295-298`), both state that
`kernelboot` and `uboot` *"don't effectively distinguish between nixos-generations on the level of
FIRMWARE"*: the FAT partition holds **one** set of DTBs, overlays and `u-boot.bin`, so a rollback
across a kernel change can fail on a DTB mismatch even though the older kernel is still present.
For a host that is rarely touched, reliable rollback is the main reason to run NixOS at all.

Costs: `configurationLimit` defaults to 4, and each generation copies kernel + initrd + DTBs +
overlays onto FAT with no symlinks — which is what the `sd-image` module's `firmwareSize = 1024`
budget is for.

Choosing `kernel` also flips `useGenerationDeviceTree` to `true`
(`default.nix:287`: `default = if cfg.bootloader == "kernel" then true else false`). That is
intended — per-generation DTBs are the point — and it is **not** the same hazard as trap 1 below,
which is specific to the `uboot` builder.

### The firmware partition is rewritten on every switch

`system.build.installBootLoader` is wired to the U-Boot builder
(`modules/system/boot/loader/raspberrypi/default.nix:570`), and nixpkgs'
`switch-to-configuration-ng` calls it for both `switch` and `boot`. So `config.txt`, all `*.dtb`,
`overlays/`, `u-boot.bin` and `extlinux.conf` track generations under `deploy-rs` — no re-imaging
needed for config changes.

**`/boot/firmware` must be mounted and writable at activation.** The builder prunes: any `.dtb` or
`overlays/*` it did not write this run is deleted. A missing or wrong mount therefore breaks boot
silently — that is upstream issue [#120](https://github.com/nvmd/nixos-raspberrypi/issues/120), whose
resolution was *"you definitely don't have the `FIRMWARE` specified, so the boot files are getting
installed in the wrong place."*

### Filesystems are the host config's job

The flake declares **no** `fileSystems` — grepping its tree for `mmcblk`, `by-label`, `NIXOS_SD` or
`by-uuid` returns nothing. That is deliberate: it does not assume SD, so USB/SATA/NVMe roots work,
but the layout must be stated explicitly.

For an image-based install, the labels come from nixpkgs' `sd-image.nix`
(`rootVolumeLabel = "NIXOS_SD"`, `firmwarePartitionName = "FIRMWARE"`):

```nix
fileSystems."/" = { device = "/dev/disk/by-label/NIXOS_SD"; fsType = "ext4"; };
fileSystems."/boot/firmware" = {
  device = "/dev/disk/by-label/FIRMWARE";
  fsType = "vfat";
  options = [ "nofail" ];   # NOT noauto — see above
};
```

Their demo repo (`nvmd/nixos-raspberrypi-demo`, `disko-usb-btrfs.nix`) uses a different three-partition
GPT layout for USB installs: `FIRMWARE` (1 GiB vfat, `/boot/firmware`), a separate `/boot` (1 GiB
vfat) carrying **GPT attribute 2, Legacy BIOS Bootable** — which is how U-Boot locates
`extlinux.conf` — and root. Either works; do not mix them.

### Kernel and firmware are version-bundled

`pkgs.linuxAndFirmware.default` is currently **6.18.34** paired with `raspberrypifw` **1.20260521**.
The pairing matters — with `useGenerationDeviceTree = false` (the Pi 4 default) the DTBs and
`overlays/` come from the firmware package while the modules come from the kernel, so a skew means DT
nodes the driver does not match.

To pin a different bundle, three things move in lockstep:

```nix
kernelBundle = pkgs.linuxAndFirmware.v6_6_31;
boot.loader.raspberry-pi.firmwarePackage = kernelBundle.raspberrypifw;
boot.kernelPackages = kernelBundle.linuxPackages_rpi4;
nixpkgs.overlays = lib.mkAfter [ (self: super: {
  inherit (kernelBundle) raspberrypifw raspberrypiWirelessFirmware;
}) ];
```

### USB/SATA root needs no extra initrd modules

`modules/raspberrypi.nix:44-52` already supplies `xhci_pci`, `usbhid`, `usb_storage`, `vc4`,
`pcie_brcmstb` (PCIe bus) and `reset-raspberrypi` (VL805 firmware load). `uas` is absent and does not
need adding: the vendor `bcm2711_defconfig` has `CONFIG_USB_UAS=y`, `CONFIG_USB_STORAGE=y`,
`CONFIG_USB_XHCI_HCD=y`, `CONFIG_SCSI=y` and `CONFIG_BLK_DEV_SD=y` built in.

## `config.txt` and device-tree overlays

Set via `hardware.raspberry-pi.config.<filter>.base-dt-params` (rendered as `dtparam=k=v`) and
`.dt-overlays.<name>` (rendered as `dtoverlay=name` followed by its scoped `dtparam` lines, then a
bare `dtoverlay=` terminator).

### PoE+ HAT fan

pi-rack no longer uses this: the CM4 build has no PoE HAT (2026-09-25). It stays as the reference
for a Pi 4 with the PoE+ HAT.

There is no PoE module in this flake. Use `config.txt`, which is also what the Ansible role does
today:

```nix
hardware.raspberry-pi.config.all.base-dt-params = {
  poe_fan_temp0 = { enable = true; value = 50000; };
  poe_fan_temp1 = { enable = true; value = 60000; };
  poe_fan_temp2 = { enable = true; value = 70000; };
  poe_fan_temp3 = { enable = true; value = 80000; };
};
```

Renders as four `dtparam=poe_fan_temp0=50000` lines. Parameter names verified against
`raspberrypi/linux` `arch/arm/boot/dts/overlays/README` @ `rpi-6.18.y` — overlay `rpi-poe-plus`,
defaults 40000 / 45000 / 50000 / 55000 millicelsius.

The firmware auto-loads the HAT overlay from the HAT EEPROM, and `rpi-poe-plus.dtbo` ships in
firmware `1.20260521`, copied to `/boot/firmware/overlays/` by the builder. One caveat from the
Raspberry Pi docs: a bare `dtoverlay=` *before* any other overlay or dtparam suppresses HAT overlay
loading entirely. The module's defaults emit `dtoverlay=vc4-kms-v3d` first, so the terminator lands
after it and is harmless — but re-check the ordering if every default overlay is ever disabled.

### Verify on the host

```sh
grep -H . /sys/class/thermal/cooling_device*/type        # find the pwm-fan device by type, not index
grep -H . /sys/class/thermal/thermal_zone0/trip_point_*_temp   # expect the configured values
```

Trip points showing the overlay's own defaults instead means `config.txt` is not reaching the
firmware partition — check that `/boot/firmware` is mounted.

## Wi-Fi-only hosts

pi-turntable uses no Ethernet, so its first boot has a problem: its Wi-Fi password is a sops secret,
and a freshly written card has no age key to decrypt it.

- **The first-boot image carries the password, and every deployed generation reads it from sops.**
  `hosts/pi-turntable/image-wifi.nix`, which only `pi-turntable-image` imports, points
  `networking.wireless.secretsFile` at a store file built from `vars.pi-turntable.wifiPsk`. The
  first deploy replaces that generation with one that reads `/run/secrets/pi-turntable-wifi`.
- The cost: the password is in plaintext in the image file, in the Mac's `nix-store` Docker volume,
  and in the Pi's store until the image's generation is garbage-collected.
- Rejected: putting the host's age key into the image. `.sops.yaml` has one creation rule, so any
  host key decrypts all of `secrets.yaml`, and the image would carry a fleet-wide key.
- Rejected: Ethernet for the first boot. It works, but needs a cable for every re-image; it stays
  the fallback when an image does not join the network.
- **The hardened wpa_supplicant unit runs as user `wpa_supplicant`** and bind-mounts `secretsFile`
  read-only, so the sops secret needs `owner = "wpa_supplicant"`; a root-owned one is unreadable to
  it. The file holds `name=value` lines, referenced as `pskRaw = "ext:<name>"`.

## Traps

1. **`uboot` only: never set `useGenerationDeviceTree = true`.** It breaks the firmware installer —
   `firmware-builder.sh:52` globs only `"$dtb_path"/*.dtb` while Pi 4 kernel DTBs live under
   `broadcom/`, so zero files match and the prune loop at `:71-75` deletes every existing `.dtb`.
   (Source-read, not tested.) **Does not apply to `kernel`**, which uses
   `install-device-tree.sh:53-55` and globs both paths — that inconsistency is exactly why the
   `kernel` bootloader can default the option to `true` safely. Both Pi hosts are on `kernel`, so
   this trap is inert here; it matters only if someone switches a host back to `uboot`.
2. **Do not cross-compile.** Issue [#195](https://github.com/nvmd/nixos-raspberrypi/issues/195):
   with `nixpkgs.buildPlatform` set, the firmware and extlinux builders are built for the *build*
   platform but executed at activation time on the Pi — `Exec format error`, failed bootloader
   install. Build natively (or on an aarch64 remote builder).
3. **`modules/raspberrypi.nix:39-42`** sets `console=serial0,115200n8` and `console=tty1` without
   `mkDefault`; overriding requires `mkForce`.
4. **`main` trails `develop`** (6.18.34 vs 6.18.42 as of writing). The README recommends `main`.
5. **`modules/installer/sd-card/sd-image-aarch64-uboot.nix` is dead** — references a non-existent
   option and a missing script; nothing imports it and the flake does not export it. Do not import it.
6. **`kernelboot` is deprecated** and emits a build warning. Irrelevant on Pi 4, which defaults to
   `uboot`.
7. **Predictable interface names rename the on-board NIC to `end0`.**
   - The Pi device trees alias the NIC as `ethernet0` (`bcm2711-rpi.dtsi:15`; on Pi 5, the RP1
     NIC via `bcm2712-rpi.dtsi:127`).
   - systemd ≥ v252 names a NIC with a DT alias `end<N>`. With NixOS's default
     `usePredictableInterfaceNames = true`, it comes up `end0`, and anything configured for
     `eth0` (keepalived here) binds nothing.
   - pi-rack **pins the name to the NIC's MAC** with `systemd.network.links."10-genetp0"`
     (`MACAddress=` → `Name=genetp0`), the same approach as `pve_pin_network_interface` on the
     Proxmox nodes. keepalived uses `genetp0`. The MAC comes from
     `vars.network-02.nicMacAddress`, which is the same 1Password field NIM uses for the DHCP
     reservation.
   - Eval shows the `.link` in `/etc/systemd/network` and in the initrd, with no networkd needed.
     On the CM4 the NIC comes up as `genetp0` (2026-09-25).
   - The blunter alternative is `usePredictableInterfaceNames = false` (adds `net.ifnames=0`,
     keeps `eth0`). It was rejected because an explicit pin survives future naming-scheme
     changes.
8. **An image built from a host config fails to evaluate unless ZFS is forced off.** The
   `sd-image` module imports `profiles/base.nix`, which enables ZFS, and the kernel's zfs module
   (nixos-raspberrypi's nixpkgs) and ours differ, tripping an assertion. `mkPiImage` in
   `flake.nix`, which builds every Pi image, sets `boot.supportedFilesystems.zfs = lib.mkForce false`.
9. **Building a whole host image locally needs `nix-shell.sh --sandbox`.** Unsandboxed, the
   container builds as root, so the first builder that writes to `$HOME` creates
   `/homeless-shelter`, and Nix refuses every later build (NixOS/nix#8313). Deploys don't hit
   this, because `deploy-host.sh` builds on the target. `build-image.sh` passes `--sandbox`.
10. **ALSA card numbers are not the ones Ubuntu or Raspberry Pi OS gives.** NixOS registers the vc4
    HDMI audio cards early, so pi-turntable's USB interface, `hw:1` under Ubuntu, is card 3 here.
    Name the card instead of numbering it: `hw:CARD=<id>,DEV=0`, with the id from
    `/proc/asound/cards`.
11. **There is no RTC, so a freshly written image boots with a wrong clock.** Until timesyncd
    syncs, TLS fails for anything that starts early: on pi-turntable's first boot,
    `dotfiles.service` failed with "certificate is not yet valid". timesyncd saves the clock to
    disk, so later boots start close enough.

## Module-system semantics worth knowing

These explain *why* rule 3 is an error rather than an override, and why a `dtparam` list must
re-state defaults it wants to keep. All from nixpkgs `lib/`.

**Priority scale** (`lib/modules.nix:1587-1592`) — **lower wins**:

| Source | Priority |
|---|---|
| an option's own `default` | 1500 (`mkOptionDefault`) |
| `lib.mkDefault` | 1000 |
| a plain definition | 100 (`defaultOverridePriority`) |
| `lib.mkForce` | 50 |

An option's `default` is not a fallback outside the system — `modules.nix:1125-1136` injects it as a
real definition at priority 1500, competing with the rest.

**Priority filtering happens before type merging** (`modules.nix:1449-1456`): `filterOverrides'`
keeps only the definitions at the minimum priority number and discards the rest *before* the type's
merge function runs. Consequences:

- `types.listOf` concatenates — but only among definitions at the same winning priority. A plain
  host-level definition **discards** a module's `mkDefault` list rather than appending to it.
- **`types.attrsOf` does not behave that way**, and the distinction matters here. Merging is
  per-key, so a host setting `hardware.raspberry-pi.config.all.base-dt-params.poe_fan_temp0` leaves
  the module's other keys intact. Verified by evaluating pi-rack on 2026-08-07, when it still set
  the PoE params: the result contained the four `poe_fan_temp*` params **and** upstream's
  `audio = "on"`, which was never restated in the host config. An earlier draft of this
  document claimed defaults had to be re-stated for `base-dt-params`; that is true for
  `dtparam`-style *lists*, false for this option.
- `types.str` merges via `mergeEqualOption` (`types.nix:555-561` → `options.nix:499-516`): two equal
  definitions merge silently; two differing ones throw ``The option `…' has conflicting definition
  values``. Two `mkDefault`s of different values are equal priority and neither is discarded, so they
  reach the merge function and it throws — which is exactly the `boot.kernelPackages` collision.

**Imports are unique-by-key** (`modules.nix:563`): the same path imported twice evaluates once, so a
duplicate import is redundant rather than an error. Worth knowing, but no longer load-bearing here —
`flake.nix` used to pass per-host module lists alongside the host files' own `imports`, and the two
duplicated each other. That is gone: `nixosConfigurations` is derived from `builtins.readDir ./hosts`
and each host file states its own modules. The Pi modules
(`inject-overlays`, `trusted-nix-caches`, `raspberry-pi-4.base`) are imported by each Pi host's
`default.nix` (`hosts/pi-rack`, `hosts/pi-turntable`), reaching it through
`specialArgs.nixos-raspberrypi`.

## Related

- `nix/docs/proxmox-workflow.md` — the equivalent for x86 Proxmox guests.
