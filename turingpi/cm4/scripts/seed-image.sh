#!/usr/bin/env bash
set -euo pipefail

CM4_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    echo "Usage: $(basename "$0") <hostname> <ubuntu-<version>-preinstalled-server-arm64+raspi.img.xz>"
    echo
    echo "Check Canonical's Ubuntu Server image for Raspberry Pi against Ubuntu's SHA256SUMS, and write a"
    echo "copy into turingpi/cm4/images/<hostname>/ (same name, recompressed) whose cloud-init seed in"
    echo "the system-boot partition is turingpi/cm4/cloud-init/user-data and <hostname>/meta-data. Writes"
    echo "the .sha that turingpi/scripts/flash-node.sh needs. Ubuntu's network-config stays. Needs mtools."
    echo
    echo "Example:"
    echo "  $(basename "$0") turingpi-cm4-01 ~/Downloads/ubuntu-26.04.1-preinstalled-server-arm64+raspi.img.xz"
    exit 1
}

HOST="${1:-}"
SRC="${2:-}"
[[ $# -eq 2 && "$HOST" =~ ^[a-z0-9-]+$ ]] || usage
USER_DATA="$CM4_DIR/cloud-init/user-data"
META_DATA="$CM4_DIR/cloud-init/$HOST/meta-data"
if [[ ! -f "$META_DATA" ]]; then
    echo "Error: no $META_DATA; a new node needs one"
    exit 1
fi
NAME="$(basename "$SRC")"
if [[ ! "$NAME" =~ ^ubuntu-([0-9]+\.[0-9]+(\.[0-9]+)?)-preinstalled-server-arm64\+raspi\.img\.xz$ ]]; then
    echo "Error: expected ubuntu-<version>-preinstalled-server-arm64+raspi.img.xz, got $NAME"
    exit 1
fi
VERSION="${BASH_REMATCH[1]}"
if [[ ! -f "$SRC" ]]; then
    echo "Error: no $SRC"
    exit 1
fi
# turingpi/scripts/write-seed.sh checks for the tools it needs.
for tool in curl shasum; do
    command -v "$tool" >/dev/null || { echo "Error: $tool not found in PATH"; exit 1; }
done

echo "Checking $NAME against Ubuntu's SHA256SUMS for $VERSION..."
WANT="$(curl -fsSL "https://cdimage.ubuntu.com/releases/$VERSION/release/SHA256SUMS" \
    | awk -v n="*$NAME" '$2 == n {print $1}')"
GOT="$(shasum -a 256 "$SRC" | awk '{print $1}')"
if [[ ! "$WANT" =~ ^[0-9a-f]{64}$ || "$GOT" != "$WANT" ]]; then
    echo "Error: $NAME has sha256 $GOT; Ubuntu's SHA256SUMS says '$WANT'"
    exit 1
fi

# Ubuntu's partition 1 is the FAT filesystem labelled system-boot, which cloud-init reads its seed
# from.
IMG="$CM4_DIR/images/$HOST/$NAME"
"$CM4_DIR/../scripts/write-seed.sh" "$SRC" "$IMG" system-boot "$USER_DATA" "$META_DATA"

echo
echo "Image: $IMG ($(du -h "$IMG" | cut -f 1))"
echo "Flash it to the host's node (turingpi/nodes.md) with:"
echo "  turingpi/scripts/flash-node.sh <node> $IMG --yes"
