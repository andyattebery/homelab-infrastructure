services-user-password-hash: {{ op://Home Lab/NixOS Template/nixos/password hash }}
tailscale-auth-key: {{ op://Personal/Tailscale/auth keys/ansible artis3n.tailscale.machine }}
beszel-agent-env: |
  KEY={{ op://Personal/Beszel/config/key }}
  TOKEN={{ op://Personal/Beszel/config/universal token }}

cloudflare-api-token: {{ op://Personal/Cloudflare API Token - Ansible Vault DNS Edit/credential }}

# adguardhome-sync
adguardhome-sync-origin-username: {{ op://Personal/adguardhome/username }}
adguardhome-sync-origin-password: {{ op://Personal/adguardhome/password }}
adguardhome-sync-replica-02-username: {{ op://Personal/adguardhome-02/username }}
adguardhome-sync-replica-02-password: {{ op://Personal/adguardhome-02/password }}
adguardhome-sync-replica-03-username: {{ op://Personal/adguardhome-03/username }}
adguardhome-sync-replica-03-password: {{ op://Personal/adguardhome-03/password }}

# network-inventory-manager
nim-adguardhome-password: {{ op://Personal/adguardhome/password }}
nim-unifi-password: {{ op://Home Lab/UniFi/users/network-inventory-manager password }}
nim-github-token: {{ op://Personal/i33z7kysyrclrbj6btdffy47ym/PAT/network-inventory-manager }}
nim-op-service-account-token: {{ op://Home Lab/5p5muinzww2t5ltjnyabgxfwvy/credential }}
diun-pushover-token: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/tokens/diun }}
pushover-user-key: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/add more/user key }}

# nut
nut-admin-password: {{ op://Home Lab/pi-rack/nut/admin password }}
nut-monitor-primary-password: {{ op://Home Lab/pi-rack/nut/upsmon password }}
nut-homeassistant-password: {{ op://Home Lab/pi-rack/nut/homeassistant password }}
nut-client-nas-host-01-password: {{ op://Home Lab/pi-rack/nut/nas-host-01 password }}
nut-client-vm-host-01-password: {{ op://Home Lab/pi-rack/nut/vm-host-01 password }}
nut-client-vm-host-02-password: {{ op://Home Lab/pi-rack/nut/vm-host-02 password }}
nut-client-network-02-password: {{ op://Home Lab/pi-rack/nut/network-02 password }}
nut-client-backup-01-password: {{ op://Home Lab/pi-rack/nut/backup-01 password }}
nut-pushover-token: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/tokens/nut }}
