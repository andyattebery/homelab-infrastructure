#!/usr/bin/env sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Pinned Nix image, tracked in git and bumped by update.sh alongside flake.lock.
IMAGE="$(cat "$SCRIPT_DIR/nix-image" 2>/dev/null || echo 'nixos/nix:2.35.1')"

PLATFORM=""
STORE_VOL="nix-store"
TTY_FLAG=""
EXTRA_DOCKER_FLAGS=""
SSH_FLAGS=""

# Config goes through NIX_CONFIG, not /etc/nix/nix.conf: the image ships that file as a
# read-only symlink into the store, so it can't be appended to. This is the set verified
# to build in this container (flakes on; build as root since there's no build-users setup;
# no sandbox in the minimal container).
NIX_CONFIG_LINES="experimental-features = nix-command flakes
build-users-group =
sandbox = false"

while [ $# -gt 0 ]; do
  case "$1" in
    --x86)
      PLATFORM="--platform linux/amd64"
      STORE_VOL="nix-store-amd64"
      EXTRA_DOCKER_FLAGS="--security-opt seccomp=unconfined"
      # QEMU/Rosetta emulation trips nix's syscall filter.
      NIX_CONFIG_LINES="$NIX_CONFIG_LINES
filter-syscalls = false"
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

# Ensure the pinned image (correct platform) is available; fall back to a cached copy
# when offline. For a pinned immutable tag the pull is a cheap manifest check.
docker pull -q $PLATFORM "$IMAGE" >/dev/null 2>&1 \
  || docker image inspect "$IMAGE" >/dev/null 2>&1 \
  || { echo "nix-shell.sh: cannot obtain $IMAGE (offline, not cached)" >&2; exit 1; }

# Keep the /nix store cache consistent with the image. The image symlinks /etc and /bin/sh
# into /nix/store/...-base-system; a volume seeded by a different image shadows /nix and
# leaves those dangling. Key the volume to the pin string: reuse while the pin is unchanged,
# recreate (Docker re-seeds it from the image on the next mount) when the pin changes.
have="$(docker volume inspect "$STORE_VOL" --format '{{index .Labels "nixImage"}}' 2>/dev/null || true)"
if [ "$have" != "$IMAGE" ]; then
  docker volume rm "$STORE_VOL" >/dev/null 2>&1 || true
  docker volume create --label nixImage="$IMAGE" "$STORE_VOL" >/dev/null
fi

ARGS=""
for arg in "$@"; do
  ARGS="$ARGS '$(echo "$arg" | sed "s/'/'\\\\''/g")'"
done

docker run --rm $TTY_FLAG $PLATFORM $EXTRA_DOCKER_FLAGS $SSH_FLAGS \
  -v "$REPO_ROOT:/work" \
  -v "$STORE_VOL:/nix" \
  -w /work/nix \
  -e NIX_CONFIG="$NIX_CONFIG_LINES" \
  "$IMAGE" \
  sh -c "nix $ARGS"
