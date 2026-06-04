{ lib, ... }: {
  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";

  boot.initrd.availableKernelModules = [ "xhci_pci" "uas" ];

  swapDevices = [{ device = "/swapfile"; size = 4096; }];

  # UUIDs filled in after NixOS install
  fileSystems."/" = {
    device = "/dev/disk/by-uuid/PLACEHOLDER";
    fsType = "ext4";
  };
  fileSystems."/boot" = {
    device = "/dev/disk/by-uuid/PLACEHOLDER";
    fsType = "vfat";
    options = [ "fmask=0022" "dmask=0022" ];
  };
}
