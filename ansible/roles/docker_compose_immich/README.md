# docker_compose_immich

Deploys [Immich](https://github.com/immich-app/immich) — self-hosted photo and video
library with search, face recognition and mobile sync. Ships the server, its Postgres and
Valkey, and the machine-learning container.

The ML half can be split onto another host, which is the point of the two toggles below.

## Status: Production

## Inputs

Required:

- `immich_photos_directory` — host path for the photo library.
- `immich_db_directory` — host path for Postgres data.
- `immich_db_username` / `immich_db_password` — from vault.

Optional:

- `immich_version` — default `release`.
- `immich_db_database_name` — default `immich`.
- `immich_no_machine_learning` — default `false`. Deploys everything except ML.
- `immich_only_machine_learning` — default `false`. Deploys only ML.
- `immich_machine_learning_host` — default `immich-machine-learning`. Point at another host
  when ML runs elsewhere.
- `immich_machine_learning_cuda` — default `false`. Selects the CUDA ML image.
- `immich_machine_learning_model_cache_directory` — host path for downloaded models.

## Example

Split across two hosts — library on the storage host:

```yaml
- role: docker_compose_immich
  vars:
    immich_no_machine_learning: true
    immich_machine_learning_host: "http://media-host:3003"
    immich_photos_directory: "/mnt/tank/immich/photos"
    immich_db_directory: "/mnt/tank/immich/db"
```

ML on the GPU host:

```yaml
- role: docker_compose_immich
  vars:
    immich_only_machine_learning: true
    immich_machine_learning_cuda: true
    immich_machine_learning_model_cache_directory: "{{ docker_compose_dst_data_directory_path }}/immich/model_cache"
```

## OCR is disabled deliberately

Immich's OCR / smart-search text extraction leaks VRAM and host RAM
([immich-app/immich#23462](https://github.com/immich-app/immich/issues/23462)) and will OOM
the ML container on a long job.

**Do not re-enable it, and do not try to tune around the OOM** — the leak is upstream and
unfixed. Everything else about smart search works.

## Database image is not stock Postgres

The database uses Immich's own image, which bundles the required vector extensions. A plain
`postgres:` image will start and then fail on schema creation. Upgrading it is not a tag
bump: check Immich's release notes for the matching image, because the extension version is
part of the contract.

`shm_size: 128mb` is required — Postgres crashes on the Docker default of 64 MB under
Immich's query load.

## Storage layout

The photo library and the database want different things: the library is large and mostly
cold, the database is small and hot. Splitting `immich_photos_directory` and
`immich_db_directory` across different filesystems is normal and expected.
