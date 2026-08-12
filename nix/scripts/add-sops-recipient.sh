#!/usr/bin/env sh
# Add a host's age public key to .sops.yaml and re-encrypt secrets for it.
#
# Both insertions are required and neither is optional: the `&<host>` anchor under `keys:`
# names the recipient, and the `- *<host>` line inside creation_rules' key_group is what
# actually adds it. With the anchor alone, sops re-encrypts to the existing recipients and
# the host silently cannot decrypt anything -- which surfaces as a failed activation,
# because services-user-password-hash is neededForUsers.
#
# Separate from add-host.sh because a host that already has config needs this and cannot
# run that: add-host.sh refuses when nix/hosts/<name>/ exists.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 <hostname> <age-public-key>" >&2
  echo "" >&2
  echo "Get the public key from: nix/scripts/host-age-key.sh [--target <ssh>] <hostname>" >&2
  exit 1
fi

HOST="$1"
AGE_KEY="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOPS_YAML="$SCRIPT_DIR/../secrets/.sops.yaml"

# An empty or malformed recipient is the failure this script exists to prevent, so it is
# checked rather than assumed.
case "$AGE_KEY" in
  age1*) ;;
  *) echo "Error: '$AGE_KEY' is not an age public key (expected age1...)" >&2; exit 1 ;;
esac

if grep -q "&$HOST " "$SOPS_YAML"; then
  echo "==> $HOST is already a recipient in .sops.yaml; nothing to add"
  echo "    Re-encrypting anyway so secrets.yaml matches the template."
else
  echo "==> Adding $HOST to .sops.yaml"
  sed -i.bak "/^creation_rules:/i\\
  - &$HOST $AGE_KEY
" "$SOPS_YAML"
  sed -i.bak "/- \*operator/a\\
        - *$HOST
" "$SOPS_YAML"
  rm -f "$SOPS_YAML.bak"
fi

echo "==> Re-encrypting secrets for all recipients"
"$SCRIPT_DIR/populate-secrets-from-op.sh"

echo ""
echo "==> Done. Verify the new recipient landed:"
echo "    grep -c 'recipient:' nix/secrets/.sops.yaml   # anchors under keys:"
echo "    grep -c 'recipient:' nix/secrets/secrets.yaml # one block per recipient"
