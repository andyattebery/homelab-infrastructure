#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

usage() {
    echo "Usage: $(basename "$0") <hostname>"
    echo
    echo "Build a flashable disk image of a NixOS host from its own configuration (the flake"
    echo "output packages.aarch64-linux.<hostname>-image) and write it, decompressed, to"
    echo "nix/images/<hostname>/, which is gitignored."
    echo
    echo "The image embeds values rendered from secrets/vars.nix. Delete it once it is flashed."
    echo
    echo "Example:"
    echo "  $(basename "$0") pi-rack"
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

# jq and zstd are needed only after the build, which can take a long time -- fail now instead.
for tool in docker git jq zstd; do
    command -v "$tool" >/dev/null || { echo "Error: $tool not found in PATH"; exit 1; }
done

# The image carries values rendered from vars.nix (the domain, password hashes, the UPS SNMP
# community) and the repo is public, so it may only land where git ignores it. Checked
# against git itself rather than assumed from .gitignore, before anything is written.
OUT_REL="nix/images/$HOST"
if ! git -C "$REPO_ROOT" check-ignore -q "$OUT_REL/image.img"; then
    echo "Error: $OUT_REL is not gitignored; add /nix/images/ to .gitignore first."
    exit 1
fi
OUT_DIR="$REPO_ROOT/$OUT_REL"

# Before building: a placeholder vars.nix fails evaluation somewhere unrelated, or bakes
# placeholder values into the image. check-secrets.sh checks top-level keys only, so a
# missing nested key (network-02.nicMacAddress, say) still surfaces as an eval error below.
"$SCRIPT_DIR"/check-secrets.sh

REF=".#packages.aarch64-linux.$HOST-image"
echo "Building $REF..."
# --sandbox: this builds a whole NixOS closure locally, and unsandboxed, one builder that
# writes to $HOME makes Nix refuse every later build (see nix-shell.sh). --json and
# </dev/null as in deploy-host.sh: jq fails loudly on a corrupted stream, and nix-shell.sh
# adds `docker run -it` when stdin is a TTY (nix-shell.sh:66). --no-link: the image is
# copied out below, so it needs no GC root in the store volume.
STORE_PATH=$("$SCRIPT_DIR/nix-shell.sh" --sandbox build "$REF" --json --no-link </dev/null \
    | jq -r '.[0].outputs.out')

# Anchored at both ends, as in deploy-host.sh.
if [[ ! "$STORE_PATH" =~ ^/nix/store/[a-z0-9]{32}-[a-zA-Z0-9.:_+?=-]+$ ]]; then
    echo "Error: could not determine the image's store path"
    echo "  got: $STORE_PATH"
    exit 1
fi

# Owner-only, the directory and everything written into it.
umask 077
mkdir -p "$OUT_DIR"

ZST_PARTIAL="$OUT_DIR/.image.img.zst.partial"
IMG_PARTIAL="$OUT_DIR/.image.img.partial"
# Nothing sensitive is left behind if what follows fails or is interrupted: both files keep a
# temporary name until the image has been decompressed and verified in full. The compressed
# copy is removed on success too; only the .img is kept.
trap 'rm -f "$ZST_PARTIAL" "$IMG_PARTIAL"' EXIT

# Copied out through a bind mount of the output directory, not streamed over stdout.
# nix-shell.sh runs only `nix`, and the nix command that reads a store file (nix store cat)
# writes to stdout, which pushes the whole image through Docker's attach stream and log
# driver. So this runs the same image against the same store volume (nix-shell.sh:8, :11),
# which the build call above has already matched to the pin. The store is mounted read-only.
#
# The file name comes from the sd-image module (image.baseName) and changes with the board
# and bootloader, so it is found rather than assumed, and exactly one is required.
NAME=$(docker run --rm \
    -v nix-store:/nix:ro \
    -v "$OUT_DIR:/out" \
    "$(cat "$SCRIPT_DIR/nix-image")" \
    sh -c '
        set -eu
        dst=$2
        set -- "$1"/sd-image/*.img.zst
        if [ $# -ne 1 ] || [ ! -f "$1" ]; then
            echo "Error: expected exactly one sd-image/*.img.zst, found: $*" >&2
            exit 1
        fi
        umask 077
        cp "$1" "$dst"
        basename "$1"
    ' sh "$STORE_PATH" "/out/$(basename "$ZST_PARTIAL")")

if [[ ! "$NAME" =~ ^[A-Za-z0-9._+-]+\.img\.zst$ ]]; then
    echo "Error: unexpected image file name: $NAME"
    exit 1
fi
IMG="$OUT_DIR/${NAME%.zst}"

# Decompressed so the flashing tool needs no zstd support. zstd checks the frame checksum
# and fails on a truncated stream, so a bad copy never reaches the final name.
zstd -d -q -f "$ZST_PARTIAL" -o "$IMG_PARTIAL"
chmod 600 "$IMG_PARTIAL"
mv -f "$IMG_PARTIAL" "$IMG"

echo
echo "Image:      $IMG ($(ls -lh "$IMG" | awk '{print $5}'))"
echo "Built from: $STORE_PATH"
echo
echo "It embeds values from secrets/vars.nix. Flash it, then delete it:"
echo "  rm '$IMG'"
