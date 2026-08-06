#!/bin/bash
set -euo pipefail

TESTDIR="/media-raw/data03/.f/test-av1"
SOURCES="$TESTDIR/Sources/TestStudio"
MODELA="$TESTDIR/Models/TestModelA"
MODELB="$TESTDIR/Models/TestModelB"
PASS=0
FAIL=0

check() {
  local desc="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS: $desc ($actual)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected=$expected, got=$actual)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Processed files ==="

# h264-1080p-25fps: should be av1/10bit/mp4
echo "h264-1080p-25fps (Main flow):"
F="$SOURCES/h264-1080p-25fps.mp4"
if [ -f "$F" ]; then
  check "file exists as .mp4" "yes" "yes"
  check "video codec" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "av1"
  check "pixel format" "$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of csv=p=0 "$F")" "yuv420p10le"
  check "audio codec" "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "aac"
else
  if [ -f "$SOURCES/h264-1080p-25fps.mkv" ]; then
    echo "  FAIL: file still .mkv — not processed"
  else
    echo "  FAIL: file missing"
  fi
  FAIL=$((FAIL + 1))
fi

# h264-1080p-25fps-ac3: should be av1/10bit/mp4 with re-encoded audio
echo ""
echo "h264-1080p-25fps-ac3 (Main flow — audio re-encode):"
F="$SOURCES/h264-1080p-25fps-ac3.mp4"
if [ -f "$F" ]; then
  check "file exists as .mp4" "yes" "yes"
  check "video codec" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "av1"
  check "pixel format" "$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of csv=p=0 "$F")" "yuv420p10le"
  check "audio codec" "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "aac"
else
  if [ -f "$SOURCES/h264-1080p-25fps-ac3.mkv" ]; then
    echo "  FAIL: file still .mkv — not processed"
  else
    echo "  FAIL: file missing"
  fi
  FAIL=$((FAIL + 1))
fi

# h264-4k-24fps: should be av1/10bit/mp4
echo ""
echo "h264-4k-24fps (4K flow):"
F="$SOURCES/h264-4k-24fps.mp4"
if [ -f "$F" ]; then
  check "file exists as .mp4" "yes" "yes"
  check "video codec" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "av1"
  check "pixel format" "$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of csv=p=0 "$F")" "yuv420p10le"
  check "audio codec" "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "aac"
else
  if [ -f "$SOURCES/h264-4k-24fps.mkv" ]; then
    echo "  FAIL: file still .mkv — not processed"
  else
    echo "  FAIL: file missing"
  fi
  FAIL=$((FAIL + 1))
fi

# mpeg4-480p-25fps: should be av1/10bit/mp4
echo ""
echo "mpeg4-480p-25fps (Legacy flow):"
F="$SOURCES/mpeg4-480p-25fps.mp4"
if [ -f "$F" ]; then
  check "file exists as .mp4" "yes" "yes"
  check "video codec" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "av1"
  check "pixel format" "$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of csv=p=0 "$F")" "yuv420p10le"
  check "audio codec" "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "aac"
else
  if [ -f "$SOURCES/mpeg4-480p-25fps.avi" ]; then
    echo "  FAIL: file still .avi — not processed"
  else
    echo "  FAIL: file missing"
  fi
  FAIL=$((FAIL + 1))
fi

# mpeg4-480i-25fps: should be av1/10bit/mp4/deinterlaced
echo ""
echo "mpeg4-480i-25fps (Legacy flow — interlaced):"
F="$SOURCES/mpeg4-480i-25fps.mp4"
if [ -f "$F" ]; then
  check "file exists as .mp4" "yes" "yes"
  check "video codec" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "av1"
  check "pixel format" "$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of csv=p=0 "$F")" "yuv420p10le"
  check "audio codec" "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "aac"
  FIELD_ORDER=$(ffprobe -v error -select_streams v:0 -show_entries stream=field_order -of csv=p=0 "$F")
  if [ "$FIELD_ORDER" = "tt" ] || [ "$FIELD_ORDER" = "bb" ] || [ "$FIELD_ORDER" = "tb" ] || [ "$FIELD_ORDER" = "bt" ]; then
    echo "  FAIL: still interlaced (field_order=$FIELD_ORDER) — bwdif deinterlace did not run"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: deinterlaced (field_order=$FIELD_ORDER)"
    PASS=$((PASS + 1))
  fi
else
  if [ -f "$SOURCES/mpeg4-480i-25fps.mkv" ]; then
    echo "  FAIL: file still .mkv — not processed"
  else
    echo "  FAIL: file missing"
  fi
  FAIL=$((FAIL + 1))
fi

echo ""
echo "=== Integrity guard test (truncated file — should be unchanged) ==="

echo "h264-1080p-25fps-truncated.mkv:"
F="$SOURCES/h264-1080p-25fps-truncated.mkv"
if [ -f "$F" ]; then
  check "still exists as .mkv (not replaced)" "yes" "yes"
  check "still h264" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "h264"
  # Verify inode and size are byte-identical to pre-processing state
  if [ -f "$TESTDIR/.truncated-pre-state" ]; then
    PRE_INODE=$(cut -d' ' -f1 "$TESTDIR/.truncated-pre-state")
    PRE_SIZE=$(cut -d' ' -f2 "$TESTDIR/.truncated-pre-state")
    check "inode unchanged (guard blocked replacement)" "$(stat -c '%i' "$F")" "$PRE_INODE"
    check "size unchanged (file not modified)" "$(stat -c '%s' "$F")" "$PRE_SIZE"
  else
    echo "  WARN: .truncated-pre-state not found, skipping inode/size comparison"
  fi
  HL="$MODELA/h264-1080p-25fps-truncated.mkv"
  if [ -f "$HL" ]; then
    check "TestModelA same inode (hardlink intact)" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$F")"
  else
    echo "  FAIL: TestModelA copy missing or renamed"; FAIL=$((FAIL + 1))
  fi
else
  if [ -f "$SOURCES/h264-1080p-25fps-truncated.mp4" ]; then
    echo "  FAIL: file was replaced with .mp4 — integrity guard did NOT catch the corrupt encode"
  else
    echo "  FAIL: file missing"
  fi
  FAIL=$((FAIL + 1))
fi

# Also check no .mp4 version exists in Models
if [ -f "$MODELA/h264-1080p-25fps-truncated.mp4" ]; then
  echo "  FAIL: ModelA has .mp4 — hardlinks were replaced despite corrupt encode"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "=== Rejected files (should be unchanged) ==="

echo "hevc-1080p-25fps.mkv:"
F="$SOURCES/hevc-1080p-25fps.mkv"
if [ -f "$F" ]; then
  check "still exists as .mkv" "yes" "yes"
  check "still hevc" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "hevc"
else
  echo "  FAIL: file missing or renamed"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "h264-1080p-60fps.mkv:"
F="$SOURCES/h264-1080p-60fps.mkv"
if [ -f "$F" ]; then
  check "still exists as .mkv" "yes" "yes"
  check "still h264" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "h264"
  FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$F")
  check "still 60fps" "$FPS" "60/1"
else
  echo "  FAIL: file missing or renamed"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "h264-4096-24fps.mkv (VR/8K width gate):"
F="$SOURCES/h264-4096-24fps.mkv"
if [ -f "$F" ]; then
  check "still exists as .mkv" "yes" "yes"
  check "still h264" "$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F")" "h264"
  WIDTH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$F")
  check "still 4096px wide" "$WIDTH" "4096"
else
  echo "  FAIL: file missing or renamed"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "broken-blank-codec.mkv (blank codec gate):"
F="$SOURCES/broken-blank-codec.mkv"
if [ -f "$F" ]; then
  check "still exists as .mkv" "yes" "yes"
  BC=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$F" 2>/dev/null || true)
  if [ -z "$BC" ] || [ "$BC" = "unknown" ]; then
    echo "  PASS: codec still blank/unreadable ($BC)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: codec readable ($BC) — file may have been replaced"
    FAIL=$((FAIL + 1))
  fi
else
  echo "  FAIL: file missing or renamed"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "=== Hardlink verification (processed files) ==="
# CIFS/SMB does not report nlink accurately (always shows 1). Verify hardlinks via inode comparison only.

echo "h264-1080p-25fps hardlinks:"
SRC="$SOURCES/h264-1080p-25fps.mp4"
if [ -f "$SRC" ]; then
  for dir in "$MODELA" "$MODELB"; do
    HL="$dir/h264-1080p-25fps.mp4"
    if [ -f "$HL" ]; then
      check "$(basename "$dir") same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
    else
      echo "  FAIL: $(basename "$dir")/h264-1080p-25fps.mp4 missing"; FAIL=$((FAIL + 1))
    fi
  done
fi

echo ""
echo "h264-1080p-25fps-ac3 hardlinks:"
SRC="$SOURCES/h264-1080p-25fps-ac3.mp4"
if [ -f "$SRC" ]; then
  HL="$MODELA/h264-1080p-25fps-ac3.mp4"
  if [ -f "$HL" ]; then
    check "TestModelA same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
  else
    echo "  FAIL: TestModelA/h264-1080p-25fps-ac3.mp4 missing"; FAIL=$((FAIL + 1))
  fi
fi

echo ""
echo "h264-4k-24fps hardlinks:"
SRC="$SOURCES/h264-4k-24fps.mp4"
if [ -f "$SRC" ]; then
  HL="$MODELA/h264-4k-24fps.mp4"
  if [ -f "$HL" ]; then
    check "TestModelA same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
  else
    echo "  FAIL: TestModelA/h264-4k-24fps.mp4 missing"; FAIL=$((FAIL + 1))
  fi
fi

echo ""
echo "mpeg4-480p-25fps hardlinks:"
SRC="$SOURCES/mpeg4-480p-25fps.mp4"
if [ -f "$SRC" ]; then
  for dir in "$MODELA" "$MODELB"; do
    HL="$dir/mpeg4-480p-25fps.mp4"
    if [ -f "$HL" ]; then
      check "$(basename "$dir") same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
    else
      echo "  FAIL: $(basename "$dir")/mpeg4-480p-25fps.mp4 missing"; FAIL=$((FAIL + 1))
    fi
  done
fi

echo ""
echo "mpeg4-480i-25fps hardlinks:"
SRC="$SOURCES/mpeg4-480i-25fps.mp4"
if [ -f "$SRC" ]; then
  HL="$MODELA/mpeg4-480i-25fps.mp4"
  if [ -f "$HL" ]; then
    check "TestModelA same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
  else
    echo "  FAIL: TestModelA/mpeg4-480i-25fps.mp4 missing"; FAIL=$((FAIL + 1))
  fi
fi

echo ""
echo "=== Hardlink verification (rejected files — should be unchanged) ==="

echo "hevc-1080p-25fps.mkv in Models:"
SRC="$SOURCES/hevc-1080p-25fps.mkv"
HL="$MODELA/hevc-1080p-25fps.mkv"
if [ -f "$HL" ]; then
  check "TestModelA same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
else
  echo "  FAIL: TestModelA copy missing"; FAIL=$((FAIL + 1))
fi

echo ""
echo "h264-1080p-60fps.mkv in Models:"
SRC="$SOURCES/h264-1080p-60fps.mkv"
HL="$MODELA/h264-1080p-60fps.mkv"
if [ -f "$HL" ]; then
  check "TestModelA same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
else
  echo "  FAIL: TestModelA copy missing"; FAIL=$((FAIL + 1))
fi

echo ""
echo "h264-4096-24fps.mkv in Models:"
SRC="$SOURCES/h264-4096-24fps.mkv"
HL="$MODELA/h264-4096-24fps.mkv"
if [ -f "$HL" ]; then
  check "TestModelA same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
else
  echo "  FAIL: TestModelA copy missing"; FAIL=$((FAIL + 1))
fi

echo ""
echo "broken-blank-codec.mkv in Models:"
SRC="$SOURCES/broken-blank-codec.mkv"
HL="$MODELA/broken-blank-codec.mkv"
if [ -f "$HL" ]; then
  check "TestModelA same inode" "$(stat -c '%i' "$HL")" "$(stat -c '%i' "$SRC")"
else
  echo "  FAIL: TestModelA copy missing"; FAIL=$((FAIL + 1))
fi

echo ""
echo "=== Old file cleanup ==="
OLD_MKV=$(find "$SOURCES" -name "*.mkv" -not -name "hevc-*" -not -name "*60fps*" -not -name "*truncated*" -not -name "*4096*" -not -name "broken-*" 2>/dev/null | wc -l)
OLD_AVI=$(find "$SOURCES" -name "*.avi" 2>/dev/null | wc -l)
check "no stale .mkv from processed files in Sources" "$OLD_MKV" "0"
check "no stale .avi from processed files in Sources" "$OLD_AVI" "0"

STALE_MODELS=$(find "$MODELA" "$MODELB" \( -name "h264-1080p-25fps.mkv" -o -name "h264-1080p-25fps-ac3.mkv" -o -name "h264-4k-24fps.mkv" -o -name "mpeg4-480p-25fps.avi" -o -name "mpeg4-480i-25fps.mkv" \) 2>/dev/null | wc -l)
check "no stale originals in Models for processed files" "$STALE_MODELS" "0"

echo ""
echo "=== Summary ==="
echo "PASS: $PASS  FAIL: $FAIL"
if [ "$FAIL" -eq 0 ]; then
  echo "All checks passed."
else
  echo "Some checks failed — review above."
  exit 1
fi
