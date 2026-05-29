# Requires docker-host.nix and tailscale.nix to be imported alongside this module.
{ config, lib, pkgs, vars, ... }:
let
  cfg = config.homelab.network;
in {
  options.homelab.network = {
    enable = lib.mkEnableOption "network host role";

    adguardhome = {
      hostname = lib.mkOption { type = lib.types.str; };
      username = lib.mkOption { type = lib.types.str; };
      passwordHash = lib.mkOption { type = lib.types.str; };
    };

    keepalived = {
      isMaster = lib.mkOption { type = lib.types.bool; default = false; };
      priority = lib.mkOption { type = lib.types.int; };
      interface = lib.mkOption { type = lib.types.str; };
      routerId = lib.mkOption { type = lib.types.int; default = 51; };
    };

  };

  config = lib.mkIf cfg.enable {
    services.resolved.extraConfig = "DNSStubListener=no";

    sops.secrets."tailscale-auth-key" = {};
    services.tailscale.authKeyFile = config.sops.secrets."tailscale-auth-key".path;
    services.tailscale.extraSetFlags = [
      "--accept-dns=false"
      "--advertise-exit-node"
      "--advertise-routes=${vars.subnetCidr}"
    ];

    sops.secrets."cloudflare-api-token" = {};
    security.acme = {
      acceptTerms = true;
      defaults.email = vars.acmeEmail;
      certs.${cfg.adguardhome.hostname} = {
        dnsProvider = "cloudflare";
        credentialFiles."CLOUDFLARE_DNS_API_TOKEN_FILE" = config.sops.secrets."cloudflare-api-token".path;
        group = "adguardhome-cert";
        reloadServices = [ "adguardhome.service" ];
      };
    };

    users.groups.adguardhome-cert = {};
    services.adguardhome = {
      enable = true;
      mutableSettings = true;
      port = 3000;
      settings = {
        users = [
          {
            name = cfg.adguardhome.username;
            password = cfg.adguardhome.passwordHash;
          }
        ];
        dns = {
          bind_hosts = [ "0.0.0.0" ];
          port = 53;
        };
        tls = {
          enabled = true;
          server_name = cfg.adguardhome.hostname;
          certificate_path = "/var/lib/acme/${cfg.adguardhome.hostname}/fullchain.pem";
          private_key_path = "/var/lib/acme/${cfg.adguardhome.hostname}/key.pem";
        };
      };
    };
    systemd.services.adguardhome.serviceConfig.SupplementaryGroups = [ "adguardhome-cert" ];

    services.keepalived = {
      enable = true;
      openFirewall = true;
      enableScriptSecurity = true;
      extraGlobalDefs = ''
        max_auto_priority -1
        script_user root
      '';
      vrrpScripts.chk_adguardhome = {
        script = "${pkgs.dnsutils}/bin/nslookup healthcheck.adguardhome.test 127.0.0.1";
        interval = 5;
        timeout = 3;
        rise = 2;
        fall = 2;
        weight = -75;
        user = "root";
      };
      vrrpInstances.adguardhome = {
        interface = cfg.keepalived.interface;
        state = if cfg.keepalived.isMaster then "MASTER" else "BACKUP";
        virtualRouterId = cfg.keepalived.routerId;
        priority = cfg.keepalived.priority;
        virtualIps = [{ addr = vars.dnsServerVip; }];
        trackScripts = [ "chk_adguardhome" ];
      };
    };

    networking.firewall.allowedTCPPorts = [ 53 80 443 853 3000 ];
    networking.firewall.allowedUDPPorts = [ 53 ];

    services.docker-compose-defaults.domainName = vars.domainName;

    services.docker-compose.keepalived-exporter = {
      composeFile = ./compose/docker-compose-keepalived-exporter.yaml;
    };

    sops.secrets."diun-pushover-token" = {};
    sops.secrets."pushover-user-key" = {};
    sops.templates."diun.yml" = {
      content = builtins.readFile ./compose/diun.yml.tpl;
    };
    services.docker-compose.diun = {
      composeFile = ../../ansible/roles/docker_compose_diun/files/docker-compose-diun.yaml;
      configFiles."diun/config/diun.yml".source = config.sops.templates."diun.yml".path;
    };

    services.docker-compose.dsm-provider = {
      composeFile = ../../ansible/roles/docker_compose_dashboard_services_manager_provider/files/docker-compose-dsm-provider.yaml;
    };
  };
}
