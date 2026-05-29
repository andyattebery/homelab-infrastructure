#!/usr/bin/env sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_DIR="$SCRIPT_DIR/../secrets"

op inject --in-file "$SECRETS_DIR/secrets.yaml.tpl" \
  | SOPS_AGE_KEY="op://Personal/Nix/age/private key" op run -- sops --encrypt \
         --input-type yaml \
         --output-type yaml \
         --config "$SECRETS_DIR/.sops.yaml" \
         /dev/stdin > "$SECRETS_DIR/secrets.yaml"

echo "Wrote $SECRETS_DIR/secrets.yaml"

op inject --in-file "$SECRETS_DIR/vars.nix.tpl" > "$SECRETS_DIR/vars.nix"
echo "Wrote $SECRETS_DIR/vars.nix"

MODULES_DIR="$SCRIPT_DIR/../modules"
op inject --in-file "$MODULES_DIR/ssh-keys.nix.tpl" > "$MODULES_DIR/ssh-keys.nix"
echo "Wrote $MODULES_DIR/ssh-keys.nix"
