# docker_compose_media_sync_manager

Deploys media-sync-manager: watches Jellyfin playlists, stages the referenced media for
Tdarr to transcode into device-friendly copies, and exposes a small web UI for bulk playlist
editing.

Two containers from one image — the sync daemon, and a `web` playlist editor with no media
access at all.

## Status: Production

## Inputs

Required:

- `media_sync_manager_jellyfin_api_key` — from vault.
- `media_sync_manager_jellyfin_user_id` — the real Jellyfin user id whose playlists are
  watched.
- `media_sync_manager_targets` — one entry per device. Each: `name`, `library_id` (the Tdarr
  library `_id`), and `playlists` of `{ playlist, segment }`. `playlist` is an
  **exact-match** Jellyfin lookup.

Optional:

- `media_sync_manager_jellyfin_url` / `_tdarr_url` — default `https://jellyfin.{{ domain_name }}`
  and `https://tdarr.{{ domain_name }}`.
- `media_sync_manager_poll_interval_seconds` — default `45`.
- `media_sync_manager_tdarr_request_timeout_seconds` — default `20`.
- `media_sync_manager_pool_host_path` — default `/mnt/storage`. The media pool, bind-mounted
  at `/media`. Must be **local** — see below.
- `media_sync_manager_media_root` / `_transcode_root` — defaults `/media` and
  `/media/Transcoded Videos`.
- `media_sync_manager_input_mode` — default `symlink`.
- `media_sync_manager_web_hostname` — default `media-sync-manager`.
- `media_sync_manager_path_maps` / `_tdarr_path_maps` — default `[]`, i.e. all three
  services see the pool at the same path.

## Example

```yaml
- role: docker_compose_media_sync_manager
  tags: media_sync_manager
```

with targets in `group_vars/all/vars.yaml`:

```yaml
media_sync_manager_targets:
  - name: Kid iPad
    library_id: "VJIq5lXoS"
    playlists:
      - { playlist: "Sync - Kid iPad - 2D Animation", segment: 2d-animation }
```

## `name` is a path component

Paths are derived per (target, segment):

    input   <transcode_root>/<name>/<segment>/<source_rel>
    output  <transcode_root>/<name>/sync/<segment>/<source_rel>

So renaming a target repoints the tool at a **new directory**. Rename the old one on disk at
the same time, or everything already transcoded is orphaned and rebuilt.

## Must run where the pool is local

Inputs are symlinks into the pool, and **SMB has no symlink-create operation** — so this
cannot run on a host that mounts the media over CIFS, only on the one that owns it.

`input_mode` is pinned to `symlink` rather than left at `auto` on purpose: the auto probe
links a single temp file from `transcode_root`, which lands on whichever pool branch the
filesystem picks, so it can report success and still leave real files failing `EXDEV` one by
one.

## `transcode_root` must stay under `media_root`

Inputs are *relative* symlinks. A link between two sibling roots resolves outside the SMB
share, where Samba's default `wide links = no` hides the file from Tdarr entirely — a
broken link would at least be visible. The tool's own `doctor` command checks this.

## The web container has no media mount

`media-sync-manager-web` runs the same image with the `web` command and deliberately no
`/media` bind mount: it only talks to Jellyfin over HTTP, so it cannot touch media files.

Its Traefik router is defined explicitly, because the default rule would name it after the
compose service (`media-sync-manager-web`) rather than the intended hostname.
