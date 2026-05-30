#!/usr/bin/env sh
# Deploys the current config to a NixOS host.
# Run from the repo root on Mac after committing and pushing.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <ssh-target> <hostname> [repo-path]"
  echo "  repo-path defaults to /root/homelab-infrastructure"
  exit 1
fi

TARGET="$1"
HOSTNAME="$2"
REPO_PATH="${3:-/root/homelab-infrastructure}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Pulling on $TARGET ($REPO_PATH)"
ssh "$TARGET" "sudo git -C $REPO_PATH pull"

echo "==> Syncing vars.nix"
scp "$SCRIPT_DIR/../secrets/vars.nix" "$TARGET:/tmp/vars.nix"
ssh "$TARGET" "sudo cp /tmp/vars.nix $REPO_PATH/nix/secrets/vars.nix && rm /tmp/vars.nix"

echo "==> Running nixos-rebuild switch"
ssh "$TARGET" "sudo nixos-rebuild switch --flake $REPO_PATH/nix#$HOSTNAME"

echo "==> Done."
