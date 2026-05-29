{ pkgs, ... }:
let
  sshKeys = import ../../modules/ssh-keys.nix;
in {
  imports = [
    ../proxmox-vm-hardware.nix
    ../../modules/proxmox-guest.nix
  ];

  networking.hostName = "nixos-template";

  services.openssh.enable = true;
  services.openssh.settings.PasswordAuthentication = false;
  users.users.root.openssh.authorizedKeys.keys = sshKeys.keys;

  boot.loader.timeout = 0;

  environment.systemPackages = with pkgs; [ git vim age ];

  system.stateVersion = "25.11";
}
