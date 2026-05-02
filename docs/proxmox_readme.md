# Proxmox README

## From debian

1. Install debian
    a. Choose EFI boot
2. Copy ssh public key
3. Install sudo
4. Add user to sudo group `usermod -a -G sudo <username>`

## From proxmox installer

1. Add non-root user `adduser <username>`
2. Install sudo `apt install sudo`
3. Add user to sudo group `usermod -a -G sudo <username>`
4. Copy ssh key for new user `ssh-copy-id <username>@<hostname>`

## Clearing stale SSH host keys (after a reinstall)

If the host previously existed and has been wiped/reinstalled, the
control node's `~/.ssh/known_hosts` still has the old host's keys and
will refuse to connect. Clear them before the first SSH:

```
ssh-keygen -R <hostname>
ssh-keygen -R <ip>
```
