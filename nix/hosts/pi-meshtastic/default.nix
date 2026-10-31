{ config, vars, nixos-raspberrypi, ... }:
let
  meshmonitorHost = "meshmonitor.${vars.domainName}";
  # The T-Echo's USB serial port, by its USB identity rather than its /dev/ttyACM* number.
  tEcho = "/dev/serial/by-id/usb-LILYGO_TTGO_eink_96404779E5A6A579-if00";
in {
  imports = [
    # hardware -- a Raspberry Pi 4 Model B (8 GB), root on a SATA drive behind a USB adapter,
    # wired Ethernet, no PoE HAT. pi-turntable's block; see nix/docs/raspberry-pi.md.
    nixos-raspberrypi.lib.inject-overlays
    nixos-raspberrypi.nixosModules.trusted-nix-caches
    nixos-raspberrypi.nixosModules.raspberry-pi-4.base
    ../../modules/rpi4.nix
    # capabilities
    ../../modules/tailscale.nix
    # Compose stacks as systemd units, plus Diun and a Docker DSM provider. It imports
    # dsm-provider itself.
    ../../modules/docker-host.nix
  ];

  nixpkgs.hostPlatform = "aarch64-linux";
  networking.hostName = "pi-meshtastic";
  system.stateVersion = "26.05";

  # Generational bootloader, as on pi-rack and pi-turntable.
  boot.loader.raspberry-pi.bootloader = "kernel";

  # Keep temp files off the drive; the host has 8 GB.
  boot.tmp.useTmpfs = true;

  # --- Tailscale: its own node, so it stays reachable when the subnet routers are down ---
  # network.nix's DNS flag. Advertising routes or an exit node is that stack's job, not this host's.
  sops.secrets."tailscale-auth-key" = { };
  services.tailscale = {
    authKeyFile = config.sops.secrets."tailscale-auth-key".path;
    extraUpFlags = [ "--accept-dns=false" ];
    extraSetFlags = [ "--accept-dns=false" ];
  };

  # --- MeshMonitor and the T-Echo's serial bridge: upstream's images ---
  # Upstream builds and tests only its image, and MeshMonitor's production mode assumes it (user
  # scripts run with the image's own interpreters), so it runs as published rather than packaged
  # here. The stack, its ports and its settings: modules/compose/docker-compose-meshmonitor.yaml.
  services.docker-compose-defaults.domainName = vars.domainName;
  sops.secrets."meshmonitor-env" = { };
  services.docker-compose.meshmonitor = {
    composeFile = ../../modules/compose/docker-compose-meshmonitor.yaml;
    environment.TECHO_DEVICE = tEcho;
    # SESSION_SECRET, from secrets.yaml.tpl's meshmonitor-env.
    environmentFiles = [ config.sops.secrets."meshmonitor-env".path ];
  };

  # --- HTTPS for MeshMonitor: pi-turntable's pattern, for one name ---
  sops.secrets."cloudflare-api-token" = { };
  security.acme = {
    acceptTerms = true;
    defaults.email = vars.acmeEmail;
    certs.${meshmonitorHost} = {
      dnsProvider = "cloudflare";
      credentialFiles."CLOUDFLARE_DNS_API_TOKEN_FILE" = config.sops.secrets."cloudflare-api-token".path;
      group = "nginx";
      reloadServices = [ "nginx.service" ];
    };
  };

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
      ${meshmonitorHost} = {
        forceSSL = true;
        useACMEHost = meshmonitorHost;
        # The compose file publishes the UI on 127.0.0.1:3001. MeshMonitor's nginx example
        # (docs/configuration/reverse-proxy.md): websocket upgrade and a 90 s read timeout.
        locations."/" = {
          proxyPass = "http://127.0.0.1:3001";
          proxyWebsockets = true;
          extraConfig = "proxy_read_timeout 90s;";
        };
      };
    };
  };

  # The dashboard entry comes from the meshmonitor container's dsm.url label, through the Docker
  # provider docker-host.nix adds. Turning the provider on, and where it reports, is the host's.
  services.dsm-provider = {
    enable = true;
    apiUrl = "https://dashboard-services-manager.${vars.domainName}";
  };
}
