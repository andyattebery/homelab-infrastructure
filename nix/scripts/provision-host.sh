#!/usr/bin/env sh
# Provisions a new NixOS host from a cloned Proxmox template.
# First run: use root@<ip> (template allows root SSH).
# Re-run: use <ssh-target> from SSH config (services user + sudo).
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
  echo "Usage: $0 [--proxmox] [--tailscale] <ssh-target> <hostname>"
  exit 1
fi

TARGET="$1"
HOSTNAME="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIX_DIR="$SCRIPT_DIR/.."
DEPLOY_USER="services"
REPO_PATH="/root/homelab-infrastructure"

# Extract hostname from user@host or plain host for ssh-keygen
TARGET_HOST=$(echo "$TARGET" | sed 's/.*@//')
ssh-keygen -R "$TARGET_HOST" 2>/dev/null || true

echo "==> Generating age key on $TARGET"
ssh -o StrictHostKeyChecking=accept-new "$TARGET" "sudo mkdir -p /var/lib/sops-nix && sudo chmod 700 /var/lib/sops-nix"
if ssh "$TARGET" "sudo test -f /var/lib/sops-nix/key.txt"; then
  echo "    Key already exists, skipping generation"
else
  ssh "$TARGET" "sudo sh -c 'age-keygen -o /var/lib/sops-nix/key.txt 2>/dev/null && chmod 600 /var/lib/sops-nix/key.txt'"
fi
AGE_PUB=$(ssh "$TARGET" "sudo age-keygen -y /var/lib/sops-nix/key.txt")
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
ssh "$TARGET" "sudo git -C $REPO_PATH pull"

echo "==> Syncing vars.nix to host"
scp "$NIX_DIR/secrets/vars.nix" "$TARGET:/tmp/vars.nix"
ssh "$TARGET" "sudo cp /tmp/vars.nix $REPO_PATH/nix/secrets/vars.nix && rm /tmp/vars.nix"

echo "==> Running nixos-rebuild on host"
ssh "$TARGET" "sudo nixos-rebuild switch --flake $REPO_PATH/nix#$HOSTNAME"

echo "==> Setting up dotfiles"
ssh "$DEPLOY_USER@$TARGET_HOST" "bash -c 'test -d ~/dotfiles || git clone https://github.com/andyattebery/dotfiles.git ~/dotfiles && cd ~/dotfiles && ./link_dotfiles.fish'"

echo ""
echo "==> Host $HOSTNAME provisioned successfully."
echo "    Deploy future changes with: nix/scripts/deploy-host.sh $HOSTNAME $HOSTNAME"
