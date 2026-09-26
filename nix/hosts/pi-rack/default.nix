{ pkgs, vars, nixos-raspberrypi, ... }: {
  imports = [
    # hardware -- a Compute Module 4 (8 GB RAM, 32 GB eMMC) on a Waveshare CM4-IO-BASE, root
    # on the eMMC. raspberry-pi-4.base covers the CM4 (same BCM2711; its nvme initrd module
    # and [cm4] config.txt section come from there). nixos-raspberrypi supplies the
    # bootloader, kernel and firmware; rpi4.nix supplies the on-disk layout, which that flake
    # deliberately omits.
    #
    # nixos-hardware.nixosModules.raspberry-pi-4 must NOT be added alongside these: both
    # set boot.kernelPackages with mkDefault to different values, which is a
    # conflicting-definition error rather than a last-one-wins override.
    # See nix/docs/raspberry-pi.md.
    nixos-raspberrypi.lib.inject-overlays
    nixos-raspberrypi.nixosModules.trusted-nix-caches
    nixos-raspberrypi.nixosModules.raspberry-pi-4.base
    ../../modules/rpi4.nix
    # capabilities
    ../../modules/nut.nix
    # stack -- brings tailscale.nix and dsm-provider with it
    ../../modules/network.nix
  ];

  nixpkgs.hostPlatform = "aarch64-linux";
  networking.hostName = "pi-rack";
  system.stateVersion = "26.05";

  # Generational bootloader: each generation gets its own directory on the firmware
  # partition with a matched kernel, initrd, DTBs and overlays. The board default is
  # "uboot", where FIRMWARE holds only one set of DTBs -- so a rollback across a kernel
  # change can fail on a DTB mismatch (upstream issue #60). Rollback is the main reason
  # this host runs NixOS, so the default is overridden deliberately.
  boot.loader.raspberry-pi.bootloader = "kernel";

  # Pin the on-board NIC's name to its MAC, the way pve_pin_network_interface does on the
  # Proxmox nodes (<controller>p<port>; the CM4's NIC is the SoC's GENET controller), so
  # keepalived.interface below can't be broken by a naming change. Unpinned, systemd >=
  # v252 names it end0 from the ethernet0 device-tree alias (bcm2711-rpi.dtsi), while
  # Ubuntu called it eth0. The name avoids the kernel's eth/en* prefixes, which systemd.link
  # warns race with the kernel's own assignment. MAC from 1Password via vars.nix.tpl.
  systemd.network.links."10-genetp0" = {
    matchConfig.MACAddress = vars.network-02.nicMacAddress;
    linkConfig.Name = "genetp0";
  };

  # Flash-write reduction for the eMMC. Size caps don't reduce wear -- bytes written do.
  # /tmp in RAM keeps temp files off the eMMC; the host has 8 GB.
  boot.tmp.useTmpfs = true;
  # Keep AdGuard's query log in memory only. On this backup DNS node it is low-value, and
  # file_enabled would write every query to the eMMC. network.nix is shared by all three DNS
  # nodes, so this is set here; it merges with network.nix's querylog.interval.
  services.adguardhome.settings.querylog.file_enabled = false;

  # No services.scrutiny.collector: eMMC has no SMART, and the collector force-enables
  # smartd, which fails with nothing to watch. Watch wear instead with
  # `mmc extcsd read /dev/mmcblk0` (DEVICE_LIFE_TIME_EST_TYP_A/B, PRE_EOL_INFO).
  environment.systemPackages = [ pkgs.mmc-utils ];

  homelab.network = {
    enable = true;
    adguardhome = {
      hostname = "adguardhome-02.${vars.domainName}";
      username = vars.network-02.adguardhomeUsername;
      passwordHash = vars.network-02.adguardhomePasswordHash;
    };
    keepalived = {
      interface = "genetp0";
      priority = 150;
      isMaster = false;
    };
  };
}
