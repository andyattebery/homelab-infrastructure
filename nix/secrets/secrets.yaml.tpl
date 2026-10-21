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
nim-op-service-account-token: {{ op://Personal/qwncbnwvw5xb4irgum6uzmbgku/credential }}
diun-pushover-token: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/tokens/diun }}
pushover-user-key: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/add more/user key }}

# nut
nut-admin-password: {{ op://Home Lab/pi-rack/nut/admin password }}
nut-monitor-primary-password: {{ op://Home Lab/pi-rack/nut/upsmon password }}
nut-homeassistant-password: {{ op://Home Lab/pi-rack/nut/homeassistant password }}
nut-client-nas-host-01-password: {{ op://Home Lab/pi-rack/nut/nas-host-01 password }}
nut-client-vm-host-01-password: {{ op://Home Lab/pi-rack/nut/vm-host-01 password }}
nut-client-vm-host-02-password: {{ op://Home Lab/pi-rack/nut/vm-host-02 password }}
nut-client-backup-01-password: {{ op://Home Lab/pi-rack/nut/backup-01 password }}
nut-pushover-token: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/tokens/nut }}

# needledrop (pi-turntable)
needledrop-lastfm-api-key: {{ op://Personal/7w3ror76qjfgbk4wgebwt2neka/api/key }}
needledrop-lastfm-api-secret: {{ op://Personal/7w3ror76qjfgbk4wgebwt2neka/api/shared secret }}
needledrop-lastfm-username: {{ op://Personal/7w3ror76qjfgbk4wgebwt2neka/username }}
needledrop-lastfm-password-hash: {{ op://Personal/7w3ror76qjfgbk4wgebwt2neka/add more/password md5 }}

# pi-turntable Wi-Fi: wpa_supplicant's secretsFile, one name=value line per secret. A block
# scalar, so YAML never parses the password. Referenced by ID: the name form contains the SSID.
pi-turntable-wifi: |
  wifi_psk={{ op://Private/gwck4n2ntjc7bpw5whlsemqdxa/5E8E08B4D29E46F792206B1C83ACDE04/password }}
