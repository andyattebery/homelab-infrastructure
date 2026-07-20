#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Pin the Nix Docker image to the current release, tracked alongside flake.lock.
# nix-shell.sh recreates its store cache when this pin changes.
docker pull -q nixos/nix:latest
ver=$(docker run --rm nixos/nix:latest nix --version | sed -n 's/.*(Nix) \([0-9][0-9.]*\).*/\1/p') || true
[ -n "$ver" ] && echo "nixos/nix:$ver" > "$SCRIPT_DIR/nix-image"   # skip write if resolution failed

# Update all flake inputs
"$SCRIPT_DIR"/nix-shell.sh flake update

# Update custom packages (keepalived-exporter, adguardhome-sync)
"$SCRIPT_DIR"/update-packages.sh

# Validate
"$SCRIPT_DIR"/nix-shell.sh flake check