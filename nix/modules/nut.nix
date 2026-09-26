{ config, pkgs, vars, ... }:
let
  nutNotifyScript = pkgs.writeShellScript "nut-notify-pushover" ''
    TOKEN=$(cat /run/secrets/nut-pushover-token)
    USER_KEY=$(cat /run/secrets/pushover-user-key)
    HOSTNAME=$(${pkgs.hostname-debian}/bin/hostname --short)

    ${pkgs.curl}/bin/curl -s \
      --form-string "token=$TOKEN" \
      --form-string "user=$USER_KEY" \
      --form-string "title=$HOSTNAME/$UPSNAME: $NOTIFYTYPE" \
      --form-string "message=$1" \
      https://api.pushover.net/1/messages.json
  '';
in {
  sops.secrets."nut-admin-password" = {};
  sops.secrets."nut-monitor-primary-password" = {};
  sops.secrets."nut-homeassistant-password" = {};
  sops.secrets."nut-client-nas-host-01-password" = {};
  sops.secrets."nut-client-vm-host-01-password" = {};
  sops.secrets."nut-client-vm-host-02-password" = {};
  sops.secrets."nut-client-backup-01-password" = {};
  # Read by nutNotifyScript, which upsmon runs as NOTIFYCMD. upsmon runs as
  # power.ups.upsmon.user, which defaults to "nutmon" -- and that is the only user the
  # NixOS ups module creates. There is no "nut" user; owning it by that name made
  # system.build.toplevel fail to evaluate.
  sops.secrets."nut-pushover-token" = { owner = "nutmon"; };
  sops.secrets."pushover-user-key".mode = "0444";

  power.ups = {
    enable = true;
    mode = "netserver";

    ups.rack-ups = {
      driver = "snmp-ups";
      port = vars.nut.upsSnmpAddress;
      description = "APC Smart-UPS SMT1500RM2U via AP9630 (NMC2)";
      directives = [
        "snmp_version = v1"
        "community = ${vars.nut.upsSnmpCommunity}"
        # NUT's default is 1 start attempt. The AP9630 NMC can be slow to answer SNMP at
        # boot, and a single failure leaves the UPS unavailable to all five clients.
        # ups.conf documents maxretry as valid both globally and per-UPS.
        "maxretry = 3"
      ];
    };

    # Loopback for the local exporter and upsmon; the service name for remote clients.
    # Deliberately not 0.0.0.0: networking.firewall.enable is false repo-wide, so that
    # would newly expose upsd on tailscale0.
    upsd.listen = [
      { address = "127.0.0.1"; }
      { address = "ups-monitor-rack.${vars.domainName}"; }
    ];

    users = {
      admin = {
        passwordFile = config.sops.secrets."nut-admin-password".path;
        actions = [ "SET" ];
        instcmds = [ "ALL" ];
      };
      monitor-primary = {
        passwordFile = config.sops.secrets."nut-monitor-primary-password".path;
        upsmon = "primary";
      };
      homeassistant = {
        passwordFile = config.sops.secrets."nut-homeassistant-password".path;
        upsmon = "secondary";
      };
      nas-host-01 = {
        passwordFile = config.sops.secrets."nut-client-nas-host-01-password".path;
        upsmon = "secondary";
      };
      vm-host-01 = {
        passwordFile = config.sops.secrets."nut-client-vm-host-01-password".path;
        upsmon = "secondary";
      };
      vm-host-02 = {
        passwordFile = config.sops.secrets."nut-client-vm-host-02-password".path;
        upsmon = "secondary";
      };
      backup-01 = {
        passwordFile = config.sops.secrets."nut-client-backup-01-password".path;
        upsmon = "secondary";
      };
    };

    upsmon = {
      monitor.rack-ups = {
        system = "rack-ups@localhost";
        powerValue = 1;
        user = "monitor-primary";
        # NUT 2.8 renamed master/slave to primary/secondary; the NixOS option still
        # defaults to "master".
        type = "primary";
      };

      settings = {
        SHUTDOWNCMD = "${pkgs.systemd}/bin/shutdown now";
        NOTIFYCMD = toString nutNotifyScript;

        NOTIFYFLAG = [
          [ "ONLINE"    "SYSLOG+WALL+EXEC" ]
          [ "ONBATT"    "SYSLOG+WALL+EXEC" ]
          [ "LOWBATT"   "SYSLOG+WALL+EXEC" ]
          [ "FSD"       "SYSLOG+WALL+EXEC" ]
          [ "COMMOK"    "SYSLOG+WALL+EXEC" ]
          [ "COMMBAD"   "SYSLOG+WALL+EXEC" ]
          [ "SHUTDOWN"  "SYSLOG+WALL+EXEC" ]
          [ "REPLBATT"  "SYSLOG+WALL+EXEC" ]
          [ "NOCOMM"    "SYSLOG+WALL+EXEC" ]
          [ "NOPARENT"  "SYSLOG+WALL+EXEC" ]
          [ "CAL"       "SYSLOG+WALL+EXEC" ]
          [ "NOTCAL"    "SYSLOG+WALL+EXEC" ]
          [ "OFF"       "SYSLOG+WALL+EXEC" ]
          [ "NOTOFF"    "SYSLOG+WALL+EXEC" ]
          # BYPASS: the UPS is powered but no longer protecting the load.
          [ "BYPASS"    "SYSLOG+WALL+EXEC" ]
          [ "NOTBYPASS" "SYSLOG+WALL+EXEC" ]
        ];
      };
    };
  };

  # upsd resolves its LISTEN address (ups-monitor-rack.<domain>) through DNS at startup. The
  # NixOS unit is upsd.service: this block used to target nut-server.service (the Debian
  # name), which only created an empty stray unit, leaving upsd ordered after network.target
  # alone. On the first boot (2026-09-25) upsd started 8 s before network-online, failed with
  # "getaddrinfo(...): Name or service not known", and with Restart=no stayed down. wants, not
  # requires: a wait-online timeout must not stop upsd from starting at all. Restart covers
  # DNS staying unreachable longer, e.g. network-01 still booting after a power event.
  systemd.services.upsd = {
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    serviceConfig = {
      Restart = "on-failure";
      RestartSec = "10s";
    };
  };

  services.prometheus.exporters.nut = {
    enable = true;
    port = 9199;
    nutServer = "127.0.0.1";
    nutUser = "monitor-primary";
    # The exporter runs as a DynamicUser (nixpkgs' exporter default), which can't own a sops
    # secret, and this secret stays root-only 0400 because upsd and upsmon use it too. So
    # systemd reads the root-owned file and hands this unit a private copy as a credential.
    # Pointing passwordPath at the secret itself failed on the first deploy (2026-09-25):
    # "cat: /run/secrets/nut-monitor-primary-password: Permission denied".
    passwordPath = "/run/credentials/prometheus-nut-exporter.service/nut-password";
    nutVariables = [
      "battery.charge" "battery.runtime" "battery.voltage" "battery.voltage.nominal"
      "input.voltage" "input.voltage.nominal" "output.voltage"
      "ups.load" "ups.status"
    ];
  };

  systemd.services.prometheus-nut-exporter.serviceConfig.LoadCredential = [
    "nut-password:${config.sops.secrets."nut-monitor-primary-password".path}"
  ];
}
