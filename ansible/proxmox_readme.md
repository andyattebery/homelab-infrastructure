# Proxmox README

## From debian

1. Install debian
    a. Choose EFI boot
2. Copy ssh public key
3. Install sudo
4. Add user to sudo group `usermod -a -G sudo <username>`
5. Run ansible playbook run-proxmox.yaml

## From proxmox installer

1. Add non-root user `adduser <username>`
2. Install sudo
3. Add user to sudo group `usermod -a -G sudo <username>`
