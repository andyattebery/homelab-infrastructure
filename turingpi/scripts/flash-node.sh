#!/usr/bin/env bash
set -euo pipefail

TURINGPI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    echo "Usage: $(basename "$0") <node 1-4> <image> [--yes]"
    echo
    echo "Write an image to a Turing Pi 2 node's eMMC through the BMC (TPI_HOSTNAME in"
    echo "turingpi/mise.toml), streamed from this Mac: about 8 minutes per GB, plus verification."
    echo "The image needs its <image>.sha beside it, as rk1-armbian-minimal's releases have; an"
    echo ".img.xz works, the BMC decompresses it. Without --yes it only shows the nodes' power state"
    echo "and the image. With it, the node is powered off, flashed, and powered on; the BMC checks the"
    echo "stream against the .sha. tpi asks for the BMC login unless it has a cached token."
    echo
    echo "Example:"
    echo "  $(basename "$0") 2 turingpi/rk1/images/<name>.img.xz --yes"
    exit 1
}

NODE="${1:-}"
IMAGE="${2:-}"
CONFIRM="${3:-}"
[[ "$NODE" =~ ^[1-4]$ && -n "$IMAGE" ]] || usage
[[ $# -le 3 && ( -z "$CONFIRM" || "$CONFIRM" == --yes ) ]] || usage

# tpi and TPI_HOSTNAME come from turingpi/mise.toml whatever directory this runs from.
tpi() {
    mise -C "$TURINGPI_DIR" exec -- tpi "$@"
}

if [[ ! -f "$IMAGE" || ! -f "$IMAGE.sha" ]]; then
    echo "Error: need $IMAGE and $IMAGE.sha, as a release has them"
    exit 1
fi
# Absolute, because tpi runs with turingpi/ as its working directory.
IMAGE="$(cd "$(dirname "$IMAGE")" && pwd)/$(basename "$IMAGE")"
SHA="$(awk '{print $1}' "$IMAGE.sha")"
if [[ ! "$SHA" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Error: no sha256 in $IMAGE.sha"
    exit 1
fi

echo "Image: $IMAGE ($(ls -lh "$IMAGE" | awk '{print $5}'))"
tpi power status
if [[ "$CONFIRM" != --yes ]]; then
    echo "Re-run with --yes to power off node $NODE, overwrite its eMMC with this image, and power it on."
    exit 1
fi

# Seconds here, rather than a failed check after a stream of several minutes.
if [[ "$(shasum -a 256 "$IMAGE" | awk '{print $1}')" != "$SHA" ]]; then
    echo "Error: $IMAGE does not match $IMAGE.sha"
    exit 1
fi

tpi power off -n "$NODE"
tpi flash -n "$NODE" -i "$IMAGE" --sha256 "$SHA"
tpi power on -n "$NODE"
echo "Flashed node $NODE. The serial console (115200 baud, buffered by the BMC; re-run to read more):"
echo "  mise -C '$TURINGPI_DIR' exec -- tpi uart -n $NODE get"
