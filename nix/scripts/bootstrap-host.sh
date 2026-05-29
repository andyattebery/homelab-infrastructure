#!/usr/bin/env sh
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <hostname>"
  exit 1
fi

HOSTNAME="$1"

echo "==> Setting hostname to $HOSTNAME"
hostnamectl set-hostname "$HOSTNAME"

echo "==> Generating sops age key"
mkdir -p /var/lib/sops-nix
if [ -f /var/lib/sops-nix/key.txt ]; then
  echo "    Key already exists at /var/lib/sops-nix/key.txt, skipping"
else
  age-keygen -o /var/lib/sops-nix/key.txt 2>&1
  chmod 600 /var/lib/sops-nix/key.txt
fi

AGE_PUB=$(age-keygen -y /var/lib/sops-nix/key.txt)

echo ""
echo "==> Bootstrap complete for $HOSTNAME"
echo ""
echo "Next steps (on your Mac):"
echo "  nix/scripts/add-host.sh $HOSTNAME $AGE_PUB"
echo "  nix/scripts/populate-secrets-from-op.sh"
echo "  git commit && git push"
echo ""
echo "Then on this host (as services user):"
echo "  cd /home/services/homelab-infrastructure/nix && git pull"
echo "  sudo nixos-rebuild switch --flake .#$HOSTNAME"
