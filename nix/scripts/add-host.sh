#!/usr/bin/env sh
set -euo pipefail

PROXMOX=false
TAILSCALE=false
SYSTEM="x86_64-linux"
TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --proxmox) PROXMOX=true; shift ;;
    --tailscale) TAILSCALE=true; shift ;;
    --system) SYSTEM="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    *) break ;;
  esac
done

# With --target the age key is generated on the host, so only <hostname> is needed.
if [ -n "$TARGET" ]; then
  EXPECTED_ARGS=1
else
  EXPECTED_ARGS=2
fi
if [ $# -ne "$EXPECTED_ARGS" ]; then
  echo "Usage: $0 [--proxmox] [--tailscale] [--system <arch>] <hostname> <age-public-key>"
  echo "       $0 [--proxmox] [--tailscale] [--system <arch>] --target <ssh-target> <hostname>"
  exit 1
fi

HOSTNAME="$1"
AGE_KEY="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIX_DIR="$SCRIPT_DIR/.."
HOST_DIR="$NIX_DIR/hosts/$HOSTNAME"

if [ -d "$HOST_DIR" ]; then
  echo "Error: $HOST_DIR already exists"
  exit 1
fi

# Generate the host's age key remotely and harvest the public half. Idempotent: an existing
# key is reused, never regenerated -- regenerating would orphan every secret already
# encrypted to it.
if [ -n "$TARGET" ]; then
  echo "==> Generating age key on $TARGET"
  ssh -o StrictHostKeyChecking=accept-new "$TARGET" \
    "sudo mkdir -p /var/lib/sops-nix && sudo chmod 700 /var/lib/sops-nix"
  if ssh "$TARGET" "sudo test -f /var/lib/sops-nix/key.txt"; then
    echo "    Key already exists, reusing"
  else
    ssh "$TARGET" \
      "sudo sh -c 'age-keygen -o /var/lib/sops-nix/key.txt 2>/dev/null && chmod 600 /var/lib/sops-nix/key.txt'"
  fi
  AGE_KEY=$(ssh "$TARGET" "sudo age-keygen -y /var/lib/sops-nix/key.txt")
  echo "    Public key: $AGE_KEY"
fi

if [ -z "$AGE_KEY" ]; then
  echo "Error: no age public key (pass one as the second argument, or use --target)"
  exit 1
fi

STATE_VERSION=$(grep 'nixpkgs.url' "$NIX_DIR/flake.nix" | sed 's/.*nixos-\([0-9.]*\).*/\1/')

echo "==> Creating $HOST_DIR/default.nix (stateVersion $STATE_VERSION)"
mkdir -p "$HOST_DIR"
if [ "$PROXMOX" = true ]; then
  cat > "$HOST_DIR/default.nix" << EOF
{ ... }: {
  imports = [
    ../proxmox-vm-hardware.nix
    ../../modules/proxmox-guest.nix
  ];
  networking.hostName = "$HOSTNAME";
  system.stateVersion = "$STATE_VERSION";
}
EOF
else
  cat > "$HOST_DIR/default.nix" << EOF
{ ... }: {
  networking.hostName = "$HOSTNAME";
  system.stateVersion = "$STATE_VERSION";
}
EOF
fi

echo "==> Adding age key to .sops.yaml"
sed -i.bak "/^creation_rules:/i\\
  - &$HOSTNAME $AGE_KEY
" "$NIX_DIR/secrets/.sops.yaml"
sed -i.bak "/- \*operator/a\\
        - *$HOSTNAME
" "$NIX_DIR/secrets/.sops.yaml"
rm -f "$NIX_DIR/secrets/.sops.yaml.bak"

echo "==> Adding host to flake.nix"
EXTRA_MODULES=""
if [ "$TAILSCALE" = true ]; then
  EXTRA_MODULES="$EXTRA_MODULES ./modules/tailscale.nix"
fi
if [ -n "$EXTRA_MODULES" ]; then
  MODULES_LIST=$(echo "$EXTRA_MODULES" | sed 's/ /\\n        /g')
  sed -i.bak "s|# END_HOSTS|$HOSTNAME = mkHost \"$HOSTNAME\" \"$SYSTEM\" [\\
        $MODULES_LIST\\
      ];\\
      # END_HOSTS|" "$NIX_DIR/flake.nix"
else
  sed -i.bak "s|# END_HOSTS|$HOSTNAME = mkHost \"$HOSTNAME\" \"$SYSTEM\" [];\\
      # END_HOSTS|" "$NIX_DIR/flake.nix"
fi
rm -f "$NIX_DIR/flake.nix.bak"

echo "==> Adding deploy node to flake.nix"
sed -i.bak "s|# END_DEPLOY_NODES|$HOSTNAME = {\\
        hostname = fqdn \"$HOSTNAME\";\\
        sshUser = \"services\";\\
        remoteBuild = true;\\
        profiles.system = {\\
          user = \"root\";\\
          path = deployPkgs.$SYSTEM.deploy-rs.lib.activate.nixos self.nixosConfigurations.$HOSTNAME;\\
        };\\
      };\\
      # END_DEPLOY_NODES|" "$NIX_DIR/flake.nix"
rm -f "$NIX_DIR/flake.nix.bak"

# Re-encrypt secrets.yaml so it includes the new host's age key as a recipient. Without
# this the host cannot decrypt anything, and services-user-password-hash is
# neededForUsers -- it fails at user activation, not at first use.
echo "==> Re-encrypting secrets for the new recipient"
"$SCRIPT_DIR/populate-secrets-from-op.sh"

# Deliberately no git operations: this repo stages only, the user commits.
echo ""
echo "==> Done. Files modified:"
echo "    $HOST_DIR/default.nix (created)"
echo "    nix/secrets/.sops.yaml (age key added)"
echo "    nix/flake.nix (host + deploy node added)"
echo "    nix/secrets/{secrets.yaml,vars.nix}, nix/modules/ssh-keys.nix (regenerated)"
echo ""
echo "Next steps:"
echo "  1. Review the generated files, and the host config in $HOST_DIR/default.nix"
echo "  2. Validate: nix/scripts/nix-shell.sh flake check"
echo "  3. Deploy:   nix/scripts/deploy-host.sh $HOSTNAME"
