#!/usr/bin/env sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLATFORM=""
STORE_VOL="nix-store"
TTY_FLAG=""
EXTRA_DOCKER_FLAGS=""
NIX_CONF_CMD="mkdir -p /etc/nix && echo 'experimental-features = nix-command flakes' >> /etc/nix/nix.conf && "
SSH_FLAGS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --x86)
      PLATFORM="--platform linux/amd64"
      STORE_VOL="nix-store-amd64"
      EXTRA_DOCKER_FLAGS="--security-opt seccomp=unconfined"
      NIX_CONF_CMD="mkdir -p /etc/nix && echo 'sandbox = false' >> /etc/nix/nix.conf && echo 'filter-syscalls = false' >> /etc/nix/nix.conf && "
      shift
      ;;
    --ssh)
      SSH_FLAGS="-v $HOME/.ssh:/root/.ssh:ro -v /run/host-services/ssh-auth.sock:/agent.sock -e SSH_AUTH_SOCK=/agent.sock"
      shift
      ;;
    *) break ;;
  esac
done

if [ -t 0 ]; then
  TTY_FLAG="-it"
fi

ARGS=""
for arg in "$@"; do
  ARGS="$ARGS '$(echo "$arg" | sed "s/'/'\\\\''/g")'"
done

docker run --rm $TTY_FLAG $PLATFORM $EXTRA_DOCKER_FLAGS $SSH_FLAGS \
  -v "$REPO_ROOT:/work" \
  -v "$STORE_VOL:/nix" \
  -w /work/nix \
  nixos/nix \
  sh -c "${NIX_CONF_CMD}nix $ARGS"
