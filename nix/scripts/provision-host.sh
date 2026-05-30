#!/usr/bin/env sh
# Provisions a new NixOS host from a cloned Proxmox template.
# Run from the repo root on Mac.
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
  echo "Usage: $0 [--proxmox] [--tailscale] <hostname> <host-ip>"
  exit 1
fi

HOSTNAME="$1"
HOST_IP="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIX_DIR="$SCRIPT_DIR/.."
REPO_URL="https://github.com/andyattebery/homelab-infrastructure.git"
REPO_PATH="/root/homelab-infrastructure"
SSH="ssh -o StrictHostKeyChecking=accept-new root@$HOST_IP"

ssh-keygen -R "$HOST_IP" 2>/dev/null || true

echo "==> Generating age key on $HOST_IP"
$SSH "mkdir -p /var/lib/sops-nix && chmod 700 /var/lib/sops-nix"
if $SSH "test -f /var/lib/sops-nix/key.txt"; then
  echo "    Key already exists, skipping generation"
else
  $SSH "age-keygen -o /var/lib/sops-nix/key.txt 2>/dev/null && chmod 600 /var/lib/sops-nix/key.txt"
fi
AGE_PUB=$($SSH "age-keygen -y /var/lib/sops-nix/key.txt")
echo "    Public key: $AGE_PUB"

HOST_DIR="$NIX_DIR/hosts/$HOSTNAME"
if [ -d "$HOST_DIR" ]; then
  echo "==> Host config already exists at $HOST_DIR, skipping add-host.sh"
  echo "==> Adding age key to .sops.yaml"
  if grep -q "$AGE_PUB" "$NIX_DIR/secrets/.sops.yaml"; then
    echo "    Age key already in .sops.yaml, skipping"
  else
    sed -i.bak "/^creation_rules:/i\\
  - &$HOSTNAME $AGE_PUB
" "$NIX_DIR/secrets/.sops.yaml"
    sed -i.bak "/- \*operator/a\\
        - *$HOSTNAME
" "$NIX_DIR/secrets/.sops.yaml"
    rm -f "$NIX_DIR/secrets/.sops.yaml.bak"
  fi
else
  echo "==> Running add-host.sh"
  ADD_HOST_FLAGS=""
  if [ "$PROXMOX" = true ]; then ADD_HOST_FLAGS="$ADD_HOST_FLAGS --proxmox"; fi
  if [ "$TAILSCALE" = true ]; then ADD_HOST_FLAGS="$ADD_HOST_FLAGS --tailscale"; fi
  "$SCRIPT_DIR/add-host.sh" $ADD_HOST_FLAGS "$HOSTNAME" "$AGE_PUB"
fi

echo "==> Populating secrets from 1Password"
"$SCRIPT_DIR/populate-secrets-from-op.sh"

echo "==> Committing and pushing"
git update-index --no-assume-unchanged "$NIX_DIR/secrets/secrets.yaml" 2>/dev/null || true
git add nix/
git diff --cached --quiet || git commit -m "provision host $HOSTNAME"
git push

echo "==> Pulling on host"
$SSH "git -C $REPO_PATH pull"

echo "==> Syncing vars.nix to host"
scp "$NIX_DIR/secrets/vars.nix" "root@$HOST_IP:$REPO_PATH/nix/secrets/vars.nix"

echo "==> Running nixos-rebuild on host"
$SSH "nixos-rebuild switch --flake $REPO_PATH/nix#$HOSTNAME"

echo ""
echo "==> Host $HOSTNAME provisioned successfully."
echo "    Deploy future changes with: nix/scripts/deploy-host.sh $HOSTNAME $HOSTNAME"
