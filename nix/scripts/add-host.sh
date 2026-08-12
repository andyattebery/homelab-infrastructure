#!/usr/bin/env sh
# Scaffold a new NixOS host: host config + age key + sops recipient.
#
# It does NOT touch flake.nix. nixosConfigurations and deploy.nodes are both derived from
# builtins.readDir ./hosts, so creating the directory is what registers the host -- there
# is no list to keep in sync and no marker comment to sed against.
#
# Only the steps whose failure is silent live here. The .sops.yaml two-place insert and the
# re-encrypt are delegated to add-sops-recipient.sh; the key lifecycle to host-age-key.sh.
# A missing or malformed host config, by contrast, is an eval error on the next command.
set -euo pipefail

PROXMOX=false
TAILSCALE=false
SYSTEM="x86_64-linux"
TARGET=""

usage() {
  cat >&2 <<'EOF'
Usage: add-host.sh [options] <hostname> <age-public-key>
       add-host.sh [options] --target <ssh-target> <hostname>

Options:
  --proxmox              host is a Proxmox VM (adds the VM hardware + guest modules)
  --tailscale            add the tailscale capability module
  --system <arch>        x86_64-linux (default) or aarch64-linux
  --target <ssh-target>  create/install the age key on that host instead of passing one in

With --target the age key is generated locally, stored in 1Password and installed over ssh;
the target needs ssh and passwordless sudo, and nothing else. Without it, pass a public key
you already have (e.g. from host-age-key.sh with no --target).
EOF
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --proxmox) PROXMOX=true; shift ;;
    --tailscale) TAILSCALE=true; shift ;;
    --system) [ $# -ge 2 ] || usage; SYSTEM="$2"; shift 2 ;;
    --target) [ $# -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) echo "Unknown option: $1" >&2; usage ;;
    *) break ;;
  esac
done

# With --target the key is fetched rather than passed, so only <hostname> is required.
if [ -n "$TARGET" ]; then
  [ $# -eq 1 ] || usage
else
  [ $# -eq 2 ] || usage
fi

HOSTNAME="$1"
# ${2:-} not $2: under `set -u` the --target form has no second argument and a bare $2
# aborts the script before it does anything.
AGE_KEY="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolved rather than "$SCRIPT_DIR/..", so every path this script prints is readable.
NIX_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOST_DIR="$NIX_DIR/hosts/$HOSTNAME"

if [ -d "$HOST_DIR" ]; then
  echo "Error: $HOST_DIR already exists" >&2
  echo "       To add a sops recipient to an existing host, use add-sops-recipient.sh" >&2
  exit 1
fi

# Everything before the first write happens up here, so an ssh or 1Password failure leaves
# the repo untouched. Once HOST_DIR exists there is state to clean up, hence the trap.
if [ -n "$TARGET" ]; then
  AGE_KEY=$("$SCRIPT_DIR/host-age-key.sh" --target "$TARGET" "$HOSTNAME")
fi

if [ -z "$AGE_KEY" ]; then
  echo "Error: no age public key (pass one as the second argument, or use --target)" >&2
  exit 1
fi

partial_state_hint() {
  status=$?
  [ "$status" -eq 0 ] && return 0
  echo "" >&2
  echo "add-host.sh failed partway. Clean up before re-running -- the 'already exists'" >&2
  echo "check will otherwise refuse:" >&2
  echo "  rm -rf $HOST_DIR" >&2
  echo "  git checkout -- nix/secrets/.sops.yaml" >&2
  return 0
}
trap partial_state_hint EXIT

STATE_VERSION=$(grep 'nixpkgs.url' "$NIX_DIR/flake.nix" | sed 's/.*nixos-\([0-9.]*\).*/\1/')

echo "==> Creating $HOST_DIR/default.nix (stateVersion $STATE_VERSION, $SYSTEM)"
mkdir -p "$HOST_DIR"

# Imports are grouped the way the rest of hosts/ groups them: hardware, then capabilities,
# then stack bundles. An invalid --system is not validated here -- nixpkgs.hostPlatform
# throws at eval, so a typo fails loudly and only affects this one new file.
{
  echo '{ ... }: {'
  if [ "$PROXMOX" = true ] || [ "$TAILSCALE" = true ]; then
    echo '  imports = ['
    if [ "$PROXMOX" = true ]; then
      echo '    # hardware'
      echo '    ../proxmox-vm-hardware.nix'
      echo '    ../../modules/proxmox-guest.nix'
    fi
    if [ "$TAILSCALE" = true ]; then
      echo '    # capabilities'
      echo '    ../../modules/tailscale.nix'
    fi
    echo '  ];'
    echo ''
  fi
  echo "  nixpkgs.hostPlatform = \"$SYSTEM\";"
  echo "  networking.hostName = \"$HOSTNAME\";"
  echo "  system.stateVersion = \"$STATE_VERSION\";"
  echo '}'
} > "$HOST_DIR/default.nix"

"$SCRIPT_DIR/add-sops-recipient.sh" "$HOSTNAME" "$AGE_KEY"

trap - EXIT

echo ""
echo "==> Done. Files changed:"
echo "    $HOST_DIR/default.nix (created -- this is what registers the host)"
echo "    nix/secrets/.sops.yaml (age key added)"
echo "    nix/secrets/{secrets.yaml,vars.nix}, nix/modules/ssh-keys.nix (regenerated)"
echo ""
echo "Next steps:"
echo "  1. Add capability modules to $HOST_DIR/default.nix as needed"
echo "  2. Validate: nix/scripts/nix-shell.sh flake check"
echo "  3. Deploy:   nix/scripts/deploy-host.sh $HOSTNAME"
