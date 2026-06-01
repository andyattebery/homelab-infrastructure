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
    environment.ADGUARDHOME_HOSTNAME = "adguardhome.${vars.domainName}";
    configFiles."adguardhome-sync.yaml".source =
      config.sops.templates."adguardhome-sync.yaml".path;
  };

  # --- network-inventory-manager ---
  sops.secrets."nim-github-token" = {};
  sops.secrets."nim-adguardhome-username" = {};
  sops.secrets."nim-adguardhome-password" = {};
  sops.secrets."nim-unifi-username" = {};
  sops.secrets."nim-unifi-password" = {};
  sops.secrets."nim-op-service-account-token" = {};

  sops.templates."nim-settings.yaml" = {
    content = ''
      config_repo: andyattebery/homelab-infrastructure
      repo_config_path: network-inventory/network_hosts_inventory.yaml.tpl
      github_token: "${config.sops.placeholder."nim-github-token"}"
      dsm_url: https://dashboard-services-manager.${vars.domainName}
      adguardhome_url: http://192.168.1.224:3000
      adguardhome_username: "${config.sops.placeholder."nim-adguardhome-username"}"
      adguardhome_password: "${config.sops.placeholder."nim-adguardhome-password"}"
      unifi_url: https://192.168.1.1
      unifi_username: "${config.sops.placeholder."nim-unifi-username"}"
      unifi_password: "${config.sops.placeholder."nim-unifi-password"}"
      op_service_account_token: "${config.sops.placeholder."nim-op-service-account-token"}"
      sync_interval: 1800
    '';
  };

  services.docker-compose.network-inventory-manager = {
    composeFile = ../../../ansible/roles/docker_compose_network_inventory_manager/files/docker-compose-network-inventory-manager.yaml;
    configFiles."settings.yaml".source =
      config.sops.templates."nim-settings.yaml".path;
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
