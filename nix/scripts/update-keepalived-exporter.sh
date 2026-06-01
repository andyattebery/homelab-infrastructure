#!/usr/bin/env sh
# Updates the keepalived-exporter Nix package to the latest GitHub release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG="$SCRIPT_DIR/../pkgs/keepalived-exporter.nix"

CURRENT=$(grep 'version = ' "$PKG" | head -1 | sed 's/.*"\(.*\)".*/\1/')
LATEST=$(gh release view --repo mehdy/keepalived-exporter --json tagName -q '.tagName' | sed 's/^v//')

if [ "$CURRENT" = "$LATEST" ]; then
  echo "keepalived-exporter $CURRENT is latest"
  exit 0
fi

echo "==> Updating $CURRENT → $LATEST"

# Nix's fetchurl uses SRI hashes (sha256-<base64>) of the raw file content.
# This computes the same hash: download the tarball, SHA-256 it, base64-encode
# the raw digest. This is brittle — if Nix changes its hash format (e.g., to
# NAR hashing or a different encoding), these hashes will be wrong and flake
# check will fail with the correct hash in the error output.
tarball_sri() {
  curl -sL "https://github.com/mehdy/keepalived-exporter/releases/download/v${LATEST}/keepalived-exporter_${LATEST}_linux_${1}.tar.gz" \
    | openssl dgst -sha256 -binary | openssl base64 -A
}

echo "==> Computing hashes..."
HASH_AMD64="sha256-$(tarball_sri amd64)"
HASH_ARM64="sha256-$(tarball_sri arm64)"
[ "$HASH_AMD64" != "sha256-" ] && [ "$HASH_ARM64" != "sha256-" ] || { echo "Failed to compute hashes"; exit 1; }
echo "    amd64: $HASH_AMD64"
echo "    arm64: $HASH_ARM64"

sed -i.bak "s|version = \"[^\"]*\"|version = \"$LATEST\"|" "$PKG"
sed -i.bak "s|amd64 = \"[^\"]*\"|amd64 = \"$HASH_AMD64\"|" "$PKG"
sed -i.bak "s|arm64 = \"[^\"]*\"|arm64 = \"$HASH_ARM64\"|" "$PKG"
rm -f "$PKG.bak"

echo "==> Verifying..."
"$SCRIPT_DIR/nix-shell.sh" flake check
echo "==> Done. Review: git diff $PKG"
