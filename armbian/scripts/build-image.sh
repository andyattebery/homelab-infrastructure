#!/usr/bin/env bash
# shellcheck disable=SC2016 # the scripts given to in_machine are single-quoted to expand in the machine
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARMBIAN_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
REPO_ROOT="$(cd "$ARMBIAN_DIR/.." && pwd -P)"
MACHINE=armbian-build

usage() {
    echo "Usage: $(basename "$0") <hostname>"
    echo
    echo "Build the Turing RK1 image -- Armbian build framework, Debian 13, Rockchip's vendor"
    echo "kernel, at the pins in versions.env -- for one node, in the OrbStack Linux machine"
    echo "'$MACHINE', which it creates on first use. The image is copied to"
    echo "armbian/images/<hostname>/, which is gitignored."
    echo
    echo "<hostname> becomes the node's hostname and names the 1Password item that holds the"
    echo "password of user services: op://Home Lab/<hostname>/password."
    echo
    echo "The image holds that password's hash. Delete it once it is flashed."
    echo
    echo "Example:"
    echo "  $(basename "$0") turingpi-rk1-01"
    exit 1
}

HOST=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            ;;
        -*)
            echo "Unknown option: $1"
            usage
            ;;
        *)
            if [[ -n "$HOST" ]]; then
                echo "Error: multiple hostnames specified"
                usage
            fi
            HOST="$1"
            shift
            ;;
    esac
done

if [[ -z "$HOST" ]]; then
    echo "Error: no hostname specified"
    usage
fi
# It becomes /etc/hostname and part of a 1Password reference, so a plain host label only.
if [[ ! "$HOST" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
    echo "Error: '$HOST' is not a hostname of lowercase letters, digits and inner hyphens"
    exit 1
fi

for tool in orb op git shasum; do
    command -v "$tool" >/dev/null || { echo "Error: $tool not found in PATH"; exit 1; }
done

# shellcheck source=SCRIPTDIR/../versions.env
source "$ARMBIAN_DIR/versions.env"

# The kernel pin is in two places: versions.env and the hook in config-rk1.conf.
if ! grep -qF "KERNELBRANCH='commit:$KERNEL_COMMIT'" "$ARMBIAN_DIR/userpatches/config-rk1.conf"; then
    echo "Error: userpatches/config-rk1.conf does not pin commit:$KERNEL_COMMIT (versions.env)"
    exit 1
fi

# The image holds a password hash and the repo is public, so it may only land where git ignores
# it. Checked against git itself, before anything is built.
OUT_REL="armbian/images/$HOST"
if ! git -C "$REPO_ROOT" check-ignore -q "$OUT_REL/image.img"; then
    echo "Error: $OUT_REL is not gitignored; add /armbian/images/ to .gitignore first."
    exit 1
fi
OUT_DIR="$REPO_ROOT/$OUT_REL"

# The same public keys the NixOS hosts take: every quoted key in the list.
KEYS="$(sed -nE 's/^[[:space:]]*"((ssh-|ecdsa-|sk-)[^"]+)"[[:space:]]*$/\1/p' \
    "$REPO_ROOT/nix/modules/ssh-keys.nix")"
if [[ -z "$KEYS" ]]; then
    echo "Error: no public keys found in nix/modules/ssh-keys.nix"
    exit 1
fi

# in_machine SCRIPT [ARGS...]: run a bash script in the machine as its default user, with ARGS
# as $1, $2, ...
in_machine() {
    local script="$1"
    shift
    orb -m "$MACHINE" bash -c "set -euo pipefail; $script" bash "$@"
}

# The checkout lives in the machine's own Linux filesystem: the kernel tree has file names that
# differ only by case, which the Mac's case-insensitive APFS volume cannot hold. Armbian reads
# userpatches only from inside its checkout (entrypoint.sh declares USERPATCHES_PATH read-only).
if ! orb list -q | grep -qx "$MACHINE"; then
    echo "Creating OrbStack machine $MACHINE (debian:trixie, arm64)..."
    orb create -a arm64 debian:trixie "$MACHINE"
fi
in_machine 'command -v git >/dev/null && command -v rsync >/dev/null ||
    { sudo apt-get update -q && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
        --no-install-recommends ca-certificates git rsync; }'

# A depth-1 fetch of the pinned commit, only when it is not already there; the build needs no
# history, and a repeat fetch downloads the whole tree again.
echo "Checking out armbian/build $ARMBIAN_BUILD_SHA in $MACHINE..."
in_machine '
    dir="$HOME/armbian-build"
    if [[ ! -d "$dir/.git" ]]; then
        git init -q "$dir"
        git -C "$dir" remote add origin "$1"
    fi
    if ! git -C "$dir" cat-file -e "$2^{commit}" 2>/dev/null; then
        git -C "$dir" fetch -q --depth 1 origin "$2"
    fi
    git -C "$dir" checkout -q --detach "$2"
    [[ "$(git -C "$dir" rev-parse HEAD)" == "$2" ]]
    # A compile.sh run as root (sudo ./compile.sh requirements) creates userpatches/ as root,
    # and rsync runs as this user.
    [[ ! -e "$dir/userpatches" ]] || sudo chown -R "$(id -u):$(id -g)" "$dir/userpatches"
    rsync -a --delete --exclude generated/ "$3/userpatches/" "$dir/userpatches/"
    cp "$3/versions.env" "$dir/userpatches/overlay/versions.env"
    # Left by an earlier run that failed after imaging; each holds a password hash.
    sudo rm -f "$dir"/output/images/*.img "$dir"/output/images/*.img.sha
' "$ARMBIAN_BUILD_REPO" "$ARMBIAN_BUILD_SHA" "$ARMBIAN_DIR"

# The two inputs only this node's image gets. They exist only inside the machine and are removed
# when this script exits, whether the build worked or not. GEN expands inside the machine.
GEN='"$HOME/armbian-build/userpatches/overlay/generated"'
PARTIAL=""
cleanup() {
    in_machine "rm -rf $GEN" || echo "Warning: could not remove $GEN in $MACHINE; remove it by hand"
    [[ -z "$PARTIAL" ]] || rm -f "$PARTIAL"
}
trap cleanup EXIT

printf '%s\n' "$KEYS" | in_machine "umask 077; mkdir -p $GEN; cat > $GEN/authorized_keys"

# One op call, so one 1Password prompt, made before the long build so it fails fast. The
# template is built from the validated hostname. The password goes from op's stdout straight
# into the machine: never on the Mac's disk, in an argument, or on screen.
echo "Reading op://Home Lab/$HOST/password (1Password will ask)..."
if ! printf '{{ op://Home Lab/%s/password }}' "$HOST" | op inject |
    in_machine "umask 077; cat > $GEN/services-password; test -s $GEN/services-password"; then
    echo "Error: no password from op://Home Lab/$HOST/password"
    exit 1
fi

# PREFER_DOCKER on the command line: Armbian picks Docker or sudo before it reads config-rk1.conf.
echo "Building $HOST (the first run compiles the kernel and U-Boot)..."
in_machine 'cd "$HOME/armbian-build" && ./compile.sh build rk1 HOST="$1" PREFER_DOCKER=no' "$HOST"

# Copied through OrbStack's mount of the Mac's /Users, owner-only, under a temporary name until
# its checksum matches the one Armbian wrote. Exactly one image is required.
umask 077
mkdir -p "$OUT_DIR"
NAME="$(in_machine '
    umask 077
    shopt -s nullglob
    imgs=("$HOME"/armbian-build/output/images/*.img)
    if [[ ${#imgs[@]} -ne 1 ]]; then
        echo "Error: expected exactly one output/images/*.img, found: ${imgs[*]}" >&2
        exit 1
    fi
    img="${imgs[0]}"
    name="$(basename "$img")"
    cp "$img" "$1/.$name.partial"
    cp "$img.sha" "$1/$name.sha"
    echo "$name"
' "$OUT_DIR")"

if [[ ! "$NAME" =~ ^[A-Za-z0-9._+-]+\.img$ ]]; then
    echo "Error: unexpected image file name: $NAME"
    exit 1
fi
IMG="$OUT_DIR/$NAME"
PARTIAL="$OUT_DIR/.$NAME.partial"
WANT="$(awk '{print $1}' "$IMG.sha")"
GOT="$(shasum -a 256 "$PARTIAL" | awk '{print $1}')"
if [[ ! "$WANT" =~ ^[0-9a-f]{64}$ || "$GOT" != "$WANT" ]]; then
    echo "Error: the copied image does not match $IMG.sha"
    exit 1
fi
mv -f "$PARTIAL" "$IMG"
PARTIAL=""
in_machine 'sudo rm -f "$HOME/armbian-build/output/images/$1" "$HOME/armbian-build/output/images/$1.sha"' "$NAME"

echo
echo "Image: $IMG ($(ls -lh "$IMG" | awk '{print $5}'))"
echo
echo "It holds the password hash of user services. Flash it with scripts/flash-node.sh, then:"
echo "  rm '$IMG' '$IMG.sha'"
