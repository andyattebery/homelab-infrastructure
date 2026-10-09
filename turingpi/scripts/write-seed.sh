#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $(basename "$0") <src.img.xz> <out.img.xz> <fat-label> <user-data> <meta-data>"
    echo
    echo "Decompress <src.img.xz>, check that its first partition is the FAT filesystem labelled"
    echo "<fat-label>, replace the cloud-init seed there (user-data and meta-data), read both back, and"
    echo "compress the result to <out.img.xz>, with the <out.img.xz>.sha turingpi/scripts/flash-node.sh"
    echo "needs. Needs xz and mtools."
    exit 1
}

[[ $# -eq 5 ]] || usage
SRC="$1" OUT="$2" LABEL="$3" USER_DATA="$4" META_DATA="$5"
[[ "$OUT" == *.img.xz && "$LABEL" =~ ^[A-Za-z0-9_-]+$ ]] || usage
for f in "$SRC" "$USER_DATA" "$META_DATA"; do
    [[ -f "$f" ]] || { echo "Error: no $f"; exit 1; }
done
for tool in xz mcopy mtype mlabel shasum; do
    command -v "$tool" >/dev/null || { echo "Error: $tool not found in PATH (mtools: brew install mtools)"; exit 1; }
done

# For an <out.img.xz> of <name>.img.xz, the image is seeded as <name>.img.part and renamed once it is
# written, read back and compressed, so an interrupted run never leaves an image that looks finished.
PART="${OUT%.xz}.part"
mkdir -p "$(dirname "$OUT")"
echo "Decompressing to $PART..."
xz -dc "$SRC" > "$PART"

# le <file> <offset> <bytes>: the little-endian unsigned integer at that byte offset.
le() {
    local -a b
    local hex="" i
    read -r -a b < <(od -An -tx1 -v -j "$2" -N "$3" "$1")
    for ((i = ${#b[@]} - 1; i >= 0; i--)); do hex+="${b[i]}"; done
    echo $((16#$hex))
}

# Partition 1's start sector, with 512-byte sectors. On an MBR disk (Ubuntu's raspi image) it is at
# byte 454. A GPT disk (rk1-armbian-minimal) has one protective MBR entry of type ee and its header
# ("EFI PART") at byte 512: the header's byte 72 gives the sector of the entry array, and the first
# entry's byte 32 its first sector. mtools reads the filesystem in place there (@@<n>S), so no disk
# tool and no mount is involved.
if [[ "$(od -An -tx1 -j 450 -N 1 "$PART" | tr -d ' \n')" == ee &&
      "$(od -An -tx1 -j 512 -N 8 "$PART" | tr -d ' \n')" == 4546492050415254 ]]; then
    LBA="$(le "$PART" $((512 * $(le "$PART" $((512 + 72)) 8) + 32)) 8)"
else
    LBA="$(le "$PART" 454 4)"
fi
FS="$PART@@${LBA}S"
if [[ "$LBA" -eq 0 ]] || ! grep -qi "^ Volume label is $LABEL" <<< "$(mlabel -s -i "$FS" :: 2>&1)"; then
    echo "Error: partition 1 of $PART is not the FAT filesystem labelled $LABEL"
    exit 1
fi

# -D o overwrites the file of the same name. stdin is /dev/null, so a name-clash prompt can't wait
# for input; the read-back below catches a file that wasn't written.
echo "Writing user-data and meta-data into $LABEL..."
mcopy -D o -i "$FS" "$USER_DATA" ::user-data < /dev/null
mcopy -D o -i "$FS" "$META_DATA" ::meta-data < /dev/null
mtype -i "$FS" ::user-data | cmp - "$USER_DATA"
mtype -i "$FS" ::meta-data | cmp - "$META_DATA"

# The BMC decompresses .xz itself, so the stream it receives is a fraction of the image. -T0 makes a
# multi-block file, as the rk1-armbian-minimal releases are. xz deletes <name>.img.part once
# <name>.img.part.xz is complete; -f replaces one left by an interrupted run.
echo "Compressing to $OUT..."
xz -T0 -f "$PART"
mv -f "$PART.xz" "$OUT"
(cd "$(dirname "$OUT")" && shasum -a 256 "${OUT##*/}") > "$OUT.sha"
echo "Seeded image: $OUT"
