{ config, pkgs, ... }:

options.proxmox.cores = 2;
options.proxmox.virtio0 = 
services.sshd.enable = true;

users.users.services = {
  isNormalUser = true;
  openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMUou4k2gaMt+EFFxhTUrBNPQTjT0aYZdrGq9vPrzmSz epsilon"
  ];
#   initialHashedPassword = "$y$j9T$7LKXOXtgdTDofX7./bMbm/$q/MV5ZzLrQEAVXJn08rnyqQ1UhMU8fnDu2dYzPFvnZ2";
  packages = with pkgs; [

  ];
};