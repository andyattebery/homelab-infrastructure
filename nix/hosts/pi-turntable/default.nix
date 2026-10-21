{ config, pkgs, vars, nixos-raspberrypi, dsm, needledrop, ... }:
let
  # One value each for the whole audio path. The dsnoop PCM, the pipe service, OwnTone and
  # needledrop all read these, so the capture rate cannot drift between them.
  rate = 48000;
  pcm = "dsnoopusb";
  # OwnTone's library holds only the turntable's named pipes. This is the container's path, so the
  # database carried over from it still points at the right file.
  media = "/srv/media";
  owntoneHost = "owntone.${vars.domainName}";
  asoundConf = config.environment.etc."asound.conf".source;
in {
  imports = [
    # hardware -- a Raspberry Pi 4 Model B (Rev 1.1, 4 GB), root on a microSD card. The same
    # block as hosts/pi-rack; see the comments there and nix/docs/raspberry-pi.md.
    nixos-raspberrypi.lib.inject-overlays
    nixos-raspberrypi.nixosModules.trusted-nix-caches
    nixos-raspberrypi.nixosModules.raspberry-pi-4.base
    ../../modules/rpi4.nix
    # capabilities
    ../../modules/owntone.nix
    dsm.nixosModules.dsm-provider
    needledrop.nixosModules.default
  ];

  nixpkgs.hostPlatform = "aarch64-linux";
  networking.hostName = "pi-turntable";
  system.stateVersion = "26.05";

  # Generational bootloader, as on pi-rack: each generation keeps its own kernel, initrd and
  # DTBs, so a rollback across a kernel change still boots.
  boot.loader.raspberry-pi.bootloader = "kernel";

  # Keep temp files off the SD card; the host has 4 GB.
  boot.tmp.useTmpfs = true;

  # --- Wi-Fi, the only network this host has ---
  # The hardened wpa_supplicant unit runs as user wpa_supplicant and bind-mounts this file
  # read-only, so a root-owned secret would be unreadable to it. The first-boot image swaps the
  # file for a plaintext one because it has no age key yet: see image-wifi.nix.
  sops.secrets."pi-turntable-wifi".owner = "wpa_supplicant";
  networking.wireless = {
    enable = true;
    secretsFile = config.sops.secrets."pi-turntable-wifi".path;
    networks.${vars.pi-turntable.wifiSsid}.pskRaw = "ext:wifi_psk";
  };

  # --- Turntable capture ---
  # A dsnoop PCM, so the pipe service and needledrop can capture from the one USB interface at the
  # same time. The card is named, not numbered: NixOS registers the vc4 HDMI cards early, so the
  # index Ubuntu gave it (hw:1,0) can point elsewhere here. ipc_perm and ipc_gid let root (the
  # pipe service) and the needledrop user share its segment; under Docker both were root.
  environment.etc."asound.conf".text = ''
    pcm.${pcm} {
      type dsnoop
      ipc_key 12345
      ipc_perm 0660
      ipc_gid audio
      slave {
        pcm "hw:CARD=CODEC,DEV=0"
        rate ${toString rate}
        channels 2
      }
    }
  '';

  # OwnTone plays the named pipes it finds in its library. Turntable.metadata carries needledrop's
  # track info to it.
  systemd.tmpfiles.rules = [
    "d ${media} 0755 root root -"
    "p ${media}/Turntable 0666 root root -"
    "p ${media}/Turntable.metadata 0666 root root -"
  ];

  # Capture into the pipe through sox's silence filter, so OwnTone only starts playing when a
  # record does. A script, not ExecStart, so the % in the thresholds is literal; the Ansible unit
  # had to write it as %%.
  systemd.services.owntone-alsa-pipe = {
    description = "ALSA capture to OwnTone pipe (Turntable)";
    wantedBy = [ "multi-user.target" ];
    wants = [ "sound.target" ];
    after = [ "sound.target" ];
    restartTriggers = [ asoundConf ];
    path = [ pkgs.alsa-utils pkgs.sox ];
    script = ''
      arecord -D ${pcm} -r ${toString rate} -f S16_LE -c 2 -t raw --buffer-size=192000 2>/dev/null \
        | sox -t raw -r ${toString rate} -b 16 -e signed-integer -c 2 - -t raw - \
            silence 1 0.1 0.5% 1 5.0 0.5% \
        > ${media}/Turntable
    '';
    serviceConfig = {
      Restart = "always";
      RestartSec = 1;
      Nice = -5;
      SupplementaryGroups = [ "audio" ];
    };
  };

  services.owntone = {
    enable = true;
    libraryDirectories = [ media ];
    pipeSampleRate = rate;
    # The container's value (its Dockerfile rewrites the default "lan"), kept for parity.
    trustedNetworks = [ "any" ];
  };

  # --- needledrop: identifies the record, scrobbles it, and feeds OwnTone and the Tuneshine ---
  # The module reads these through LoadCredential, so they stay root-owned.
  sops.secrets."needledrop-lastfm-api-key" = { };
  sops.secrets."needledrop-lastfm-api-secret" = { };
  sops.secrets."needledrop-lastfm-username" = { };
  sops.secrets."needledrop-lastfm-password-hash" = { };

  services.needledrop = {
    enable = true;
    secretFiles = {
      LASTFM_API_KEY = config.sops.secrets."needledrop-lastfm-api-key".path;
      LASTFM_API_SECRET = config.sops.secrets."needledrop-lastfm-api-secret".path;
      LASTFM_USERNAME = config.sops.secrets."needledrop-lastfm-username".path;
      LASTFM_PASSWORD_HASH = config.sops.secrets."needledrop-lastfm-password-hash".path;
    };
    settings = {
      audio = {
        alsa_device = pcm;
        sample_rate = rate;
      };
      outputs = {
        lastfm = {
          enabled = true;
          api_key = "$LASTFM_API_KEY";
          api_secret = "$LASTFM_API_SECRET";
          username = "$LASTFM_USERNAME";
          password_hash = "$LASTFM_PASSWORD_HASH";
          scrobble_threshold_seconds = 30;
        };
        owntone_metadata = {
          enabled = true;
          metadata_fifo = "${media}/Turntable.metadata";
        };
        tuneshine = {
          enabled = true;
          host = "tuneshine.${vars.domainName}";
        };
        log.enabled = true;
      };
    };
  };
  systemd.services.needledrop.restartTriggers = [ asoundConf ];

  # --- HTTPS for OwnTone's web interface: network.nix's pattern, for one name ---
  sops.secrets."cloudflare-api-token" = { };
  security.acme = {
    acceptTerms = true;
    defaults.email = vars.acmeEmail;
    certs.${owntoneHost} = {
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
      ${owntoneHost} = {
        forceSSL = true;
        useACMEHost = owntoneHost;
        locations."/".proxyPass = "http://127.0.0.1:3689";
        # The web interface's live updates: OwnTone serves its websocket here (websocket_port = 0,
        # modules/owntone.nix). It sends no pings, so this timeout is what ends an idle one; the
        # 60 s default would reconnect it, and the page would reload all its state, every minute.
        locations."= /ws" = {
          proxyPass = "http://127.0.0.1:3689";
          proxyWebsockets = true;
          extraConfig = "proxy_read_timeout 1h;";
        };
      };
    };
  };

  # The dashboard entry, which NIM also turns into the owntone.<domain_name> DNS rewrite. Under
  # Docker, DSM read it from the container's traefik labels.
  services.dsm-provider = {
    enable = true;
    apiUrl = "https://dashboard-services-manager.${vars.domainName}";
    services = [
      {
        name = "owntone";
        url = "https://${owntoneHost}";
        hostname = config.networking.hostName;
      }
    ];
  };
}
