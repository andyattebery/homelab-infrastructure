{ config, pkgs, vars, ... }: {
  imports = [
    ../proxmox-vm-hardware.nix
    ../../modules/proxmox-guest.nix
    ../../modules/tailscale.nix
    ../../modules/docker-host.nix
    ../../modules/network.nix
  ];

  networking.hostName = "network-01";

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
    content = ''
      cron: "*/30 * * * *"
      runOnStart: true
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

  services.docker-compose.adguardhome-sync = {
    composeFile = ../../../ansible/roles/docker_compose_adguardhome_sync/files/docker-compose-adguardhome-sync.yaml;
    configFiles."adguardhome-sync.yaml".source =
      config.sops.templates."adguardhome-sync.yaml".path;
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

  # --- adguardhome-sync textfile collector ---
  systemd.services.textfile-collector-adguardhome-sync = {
    description = "Textfile collector for adguardhome-sync";
    after = [ "docker-compose-adguardhome-sync.service" ];
    path = [ config.virtualisation.docker.package pkgs.gawk pkgs.coreutils ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = pkgs.writeShellScript "textfile-collector-adguardhome-sync" ''
        set -u
        OUT_FILE="/var/lib/node_exporter/adguardhome-sync.prom"
        TMP_FILE="$OUT_FILE.tmp.$$"
        cleanup() { rm -f "$TMP_FILE"; }
        trap cleanup EXIT
        {
          ts=$(docker logs --since=24h adguardhome-sync 2>&1 | grep 'Sync done' | tail -1 | awk '{print $1}')
          [ -n "$ts" ] && printf 'adguardhome_sync_last_success_timestamp %d\n' "$(date -d "$ts" +%s)"
        } > "$TMP_FILE"
        mv "$TMP_FILE" "$OUT_FILE"
      '';
    };
  };

  systemd.timers.textfile-collector-adguardhome-sync = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "30s";
      OnUnitActiveSec = "300s";
      AccuracySec = "1s";
    };
  };
}
