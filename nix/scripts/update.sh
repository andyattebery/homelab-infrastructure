#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Update all flake inputs
"$SCRIPT_DIR"/nix-shell.sh flake update

# Update custom packages (keepalived-exporter, adguardhome-sync)
"$SCRIPT_DIR"/update-packages.sh

# Validate
"$SCRIPT_DIR"/nix-shell.sh flake check