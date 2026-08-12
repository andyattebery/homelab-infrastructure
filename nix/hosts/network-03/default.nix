{ vars, dsm, ... }: {
  imports = [
    # hardware
    ../proxmox-vm-hardware.nix
    ../../modules/proxmox-guest.nix
    # capabilities
    ../../modules/tailscale.nix
    dsm.nixosModules.dsm-provider
    # stack
    ../../modules/network.nix
  ];

  nixpkgs.hostPlatform = "x86_64-linux";
  networking.hostName = "network-03";
  system.stateVersion = "25.11";

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
