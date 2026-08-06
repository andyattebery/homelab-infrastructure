# Hardlink Manager

HTTP API for detecting and replacing btrfs hardlinks on nas-01. Runs in Docker with bind-mounted data disks.

## Why this exists

Tdarr transcodes media files that have hardlink siblings across per-disk btrfs shares. The
transcoding node mounts those shares over CIFS, and doing the hardlink work from there is
not merely awkward — it cannot be verified, so it must happen on the NAS instead.

`link(2)` over CIFS **does** create a real hardlink on the server. The CIFS client then
assigns different local inode numbers to source and target, so every client-side check of
the result is wrong. Measured by creating a hardlink inside the node container and stat-ing
it from both sides:

| Checked from | Source inode | Target inode | Match |
| --- | --- | --- | --- |
| CIFS client, in the container | 1033565 | 1033566 | no |
| btrfs, on the NAS | 2231913 | 2231913 | yes |

All three obvious verification methods fail for the same reason:

- `stat` returns different inodes for what is one file on disk
- `find -samefile` cannot match a newly created hardlink, because it compares client inodes
- `nlink` is unreliable — CIFS reports `1` for files that demonstrably have siblings

So no amount of client-side code can confirm the operation succeeded. The failure is
silent and expensive: a replacement that appears to fail (but did not) leaves both the old
and the new copy on disk. Across a library of this size that is terabytes of duplicate data
on disks already near capacity, which is why the service verifies inodes locally and rolls
back rather than guessing.

Detection lives here too, even though `find -samefile` works for *pre-existing* hardlinks
over CIFS. One source of truth for every inode operation is simpler than two rules about
when the client can be trusted.

## Path translation is the caller's job

Every path this service receives is NAS-local. The Tdarr plugin translates before calling,
replacing the container's CIFS mount prefix with the NAS path:

| In the container | On the NAS |
| --- | --- |
| `/media-raw/data03/.f/Sources/Movie.mkv` | `/mnt/data/data03/.f/Sources/Movie.mkv` |

Per-disk shares are mounted **without** `noserverino` for this reason — the merged pool
mount uses it and cannot report usable inodes.

## Endpoints

### `GET /health`

Returns `{"status": "ok"}`.

### `POST /detect`

Find hardlink siblings of a file.

```json
{
  "file_path": "/mnt/data/data03/.f/Sources/Movie.mkv",
  "search_root": "/mnt/data/data03/.f"
}
```

Response:

```json
{
  "status": "ok",
  "inode": 2231913,
  "siblings": ["/mnt/data/data03/.f/Models/TestModelA/Movie.mkv"]
}
```

If `find` encounters permission errors on some subdirectories but still returns results, the response includes a `warnings` field with stderr. If `find` fails entirely (no results), status is `error`.

Timeout: controlled by `FIND_TIMEOUT` env var (default 300s).

### `POST /replace`

Replace hardlink siblings with links to a new primary file.

```json
{
  "new_primary": "/mnt/data/data03/.f/Sources/Movie.mp4",
  "old_ext": ".mkv",
  "new_ext": ".mp4",
  "siblings": [
    "/mnt/data/data03/.f/Models/TestModelA/Movie.mkv",
    "/mnt/data/data03/.f/Models/TestModelB/Movie.mkv"
  ]
}
```

Response:

```json
{
  "status": "ok",
  "replaced": 2,
  "errors": 0,
  "details": [
    {"sibling": "...", "new_path": "...", "result": "ok"},
    {"sibling": "...", "new_path": "...", "result": "ok"}
  ]
}
```

Top-level `status` is `error` if any sibling failed. Each sibling reports independently — a failure on one does not stop processing of others.

**Idempotent**: calling replace multiple times with the same inputs produces the same result. If the target already exists with the correct inode, the sibling is skipped (reported as `ok`).

## Per-sibling replace flow

For each sibling:

1. Compute new path (swap extension if `old_ext != new_ext`)
2. If target already exists with correct inode → skip (idempotent success)
3. If target already exists with wrong inode → remove stale file
4. Backup: `mv sibling sibling.hlbak` (atomic rename on btrfs)
5. Create hardlink: `ln new_primary new_sibling_path`
6. Verify: `stat` both, confirm inodes match
7. On success: `rm sibling.hlbak`
8. On failure: `mv sibling.hlbak sibling` (restore original)

## Failure scenarios

### Detect

| Scenario | Handling |
|----------|----------|
| file_path doesn't exist | stat fails → `{"status": "error"}` with stderr |
| search_root doesn't exist | find fails with empty stdout → error with stderr |
| Path traversal (symlink escape) | `validate_path` raises HTTP 400 |
| No siblings (nlink=1) | `{"status": "ok", "siblings": []}` |
| Permission denied on subdirs | find exits non-zero but returns partial results → results returned with `warnings` field |
| Huge directory tree | `FIND_TIMEOUT` (default 300s) → timeout error |

### Replace

| Scenario | Handling |
|----------|----------|
| new_primary doesn't exist | Error before any sibling processing |
| Sibling missing, no .hlbak | Per-sibling error, other siblings continue |
| Both sibling and .hlbak exist (stale cleanup) | `mv sibling .hlbak` overwrites stale backup |
| Orphan: .hlbak exists, sibling gone (crash recovery) | Reuses existing backup, skips redundant mv |
| `ln` fails (cross-device, dir missing) | Restore backup, per-sibling error |
| `ln` fails AND restore fails | .hlbak remains on disk; orphan recovery on next run |
| Target exists with correct inode (previous success) | Skip ln, clean up backup (idempotent) |
| Target exists with wrong inode | Remove stale target, then create hardlink |
| Empty/invalid extensions | Validated at request level: must be non-empty, start with `.` |
| Power failure mid-operation | Atomic mv on btrfs; orphan recovery on next request |

### Tdarr flow failures

| Scenario | Recovery |
|----------|----------|
| Flow fails after detect, before replace | No side effects. Retry re-detects |
| HTTP response lost during replace | Plugin retries all siblings. Already-done siblings are idempotent (target exists with correct inode → skip) |
| Partial replace, then crash | Done siblings → idempotent skip. Orphan siblings → backup reuse. Untouched → normal |
| replaceOriginalFile succeeded, replace never called | Siblings point to old data. Replace can be called later — normal operation |
| Replace called with stale sibling list | Missing siblings get per-sibling errors. Others proceed |

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `ALLOWED_PATH_PREFIX` | `/mnt/data/` | All input paths must resolve under this prefix |
| `FIND_TIMEOUT` | `300` | Seconds before find subprocess is killed |

## Deployment

Deployed via Ansible role `docker_compose_hardlink_manager` in `playbook-nas-01.yaml`. The role copies source to the host and `docker compose up --build` builds the image.

```bash
ansible-playbook ansible/playbook-nas-01.yaml
```

Accessible at `https://hardlink-manager.<domain_name>` via Traefik.
