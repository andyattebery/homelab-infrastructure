#!/usr/bin/env bash
set -euo pipefail

# Post-batch hardlink verification for Tdarr AV1 flows.
# Run inside the tdarr-node container.
# Usage: bash test-av1-verify-hardlinks.sh [search_root ...]
# Default search roots: all /media-raw/data* mounts.
#
# The hardlink integrity check does a single traversal per root,
# grouping files by basename. Files with the same basename in different
# directories should share an inode (hardlinked). If they don't, they're
# independent copies wasting disk.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

errors=0
warnings=0

if [ $# -gt 0 ]; then
    ROOTS=("$@")
else
    ROOTS=()
    while IFS= read -r line; do
        mountpoint=$(echo "$line" | awk '{print $2}')
        ROOTS+=("$mountpoint")
    done < <(grep '/media-raw/data' /proc/mounts)
fi

if [ ${#ROOTS[@]} -eq 0 ]; then
    echo -e "${RED}FAIL${NC}: No /media-raw/data* mounts found"
    exit 1
fi

echo "=== Serverino Check ==="
while IFS= read -r line; do
    mountpoint=$(echo "$line" | awk '{print $2}')
    opts=$(echo "$line" | awk '{print $4}')
    if echo "$opts" | grep -q 'serverino'; then
        echo -e "  ${GREEN}OK${NC}  $mountpoint"
    else
        echo -e "  ${RED}FAIL${NC}  $mountpoint — serverino missing"
        errors=$((errors + 1))
    fi
done < <(grep '/media-raw/data' /proc/mounts)
echo ""

echo "=== Orphaned Files ==="
orphan_count=0
for root in "${ROOTS[@]}"; do
    while IFS= read -r f; do
        echo -e "  ${YELLOW}ORPHAN${NC}  $f"
        orphan_count=$((orphan_count + 1))
    done < <(find "$root" \( -name '*.hlbak' -o -name '*.partial.old' \) -type f 2>/dev/null)
done
if [ "$orphan_count" -eq 0 ]; then
    echo -e "  ${GREEN}OK${NC}  No orphaned .hlbak or .partial.old files"
else
    echo -e "  ${YELLOW}WARN${NC}  $orphan_count orphaned file(s) found"
    warnings=$((warnings + 1))
fi
echo ""

echo "=== Hardlink Integrity ==="
broken_groups=0
total_files=0
total_unique_inodes=0
tmpfile=$(mktemp)
trap 'rm -f "$tmpfile"' EXIT

for root in "${ROOTS[@]}"; do
    # Single traversal: stat all media files, output "inode basename path"
    find "$root" -type f \( -name '*.mp4' -o -name '*.mkv' -o -name '*.avi' \) \
        -exec stat -c '%i %n' {} + 2>/dev/null | while IFS=' ' read -r ino filepath; do
        basename=$(basename "$filepath")
        echo "$basename $ino $filepath"
    done >> "$tmpfile"
done

total_files=$(wc -l < "$tmpfile")

if [ "$total_files" -eq 0 ]; then
    echo -e "  ${YELLOW}WARN${NC}  No media files found"
else
    # Group by basename. For each basename that appears multiple times,
    # all entries should share the same inode (hardlinked).
    sort "$tmpfile" | awk '
    {
        basename = $1
        ino = $2
        path = $3
        if (basename == prev_basename) {
            group_count++
            if (ino != group_ino) {
                broken++
                if (broken_printed < 20) {
                    print "  \033[0;31mBROKEN\033[0m  " basename ": ino=" group_ino " vs ino=" ino
                    print "    " group_first_path
                    print "    " path
                    broken_printed++
                }
            }
        } else {
            if (group_count > 1) { groups++ }
            group_count = 1
            group_ino = ino
            group_first_path = path
            prev_basename = basename
        }
    }
    END {
        if (group_count > 1) { groups++ }
        if (broken > 0) {
            print "  \033[0;31mFAIL\033[0m  " broken " broken hardlink group(s) out of " groups+0 " groups"
            exit 1
        } else {
            print "  \033[0;32mOK\033[0m  All hardlink groups intact (" groups+0 " groups, " NR " files)"
        }
    }' || { broken_groups=1; errors=$((errors + 1)); }

    total_unique_inodes=$(awk '{print $2}' "$tmpfile" | sort -u | wc -l)
    ratio=$(awk "BEGIN {printf \"%.1f\", $total_files / $total_unique_inodes}")
    echo "  Files: $total_files, Unique inodes: $total_unique_inodes (ratio: ${ratio}x)"
fi
echo ""

echo "=== Disk Usage ==="
for root in "${ROOTS[@]}"; do
    usage=$(df -h "$root" | tail -1 | awk '{print $3 " / " $2 " (" $5 ")"}')
    echo "  $root: $usage"
done
echo ""

echo "=== Summary ==="
if [ "$errors" -gt 0 ]; then
    echo -e "${RED}FAILED${NC}: $errors error(s), $warnings warning(s)"
    exit 1
elif [ "$warnings" -gt 0 ]; then
    echo -e "${YELLOW}WARNINGS${NC}: $warnings warning(s)"
    exit 0
else
    echo -e "${GREEN}PASSED${NC}: all checks clean"
    exit 0
fi
