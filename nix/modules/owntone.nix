# Capability: OwnTone, a DAAP/MPD server that streams to AirPlay and Chromecast speakers.
#
# nixpkgs ships the package but no module. The unit follows upstream's owntone.service.in
# (`owntone -f`, its memory cap and restart limits), except that it runs as its own user from the
# start instead of as root dropping privileges. That user gets one capability, for PTP (below).
#
# OwnTone finds and announces speakers through the host's avahi-daemon, so this enables it. The
# container pi-turntable ran before NixOS carried its own dbus + avahi instead.
#
# Requires base.nix, which is where pkgs-unstable comes from (as for tailscale.nix).
{ config, lib, pkgs, pkgs-unstable, ... }:
let
  cfg = config.services.owntone;
  quote = s: ''"${s}"'';

  # libconfuse syntax. Only what has to differ from OwnTone's built-in defaults is set
  # (src/conffile.c):
  #   - db_path, cache_dir: every path default points into the read-only store, because nixpkgs
  #     builds without --localstatedir.
  #   - logfile: run with -f, OwnTone logs to stderr regardless, and that reaches the journal
  #     (src/logger.c). The file log must still name something it can open; /dev/null keeps it
  #     off the disk. Expect two warnings at start: as non-root it cannot chown or chmod it.
  #   - user_agent: HomePod OS 27 / tvOS 27 answer AirPlay's GET /info with 403 unless the
  #     User-Agent looks like Apple's, and every speaker then fails to activate (owntone-server
  #     #2042). Upstream fixed it after 29.3 (34603ba) with a separate airplay_shared.user_agent;
  #     until nixpkgs ships a release with that, general.user_agent is the only lever. In 29.x it
  #     is also the User-Agent of AirPlay 1 (RAOP) and of OwnTone's HTTP fetches. Drop it once
  #     the package includes 34603ba.
  #   - websocket_port = 0: the web interface's websocket is then served on the HTTP port at /ws,
  #     so a reverse proxy carries it like any other path and plain HTTP keeps it too. That needs
  #     libevent >= 2.2 (configure.ac:172-175), which the package below is built against; with 2.1,
  #     0 turns the websocket off (src/websocket.c). A port instead means libwebsockets, which in
  #     nixpkgs' build (LWS_WITH_PLUGINS) never sends events unless OwnTone also sets
  #     LWS_SERVER_OPTION_VH_INSTANTIATE_ALL_PROTOCOLS (lib/core-net/vhost.c
  #     lws_protocol_init_vhost).
  conf = pkgs.writeText "owntone.conf" ''
    general {
      uid = "owntone"
      db_path = "/var/lib/owntone/database.db"
      cache_dir = "/var/cache/owntone"
      logfile = "/dev/null"
      user_agent = "AirPlay/999.0.0"
      websocket_port = 0
      trusted_networks = { ${lib.concatMapStringsSep ", " quote cfg.trustedNetworks} }
    }

    library {
      directories = { ${lib.concatMapStringsSep ", " quote cfg.libraryDirectories} }
    ${lib.optionalString (cfg.pipeSampleRate != null) "  pipe_sample_rate = ${toString cfg.pipeSampleRate}"}
    }
  '';

  # libevent 2.2, for OwnTone only. websocket_port = 0 above needs evws, libevent's websocket
  # server, which exists only from 2.2 (include/event2/ws.h); nixpkgs has 2.1.13. 2.2 has only
  # alpha releases. nixpkgs' one patch, for LibreSSL (upstream 883630f), is already in 2.2.2, and
  # 2.2's configure, unlike 2.1's, stops without pkg-config.
  libevent22 = pkgs-unstable.libevent.overrideAttrs (old: {
    version = "2.2.2-alpha";
    src = pkgs.fetchurl {
      url = "https://github.com/libevent/libevent/releases/download/release-2.2.2-alpha/libevent-2.2.2-alpha.tar.gz";
      hash = "sha256-SrGzaby1rwxZcbit5OlaLBMm9tDcG6ddYgvwMxwxhKg=";
    };
    patches = [ ];
    nativeBuildInputs = old.nativeBuildInputs ++ [ pkgs-unstable.pkg-config ];
  });

  # OwnTone's libevent websocket removes a closed client by walking its list with ws_clients->next
  # instead of client->next, so closing any client but the two newest loops forever on the HTTP
  # thread (src/httpd_libevhttp.c ws_client_close_cb). Against 29.3; unfixed in master on
  # 2026-10-21. The blank context line is written ${" "}: an indented string empties a line that
  # holds only whitespace.
  wsClosePatch = pkgs.writeText "owntone-ws-close.patch" ''
    --- a/src/httpd_libevhttp.c
    +++ b/src/httpd_libevhttp.c
    @@ -323,7 +323,7 @@
       struct ws_client *client = NULL;
       struct ws_client *prev = NULL;
    ${" "}
    -  for (client = ws_clients; client && client != arg; client = ws_clients->next)
    +  for (client = ws_clients; client && client != arg; client = client->next)
         {
           prev = client;
         }
  '';
in {
  options.services.owntone = {
    enable = lib.mkEnableOption "OwnTone";

    # From nixpkgs-unstable, as tailscale.nix does: 26.05 carries 29.2, and 29.3 fixes a
    # heap-buffer-over-read in the web server, along with Spotify fixes. Built against libevent22
    # with wsClosePatch (both above), which means no binary cache: the host compiles libevent and
    # OwnTone whenever their inputs change.
    package = lib.mkOption {
      type = lib.types.package;
      default = (pkgs-unstable.owntone.override { libevent = libevent22; }).overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [ wsClosePatch ];
      });
      defaultText = lib.literalMD "`pkgs-unstable.owntone` built against libevent 2.2, with this module's websocket patch";
      description = "The OwnTone package to use. It must be built against libevent >= 2.2: the configuration sets websocket_port = 0.";
    };

    libraryDirectories = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      description = "Directories OwnTone indexes. Named pipes in them are played as live inputs.";
    };

    pipeSampleRate = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
      description = "Sample rate of the raw PCM written to the library's named pipes. Null keeps OwnTone's 44100.";
    };

    trustedNetworks = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "lan" ];
      description = ''Who may connect without authorisation: "any", "lan", "localhost", "none" or address prefixes.'';
    };
  };

  config = lib.mkIf cfg.enable {
    services.avahi = {
      enable = true;
      publish = {
        enable = true;
        # OwnTone announces its DAAP, MPD and Remote services through the daemon.
        userServices = true;
        # <hostname>.local, which distributions' avahi publishes by default.
        addresses = true;
      };
    };

    users.users.owntone = {
      isSystemUser = true;
      group = "owntone";
    };
    users.groups.owntone = { };

    systemd.services.owntone = {
      description = "OwnTone DAAP/MPD server";
      wantedBy = [ "multi-user.target" ];
      requires = [ "avahi-daemon.socket" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" "sound.target" "avahi-daemon.socket" ];
      startLimitBurst = 10;
      startLimitIntervalSec = 600;
      serviceConfig = {
        ExecStart = "${lib.getExe cfg.package} -f -c ${conf}";
        User = "owntone";
        Group = "owntone";
        StateDirectory = "owntone";
        CacheDirectory = "owntone";
        # AirPlay 2's PTP clock listens on UDP 319 and 320, which are privileged ports. Without
        # this capability OwnTone logs "Could not bind to PTP event port" and offers speakers NTP
        # timing only. Upstream's own airptpd.service grants the same capability.
        AmbientCapabilities = [ "CAP_NET_BIND_SERVICE" ];
        # Upstream's cap, sized from a Pi 3 under load, so a runaway query cannot freeze the host.
        MemoryMax = "256M";
        Restart = "on-failure";
        RestartSec = 5;
      };
    };
  };
}
