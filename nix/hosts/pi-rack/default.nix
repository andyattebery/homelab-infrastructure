{ config, vars, ... }: {
  imports = [
    ../../modules/rpi4.nix
    ../../modules/tailscale.nix
    ../../modules/network.nix
    ../../modules/nut.nix
  ];

  networking.hostName = "pi-rack";
  system.stateVersion = "26.05";

  # Generational bootloader: each generation gets its own directory on the firmware
  # partition with a matched kernel, initrd, DTBs and overlays. The board default is
  # "uboot", where FIRMWARE holds only one set of DTBs -- so a rollback across a kernel
  # change can fail on a DTB mismatch (upstream issue #60). Rollback is the main reason
  # this host runs NixOS, so the default is overridden deliberately.
  boot.loader.raspberry-pi.bootloader = "kernel";

  # PoE+ HAT fan curve, in millidegrees. This is the config.txt route -- the same
  # dtparam= lines the Ansible role writes into /boot/firmware/config.txt today.
  # Not nixos-hardware's hardware.raspberry-pi."4".poe-plus-hat: that works via
  # hardware.deviceTree.overlays, which nixos-hardware is itself removing (its issue
  # #1946). The firmware auto-loads the HAT overlay from the HAT EEPROM; these only
  # tune its trip points (defaults are 40000/45000/50000/55000).
  hardware.raspberry-pi.config.all.base-dt-params = {
    poe_fan_temp0 = { enable = true; value = 50000; };
    poe_fan_temp1 = { enable = true; value = 60000; };
    poe_fan_temp2 = { enable = true; value = 70000; };
    poe_fan_temp3 = { enable = true; value = 80000; };
  };

  homelab.network = {
    enable = true;
    adguardhome = {
      hostname = "adguardhome-02.${vars.domainName}";
      username = vars.network-02.adguardhomeUsername;
      passwordHash = vars.network-02.adguardhomePasswordHash;
    };
    keepalived = {
      interface = "eth0";
      priority = 150;
      isMaster = false;
    };
  };

  services.scrutiny.collector = {
    enable = true;
    settings = {
      host.id = config.networking.hostName;
      api.endpoint = "https://scrutiny.${vars.domainName}";
    };
  };
}
