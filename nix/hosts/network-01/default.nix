{ config, pkgs, vars, ... }:
let
  adguardhome-sync = pkgs.callPackage ../../pkgs/adguardhome-sync.nix {};
in {
  imports = [
    ../proxmox-vm-hardware.nix
    ../../modules/proxmox-guest.nix
    ../../modules/tailscale.nix
    ../../modules/network.nix
  ];

  networking.hostName = "network-01";
  system.stateVersion = "25.11";

  homelab.network = {
    enable = true;
    adguardhome = {
      hostname = "adguardhome.${vars.domainName}";
      username = vars.network-01.adguardhomeUsername;
      passwordHash = vars.network-01.adguardhomePasswordHash;
    };
    keepalived = {
      interface = "ens18";
      priority = 200;
      isMaster = true;
    };
    reverseProxy = {
      enable = true;
      virtualHosts = {
        "adguardhome-sync" = { port = 8080; };
        "network-inventory-manager" = { port = 8090; };
      };
    };
  };

  # --- adguardhome-sync ---
  sops.secrets."adguardhome-sync-origin-username" = {};
  sops.secrets."adguardhome-sync-origin-password" = {};
  sops.secrets."adguardhome-sync-replica-02-username" = {};
  sops.secrets."adguardhome-sync-replica-02-password" = {};
  sops.secrets."adguardhome-sync-replica-03-username" = {};
  sops.secrets."adguardhome-sync-replica-03-password" = {};

  sops.templates."adguardhome-sync.yaml" = {
    owner = "services";
    restartUnits = [ "adguardhome-sync.service" ];
    content = ''
      cron: "*/30 * * * *"
      runOnStart: true
      api:
        metrics:
          enabled: true
      origin:
        url: https://adguardhome.${vars.domainName}
        username: ${config.sops.placeholder."adguardhome-sync-origin-username"}
        password: ${config.sops.placeholder."adguardhome-sync-origin-password"}
      replicas:
        - url: https://adguardhome-02.${vars.domainName}
          username: ${config.sops.placeholder."adguardhome-sync-replica-02-username"}
          password: ${config.sops.placeholder."adguardhome-sync-replica-02-password"}
        - url: https://adguardhome-03.${vars.domainName}
          username: ${config.sops.placeholder."adguardhome-sync-replica-03-username"}
          password: ${config.sops.placeholder."adguardhome-sync-replica-03-password"}
    '';
  };

  systemd.services.adguardhome-sync = {
    description = "AdGuard Home Sync";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      User = "services";
      Group = "services";
      ExecStart = "${adguardhome-sync}/bin/adguardhome-sync run --config ${config.sops.templates."adguardhome-sync.yaml".path}";
      Restart = "always";
      RestartSec = 10;
    };
  };

  services.dsm-provider.services = [
    {
      name = "AdGuard Home Sync";
      url = "https://adguardhome-sync.${vars.domainName}";
      hostname = config.networking.hostName;
    }
  ];

  # --- network-inventory-manager ---
  sops.secrets."nim-adguardhome-password" = {};
  sops.secrets."nim-unifi-password" = {};
  sops.secrets."nim-github-token" = {};
  sops.secrets."nim-op-service-account-token" = {};

  sops.templates."nim-env".content = ''
    ADGUARDHOME_PASSWORD=${config.sops.placeholder."nim-adguardhome-password"}
    UNIFI_PASSWORD=${config.sops.placeholder."nim-unifi-password"}
    GITHUB_TOKEN=${config.sops.placeholder."nim-github-token"}
    OP_SERVICE_ACCOUNT_TOKEN=${config.sops.placeholder."nim-op-service-account-token"}
  '';

  services.network-inventory-manager = {
    enable = true;
    settings = {
      dsmUrl = "https://dashboard-services-manager.${vars.domainName}";
      adguardhomeUrl = "http://localhost:3000";
      adguardhomeUsername = vars.network-01.adguardhomeUsername;
      unifiUrl = "https://192.168.1.1";
      unifiUsername = vars.nim.unifiUsername;
      configRepo = "andyattebery/homelab-infrastructure";
      repoConfigPath = "network-inventory/network_hosts_inventory.yaml.tpl";
      syncInterval = 1800;
      port = 8090;
    };
    environmentFile = config.sops.templates."nim-env".path;
  };

}
