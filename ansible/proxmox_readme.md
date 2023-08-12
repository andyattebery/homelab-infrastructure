# Proxmox README

## Configure new host

1. Install debian
    a. Choose EFI boot
2. Copy ssh public key
3. Install sudo
4. Add user to sudo group `usermod -a -G sudo <username>`
5. Run ansible playbook run-proxmox.yaml
