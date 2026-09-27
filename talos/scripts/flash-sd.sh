#!/usr/bin/env bash
set -euo pipefail

TALOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TALOS_DIR"

usage() {
    echo "Usage: $(basename "$0") <diskN> [--yes]"
    echo
    echo "Write this cluster's Talos image -- schematic.yaml, at the talosctl version mise.toml"
    echo "pins -- to the microSD card at /dev/<diskN>. Without --yes it only shows which card that"
    echo "is. Refuses anything that is not a whole, removable disk of 4-128 GB."
    echo
    echo "Example:"
    echo "  $(basename "$0") disk4 --yes"
    exit 1
}

DISK="${1:-}"
CONFIRM="${2:-}"
[[ "$DISK" =~ ^disk[0-9]+$ ]] || usage
[[ $# -le 2 && ( -z "$CONFIRM" || "$CONFIRM" == --yes ) ]] || usage

# An SD card is removable media, in the built-in slot or a USB reader. The Mac's own SSD and a
# USB-attached SSD (a PM991 in an enclosure) are not, and are bigger than any card here.
check_disk() {
    local info whole removable size name
    info="$(diskutil info -plist "/dev/$DISK")"
    whole="$(plutil -extract WholeDisk raw -o - - <<<"$info")"
    removable="$(plutil -extract RemovableMedia raw -o - - <<<"$info")"
    size="$(plutil -extract TotalSize raw -o - - <<<"$info")"
    name="$(plutil -extract MediaName raw -o - - <<<"$info")"
    echo "/dev/$DISK: $name, $((size / 1000000000)) GB, whole=$whole removable=$removable"
    if [[ "$whole" != true || "$removable" != true ]]; then
        echo "Error: /dev/$DISK is not a whole removable disk"
        exit 1
    fi
    if (( size < 4000000000 || size > 128000000000 )); then
        echo "Error: /dev/$DISK is $size bytes; the SD cards are 4-128 GB"
        exit 1
    fi
}

check_disk
if [[ "$CONFIRM" != --yes ]]; then
    echo "Re-run with --yes to erase /dev/$DISK and write Talos to it."
    exit 1
fi

# The ID is content-addressed: the same schematic.yaml always gets the same one. gen-config.sh
# builds the installer image name from schematic.id, so a changed schematic must be deliberate.
SCHEMATIC="$(curl -fsS -X POST --data-binary @schematic.yaml https://factory.talos.dev/schematics | jq -r .id)"
if [[ ! "$SCHEMATIC" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Error: Image Factory returned no schematic ID"
    exit 1
fi
if [[ -f schematic.id && "$(cat schematic.id)" != "$SCHEMATIC" ]]; then
    echo "Error: schematic.yaml now gives $SCHEMATIC, but schematic.id holds $(cat schematic.id)."
    echo "The nodes were installed with the old one; see README.md, \"Upgrades\"."
    exit 1
fi
echo "$SCHEMATIC" > schematic.id

# The image is always the talosctl version mise.toml pins, so the two cannot drift apart.
VERSION="$(talosctl version --client --short | awk '/^Talos/ {print $2}')"
if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: could not read the talosctl version; run this from talos/ so mise provides it"
    exit 1
fi
# Both steps write a .part file and rename it, so an interrupted run never leaves a partial
# image that the next run would take as complete and flash.
IMAGE="images/metal-arm64-$SCHEMATIC-$VERSION.raw"
if [[ ! -f "$IMAGE" ]]; then
    mkdir -p images
    if [[ ! -f "$IMAGE.xz" ]]; then
        curl -fL --progress-bar -o "$IMAGE.xz.part" \
            "https://factory.talos.dev/image/$SCHEMATIC/$VERSION/metal-arm64.raw.xz"
        mv "$IMAGE.xz.part" "$IMAGE.xz"
    fi
    xz -dc "$IMAGE.xz" > "$IMAGE.part"
    mv "$IMAGE.part" "$IMAGE"
fi

# Checked again: the first run spends minutes downloading, and a card swapped in the meantime
# must not mean /dev/$DISK is now something else.
check_disk
diskutil unmountDisk "/dev/$DISK"
sudo dd if="$IMAGE" of="/dev/r$DISK" bs=4m status=progress
sync
diskutil eject "/dev/$DISK"
echo "Wrote Talos $VERSION ($SCHEMATIC) to /dev/$DISK."
