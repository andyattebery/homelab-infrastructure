# Proxmox README

## From debian

1. Install debian
    a. Choose EFI boot
2. Copy ssh public key
3. Install sudo
4. Add user to sudo group `usermod -a -G sudo <username>`

## From proxmox installer

1. Add non-root user `adduser <username>`
2. Install sudo `apt update -y && apt install sudo`
3. Add user to sudo group `usermod -a -G sudo <username>`
4. Copy ssh key for new user `ssh-copy-id <username>@<hostname>`