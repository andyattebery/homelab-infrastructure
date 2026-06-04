{ config, vars, ... }: {
  imports = [
    ../../modules/rpi4.nix
    ../../modules/tailscale.nix
    ../../modules/docker-host.nix
    ../../modules/network.nix
    ../../modules/nut.nix
  ];

  networking.hostName = "network-02";

  hardware.raspberry-pi."4".poe-plus-hat = {
    enable = true;
    fan.temperature0 = 50000;
    fan.temperature1 = 60000;
    fan.temperature2 = 70000;
    fan.temperature3 = 80000;
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
