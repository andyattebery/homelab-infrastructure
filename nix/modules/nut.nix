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
  sops.secrets."nut-client-network-02-password" = {};
  sops.secrets."nut-client-backup-01-password" = {};
  sops.secrets."nut-pushover-token" = { owner = "nut"; };
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
      ];
    };

    upsd.listen = [
      { address = "127.0.0.1"; }
      { address = "192.168.1.226"; }
      { address = "ups-monitor-rack.${vars.domainName}"; }
      { address = "pi-rack.${vars.domainName}"; }
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
      network-02 = {
        passwordFile = config.sops.secrets."nut-client-network-02-password".path;
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
        type = "master";
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
        ];
      };
    };
  };

  systemd.services.nut-server = {
    requires = [ "network-online.target" ];
    after = [ "network-online.target" ];
  };

  services.prometheus.exporters.nut = {
    enable = true;
    port = 9199;
    nutServer = "127.0.0.1";
    nutUser = "monitor-primary";
    passwordPath = config.sops.secrets."nut-monitor-primary-password".path;
    nutVariables = [
      "battery.charge" "battery.runtime" "battery.voltage" "battery.voltage.nominal"
      "input.voltage" "input.voltage.nominal" "output.voltage"
      "ups.load" "ups.status"
    ];
  };
}
