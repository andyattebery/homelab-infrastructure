#!/bin/bash
set -euo pipefail

TESTDIR="/media-raw/data03/.f/test-av1"
SOURCES="$TESTDIR/Sources/TestStudio"
MODELA="$TESTDIR/Models/TestModelA"
MODELB="$TESTDIR/Models/TestModelB"

# Clean slate
rm -rf "$TESTDIR"
mkdir -p "$SOURCES" "$MODELA" "$MODELB"

echo "=== Creating test files ==="

# 1. h264, 1920x1080, 25fps, ~10s, AAC audio
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  "$SOURCES/h264-1080p-25fps.mkv"

# 2. h264, 3840x2160, 24fps, ~10s, AAC audio
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=3840x2160:rate=24:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  "$SOURCES/h264-4k-24fps.mkv"

# 3. mpeg4, 720x480, 25fps, ~10s, MP3 audio (non-AAC to test re-encode)
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=720x480:rate=25:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v mpeg4 -q:v 5 \
  -c:a libmp3lame -b:a 128k \
  "$SOURCES/mpeg4-480p-25fps.avi"

# 4. hevc, 1920x1080, 25fps, ~10s
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx265 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  "$SOURCES/hevc-1080p-25fps.mkv"

# 5. h264, 1920x1080, 60fps, ~10s
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=1920x1080:rate=60:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  "$SOURCES/h264-1080p-60fps.mkv"

# 6. h264, 1920x1080, 25fps, ~10s, AC3 audio — Main flow audio re-encode branch
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a ac3 -b:a 192k \
  "$SOURCES/h264-1080p-25fps-ac3.mkv"

# 7. Truncated h264 — integrity guard test
# Create a full 10s file, then truncate to ~30% of its size.
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  "$SOURCES/h264-1080p-25fps-truncated.mkv"
FULL_SIZE=$(stat -c '%s' "$SOURCES/h264-1080p-25fps-truncated.mkv")
TRUNC_SIZE=$((FULL_SIZE * 30 / 100))
truncate -s "$TRUNC_SIZE" "$SOURCES/h264-1080p-25fps-truncated.mkv"
echo "  Truncated h264-1080p-25fps-truncated.mkv: ${FULL_SIZE} → ${TRUNC_SIZE} bytes"

# Assert the MKV header still reports ~10s duration after truncation.
# If it doesn't, the duration-ratio guard will compare short-vs-short and pass — a false green.
REPORTED_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 \
  "$SOURCES/h264-1080p-25fps-truncated.mkv" | cut -d. -f1)
echo "  Truncated file reports duration: ${REPORTED_DUR}s (need ~10 for a valid guard test)"
if [ "${REPORTED_DUR:-0}" -lt 8 ]; then
  echo "ERROR: truncated file reports ${REPORTED_DUR}s, not ~10s."
  echo "The header no longer claims full duration, so this file will NOT test the duration-ratio"
  echo "guard (output will match the short reported duration and pass). Adjust truncation or use"
  echo "dd conv=notrunc to corrupt video payload while preserving container metadata."
  exit 1
fi

# Record inode+size before processing for verify script comparison
stat -c '%i %s' "$SOURCES/h264-1080p-25fps-truncated.mkv" > "$TESTDIR/.truncated-pre-state"
echo "  Recorded inode+size to .truncated-pre-state for post-processing verification"

# 8. h264, 4096x2160, 24fps, ~10s — VR/8K width gate test (≥4000px, rejected by all flows)
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=4096x2160:rate=24:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  "$SOURCES/h264-4096-24fps.mkv"

# 9. mpeg4, 720x480, interlaced, 25fps, ~10s — Legacy deinterlace branch test
# Uses MKV container (not AVI) because AVI can't store field_order metadata.
# The Legacy flow gates on mpeg4 codec, not container, so MKV works.
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=720x480:rate=50:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -vf "tinterlace=interleave_top,setfield=tff" \
  -c:v mpeg4 -q:v 5 -flags +ilme+ildct \
  -c:a libmp3lame -b:a 128k \
  "$SOURCES/mpeg4-480i-25fps.mkv"

# 10. Blank/unreadable codec — exercises include-only codec gate for the 22 broken production files
# Create a valid h264 MKV, then hard-truncate to 4KB so codec identification fails.
ffmpeg -hide_banner -y \
  -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=10" \
  -f lavfi -i "sine=frequency=440:duration=10" \
  -c:v libx264 -preset ultrafast -crf 28 \
  -c:a aac -b:a 128k \
  "$SOURCES/broken-blank-codec.mkv"
truncate -s 512 "$SOURCES/broken-blank-codec.mkv"

echo ""
echo "=== Creating hardlinks ==="
# Every source file gets at least one model hardlink
for f in "$SOURCES"/*; do
  ln "$f" "$MODELA/$(basename "$f")"
done
ln "$BRACKET_DIR/h264-brackets.mkv" "$MODELA/h264-brackets.mkv"
# Two files get a second model tag (multi-sibling test)
ln "$SOURCES/h264-1080p-25fps.mkv" "$MODELB/h264-1080p-25fps.mkv"
ln "$SOURCES/mpeg4-480p-25fps.avi" "$MODELB/mpeg4-480p-25fps.avi"

echo ""
echo "=== Verification ==="
for f in "$SOURCES"/*; do
  CODEC=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$f" 2>/dev/null || true)
  WIDTH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$f" 2>/dev/null || true)
  FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$f" 2>/dev/null || true)
  AUDIO=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$f" 2>/dev/null || true)
  SIZE=$(stat -c '%s' "$f")
  echo "$(basename "$f"): codec=$CODEC width=$WIDTH fps=$FPS audio=$AUDIO size=$SIZE"
done

echo ""
echo "=== Blank-codec file check ==="
BC=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 \
  "$SOURCES/broken-blank-codec.mkv" 2>/dev/null || true)
echo "broken-blank-codec.mkv probes codec='${BC}' (need empty/unreadable)"
if [ -n "$BC" ] && [ "$BC" != "unknown" ]; then
  echo "ERROR: file probes as '$BC', not blank — won't test the blank-codec gate path."
  echo "Truncate harder or corrupt the codec header region differently."
  exit 1
fi

echo ""
echo "=== Interlaced file field_order check ==="
FIELD_ORDER=$(ffprobe -v error -select_streams v:0 -show_entries stream=field_order -of csv=p=0 "$SOURCES/mpeg4-480i-25fps.mkv")
echo "mpeg4-480i-25fps.mkv field_order=$FIELD_ORDER"
if [ "$FIELD_ORDER" != "tt" ] && [ "$FIELD_ORDER" != "bb" ] && [ "$FIELD_ORDER" != "tb" ] && [ "$FIELD_ORDER" != "bt" ]; then
  echo "ERROR: field_order is not interlaced — the Legacy deinterlace branch will not be tested"
  exit 1
fi

echo ""
echo "=== Hardlink check ==="
for dir in "$MODELA" "$MODELB"; do
  echo "$(basename "$dir"):"
  for f in "$dir"/*; do
    SRC="$SOURCES/$(basename "$f")"
    if [ "$(stat -c '%i' "$f")" = "$(stat -c '%i' "$SRC")" ]; then
      echo "  $(basename "$f"): OK (same inode)"
    else
      echo "  $(basename "$f"): FAIL (different inode)"
    fi
  done
done

echo ""
echo "Done. Test files at: $TESTDIR"
