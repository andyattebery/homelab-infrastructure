services-user-password-hash: {{ op://Personal/NixOS Template/nixos/password hash }}
tailscale-auth-key: {{ op://Personal/Tailscale/auth keys/ansible artis3n.tailscale.machine }}
beszel-agent-env: |
  KEY={{ op://Personal/Beszel/config/key }}
  TOKEN={{ op://Personal/Beszel/config/universal token }}

cloudflare-api-token: {{ op://Personal/Cloudflare API Token - Ansible Vault DNS Edit/credential }}
diun-pushover-token: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/tokens/diun }}
pushover-user-key: {{ op://Personal/6iivbkri4bhihgjhc7rnxva5l4/add more/user key }}
