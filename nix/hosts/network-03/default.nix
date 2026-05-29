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
    adguardhome.hostname = "adguardhome-03.${vars.domainName}";
    wireguardPort = 51820;
    keepalived = {
      priority = 100;
      isMaster = false;
    };
  };
}
