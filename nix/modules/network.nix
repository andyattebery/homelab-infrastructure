# Stack bundle: AdGuard Home + keepalived VRRP + ACME, and nginx when reverseProxy.enable.
#
# Imports the two modules it configures unconditionally, so a host gets them by importing this
# one and does not have to know they are needed:
#   - tailscale.nix        -- this sets services.tailscale.{authKeyFile,extraUpFlags,extraSetFlags},
#                             including --advertise-exit-node and --advertise-routes. The exit node
#                             is a property of this stack, not of the machine.
#   - dsm-provider (input) -- this sets services.dsm-provider.{enable,apiUrl,services}
#
# Both stay opt-in capabilities in their own right: a host wanting Tailscale or dashboard entries
# without this stack imports them directly. Importing dsm-provider here AND from a host file is
# safe -- its exported module carries an explicit `key`, so the duplicate collapses instead of
# conflicting on services.dsm-provider.package.
{ config, lib, pkgs, vars, dsm, ... }:
let
  cfg = config.homelab.network;
in {
  imports = [
    ./tailscale.nix
    dsm.nixosModules.dsm-provider
  ];

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
            # IP literals, NOT hostnames -- do not "tidy" these back into names.
            #
            # A hostname upstream has to be resolved first, by bootstrap, over plaintext
            # UDP/53. On 2026-08-21 the AT&T gateway lost its WAN for ~65s, intercepted
            # port 53 while it was down, and answered every DoH hostname with its own
            # address (192.168.1.254, unreachable from behind the UDM). AdGuard cached
            # that and kept dialling a dead address long after the WAN recovered: a 65
            # second blip became a 36 minute outage. See
            # tasks/keepalived-vip-dns-outage-2026-08-21.md.
            #
            # dnsproxy skips bootstrap entirely when the upstream host parses as an
            # address (upstream/resolver.go, NotBootstrapError), so there is no plaintext
            # lookup to intercept. Same three providers as before -- dns.quad9.net already
            # resolved to 9.9.9.9, and 1.1.1.1 is Cloudflare's canonical DoH address --
            # so this changes addressing, not who resolves our DNS. All three serve DoH
            # on these literals with certificates carrying the IP in subjectAltName.
            upstream_dns = [
              "https://1.1.1.1/dns-query"
              "https://9.9.9.9/dns-query"
              "https://8.8.8.8/dns-query"
            ];
            # No longer used by upstream_dns above, and kept deliberately: AdGuard's
            # safebrowsing/parental service upstream (family.adguard-dns.com) is not
            # exposed as an option and still resolves by hostname, and leaving the list
            # in place means re-adding a hostname upstream later cannot silently break.
            # One resolver per operator, so no single operator can stop bootstrap working.
            bootstrap_dns = [
              "9.9.9.10" "149.112.112.10" "2620:fe::10" "2620:fe::fe:10"
              "1.1.1.1" "1.0.0.1" "2606:4700:4700::1111"
              "8.8.8.8" "8.8.4.4" "2001:4860:4860::8888"
            ];
            # parallel: query every upstream, take the first answer. load_balance sends
            # each query to one upstream, so a slow upstream slows that share of queries.
            upstream_mode = "parallel";
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
          # AdGuard has no size cap for the query log -- `interval` is the only control, and
          # it takes only 6h/1d/7d/30d/90d (checkInterval, internal/querylog/qlog.go).
          # Retention is TWICE the interval: rotation renames querylog.json to
          # querylog.json.1 rather than deleting it. At ~1.44M queries/day the 90d default
          # had grown to 31.5 GiB on a 63 GiB disk.
          querylog.interval = "7d";
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
        # The probe has to prove AdGuard *resolves*, not merely that it answers. The old
        # probe used healthcheck.adguardhome.test, which AdGuard synthesises itself as a
        # NODATA answer without contacting any upstream -- so on 2026-08-21 it passed for
        # 36 minutes while every upstream was unreachable, and the VIP never moved. See
        # tasks/keepalived-vip-dns-outage-2026-08-21.md.
        #
        # dns-probe.<domain_name> is an A record in our own zone (127.0.0.1, TTL 60) that
        # exists only for this. Two properties matter and both are load-bearing:
        #   - it must NOT be in network-inventory/network_hosts_inventory.yaml.tpl. A NIM
        #     rewrite would make AdGuard answer it locally and silently turn this back into
        #     a liveness check.
        #   - it must be a name we own. A blocked name returns 0.0.0.0, which nslookup
        #     accepts as an answer and exits 0 on, so a public name landing on a blocklist
        #     would fail open. Nothing can add our own zone to a blocklist.
        # nslookup exits 1 on SERVFAIL -- the failure mode the outage actually produced --
        # on both the BIND build here and the busybox build in pi-rack's container.
        #
        # The name stays chk_adguardhome to match ansible's keepalived.conf.j2, which
        # hardcodes chk_{{ keepalived_instance_name }}. Nothing scrapes the script name.
        vrrpScripts.chk_adguardhome = {
          script = "${pkgs.dnsutils}/bin/nslookup dns-probe.${vars.domainName} 127.0.0.1";
          interval = 5;
          timeout = 3;
          rise = 2;
          # 3 consecutive failures at 5s spacing, so ~15s of sustained failure before the
          # weight lands. A single slow DoH round-trip must not move the VIP.
          fall = 3;
          # 200/150/100 - 75 = 125/75/25. A failure on every node preserves the order, so a
          # real internet outage leaves the VIP where it is; only a differential failure
          # moves it.
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
