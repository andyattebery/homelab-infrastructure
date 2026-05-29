#!/usr/bin/env sh
# Run as root from the NixOS live ISO: curl ... | sudo sh
# Partitions the disk, clones the repo, and installs from the flake.
# After reboot, the VM is ready to be converted to a Proxmox template.
set -euo pipefail

REPO_URL="https://github.com/andyattebery/homelab-infrastructure.git"

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: must run as root (sudo sh)"
  exit 1
fi

if [ -b /dev/sda ]; then
  DISK="/dev/sda"
elif [ -b /dev/vda ]; then
  DISK="/dev/vda"
else
  echo "Error: no disk found at /dev/sda or /dev/vda"
  exit 1
fi

echo "==> Checking network connectivity"
if ! ping -c 1 -W 3 github.com > /dev/null 2>&1; then
  echo "Error: no network connectivity. Ensure DHCP is working."
  exit 1
fi

echo "==> Partitioning $DISK"
parted "$DISK" -- mklabel gpt
parted "$DISK" -- mkpart ESP fat32 1MiB 512MiB
parted "$DISK" -- set 1 esp on
parted "$DISK" -- mkpart primary 512MiB 100%

echo "==> Formatting"
mkfs.fat -F32 "${DISK}1"
mkfs.ext4 -L nixos "${DISK}2"

echo "==> Mounting"
mount "${DISK}2" /mnt
mkdir -p /mnt/boot
mount "${DISK}1" /mnt/boot

echo "==> Generating hardware config"
nixos-generate-config --root /mnt

echo "==> Cloning repo"
git clone "$REPO_URL" /mnt/root/homelab-infrastructure

echo "==> Copying hardware-configuration.nix into repo"
cp /mnt/etc/nixos/hardware-configuration.nix /mnt/root/homelab-infrastructure/nix/hosts/proxmox-vm-hardware.nix
git -C /mnt/root/homelab-infrastructure add nix/hosts/proxmox-vm-hardware.nix

echo "==> Installing NixOS from flake"
nixos-install --no-root-password --flake /mnt/root/homelab-infrastructure/nix#proxmox-template

echo ""
echo "==> Installation complete."
echo "    1. Remove the ISO from the VM's CD drive in Proxmox"
echo "    2. Reboot: sudo reboot"
echo "    3. Verify SSH works: ssh root@<vm-ip>"
echo "    4. Get the hardware config (from Mac):"
echo "       scp root@<vm-ip>:/root/homelab-infrastructure/nix/hosts/proxmox-vm-hardware.nix nix/hosts/"
echo "    5. Shut down the VM and convert to template in Proxmox UI"
