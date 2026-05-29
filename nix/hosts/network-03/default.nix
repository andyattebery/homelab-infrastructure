{ vars, ... }: {
  imports = [
    ../proxmox-vm-hardware.nix
    ../../modules/proxmox-guest.nix
    ../../modules/tailscale.nix
    ../../modules/docker-host.nix
    ../../modules/network.nix
  ];

  networking.hostName = "network-03";

  homelab.network = {
    enable = true;
    adguardhome = {
      hostname = "adguardhome-03.${vars.domainName}";
      username = vars.network-03.adguardhomeUsername;
      passwordHash = vars.network-03.adguardhomePasswordHash;
    };
    keepalived = {
      interface = "ens18";
      priority = 100;
      isMaster = false;
    };
  };
}
