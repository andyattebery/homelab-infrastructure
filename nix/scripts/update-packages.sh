#!/usr/bin/env bash
# Updates all custom Nix packages to their latest GitHub releases.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

update_github_package() {
  local name="$1" repo="$2"
  local pkg="$SCRIPT_DIR/../pkgs/${name}.nix"

  CURRENT=$(grep 'version = ' "$pkg" | head -1 | sed 's/.*"\(.*\)".*/\1/')
  LATEST=$(gh release view --repo "$repo" --json tagName -q '.tagName' | sed 's/^v//')

  if [ "$CURRENT" = "$LATEST" ]; then
    echo "$name $CURRENT is latest"
    return
  fi

  echo "==> Updating $name $CURRENT → $LATEST"

  tarball_sri() {
    curl -sL "https://github.com/${repo}/releases/download/v${LATEST}/${name}_${LATEST}_linux_${1}.tar.gz" \
      | openssl dgst -sha256 -binary | openssl base64 -A
  }

  echo "==> Computing hashes..."
  HASH_AMD64="sha256-$(tarball_sri amd64)"
  HASH_ARM64="sha256-$(tarball_sri arm64)"
  [ "$HASH_AMD64" != "sha256-" ] && [ "$HASH_ARM64" != "sha256-" ] || { echo "Failed to compute hashes for $name"; exit 1; }
  echo "    amd64: $HASH_AMD64"
  echo "    arm64: $HASH_ARM64"

  sed -i.bak "s|version = \"[^\"]*\"|version = \"$LATEST\"|" "$pkg"
  sed -i.bak "s|amd64 = \"[^\"]*\"|amd64 = \"$HASH_AMD64\"|" "$pkg"
  sed -i.bak "s|arm64 = \"[^\"]*\"|arm64 = \"$HASH_ARM64\"|" "$pkg"
  rm -f "$pkg.bak"
}

update_github_package "keepalived-exporter" "mehdy/keepalived-exporter"
update_github_package "adguardhome-sync" "bakito/adguardhome-sync"

echo "==> Verifying..."
"$SCRIPT_DIR/nix-shell.sh" flake check
echo "==> Done."
