# Foundation: everything every host gets. Imported by mkHost, never by a host file.
#
# Capability modules (tailscale.nix, nut.nix, docker-host.nix, dsm-provider), hardware
# modules (rpi4.nix, proxmox-guest.nix) and stack bundles (network.nix) are opted into by
# the host file instead. If something belongs on every host it belongs here; if a host
# could reasonably decline it, it does not.
#
# Exports _module.args.pkgs-unstable, which tailscale.nix consumes -- that module cannot
# evaluate without this one.
{ config, lib, pkgs, vars, nixpkgs-unstable, sops-nix, ... }:
let
  sshKeys = import ./ssh-keys.nix;
  pkgs-unstable = import nixpkgs-unstable {
    inherit (pkgs.stdenv.hostPlatform) system;
    inherit (config.nixpkgs) config;
  };
in {
  # sops config below is this module's own, so the module that provides it is this
  # module's dependency rather than mkHost's.
  imports = [ sops-nix.nixosModules.sops ];

  _module.args.pkgs-unstable = pkgs-unstable;
  sops.defaultSopsFile = ../secrets/secrets.yaml;
  sops.age.keyFile = "/var/lib/sops-nix/key.txt";

  sops.secrets."services-user-password-hash" = {
    neededForUsers = true;
  };

  time.timeZone = "America/Chicago";
  i18n.defaultLocale = "en_US.UTF-8";

  users.mutableUsers = false;
  users.groups.services.gid = 1000;
  users.users.services = {
    isNormalUser = true;
    uid = 1000;
    group = "services";
    extraGroups = [ "wheel" ];
    hashedPasswordFile = config.sops.secrets."services-user-password-hash".path;
    openssh.authorizedKeys.keys = sshKeys.keys;
    shell = pkgs.fish;
  };
  programs.fish.enable = true;
  security.sudo.wheelNeedsPassword = false;
  security.sudo.extraConfig = ''
    Defaults env_keep += "SSH_AUTH_SOCK"
  '';

  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      PermitRootLogin = "no";
      KbdInteractiveAuthentication = false;
      X11Forwarding = false;
      PermitEmptyPasswords = false;
    };
  };

  system.activationScripts.hostname = lib.stringAfter [ "etc" ] ''
    currentHostname=$(${pkgs.hostname-debian}/bin/hostname)
    desiredHostname="${config.networking.hostName}"
    if [ -n "$desiredHostname" ] && [ "$currentHostname" != "$desiredHostname" ]; then
      ${pkgs.hostname-debian}/bin/hostname "$desiredHostname"
    fi
  '';

  # Firewall disabled — do not add allowedTCPPorts/allowedUDPPorts/openFirewall anywhere.
  networking.firewall.enable = false;

  # UDM Pro sends option 24 (Path MTU Aging Timeout) with encoding dhcpcd can't parse as embedded.
  networking.dhcpcd.extraConfig = ''
    define 24 uint32 mtu_aging_timeout
  '';

  environment.systemPackages = with pkgs; [
    git vim tmux mosh htop jq
  ];

  sops.secrets."beszel-agent-env" = {};
  services.beszel.agent = {
    enable = true;
    environment = {
      HUB_URL = "https://beszel.${vars.domainName}";
      DATA_DIR = "/var/lib/beszel-agent";
    };
    environmentFile = config.sops.secrets."beszel-agent-env".path;
  };
  # Workaround: NixOS beszel module sets DynamicUser=true but no StateDirectory,
  # so the agent can't persist its fingerprint. nixpkgs PR #500866.
  systemd.services.beszel-agent.serviceConfig.StateDirectory = "beszel-agent";

  # Prometheus node_exporter. Was modules/monitoring.nix, which mkHost imported into every
  # host unconditionally -- a capability nobody could decline is foundation, so it lives
  # here now. prometheus.yml scrapes <host>:9100 fleet-wide and assumes it is present.
  systemd.tmpfiles.rules = [ "d /var/lib/node_exporter 0755 root root -" ];

  services.prometheus.exporters.node = {
    enable = true;
    enabledCollectors = [ "systemd" "textfile" ];
    port = 9100;
    extraFlags = [ "--collector.textfile.directory=/var/lib/node_exporter" ];
  };

  systemd.services.dotfiles = {
    description = "Clone/update and link dotfiles for services user";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    path = [ pkgs.git pkgs.fish pkgs.findutils pkgs.coreutils ];
    serviceConfig = {
      Type = "oneshot";
      User = "services";
      Group = "services";
      RemainAfterExit = true;
    };
    script = ''
      if [ -d "$HOME/dotfiles" ]; then
        cd "$HOME/dotfiles"
        git pull --ff-only || true
      else
        git clone https://github.com/andyattebery/dotfiles.git "$HOME/dotfiles"
        cd "$HOME/dotfiles"
      fi
      fish --no-config ./link_dotfiles.fish
    '';
  };

  services.timesyncd.enable = true;
  networking.timeServers = [ "0.us.pool.ntp.org" "1.us.pool.ntp.org" "2.us.pool.ntp.org" "3.us.pool.ntp.org" ];
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
}
