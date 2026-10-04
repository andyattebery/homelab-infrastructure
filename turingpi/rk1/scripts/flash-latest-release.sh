#!/usr/bin/env bash
set -euo pipefail

TURINGPI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO=andyattebery/rk1-armbian-minimal

usage() {
    echo "Usage: $(basename "$0") <node 1-2> [--yes]"
    echo
    echo "Download the latest release of $REPO into turingpi/rk1/images/<tag>/,"
    echo "check it against its .sha, and flash it to an RK1 node with turingpi/scripts/flash-node.sh."
    echo "Without --yes it stops after the download and shows the image and the nodes' power state."
    echo "With it, the node is powered off, flashed, and powered on: about 7 minutes."
    echo
    echo "Example:"
    echo "  $(basename "$0") 2 --yes"
    exit 1
}

NODE="${1:-}"
CONFIRM="${2:-}"
# The RK1s are in slots 1 and 2 (turingpi/hardware.md); no other module may get this image.
[[ "$NODE" =~ ^[12]$ ]] || usage
[[ $# -le 2 && ( -z "$CONFIRM" || "$CONFIRM" == --yes ) ]] || usage

TAG="$(gh release view -R "$REPO" --json tagName --jq .tagName)"
NAME="$(gh release view "$TAG" -R "$REPO" --json assets \
    --jq '[.assets[].name | select(endswith(".img.xz"))] | if length == 1 then .[0] else "" end')"
if [[ ! "$TAG" =~ ^[A-Za-z0-9._-]+$ || ! "$NAME" =~ ^[A-Za-z0-9._+-]+\.img\.xz$ ]]; then
    echo "Error: expected the latest release to have a tag and one .img.xz; got '$TAG' and '$NAME'"
    exit 1
fi
echo "Latest release: $TAG"

# One directory per release, because Armbian names the image after the kernel and two builds of one
# kernel share a file name. Downloaded into <tag>.part/ and renamed once it matches its .sha, so an
# interrupted run never leaves a directory that the next run would take as complete.
DIR="$TURINGPI_DIR/rk1/images/$TAG"
if [[ ! -d "$DIR" ]]; then
    gh release download "$TAG" -R "$REPO" --pattern "$NAME" --pattern "$NAME.sha" \
        --dir "$DIR.part" --clobber
    (cd "$DIR.part" && shasum -a 256 -c "$NAME.sha")
    mv "$DIR.part" "$DIR"
fi

exec "$TURINGPI_DIR/scripts/flash-node.sh" "$NODE" "$DIR/$NAME" ${CONFIRM:+"$CONFIRM"}
