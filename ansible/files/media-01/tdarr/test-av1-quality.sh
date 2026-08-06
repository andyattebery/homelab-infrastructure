#!/bin/bash
# Test AV1 NVENC encoding with production parameters.
# Run inside the Tdarr container: docker exec -it tdarr-node bash
# Usage: ./test-av1-quality.sh /media-raw/data03/.f/Sources/path/to/file.mkv

set -euo pipefail

INPUT="$1"
BASENAME=$(basename "${INPUT%.*}")
OUTDIR="/temp/av1-test"
mkdir -p "$OUTDIR"

echo "Source: $INPUT"
echo "Size:   $(du -h "$INPUT" | cut -f1)"
echo "Codec:  $(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,width,height -of csv=p=0 "$INPUT")"
echo ""

OUT="$OUTDIR/${BASENAME}_p7_cq34_10bit.mp4"
echo "--- Encoding: p7/uhq, CQ 34, 10-bit ---"
START=$(date +%s)
ffmpeg -hide_banner -hwaccel cuda \
  -i "$INPUT" \
  -c:v av1_nvenc \
  -preset p7 -tune uhq -rc vbr -b:v 0 -cq 34 \
  -rc-lookahead 32 -spatial-aq 1 -temporal-aq 1 \
  -b_ref_mode middle -g 120 -pix_fmt p010le \
  -c:a aac \
  "$OUT" -y 2>&1
ELAPSED=$(( $(date +%s) - START ))
echo ""
echo "=== Result ==="
echo "Output: $(du -h "$OUT" | cut -f1)  (${ELAPSED}s)"
echo ""

echo "=== Verification ==="
PROBE=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt -of csv=p=0 "$OUT")
echo "Video: $PROBE"
EXPECTED="av1,yuv420p10le"
if [ "$PROBE" = "$EXPECTED" ]; then
  echo "OK: codec and pixel format match ($EXPECTED)"
else
  echo "FAIL: expected $EXPECTED, got $PROBE"
  exit 1
fi
AUDIO=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$OUT")
echo "Audio: $AUDIO"
echo ""
echo "Copy to Mac: scp <host>:$OUT ~/Desktop/"
