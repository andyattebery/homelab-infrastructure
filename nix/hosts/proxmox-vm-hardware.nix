# Shared hardware config for Proxmox VMs.
# Replaced automatically by install-proxmox-template.sh with the output of nixos-generate-config.
{ lib, ... }: {
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
    autoResize = true;
  };
  fileSystems."/boot" = {
    device = "/dev/disk/by-label/ESP";
    fsType = "vfat";
  };
}
