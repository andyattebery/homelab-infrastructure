#!/usr/bin/env sh
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <user@host-or-ip> [repo-path]"
  echo "  repo-path defaults to /home/services/homelab-infrastructure"
  exit 1
fi

TARGET="$1"
REPO_PATH="${2:-/home/services/homelab-infrastructure}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Syncing vars.nix to $TARGET:$REPO_PATH/nix/secrets/"
scp "$SCRIPT_DIR/../secrets/vars.nix" "$TARGET:$REPO_PATH/nix/secrets/vars.nix"
echo "Done."
