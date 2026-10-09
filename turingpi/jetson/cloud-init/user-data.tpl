#cloud-config
# First-boot settings for every Jetson Orin Nano card in this homelab (turingpi/jetson/README.md).
# The card holds the generic image from github.com/andyattebery/jetson-orin-nano-l4t-minimal.
#
# This is a 1Password template. op inject renders it onto the card's CIDATA volume as user-data,
# next to the node's meta-data (turingpi/jetson/cloud-init/<hostname>/meta-data). The rendered
# file holds the domain, so it never goes into the repo. cloud-init needs both files, applies them
# on the first boot, then disables itself (the last write_files entry).
#
# No dollar sign anywhere in this file: op inject replaces a dollar sign followed by a name with that
# environment variable.
#
# Access matches the NixOS hosts (nix/modules/base.nix), except that there is no password: user
# services, uid 1000, passwordless sudo that keeps SSH_AUTH_SOCK, SSH keys only. The keys are
# copied from nix/modules/ssh-keys.nix. A key changed there must be changed here too.

# Turing Pi 2: the module's QSPI holds NVIDIA's firmware with the carrier-board EEPROM read turned
# off, which the Turing Pi needs to boot. NVIDIA's L4T packages come from a private apt repo whose
# nvidia-l4t-bootloader carries that firmware. write_files adds its source, key and pin, and a
# first-boot check that runcmd runs last.
#
# Until the first apt upgrade the card has NVIDIA's own bootloader package. NVIDIA's
# nv-l4t-bootloader-config.service replaces QSPI with that package's stock capsule whenever the
# package is newer than QSPI, unless this switch is off. bootcmd runs in cloud-init's network
# stage, which is ordered before sysinit.target, so the switch is off before that service first
# runs.
bootcmd:
  - [sed, -i, 's/^ENABLE_AUTO_QSPI_UPDATE=.*/ENABLE_AUTO_QSPI_UPDATE="0"/', /opt/nvidia/l4t-bootloader-config/nv-l4t-bootloader-config.conf]

users:
  - name: services
    uid: 1000
    groups: [sudo, video, render]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINbbqGPcNfykhW1otDDfnW5NspRaHJYbpVVu+ZpobYtb"
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDjcevFbdJJVYgNRDzkU8qDlamNFm2/qcXEYAW2HmNqa"
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILzB/Pe+lol11t3Fwit7haMr7QsSpG4y/mAokuvZPXsu"
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFM8kpGI/ndVzIGhlOG8vcFzKky9SenwP9+7cvZcsA88"
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ4o8GVZBMulmiIVoqt5OJ2n5tlU4bx1+Mlnfkz974x/"
ssh_pwauth: false

timezone: America/Chicago
locale: en_US.UTF-8
manage_etc_hosts: localhost

write_files:
  - path: /etc/sudoers.d/91-ssh-auth-sock
    permissions: "0440"
    content: |
      Defaults env_keep += "SSH_AUTH_SOCK"
  # The private repo's signing key, from Forgejo's Debian registry (org homelab), fingerprint
  # 5178 F72C 3F04 55AD 7C2F 3AF8 F13C C0A1 6293 B12A. It's public, and its user ID names no host
  # ("(Debian Registry)"), so it can be committed.
  - path: /etc/apt/keyrings/l4t-private.asc
    permissions: "0644"
    content: |
      -----BEGIN PGP PUBLIC KEY BLOCK-----

      xsBNBGrB22MBCACmWzMJXu3Nt5cVQkJy25TZgs31lfzfimLbCM1rCy0lNW1W7rQ7
      ifMHlq5kP+pvq1hB+ZxMfar9EIPJQd01lhSb5iAVBIbh2IV+MsjgxHAHYy44W8Qq
      sLLsgTxdKGFzHmkKTpoMaDRj8IK6wpYgelNse2ev4B6SNl/jsPUrFrnkRF9QAOg1
      4ZtrHjQ4wrllPgJV4GNBvjYSSd44ECQHvrZNBhvqkTjTnAeLdJi77OS52uSm1wFV
      rm0ZQ1SGmG17AHW6mnSlAXmfv9kBiqt6wqMZFoJHjgO+9UwgDTMQ/jsnivp5dulL
      D8ORZiNFaXvH0O78x3fZkOr9aUSTSX30RmKnABEBAAHNEShEZWJpYW4gUmVnaXN0
      cnkpwsC7BBMBCABvBYJqwdtjAgsHCRDxPMChYpOxKjUUAAAAAAAcABBzYWx0QG5v
      dGF0aW9ucy5vcGVucGdwanMub3JnE9FdpCOj5hCN9E28qZbsfwIVCAIWAAIZAQKb
      AwIeARYhBFF49yw/BFWtfC86+PE8wKFik7EqAADeMAf/eV0rT8FJkMrZpPKqnA8e
      nIjgcac3/C0Mw8lw0ocMeQpGy672NrkKB6Cgdyatzv1PSZjJ62EUOp3OOC6TGmzO
      +KCf08WO7MLeQbGFTwSSMo1R+yHgQtScd6aV6di7t774r9lBCHs43n4pGzm3S3oz
      OVBPCNYwKN/MZMumcJ5Khe71QsmIToQGY3ZZ9p4ffTqbiNeO3yLpM1VhoM/fdnFm
      U4bxXc9aKDt2uCcE+RI5n7ZnM65JEujHXkAqA8ogRb1XEpinuGXuDeES91oCmFmC
      MoHhDktLTQw2hJbdG/ry48pCWBwrbpWqYJ2e7af2YSJL03so+1EJi+zT29xo+yFA
      ys7ATQRqwdtjAQgAvF3kT81AoQfLbyeEEe87qojSaYOlpPQ8fu8acrPX8Kbtv7/F
      7XzEMyvHSWULXU6YaMEt+fgG0KbhuW5PSm9M6givrI2dX3Ygcj8wRXpL8shyNPJC
      os5+rmcVlWPotJutNjQWTqVTA3rt7Lw7HSIu+S5cirbc9GQLT5Dy55zRib3QiQiZ
      sg7myahNbJpHNya9LmCJbtd5+90StZWRPIwGS9uanzOfyBfCyFcY3grvh0Xu/XVy
      97YzPh078LpZ0jXeah24SoKZepO8HlFh2dTDM7FTpGgEWPkYQxNdfcDVN6brDLE2
      YlbeHHMA29454K033rlVdNdYT4ibH731GC0ozwARAQABwsCsBBgBCABgBYJqwdtj
      CRDxPMChYpOxKjUUAAAAAAAcABBzYWx0QG5vdGF0aW9ucy5vcGVucGdwanMub3Jn
      1v29rCdrZrDYBnptzAS92gKbDBYhBFF49yw/BFWtfC86+PE8wKFik7EqAACFdQf/
      f2apjFj2nYVuoZ47BRX0sffjaebWiXAfhO/cORtzPc8hWlymC5jC9KPOi/xHZuB0
      d54M7HOf4BSM+ZDjsOuo4dTZkzrp6Bp3dv26vdPs6FEpgCdBs3H+0dkIeHa/vD18
      VmZc5B9gY8RoTdCUM0ve6eY9jErhmQUueajPgMhBMfR5q/WCqlFw1UCAdAZHfUYO
      8t6Kittgl9y1JQa/JMIS7hPtZDUJixcRdDVESfi8UNBwlOPVfo6b/1mB32uCbpA7
      xsUF1u+3Qv0jpXylsaiNop0pqTzArIaGoOfT5tgKLp46NcrnwSt2W+ZbcBO+7brh
      VWUj0FvVHX9VDIl+zmekKQ==
      =j9bS
      -----END PGP PUBLIC KEY BLOCK-----
  # NVIDIA's L4T release for carriers without an EEPROM: nvidia-l4t-bootloader rebuilt around a
  # capsule with cvb_eeprom_read_size = <0x0>, and NVIDIA's other packages unchanged
  # (research/turing-pi-cluster/orin-nano-qspi-updates.md).
  - path: /etc/apt/sources.list.d/l4t-private.sources
    permissions: "0644"
    content: |
      Types: deb
      URIs: https://forgejo.{{ op://Home Lab/Home Lab/domains/internal }}/api/packages/homelab/debian
      Suites: l4t-bootloader-no-carrier-eeprom
      Components: main
      Signed-By: /etc/apt/keyrings/l4t-private.asc
  # Every package the private repo carries wins at 990, against NVIDIA's 600. NVIDIA's own
  # nvidia-l4t-bootloader never installs (-1).
  - path: /etc/apt/preferences.d/l4t-private
    permissions: "0644"
    content: |
      Package: nvidia-l4t-bootloader
      Pin: release o=Nvidia
      Pin-Priority: -1

      Package: *
      Pin: release n=l4t-bootloader-no-carrier-eeprom
      Pin-Priority: 990
  - path: /usr/local/sbin/l4t-private-repo-check
    permissions: "0755"
    content: |
      #!/bin/sh
      # Run once, as runcmd's last item. Unless apt takes nvidia-l4t-bootloader from the private repo (the
      # rebuild's version carries a "+"), hold every installed nvidia-l4t-* package, so nothing upgrades from
      # NVIDIA's repo alone. Recovery once the repo works: apt-mark unhold '?and(?installed,?name(^nvidia-l4t-))'
      # No dollar sign anywhere in this file: op inject renders it, and its template syntax has variables.
      apt-get update || true
      if apt-cache policy nvidia-l4t-bootloader | grep -q '^ *Candidate: .*+'; then
        echo "l4t-private-repo-check: the candidate is the rebuild; nothing held."
      else
        echo "l4t-private-repo-check: the candidate is not the rebuild; holding the installed nvidia-l4t-* packages." >&2
        apt-cache policy nvidia-l4t-bootloader >&2
        apt-mark hold '?and(?installed,?name(^nvidia-l4t-))'
      fi
  # cloud-init runs once. Left enabled, it reads CIDATA on every boot: edits there would do nothing
  # unless instance-id changed, and deleting the files would make it treat the node as new and
  # regenerate the SSH host keys. Re-provisioning is rewriting the card.
  - path: /etc/cloud/cloud-init.disabled
    defer: true
    content: ""

# runcmd runs in cloud-init's final stage, after multi-user.target. The image holds that stage
# until NTP has set the clock, so the network is up too. Packages and the login shell (fish) are
# Ansible's job.
runcmd:
  # No swap on the card. NVIDIA's first-boot nvfb-swapfile.service made /swapfile; it is wanted by
  # multi-user.target, which this stage runs after. Swap goes on the NVMe (data_disk_offload).
  - |
    if swapon --show=NAME --noheadings | grep -qx /swapfile; then swapoff /swapfile; fi
    rm -f /swapfile
    sed -i '\#^/swapfile #d' /etc/fstab
  # The private repo's first-boot check (write_files): it holds every installed nvidia-l4t-* package
  # unless apt takes the rebuilt bootloader from the private repo. Last, because cloud-init joins
  # runcmd's items into one sh script without set -e and reports only its final exit status, which
  # is then the check's.
  - /usr/local/sbin/l4t-private-repo-check
