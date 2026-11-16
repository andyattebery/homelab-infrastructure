# docker_compose_immich

Deploys [Immich](https://github.com/immich-app/immich) — self-hosted photo and video
library with search, face recognition and mobile sync. Ships the server, its Postgres and
Valkey, and the machine-learning container.

The ML half can be split onto another host, which is the point of the two toggles below.

## Status: Production

## Inputs

Required for the server, unless `immich_only_machine_learning`:

- `immich_photos_directory`: host path for the photo library.
  - No default. Unset, the run fails on the undefined variable.
  - A wrong path is bind-mounted anyway: Docker creates a missing source as root, so the server
    starts on an empty directory.
- `immich_db_directory`: host path for Postgres data. No default, and the same two failures.
- `immich_db_username` / `immich_db_password`: from vault. No default. Wrong, the server can't log
  in to an existing database.

Required for ML, unless `immich_no_machine_learning`:

- `immich_machine_learning_hwaccel`: `cuda` or `rknn`, with no default.
  - **What it selects:** the image, `immich-machine-learning:<version>-<hwaccel>`, and its device
    access.
  - **`cuda`:** the NVIDIA runtime and every GPU. The host needs the driver and the container toolkit
    (`nvidia_driver`, `nvidia_container_toolkit`).
  - **`rknn`:** upstream's rknn block, `docker/hwaccel.ml.yml` @v3.4.1.
    - It sets `security_opt` `systempaths=unconfined` and `apparmor=unconfined`, and maps `/dev/dri`.
    - The host needs a Rockchip SoC Immich supports (RK3566, RK3568, RK3576 or RK3588,
      `models/constants.py`), and an RKNPU driver of 0.9.8 or later.
  - **Anything else, or unset,** fails the role's assert before anything is deployed.
- `immich_machine_learning_model_cache_directory`: host path for downloaded models, mounted at
  `/cache`.
  - No default. Unset, the run fails on the undefined variable.
  - On `rknn` it grows to about 12 GB (RKNN, below).

Optional:

- `immich_version`, default `release`: the image tag for the server and for ML.
  - Immich warns that "Version mismatches between both hosts may cause bugs and instability".
  - So a split deployment updates every host together.
- `immich_db_database_name`, default `immich`.
- `immich_no_machine_learning`, default `false`: deploys everything except ML.
- `immich_only_machine_learning`, default `false`: deploys only ML. It publishes port 3003 on all of
  the host's interfaces, for the server to reach.
- `immich_machine_learning_environment`, default `{}`: environment variables for the ML container.
  - They're rendered into its compose file, not the host's shared `.env`.
  - Immich ignores a name it doesn't know [I], so a misspelled one does nothing.
  - The RK3588 example sets `MACHINE_LEARNING_MODEL_REVISION: v2` (RKNN, below).
- `immich_machine_learning_host`, default `immich-machine-learning`. **It has no effect.**
  - It's written to `.env` as `IMMICH_MACHINE_LEARNING_HOST`, which no compose file reads.
  - The server's ML URLs are set in Immich's admin settings, under Machine Learning.

## Examples

Split across hosts — library on the storage host:

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
    immich_machine_learning_hwaccel: cuda
    immich_machine_learning_model_cache_directory: "{{ (docker_compose_dst_data_directory_path, 'immich/model_cache') | path_join }}"
```

ML on an RK3588 host's NPU:

```yaml
- role: docker_compose_immich
  vars:
    immich_only_machine_learning: true
    immich_machine_learning_hwaccel: rknn
    # main has no RK3588 build of the OCR model; without v2, OCR runs on the CPU.
    immich_machine_learning_environment:
      MACHINE_LEARNING_MODEL_REVISION: v2
    immich_machine_learning_model_cache_directory: "{{ (docker_compose_dst_data_directory_path, 'immich/model_cache') | path_join }}"
```

## More than one ML host

Immich doesn't spread its ML requests over its ML URLs. It tries them in order, healthy ones first,
and stops at the first that answers (`server/src/repositories/machine-learning.repository.ts`
@v3.4.1). Its guide recommends "a dedicated load balancer for such use-cases" instead
(`docs/docs/guides/remote-machine-learning.md` @v3.4.1).

- **Put a balancer in front of the ML hosts, and give Immich its URL first.** The storage host does
  this with `docker_compose_haproxy`, on this role's `immich` network, so the server reaches the
  balancer by its container name.
- **A URL after the balancer's is still a fallback.** With every ML host down the balancer answers
  503, so Immich's health check marks it unhealthy and Immich moves on to the next URL.
- **More hosts help only if Immich sends more requests at once.** Raise Smart Search's and Face
  detection's concurrency in Immich's System Settings, under Job Settings, "Manage job concurrency"
  (`web/src/routes/admin/system-settings/` @v3.4.1). Keep OCR's at 1 (RKNN, below).

## RKNN (Rockchip NPU)

- **`v2` is required for OCR on the NPU.**
  - Immich's default model revision is `main`. It has no RK3588 build of `EN__PP-OCRv5_mobile`.
  - `v2` has builds for the CLIP, face and OCR models in the example.
  - When RKNN is available, Immich loads every model from its RKNN build. A model without one falls
    back to ONNX on the CPU, logging "RKNN is available, but model '…' does not support it."
    (`machine-learning/immich_ml/main.py` @v3.4.1).
  - So a missing `v2` slows OCR down rather than breaking it.
  - Switching an existing host from `main` to `v2` re-runs nothing: the two are "numerically
    equivalent" (v3.3.0 release notes).
- **The model cache reaches about 12 GB.**
  - For RKNN, Immich downloads each model's whole Hugging Face repository except `*.armnn`
    (`models/base.py`). That's the fp32 weights plus every SoC's builds.
  - For SigLIP2 SO400M, antelopev2 and PP-OCRv5 mobile that's about 11, 0.8 and 0.4 GB.
  - Put the cache on a data disk.
- **SoC detection:** Immich reads `/proc/device-tree/compatible` to pick the SoC's builds, and the
  `security_opt` above is what lets it [I: Docker masks `/sys/firmware`, where `/proc/device-tree`
  points, unless `systempaths=unconfined`].
  - Under Kubernetes a non-privileged pod gets no NPU, and Immich runs on the CPU (immich#25057).
- **Contexts:** since v3.4.0, `MACHINE_LEARNING_RKNN_THREADS` defaults to the NPU's core count, three
  on the RK3588, and a model's contexts share its weights.
  - Keep `MACHINE_LEARNING_WORKERS` at 1: "each worker process still loads its own copy of the
    weights" (Immich's hardware-acceleration docs).
- **Keep OCR's job concurrency at 1,** Immich's default.
  - At v3.3.1, OCR running on several NPU contexts at once panicked RK3588 kernels (immich#32324,
    open).
  - It's untested at v3.4.x.
  - `MACHINE_LEARNING_RKNN_THREADS: "1"` stopped it too, at about a third of the throughput [I].
- **To check the NPU is used:** the container's log shows "Loaded RKNN model from … sharing its
  weights" for each model it loads.

## OCR

Whether OCR runs is a setting in Immich's admin settings, which this role doesn't manage.

- **The leak is fixed upstream, with a catch.**
  - Its VRAM and RAM leak, immich#23462, was closed on 2026-09-28: "memory usage should be bounded as
    of #31742 and #31750", both in v3.3.0.
  - #31750's changes come with the `v2` exports: "Fetching the new models is currently opt-in with
    `MACHINE_LEARNING_MODEL_REVISION=v2` and is needed to fully benefit from the changes".
  - So a host on the default `main` may not get the bound [I].
- **If the ML container runs out of GPU memory during OCR on such a host,** setting `v2` through
  `immich_machine_learning_environment` is the first thing to try.

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
