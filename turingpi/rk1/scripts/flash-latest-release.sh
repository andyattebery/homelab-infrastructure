#!/usr/bin/env bash
set -euo pipefail

TURINGPI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO=andyattebery/rk1-armbian-minimal

usage() {
    echo "Usage: $(basename "$0") <node 1-2> <trixie|resolute> [--yes]"
    echo
    echo "Download one image of the latest release of $REPO, Debian 13 (trixie) or Ubuntu 26.04"
    echo "(resolute), into turingpi/rk1/images/<tag>/<trixie|resolute>/, check it against its .sha,"
    echo "write the node's cloud-init seed (turingpi/rk1/cloud-init/) into a copy in"
    echo "<trixie|resolute>/<hostname>/, and flash that to the node with turingpi/scripts/flash-node.sh."
    echo "Without --yes it stops after the seed and shows the image and the nodes' power state."
    echo "With it, the node is powered off, flashed, and powered on."
    echo
    echo "Example:"
    echo "  $(basename "$0") 2 resolute --yes"
    exit 1
}

NODE="${1:-}"
DISTRO="${2:-}"
CONFIRM="${3:-}"
# The RK1s are in slots 1 and 2 (turingpi/nodes.md); no other module may get this image.
[[ "$NODE" =~ ^[12]$ ]] || usage
# No default: every release carries both images, and flashing the wrong one costs a reflash. Checked
# here, before it goes into the jq filter below.
[[ "$DISTRO" =~ ^(trixie|resolute)$ ]] || usage
[[ $# -le 3 && ( -z "$CONFIRM" || "$CONFIRM" == --yes ) ]] || usage

TAG="$(gh release view -R "$REPO" --json tagName --jq .tagName)"
NAME="$(gh release view "$TAG" -R "$REPO" --json assets \
    --jq '[.assets[].name | select(endswith(".img.xz") and contains("_'"$DISTRO"'_vendor_"))] | if length == 1 then .[0] else "" end')"
if [[ ! "$TAG" =~ ^[A-Za-z0-9._-]+$ || ! "$NAME" =~ ^[A-Za-z0-9._+-]+\.img\.xz$ ]]; then
    echo "Error: expected the latest release to have a tag and one $DISTRO .img.xz; got '$TAG' and '$NAME'"
    exit 1
fi
echo "Latest release: $TAG"

# One directory per release and distro, because Armbian names the image after the kernel and two
# builds of one kernel share a file name. Downloaded into <distro>.part/ and renamed once it matches
# its .sha, so an interrupted run never leaves a directory that the next run would take as complete.
DIR="$TURINGPI_DIR/rk1/images/$TAG/$DISTRO"
if [[ ! -d "$DIR" ]]; then
    mkdir -p "$(dirname "$DIR")"
    gh release download "$TAG" -R "$REPO" --pattern "$NAME" --pattern "$NAME.sha" \
        --dir "$DIR.part" --clobber
    (cd "$DIR.part" && shasum -a 256 -c "$NAME.sha")
    mv "$DIR.part" "$DIR"
fi

# The node's cloud-init seed goes into a fresh copy on every run, so it always matches
# turingpi/rk1/cloud-init/.
HOST="turingpi-rk1-0$NODE"
META_DATA="$TURINGPI_DIR/rk1/cloud-init/$HOST/meta-data"
[[ -f "$META_DATA" ]] || { echo "Error: no $META_DATA"; exit 1; }
SEEDED="$DIR/$HOST/$NAME"
"$TURINGPI_DIR/scripts/write-seed.sh" "$DIR/$NAME" "$SEEDED" armbi_boot \
    "$TURINGPI_DIR/rk1/cloud-init/user-data" "$META_DATA"
exec "$TURINGPI_DIR/scripts/flash-node.sh" "$NODE" "$SEEDED" ${CONFIRM:+"$CONFIRM"}
