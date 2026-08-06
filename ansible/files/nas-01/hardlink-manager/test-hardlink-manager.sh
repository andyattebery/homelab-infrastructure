#!/bin/bash
# Direct API tests for hardlink-manager /detect and /replace endpoints.
# Run on nas-01 (creates temp files under /mnt/data/).
#
# Usage: HARDLINK_MANAGER_URL=https://hardlink-manager.<domain_name> bash test-hardlink-manager.sh
#        bash test-hardlink-manager.sh https://hardlink-manager.<domain_name>
# The URL is not hardcoded because this repo is public.

set -euo pipefail

API="${1:-${HARDLINK_MANAGER_URL:-}}"
if [ -z "$API" ]; then
  echo "ERROR: set HARDLINK_MANAGER_URL or pass the API URL as \$1"
  exit 1
fi
TESTDIR="/mnt/data/data03/.f/test-hardlink-manager"
PASS=0
FAIL=0

cleanup() { rm -rf "$TESTDIR"; }
trap cleanup EXIT

api() {
  local endpoint="$1"; shift
  curl -sf "$API$endpoint" -H 'Content-Type: application/json' "$@"
}

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (expected='$expected', got='$actual')"
    FAIL=$((FAIL + 1))
  fi
}

assert_ne() {
  local label="$1" unexpected="$2" actual="$3"
  if [ "$unexpected" != "$actual" ]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (should not be '$unexpected')"
    FAIL=$((FAIL + 1))
  fi
}

# ── Setup ──

cleanup
mkdir -p "$TESTDIR/sources" "$TESTDIR/models" "$TESTDIR/sources/Title.XXX-GRP[rarbg]"

echo "=== Test 1: detect excludes source (no glob chars) ==="

echo "file-a" > "$TESTDIR/sources/plain.txt"
ln "$TESTDIR/sources/plain.txt" "$TESTDIR/models/plain.txt"

RESP=$(api /detect -d "{
  \"file_path\": \"$TESTDIR/sources/plain.txt\",
  \"search_root\": \"$TESTDIR\"
}")
STATUS=$(echo "$RESP" | jq -r .status)
SIBLING_COUNT=$(echo "$RESP" | jq '.siblings | length')
HAS_SOURCE=$(echo "$RESP" | jq "[.siblings[] | select(. == \"$TESTDIR/sources/plain.txt\")] | length")

assert_eq "status is ok" "ok" "$STATUS"
assert_eq "1 sibling found" "1" "$SIBLING_COUNT"
assert_eq "source not in siblings" "0" "$HAS_SOURCE"


echo ""
echo "=== Test 2: detect excludes source with [brackets] in path ==="

echo "file-b" > "$TESTDIR/sources/Title.XXX-GRP[rarbg]/brackets.txt"
ln "$TESTDIR/sources/Title.XXX-GRP[rarbg]/brackets.txt" "$TESTDIR/models/brackets.txt"

RESP=$(api /detect -d "{
  \"file_path\": \"$TESTDIR/sources/Title.XXX-GRP[rarbg]/brackets.txt\",
  \"search_root\": \"$TESTDIR\"
}")
STATUS=$(echo "$RESP" | jq -r .status)
SIBLING_COUNT=$(echo "$RESP" | jq '.siblings | length')
HAS_SOURCE=$(echo "$RESP" | jq "[.siblings[] | select(contains(\"[rarbg]\"))] | length")

assert_eq "status is ok" "ok" "$STATUS"
assert_eq "1 sibling found" "1" "$SIBLING_COUNT"
assert_eq "source (with brackets) not in siblings" "0" "$HAS_SOURCE"


echo ""
echo "=== Test 3: replace with same extension (.txt -> .txt) ==="

# Create a "new primary" (different content/inode from the hardlink pair)
echo "transcoded-content" > "$TESTDIR/sources/plain-new.txt"
PRIMARY_INODE=$(stat -c '%i' "$TESTDIR/sources/plain-new.txt")
SIBLING_INODE_BEFORE=$(stat -c '%i' "$TESTDIR/models/plain.txt")

# Sanity: primary and sibling have different inodes before replace
assert_ne "inodes differ before replace" "$PRIMARY_INODE" "$SIBLING_INODE_BEFORE"

RESP=$(api /replace -d "{
  \"new_primary\": \"$TESTDIR/sources/plain-new.txt\",
  \"old_ext\": \".txt\",
  \"new_ext\": \".txt\",
  \"siblings\": [\"$TESTDIR/models/plain.txt\"]
}")
STATUS=$(echo "$RESP" | jq -r .status)
REPLACED=$(echo "$RESP" | jq -r .replaced)
ERRORS=$(echo "$RESP" | jq -r .errors)

assert_eq "status is ok" "ok" "$STATUS"
assert_eq "1 replaced" "1" "$REPLACED"
assert_eq "0 errors" "0" "$ERRORS"

# Verify the sibling still exists and has the correct inode
if [ -e "$TESTDIR/models/plain.txt" ]; then
  SIBLING_INODE_AFTER=$(stat -c '%i' "$TESTDIR/models/plain.txt")
  assert_eq "sibling inode matches primary" "$PRIMARY_INODE" "$SIBLING_INODE_AFTER"
else
  echo "  FAIL: sibling was deleted (same-ext stale-target bug)"
  FAIL=$((FAIL + 1))
fi

# Verify no .hlbak leftover
if [ -e "$TESTDIR/models/plain.txt.hlbak" ]; then
  echo "  FAIL: .hlbak backup was not cleaned up"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: no .hlbak leftover"
  PASS=$((PASS + 1))
fi


echo ""
echo "=== Test 4: replace with extension change (.mkv -> .mp4) ==="

echo "old-content" > "$TESTDIR/models/extchange.mkv"
echo "new-primary" > "$TESTDIR/sources/extchange.mp4"
PRIMARY_INODE=$(stat -c '%i' "$TESTDIR/sources/extchange.mp4")

RESP=$(api /replace -d "{
  \"new_primary\": \"$TESTDIR/sources/extchange.mp4\",
  \"old_ext\": \".mkv\",
  \"new_ext\": \".mp4\",
  \"siblings\": [\"$TESTDIR/models/extchange.mkv\"]
}")
STATUS=$(echo "$RESP" | jq -r .status)
REPLACED=$(echo "$RESP" | jq -r .replaced)

assert_eq "status is ok" "ok" "$STATUS"
assert_eq "1 replaced" "1" "$REPLACED"

# Old .mkv should be gone, new .mp4 should exist with correct inode
if [ -e "$TESTDIR/models/extchange.mkv" ]; then
  echo "  FAIL: old .mkv still exists"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: old .mkv removed"
  PASS=$((PASS + 1))
fi

NEW_INODE=$(stat -c '%i' "$TESTDIR/models/extchange.mp4")
assert_eq "new .mp4 inode matches primary" "$PRIMARY_INODE" "$NEW_INODE"


echo ""
echo "=== Test 5: replace idempotency (re-run same replace) ==="

RESP=$(api /replace -d "{
  \"new_primary\": \"$TESTDIR/sources/extchange.mp4\",
  \"old_ext\": \".mp4\",
  \"new_ext\": \".mp4\",
  \"siblings\": [\"$TESTDIR/models/extchange.mp4\"]
}")
STATUS=$(echo "$RESP" | jq -r .status)
DETAIL_RESULT=$(echo "$RESP" | jq -r '.details[0].result')

assert_eq "status is ok" "ok" "$STATUS"
assert_eq "detail result is ok (idempotent)" "ok" "$DETAIL_RESULT"

INODE_STILL=$(stat -c '%i' "$TESTDIR/models/extchange.mp4")
assert_eq "inode unchanged after re-run" "$PRIMARY_INODE" "$INODE_STILL"


echo ""
echo "=== Test 6: detect with multiple siblings ==="

echo "multi" > "$TESTDIR/sources/multi.txt"
mkdir -p "$TESTDIR/models/groupA" "$TESTDIR/models/groupB"
ln "$TESTDIR/sources/multi.txt" "$TESTDIR/models/groupA/multi.txt"
ln "$TESTDIR/sources/multi.txt" "$TESTDIR/models/groupB/multi.txt"

RESP=$(api /detect -d "{
  \"file_path\": \"$TESTDIR/sources/multi.txt\",
  \"search_root\": \"$TESTDIR\"
}")
SIBLING_COUNT=$(echo "$RESP" | jq '.siblings | length')
HAS_SOURCE=$(echo "$RESP" | jq "[.siblings[] | select(. == \"$TESTDIR/sources/multi.txt\")] | length")

assert_eq "2 siblings found" "2" "$SIBLING_COUNT"
assert_eq "source not in siblings" "0" "$HAS_SOURCE"


echo ""
echo "=== Test 7: replace same-ext with multiple siblings ==="

echo "multi-new" > "$TESTDIR/sources/multi-new.txt"
PRIMARY_INODE=$(stat -c '%i' "$TESTDIR/sources/multi-new.txt")

RESP=$(api /replace -d "{
  \"new_primary\": \"$TESTDIR/sources/multi-new.txt\",
  \"old_ext\": \".txt\",
  \"new_ext\": \".txt\",
  \"siblings\": [\"$TESTDIR/models/groupA/multi.txt\", \"$TESTDIR/models/groupB/multi.txt\"]
}")
STATUS=$(echo "$RESP" | jq -r .status)
REPLACED=$(echo "$RESP" | jq -r .replaced)

assert_eq "status is ok" "ok" "$STATUS"
assert_eq "2 replaced" "2" "$REPLACED"

for grp in groupA groupB; do
  p="$TESTDIR/models/$grp/multi.txt"
  if [ -e "$p" ]; then
    inode=$(stat -c '%i' "$p")
    assert_eq "$grp inode matches primary" "$PRIMARY_INODE" "$inode"
  else
    echo "  FAIL: $grp sibling was deleted (same-ext stale-target bug)"
    FAIL=$((FAIL + 1))
  fi
done


echo ""
echo "=== Results ==="
echo "PASS: $PASS  FAIL: $FAIL"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
