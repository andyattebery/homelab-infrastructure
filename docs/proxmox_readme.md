# Proxmox README

## From debian

1. Install debian
    a. Choose EFI boot
2. Copy ssh public key
3. Install sudo
4. Add user to sudo group `usermod -a -G sudo <username>`

## From proxmox installer

One play does what used to be four hand steps plus the stale-host-key cleanup — from the
control node, in a terminal (the root password is prompted for):

```sh
cd ansible
.venv/bin/ansible-playbook playbook-prod-proxmox-cluster-node-rebuild.yaml \
  -e rebuild_node=<node> -e rebuild_osd=preserve --tags bootstrap --ask-pass
```

It forgets the node's old host keys in `~/.ssh/known_hosts` (short name, FQDN, address),
installs `sudo`, creates the automation user with the control node's key and passwordless
sudo, and nothing else; the main playbook does the rest. `rebuild_osd` is required by the
playbook's input check but unused by this phase. Details and the whole rebuild flow:
[proxmox_node_reinstall.md](proxmox_node_reinstall.md), Phase 4.
