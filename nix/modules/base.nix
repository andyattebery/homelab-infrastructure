{ config, lib, pkgs, vars, ... }:
let
  sshKeys = import ./ssh-keys.nix;
in {
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

  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      PermitRootLogin = "no";
      KbdInteractiveAuthentication = false;
    };
  };

  system.activationScripts.hostname = lib.stringAfter [ "etc" ] ''
    currentHostname=$(${pkgs.hostname-debian}/bin/hostname)
    desiredHostname="${config.networking.hostName}"
    if [ -n "$desiredHostname" ] && [ "$currentHostname" != "$desiredHostname" ]; then
      ${pkgs.hostname-debian}/bin/hostname "$desiredHostname"
    fi
  '';

  networking.firewall.enable = false;

  environment.systemPackages = with pkgs; [
    git vim tmux mosh htop jq
  ];

  sops.secrets."beszel-agent-env" = {};
  services.beszel.agent = {
    enable = true;
    environment = {
      HUB_URL = "https://beszel.${vars.domainName}";
    };
    environmentFile = config.sops.secrets."beszel-agent-env".path;
  };

  services.chrony.enable = true;
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  system.stateVersion = "25.11";
}
