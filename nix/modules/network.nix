# Requires tailscale.nix to be imported alongside this module.
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

    reverseProxy = {
      enable = lib.mkEnableOption "nginx reverse proxy for network services";
      virtualHosts = lib.mkOption {
        type = lib.types.attrsOf (lib.types.submodule {
          options.port = lib.mkOption { type = lib.types.port; };
        });
        default = {};
      };
    };

  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      services.resolved.settings.Resolve.DNSStubListener = "no";

      sops.secrets."tailscale-auth-key" = {};
      services.tailscale.authKeyFile = config.sops.secrets."tailscale-auth-key".path;
      services.tailscale.extraUpFlags = [
        "--accept-dns=false"
        "--advertise-exit-node"
        "--advertise-routes=${vars.subnetCidr}"
      ];
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
          domain = lib.mkIf cfg.reverseProxy.enable "*.${vars.domainName}";
          dnsProvider = "cloudflare";
          credentialFiles."CLOUDFLARE_DNS_API_TOKEN_FILE" = config.sops.secrets."cloudflare-api-token".path;
          group = "adguardhome-cert";
          reloadServices = [ "adguardhome.service" ]
            ++ lib.optionals cfg.reverseProxy.enable [ "nginx.service" ];
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
            upstream_dns = [
              "https://dns.cloudflare.com/dns-query"
              "https://doh.libredns.gr/ads"
              "https://dns.quad9.net/dns-query"
            ];
            bootstrap_dns = [ "9.9.9.10" "149.112.112.10" "2620:fe::10" "2620:fe::fe:10" ];
            upstream_mode = "load_balance";
            ratelimit = 0;
            cache_size = 4194304;
            cache_enabled = true;
            refuse_any = true;
            trusted_proxies = [ "127.0.0.0/8" "::1/128" "10.0.0.0/24" "10.0.10.0/24" ];
          };
          tls = {
            enabled = true;
            server_name = cfg.adguardhome.hostname;
            certificate_path = "/var/lib/acme/${cfg.adguardhome.hostname}/fullchain.pem";
            private_key_path = "/var/lib/acme/${cfg.adguardhome.hostname}/key.pem";
          } // lib.optionalAttrs cfg.reverseProxy.enable {
            port_https = 0;
            force_https = false;
          };
          filtering = {
            filtering_enabled = true;
            safebrowsing_enabled = true;
            filters_update_interval = 24;
          };
          filters = [
            { name = "AdGuard DNS filter"; url = "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt"; enabled = true; id = 1; }
            { name = "AdAway Default Blocklist"; url = "https://adaway.org/hosts.txt"; enabled = true; id = 2; }
            { name = "HaGeZi's Normal Blocklist"; url = "https://adguardteam.github.io/HostlistsRegistry/assets/filter_34.txt"; enabled = true; id = 3; }
          ];
        } // lib.optionalAttrs cfg.reverseProxy.enable {
          http.doh.insecure_enabled = true;
        };
      };
      systemd.services.adguardhome.serviceConfig.SupplementaryGroups = [ "adguardhome-cert" ];

      services.keepalived = {
        enable = true;
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

      services.dsm-provider = {
        enable = true;
        apiUrl = "https://dashboard-services-manager.${vars.domainName}";
      };

      systemd.services.keepalived-exporter = {
        description = "Prometheus keepalived exporter";
        after = [ "keepalived.service" ];
        wantedBy = [ "multi-user.target" ];
        path = [ pkgs.bash pkgs.keepalived ];
        serviceConfig = {
          ExecStart = "${pkgs.callPackage ../pkgs/keepalived-exporter.nix {}}/bin/keepalived-exporter --ka.pid-path=/run/keepalived.pid";
          Restart = "always";
        };
      };

      services.dsm-provider.services = [
        {
          name = "AdGuard Home";
          url = "https://${cfg.adguardhome.hostname}";
          hostname = config.networking.hostName;
        }
      ];
    }

    (lib.mkIf cfg.reverseProxy.enable {
      users.users.nginx.extraGroups = [ "adguardhome-cert" ];

      services.nginx = {
        enable = true;
        recommendedProxySettings = true;
        recommendedTlsSettings = true;
        recommendedOptimisation = true;
        recommendedGzipSettings = true;

        virtualHosts = {
          "_" = {
            default = true;
            rejectSSL = true;
          };
          ${cfg.adguardhome.hostname} = {
            forceSSL = true;
            useACMEHost = cfg.adguardhome.hostname;
            locations."/".proxyPass = "http://127.0.0.1:3000";
            locations."/".proxyWebsockets = true;
          };
        } // lib.mapAttrs' (subdomain: hostCfg:
          lib.nameValuePair "${subdomain}.${vars.domainName}" {
            forceSSL = true;
            useACMEHost = cfg.adguardhome.hostname;
            locations."/".proxyPass = "http://127.0.0.1:${toString hostCfg.port}";
            locations."/".proxyWebsockets = true;
          }
        ) cfg.reverseProxy.virtualHosts;
      };
    })
  ]);
}
