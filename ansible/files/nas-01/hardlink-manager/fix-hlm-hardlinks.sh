#!/bin/bash
# Recover hardlinks deleted by the same-ext stale-target bug in hardlink-manager.
# Parses Tdarr job reports via API to find failed sibling replacements,
# then re-creates the missing hardlinks.
#
# Run on nas-01. TDARR_URL must be supplied, by env or as $3 — the domain is not hardcoded
# here because this repo is public:
#   TDARR_URL=https://tdarr.<domain_name> bash fix-hlm-hardlinks.sh "2026-06-13 20:00"
#   TDARR_URL=... bash fix-hlm-hardlinks.sh "2026-06-13 20:00" --apply
#   bash fix-hlm-hardlinks.sh "2026-06-13 20:00" --dry-run https://tdarr.<domain_name>
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 START_TIME [--dry-run|--apply] [TDARR_URL]"
  echo "  START_TIME: only process reports after this time (e.g. '2026-06-13 20:00')"
  exit 1
fi

START_TIME="$1"
START_MS=$(date -d "$START_TIME" +%s%3N 2>/dev/null || date -j -f "%Y-%m-%d %H:%M" "$START_TIME" +%s000 2>/dev/null)
if [ -z "$START_MS" ]; then
  echo "ERROR: could not parse start time: $START_TIME"
  exit 1
fi

MODE="${2:---dry-run}"
# No baked-in default: this repo is public, so the domain comes from the environment or $3.
TDARR_URL="${3:-${TDARR_URL:-}}"
if [ -z "$TDARR_URL" ]; then
  echo "ERROR: set TDARR_URL (e.g. https://tdarr.example.com) or pass it as \$3"
  exit 1
fi

if [ "$MODE" != "--dry-run" ] && [ "$MODE" != "--apply" ]; then
  echo "Usage: $0 START_TIME [--dry-run|--apply] [TDARR_URL]"
  exit 1
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "Tdarr API: $TDARR_URL"
echo "Mode: $MODE"
echo "Start time: $START_TIME (epoch ms: $START_MS)"
echo ""

# ── Step 1: Get transcode report filenames after START_MS ──

echo "Fetching report list..."
curl -sf "$TDARR_URL/api/v2/search-job-reports" \
  -H 'Content-Type: application/json' \
  -d '{"data":{"searchTerms":""}}' \
  | jq -r '.jobReports[].filename' \
  | grep '()transcode()' \
  | while IFS= read -r fname; do
      # Timestamp is the last ()-delimited segment before .txt
      ts=$(echo "$fname" | grep -oP '\d+(?=\.txt$)')
      if [ -n "$ts" ] && [ "$ts" -ge "$START_MS" ]; then
        echo "$fname"
      fi
    done \
  > "$TMPDIR/report-filenames.txt"

REPORT_COUNT=$(wc -l < "$TMPDIR/report-filenames.txt")
echo "Found $REPORT_COUNT transcode reports since $START_TIME"

# ── Step 2: Fetch each report and extract errors ──

echo "Scanning reports for hardlink errors..."
SCANNED=0
ERROR_REPORTS=0

# Output file: primary_path \t sibling_path per line
> "$TMPDIR/fixes.tsv"

while IFS= read -r filename; do
  SCANNED=$((SCANNED + 1))

  # Extract jobId (4th ()-delimited segment)
  jobId=$(echo "$filename" | sed 's/()/ /g' | awk '{print $4}')
  if [ -z "$jobId" ]; then
    continue
  fi

  # Fetch report
  report=$(curl -sf "$TDARR_URL/api/v2/job-reports/$jobId" 2>/dev/null || true)
  if [ -z "$report" ]; then
    continue
  fi

  text=$(echo "$report" | jq -r '.text // empty' 2>/dev/null || true)
  if [ -z "$text" ]; then
    continue
  fi

  # Check for sibling-not-found errors
  if ! echo "$text" | grep -q 'Sibling not found'; then
    continue
  fi

  ERROR_REPORTS=$((ERROR_REPORTS + 1))

  # Extract primary path
  primary=$(echo "$text" | grep -oP 'New primary \(NAS\): \K/mnt/data/\S+' | head -1)
  if [ -z "$primary" ]; then
    echo "  WARN: report $jobId has errors but no primary path"
    continue
  fi

  # Extract failed sibling paths
  echo "$text" | grep -oP 'ERROR on \K/mnt/data/[^:]+(?=: Sibling not found)' | while read -r sibling; do
    printf '%s\t%s\n' "$primary" "$sibling" >> "$TMPDIR/fixes.tsv"
  done

  # Progress
  if [ $((SCANNED % 50)) -eq 0 ]; then
    echo "  ...scanned $SCANNED/$REPORT_COUNT"
  fi

done < "$TMPDIR/report-filenames.txt"

echo "Scanned $SCANNED reports, $ERROR_REPORTS had hardlink errors"

FIX_COUNT=$(wc -l < "$TMPDIR/fixes.tsv")
if [ "$FIX_COUNT" -eq 0 ]; then
  echo "No missing siblings found. Nothing to do."
  exit 0
fi

echo "Found $FIX_COUNT sibling entries to check"
echo ""

# ── Step 3: Check disk and fix ──

TOTAL=0
SKIP_EXISTS=0
SKIP_NO_PRIMARY=0
SKIP_NO_PARENT=0
FIXED=0
ERRORS=0

while IFS=$'\t' read -r primary sibling; do
  TOTAL=$((TOTAL + 1))

  if [ -e "$sibling" ]; then
    SKIP_EXISTS=$((SKIP_EXISTS + 1))
    continue
  fi

  if [ ! -e "$primary" ]; then
    echo "SKIP (primary missing): $primary -> $sibling"
    SKIP_NO_PRIMARY=$((SKIP_NO_PRIMARY + 1))
    continue
  fi

  parent=$(dirname "$sibling")
  if [ ! -d "$parent" ]; then
    echo "SKIP (parent dir missing: $parent): $sibling"
    SKIP_NO_PARENT=$((SKIP_NO_PARENT + 1))
    continue
  fi

  if [ "$MODE" = "--dry-run" ]; then
    echo "ln \"$primary\" \"$sibling\""
    FIXED=$((FIXED + 1))
  else
    primary_inode=$(stat -c '%i' "$primary")
    if ln "$primary" "$sibling" 2>/dev/null; then
      new_inode=$(stat -c '%i' "$sibling")
      if [ "$new_inode" = "$primary_inode" ]; then
        echo "OK: $sibling (inode=$new_inode)"
        FIXED=$((FIXED + 1))
      else
        echo "ERROR (inode mismatch after ln): $sibling"
        ERRORS=$((ERRORS + 1))
      fi
    else
      echo "ERROR (ln failed): $sibling"
      ERRORS=$((ERRORS + 1))
    fi
  fi

done < "$TMPDIR/fixes.tsv"

echo ""
echo "=== Summary ==="
echo "Total entries: $TOTAL"
echo "Skipped (already exists): $SKIP_EXISTS"
echo "Skipped (no primary): $SKIP_NO_PRIMARY"
echo "Skipped (no parent dir): $SKIP_NO_PARENT"
if [ "$MODE" = "--dry-run" ]; then
  echo "Would fix: $FIXED"
else
  echo "Fixed: $FIXED"
  echo "Errors: $ERRORS"
fi
