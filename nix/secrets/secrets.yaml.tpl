services-user-password-hash: {{ op://Personal/NixOS Template/nixos/password hash }}
tailscale-auth-key: {{ op://Personal/Tailscale/auth keys/ansible artis3n.tailscale.machine }}
beszel-key: {{ op://Personal/Beszel/config/key }}
beszel-universal-token: {{ op://Personal/Beszel/config/universal token }}

cloudflare-api-token: {{ op://Personal/Cloudflare API Token - Ansible Vault DNS Edit/credential }}
diun-pushover-token: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/tokens/diun }}
pushover-user-key: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/add more/user key }}

network-03-wireguard-env: |
  WIREGUARD_EXTERNAL_DOMAIN={{ op://Personal/wireguard - network-03/config/domain }}
  WIREGUARD_PORT={{ op://Personal/wireguard - network-03/config/port }}
  WIREGUARD_PEERS={{ op://Personal/wireguard - network-03/config/peers }}
  WIREGUARD_INTERNAL_SUBNET={{ op://Personal/wireguard - network-03/config/subnet }}
