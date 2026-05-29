#!/usr/bin/env sh
set -euo pipefail

PROXMOX=false
TAILSCALE=false
while [ $# -gt 0 ]; do
  case "$1" in
    --proxmox) PROXMOX=true; shift ;;
    --tailscale) TAILSCALE=true; shift ;;
    *) break ;;
  esac
done

if [ $# -ne 2 ]; then
  echo "Usage: $0 [--proxmox] [--tailscale] <hostname> <age-public-key>"
  exit 1
fi

HOSTNAME="$1"
AGE_KEY="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIX_DIR="$SCRIPT_DIR/.."
HOST_DIR="$NIX_DIR/hosts/$HOSTNAME"

if [ -d "$HOST_DIR" ]; then
  echo "Error: $HOST_DIR already exists"
  exit 1
fi

echo "==> Creating $HOST_DIR/default.nix"
mkdir -p "$HOST_DIR"
if [ "$PROXMOX" = true ]; then
  cat > "$HOST_DIR/default.nix" << EOF
{ ... }: {
  imports = [
    ../proxmox-vm-hardware.nix
    ../../modules/proxmox-guest.nix
  ];
  networking.hostName = "$HOSTNAME";
}
EOF
else
  cat > "$HOST_DIR/default.nix" << EOF
{ ... }: {
  networking.hostName = "$HOSTNAME";
}
EOF
fi

echo "==> Adding age key to .sops.yaml"
sed -i.bak "/^creation_rules:/i\\
  - &$HOSTNAME $AGE_KEY
" "$NIX_DIR/secrets/.sops.yaml"
sed -i.bak "/- \*operator/a\\
        - *$HOSTNAME
" "$NIX_DIR/secrets/.sops.yaml"
rm -f "$NIX_DIR/secrets/.sops.yaml.bak"

echo "==> Adding host to flake.nix"
EXTRA_MODULES=""
if [ "$TAILSCALE" = true ]; then
  EXTRA_MODULES="$EXTRA_MODULES ./modules/tailscale.nix"
fi
if [ -n "$EXTRA_MODULES" ]; then
  MODULES_LIST=$(echo "$EXTRA_MODULES" | sed 's/ /\\n        /g')
  sed -i.bak "s|# END_HOSTS|$HOSTNAME = mkHost \"$HOSTNAME\" [\\
        $MODULES_LIST\\
      ];\\
      # END_HOSTS|" "$NIX_DIR/flake.nix"
else
  sed -i.bak "s|# END_HOSTS|$HOSTNAME = mkHost \"$HOSTNAME\" [];\\
      # END_HOSTS|" "$NIX_DIR/flake.nix"
fi
rm -f "$NIX_DIR/flake.nix.bak"

echo ""
echo "==> Done. Files modified:"
echo "    $HOST_DIR/default.nix (created)"
echo "    nix/secrets/.sops.yaml (age key added)"
echo "    nix/flake.nix (host added)"
echo ""
echo "Next steps:"
echo "  1. Review the generated files"
echo "  2. Run: nix/scripts/populate-secrets-from-op.sh"
echo "  3. git commit && git push"
echo "  4. Run: nix/scripts/sync-vars.sh $HOSTNAME"
echo "  5. On the host: cd /root/homelab-infrastructure/nix && git pull"
echo "     sudo nixos-rebuild switch --flake .#$HOSTNAME"
