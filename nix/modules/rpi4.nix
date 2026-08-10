# Raspberry Pi 4 on-disk layout.
#
# Requires nixos-raspberrypi's raspberry-pi-4.base to be imported alongside this module --
# that supplies the bootloader, firmware partition handling, kernel and initrd modules.
# See nix/docs/raspberry-pi.md.
{ ... }: {
  # nixos-raspberrypi deliberately declares no fileSystems of its own (grep it for
  # mmcblk / by-label / NIXOS_SD and you get nothing), so this is the only place the
  # layout is stated.
  #
  # NIXOS_SD and FIRMWARE are nixpkgs' sd-image.nix defaults (rootVolumeLabel,
  # firmwarePartitionName), inherited by both a self-built image and upstream's
  # rpi4-installer -- so this holds whichever is used to write the disk. Only a disko
  # layout would need different values.
  fileSystems."/" = {
    device = "/dev/disk/by-label/NIXOS_SD";
    fsType = "ext4";
  };

  # nofail, but NOT noauto: installBootLoader rewrites config.txt and each generation's
  # kernel/initrd/DTBs/overlays here on every switch. If this isn't mounted the boot files
  # are written to the wrong place and the system silently stops booting -- upstream
  # nixos-raspberrypi issue #120.
  fileSystems."/boot/firmware" = {
    device = "/dev/disk/by-label/FIRMWARE";
    fsType = "vfat";
    options = [ "nofail" ];
  };

  swapDevices = [{ device = "/swapfile"; size = 4096; }];
}
