# Tdarr AV1 NVENC Flow

Three flows transcode the media library to AV1 using NVENC on the RTX 5060 Ti (wsl-01). They share identical encode parameters, integrity guard, and hardlink handling — differing only in input gates.

| Flow | Codec gate | Width gate | FPS gate | Extra |
|------|-----------|-----------|---------|-------|
| Main | h264 | [0, 3000) | < 50 | — |
| 4K | h264 | [3000, 4000) | < 50 | — |
| Legacy | mpeg4 | none | < 50 | bwdif deinterlace for interlaced content |

Files outside all three gates (hevc, blank codec, width >= 4000, fps >= 50) get no flow.

## Flow steps

Using Main as the reference. 4K and Legacy differ only in the input gate section.

```
Input File
  → Check Video Codec (h264 include-only)
  → Check Width + FPS (custom plugin)
  → Detect Hardlinks
  → [transcode pipeline]
  → Check Duration Ratio
  → Check Size Ratio (>= 10%)
  → Health Check (thorough)
  → Replace Original File
  → Replace Hardlinks
```

### 1. Input gates

**Codec**: include-only match (`h264` or `mpeg4`). Blank/unreadable codecs fail the positive match and exit — excluded by construction, never routed to a flow that deletes sources.

**Width + FPS** (`checkVideoProperties`, custom plugin): reads existing ffprobe data, no re-probe. Width is `[minWidth, maxWidth)` (inclusive lower, exclusive upper). FPS parsed from `r_frame_rate` as a fraction. FPS <= 0 (unparseable) skips the file — fail-safe.

### 2. Detect Hardlinks

Runs `find -samefile <filePath>` under a search root derived from the file path (first three path components: `/media-raw/data03/.f`). Stores sibling paths as JSON in `args.variables.user.hardlinkSiblings` for the Replace Hardlinks step at the end.

Both outputs (siblings found / no siblings) proceed to the transcode. The variable is simply absent if no siblings exist.

**CIFS requirement**: the per-disk CIFS mounts (`/media-raw/dataXX`) must have `serverino` active so the kernel uses server-provided inode numbers. Without it, `find -samefile` can't match files by inode. See "CIFS serverino" section below.

### 3. Transcode

Encode parameters (from RD sweep, do not modify without re-measurement):

```
-preset p7 -tune uhq -rc vbr -b:v 0 -cq 34 -rc-lookahead 32
-spatial-aq 1 -temporal-aq 1 -b_ref_mode middle -g 120 -pix_fmt p010le
```

Audio: `-c:a copy` if source is AAC, `-c:a aac` otherwise. Container: `.mp4`.

Legacy flow adds `-vf bwdif` for interlaced content (detected via `field_order` stream property).

Do not add `-bf N` (causes `InitializeEncoder failed: invalid param (8)` on NVENC).

### 4. Integrity guard

Three checks between Execute and Replace Original File. ALL must pass before the source is deleted.

| Check | What it catches | Fail action |
|-------|----------------|-------------|
| Duration ratio (99.5%-100.5%) | Truncated encodes, mid-write crashes | Flow fails, source preserved |
| Size ratio (>= 10%) | Near-empty / corrupt output. Lower bound is 10% not default 40% because CQ 34 AV1 legitimately compresses to 15-40% of h264 size | Flow fails, source preserved |
| Health check (thorough full decode) | Bitstream corruption that still probes/plays but is garbage | Flow fails, source preserved |

### 5. Replace Original File

Tdarr community plugin. Replaces the source file with the transcoded output. Only reached after all integrity checks pass.

### 6. Replace Hardlinks

Reads sibling paths stored by Detect Hardlinks (step 2). For each sibling:

1. Check if sibling exists. If not, check for orphaned `.hlbak` backup from a previous crash and recover it.
2. Rename sibling to `<path>.hlbak` (atomic, preserves data).
3. Create hardlink from new primary to sibling location via `fs.linkSync`.
4. Verify inodes match using `fs.statSync` with `{ bigint: true }` (server inodes can exceed `Number.MAX_SAFE_INTEGER`).
5. If inodes differ (CIFS created a copy instead of a hardlink): delete the bad copy, throw error.
6. On success: delete `.hlbak` backup.
7. On any failure: restore `.hlbak` back to original path. Log error, continue to next sibling.

Partial success is possible — some siblings replaced, others failed. The plugin returns output 2 (failure) if any sibling failed.

## Hardlink failure analysis

At 14,000+ files with hardlinks, failures can't be caught by manual inspection. The two catastrophic outcomes are **disk fill** (old + new data both on disk, disks at 93% capacity) and **data loss** (original data freed before replacement confirmed). Every scenario below is traced through the actual code.

### How Replace Original File works (community plugin source)

Understanding this is critical to the analysis. The plugin:

1. Moves transcoded file from temp to `<originalPath>.tmp`
2. Renames original to `<originalPath>.partial.old` (atomic — old inode preserved, nlink unchanged)
3. Moves `.tmp` to final path (new inode at original's location)
4. Deletes `.partial.old` (nlink decremented; data freed only if nlink reaches 0)

Because step 2 is a rename (not unlink), siblings still reference the old inode. Step 4's unlink decrements nlink by 1, but if siblings exist, nlink stays >= 1 and old data persists.

After Replace Original File completes on a file with 2 siblings:
- Primary path → new transcoded file (new inode, nlink=1)
- Sibling A → old data (old inode, nlink=2)
- Sibling B → old data (old inode, nlink=2)
- Disk: old data (1 copy, via siblings) + new data (1 copy, via primary)

Old data is only freed when Replace Hardlinks successfully replaces ALL siblings.

### Scenario matrix

#### Scenarios where source is preserved (no hardlink risk)

| Scenario | Trigger | Result |
|----------|---------|--------|
| Integrity guard rejects | Truncated/corrupt/undersized output | Flow fails. Source untouched. Hardlink replacement never runs. |
| Transcode fails | ffmpeg error/crash | ffmpegCommandExecute throws. Flow stops. Source untouched. |
| Replace Original File fails | Disk full, permission error | Plugin has internal rollback (restores `.partial.old`). replaceHardlinks never runs. |
| Codec gate rejects | File is already AV1, HEVC, blank codec | File exits flow immediately. No processing. |

None of these affect hardlinks.

#### DISK FILL: Siblings not detected (silent)

**Trigger**: `serverino` is auto-disabled on the CIFS mount. `find -samefile` uses client-generated inodes, which are unique per path regardless of actual hardlinks. Every file returns zero siblings.

**What happens**:
1. detectHardlinks finds no siblings. Sets no flow variable. Returns output 2 ("no hardlinks"). No error logged.
2. Transcode proceeds normally. Integrity guard passes.
3. replaceOriginalFile replaces primary. Old data persists via siblings.
4. replaceHardlinks: no `siblingsJson`, returns output 1 ("success"). No error logged.
5. Result: new primary + old siblings. Both on disk. **Silent — no errors in any log.**

**Disk impact**: every hardlinked file adds the transcoded file size to disk. AV1 at CQ34 ≈ 15-40% of h264 size. 14,000 files averaging 2GB h264 → 0.6GB AV1 = ~8TB added. At 93% capacity this overflows the disks.

**Mitigated by**: `veto files = /.snapshots/` in Samba config hides btrfs snapshot subvolumes that cause inode collisions. Docker volumes must be recreated after config change.

**Residual risk**: any new source of inode collisions (new snapshot paths, btrfs subvolume operations) could trigger auto-disable again. There is no warning before it happens — only a kernel log message after.

**Detection**: `dmesg | grep -i 'autodisabling.*serverino'` on the tdarr-node host. Or check `cat /proc/mounts | grep <share>` for missing `serverino`.

#### DISK FILL: `find -samefile` timeout

**Trigger**: search root contains millions of files. `find` exceeds the 600-second timeout.

**What happens**: same as "siblings not detected" above. detectHardlinks catches the timeout error, logs "find command failed", returns output 2 ("no hardlinks"). Flow proceeds without hardlink handling.

**Silent**: the job log says "find command failed" but the flow succeeds. Disk fills.

#### DISK FILL: Hardlink replacement fails consistently

**Trigger**: `fs.linkSync` fails (CIFS error, permission issue) or inode check fails (copies instead of hardlinks) on every sibling.

**What happens**:
1. detectHardlinks finds siblings correctly.
2. Transcode + integrity guard + replaceOriginalFile all succeed.
3. replaceHardlinks: for each sibling, linkSync or inode check fails. `.hlbak` restored. Error logged.
4. Plugin returns output 2 (failure).
5. Result: new primary + old siblings (restored from `.hlbak`). Both on disk.

**Not silent**: errors are logged per sibling. But the primary transcode already succeeded and the original is already replaced. The old data persists via siblings.

**Disk impact**: same as "siblings not detected" — both old and new on disk.

#### DISK FILL: Partial sibling replacement

**Trigger**: sibling A replacement succeeds, sibling B replacement fails (e.g., transient CIFS error).

**What happens**:
1. Sibling A: renamed to `.hlbak`, linkSync succeeds, inode verified, `.hlbak` deleted. Old inode nlink decremented.
2. Sibling B: renamed to `.hlbak`, linkSync fails, `.hlbak` restored. Old inode nlink unchanged.
3. Result: primary + sibling A → new data. Sibling B → old data. Old inode nlink=1 (sibling B only).

**Disk**: old data (1 copy via sibling B) + new data (1 copy via primary + sibling A). Extra = new file size.

**Not data loss**: old data preserved via sibling B. But disk has both.

#### Concurrent workers on hardlinked files (race condition)

**Trigger**: two files in the same Tdarr library are hardlinks of each other. Both get queued. Multiple GPU workers process them simultaneously.

**What happens**:
1. Worker 1: detectHardlinks on file A, finds file B as sibling.
2. Worker 2: detectHardlinks on file B, finds file A as sibling.
3. Both start transcoding the same source data independently.
4. Both run replaceOriginalFile independently — each replaces their primary.
5. Both run replaceHardlinks — each tries to replace the other's path.
6. Race condition: renames, linkSyncs, and unlinks interleave unpredictably.

**Possible outcomes**: double transcode (2x GPU time wasted), both files end up as independent AV1 copies (2x disk for what should be 1 hardlinked copy), or one worker's output overwrites the other.

**Production mitigation**: the library source folder (`Sources/`) contains one copy per file. Siblings are in `Models/` directories outside the library. Tdarr only queues files from the library source, so it won't queue both copies. **This depends on the library source path not overlapping with sibling locations.** If the library source is set to the disk root (e.g., `/media-raw/data03/.f/`), both copies would be queued.

#### Crash during Replace Original File

**Trigger**: tdarr-node crashes between rename and unlink inside replaceOriginalFile.

**What happens**: `.partial.old` file left on disk alongside the new file. The community plugin checks for stale `.partial.old` on re-run and removes it — but the file is only re-run if it's re-queued. After successful transcode, the codec gate (h264) rejects the now-AV1 file, so it won't be re-queued. `.partial.old` persists.

**Disk impact**: `.partial.old` shares the old inode with siblings — no extra data storage. Just a stale directory entry. Low impact.

#### Crash during Replace Hardlinks (mid-loop)

**Trigger**: tdarr-node crashes between renaming a sibling to `.hlbak` and restoring it.

**What happens**: `.hlbak` file left on disk. On re-run (if file is re-queued), detectHardlinks runs `find -samefile` and finds the `.hlbak` file (same inode, different name). replaceHardlinks receives it as a sibling path with `.hlbak` suffix.

**Problem**: the sibling path in the list is `something.hlbak`, not the original path. Extension substitution logic would produce `something.hlmp4` or similar — wrong. The rename to `something.hlbak.hlbak` creates nesting.

**In practice**: the file is already transcoded (AV1), so the codec gate rejects it and it's never re-queued. The `.hlbak` persists as an orphan. Same inode as other siblings — no extra disk usage for data. But the original path is missing, replaced by the `.hlbak` path.

**Mitigation**: replaceHardlinks checks for `.hlbak` if the sibling path doesn't exist and restores it. But this only helps if the sibling list has the ORIGINAL path (not the `.hlbak` path). Since detectHardlinks runs fresh on re-run and finds whatever paths currently exist, the `.hlbak` path is what gets found. The original-path recovery code in replaceHardlinks wouldn't trigger because the sibling path it received (`.hlbak`) DOES exist.

#### Data loss: is it possible?

Tracing every path through the code: **no scenario permanently loses data** as long as at least one sibling exists.

- replaceOriginalFile replaces the primary, but old data survives via siblings (nlink >= 1).
- replaceHardlinks only deletes `.hlbak` AFTER verifying the new hardlink's inode matches. If verification fails, `.hlbak` is restored.
- The only way old data is freed is when ALL links are successfully replaced (nlink reaches 0). This is the intended behavior.

**Edge case**: if the inode comparison gives a false positive (both `statSync` calls return the same BigInt for what are actually different inodes), `.hlbak` is deleted and the old data may lose a link. This would require the CIFS client to generate identical client inodes for two different paths — unlikely with path-based hashing, but not structurally prevented.

### In-flow serverino pre-check

detectHardlinks reads `/proc/mounts` before every `find -samefile` call. If `serverino` is not in the mount options for the file's mount point, the plugin throws an error and the flow fails. This is structurally enforced — no serverino = no processing. The file appears as "errored" in Tdarr UI, source is preserved.

Similarly, if `find -samefile` itself fails (timeout, permission error), the plugin throws instead of silently returning "no siblings."

### Monitoring during batch processing

**Before starting the batch**:
```bash
# Verify serverino is active on all per-disk mounts
docker exec tdarr-node cat /proc/mounts | grep media-raw | grep -v serverino
# Should return nothing. Any output = missing serverino.

# Check kernel log for auto-disable
dmesg | grep -i 'autodisabling.*serverino'
```

**During the batch**:
```bash
# Monitor disk usage per data disk
df -h /mnt/data/data*

# Count failed hardlink replacements in recent job logs (via Tdarr API)
# Look for "ERROR on" in job report text
```

**After the batch** — run the verification script inside the tdarr-node container:
```bash
docker exec tdarr-node bash /path/to/test-av1-verify-hardlinks.sh
```

The script (`test-av1-verify-hardlinks.sh`) checks:
1. `serverino` active on all `/media-raw/data*` mounts
2. Zero orphaned `.hlbak` and `.partial.old` files
3. All hardlink groups have matching inodes (no independent copies)
4. Disk usage per mount

## CIFS serverino

The per-disk mounts (`/media-raw/dataXX`) require `serverino` so the CIFS client uses server-provided inode numbers. Without `serverino`, each path gets a unique client-generated inode regardless of whether files are actually hardlinked, making `find -samefile` and the inode verification useless.

### Auto-disable mechanism

The Linux CIFS client auto-disables `serverino` at runtime if it detects inode number collisions during a directory listing. This is permanent for the lifetime of the mount. Kernel log:

```
CIFS: VFS: Autodisabling the use of server inode numbers on \\server\share
```

Explicitly passing `serverino` as a mount option does not prevent this — the client silently strips it after detecting collisions.

### Root cause: btrfs snapshots

The NAS uses btrfs with `subvol=/data` mounts. Snapshot subvolumes (`.snapshots/`) within the data subvolume have independent inode number spaces. Files in a snapshot can have the same inode number as files in the main tree. When the CIFS client encounters this collision during `readdir()`, it disables `serverino`.

### Fix

Samba share config uses `veto files = /.snapshots/` on all per-disk shares to hide the snapshot subvolumes from CIFS clients. This prevents the client from seeing the collision. The Docker volume must be recreated after changing the Samba config (`docker compose down`, `docker volume rm`, `docker compose up`) since the auto-disable is permanent per mount.

## Infrastructure

### Tdarr node container (wsl-01)

- Template: `ansible/roles/docker_compose_tdarr/templates/docker-compose-tdarr-node.yaml.j2`
- Custom ffmpeg: BtbN/FFmpeg-Builds master build at `/opt/ffmpeg-btbn/bin/ffmpeg` (mounted as `/ffmpeg/ffmpeg` in container). Required for `-tune uhq` support in `av1_nvenc`.
- CIFS volumes: `/media` (merged storage, `noserverino`) for Tdarr library browsing. `/media-raw/dataXX` (per-disk, `serverino` via default) for hardlink operations.
- GPU: NVIDIA runtime with WSL2 library passthrough.

### Files

| Path | Purpose |
|------|---------|
| `ansible/files/media-01/tdarr/tdarr-flow-av1-main.json` | Main flow definition |
| `ansible/files/media-01/tdarr/tdarr-flow-av1-4k.json` | 4K flow definition |
| `ansible/files/media-01/tdarr/tdarr-flow-av1-legacy.json` | Legacy flow definition |
| `ansible/files/media-01/tdarr/tdarr-plugins/.../detectHardlinks/` | Detect plugin |
| `ansible/files/media-01/tdarr/tdarr-plugins/.../replaceHardlinks/` | Replace plugin |
| `ansible/files/media-01/tdarr/tdarr-plugins/.../checkVideoProperties/` | Width+FPS gate plugin |
| `ansible/files/media-01/tdarr/test-av1-create-samples.sh` | Test file creation |
| `ansible/files/media-01/tdarr/test-av1-verify.sh` | Test verification |
| `ansible/roles/samba/templates/smb.conf.j2` | Samba config (veto_files support) |
| `ansible/playbook-nas-01.yaml` | NAS playbook (per-disk shares with veto_files) |

### Processing order

Tdarr doesn't support multiple libraries on the same source folder. The three flows must be processed serially — one library at a time. After each flow completes, disable its library processing before enabling the next.
