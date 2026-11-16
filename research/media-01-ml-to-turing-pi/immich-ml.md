# Immich ML on the RK1's NPU and the Orin's GPU

Researched 2026-11-14; first researched 2026-10-09 at v3.3.1. **[I]** marks inference. Nothing here was
run on the boards. Immich source was read at **v3.4.1** (released 2026-11-11), the newest release, which
the role's floating `release` tag follows.

**What runs today:**
- nas-01 runs the Immich server with ML off (`playbook-nas-01.yaml:213-218`).
- media-01 runs `immich-machine-learning:release-cuda` on the A4000 (`playbook-media-01.yaml:137-141`).
  - The role gives that container no environment variables (README, Repo findings).
  - So it runs Immich's defaults, including the `main` exports at fp32 [I: from the template; the
    container wasn't inspected].

**Models in use** (the owner's admin settings, 2026-10-09; confirmed unchanged 2026-11-14):

| Task | Model |
|---|---|
| Smart search | `ViT-SO400M-16-SigLIP2-384__webli` |
| Faces | `antelopev2` |
| OCR | enabled, `PP-OCRv5_mobile (English-only)`, max resolution 736 (the default); the Hugging Face repo `immich-app/EN__PP-OCRv5_mobile` [I: the label-to-repo mapping] |

**The RK1s.**
- They are identical (`turingpi/nodes.md`): Ubuntu 26.04 on Rockchip's vendor kernel 6.1.172, 16 GB of
  RAM.
- The RKNPU driver is 0.9.8 (`../turing-pi-cluster/rk1-gpu-npu.md:192`).
- Everything said below of "the RK1" holds for `turingpi-rk1-02`.

## Image architectures

The `ml-variants` matrix in `.github/workflows/docker.yml:85-107` @v3.4.1:

| Image | Platforms |
|---|---|
| `-cuda`, `-openvino`, `-rocm` | amd64 only |
| `-armnn`, `-rknn` | arm64 only |

- **`-rknn`:**
  - Base `python:3.12-slim-trixie`.
  - It bundles `librknnrt.so` from rknn-toolkit2 v2.3.0, pinned by checksum
    (`machine-learning/Dockerfile:137-144`).
  - Since v3.4.0 Immich calls that library directly, and `rknn-toolkit-lite2` is no longer a dependency
    (`pyproject.toml:69`).
- **`-cuda`:**
  - Base `nvidia/cuda:12.2.2-runtime-ubuntu22.04` (`Dockerfile:98`).
  - It installs `onnxruntime-gpu>=1.27.1,<1.28`, with the comment "last ORT release supporting CUDA
    12.2, also need to handle CUDA 13" (`pyproject.toml:64`).
  - That comes from Microsoft's CUDA 12 index (`pyproject.toml:78,86-88`), which carries only x86-64
    and Windows wheels.

## RKNN on the RK1

### The models in use all have RK3588 builds

`v2` revision, Hugging Face API trees, read 2026-11-14 (the same files as on 2026-10-09):

| Repo | RK3588 file | Size |
|---|---|---|
| `ViT-SO400M-16-SigLIP2-384__webli` | `visual/rknpu/rk3588/model.rknn` | 889,843,962 B |
| | `textual/rknpu/rk3588/model.rknn` | 847,230,462 B |
| `antelopev2` | `detection/rknpu/rk3588/model.rknn` | 10,320,042 B |
| | `recognition/rknpu/rk3588/model.rknn` | 131,712,819 B |
| `EN__PP-OCRv5_mobile` | `detection/rknpu/rk3588/res736/model.rknn` | 19,852,923 B |
| | `detection/rknpu/rk3588/res1088/model.rknn` | 31,691,261 B |
| | `detection/rknpu/rk3588/res1440/model.rknn` | 48,047,421 B |
| | `recognition/rknpu/rk3588/model.rknn` | 11,601,082 B |

- **`v2` is required for OCR on the NPU.** The `main` revision has RK3588 builds of SO400M and
  antelopev2, but none of `EN__PP-OCRv5_mobile`, so under `main` OCR runs on the CPU (next section).
  Immich's default is `main` (`immich_ml/config.py:80`).
- **The text tower's token embeddings stay on the host in `v2` [I].**
  - The two revisions' SO400M text towers differ by 583 MB: `main` is 1,429,909,164 B, `v2` 847,230,462 B.
  - That is about the size of its 256,000 × 1,152 token-embedding table at fp16.
  - The `v2` exports leave that table to the host (ml-models#70, via isac322/homelab #416).

### How it loads and runs

- **Every model loads from its RKNN build when RKNN is available** (`models/base.py:186-188`).
  - The path is `rknpu/rk3588/<label>/model.rknn` (`base.py:147-148`).
  - A model without an RK3588 build falls back to ONNX on the CPU. Immich logs "RKNN is available, but
    model '…' does not support it." and reloads it as ONNX (`main.py:222-238`).
- **Precision:** fp16. The docs: "RKNPU always uses FP16".
- **Requirements:** an RK3588 and an RKNPU driver of 0.9.8 or later (docs). The RK1 has 0.9.8.
- **Compose** (`docker/hwaccel.ml.yml:17-22` @v3.4.1). Not privileged:

      rknn:
        security_opt:
          - systempaths=unconfined
          - apparmor=unconfined
        devices:
          - /dev/dri:/dev/dri

- **SoC detection** reads `/proc/device-tree/compatible` (`sessions/rknn/rknnpool.py:136`).
  - Under Docker the `security_opt` above covers it.
  - Under Kubernetes the path is masked, and a non-privileged pod gets no NPU. With `privileged: true` it
    works (#25057, open).
- **Environment** (`environment-variables.md` and `config.py` @v3.4.1):

  | Variable | Default | Notes |
  |---|---|---|
  | `MACHINE_LEARNING_RKNN` | `True` | |
  | `MACHINE_LEARNING_RKNN_THREADS` | number of NPU cores: 3 on the RK3588 | "Number of RKNN contexts per model, which share its weights" |
  | `MACHINE_LEARNING_WORKERS` | `1` | Keep at 1: "each worker process still loads its own copy of the weights" |
  | `MACHINE_LEARNING_MODEL_REVISION` | `main` | `v2` is required here |
  | `MACHINE_LEARNING_MODEL_TTL` | `300` | "Inactivity time (s) before a model is unloaded" |

### OCR detection's resolution

- RKNPU "ships a binary per short side, which the label picks" (`models/ocr/detection.py:27-30`).
- The label is `res` plus the max resolution rounded up to a multiple of 32 (`detection.py:103-105`).
- The `v2` tree has RK3588 builds for `res736`, `res1088` and `res1440`.
- So on the NPU the max resolution must lie in 705–736, 1057–1088 or 1409–1440. The server's default
  is 736 (`server/src/dtos/config.dto.ts:688`), and so is the owner's setting.

### The pool since v3.4.0: one context per core, sharing weights

- **PR #23958,** merged 2026-10-28 and released in v3.4.0.
  - "One context per thread, all but the first duplicated from it so that they share its weights"
    (`rknnpool.py:162`).
  - It calls `rknn_init` once, then `rknn_dup_context` for each extra context (`rknnpool.py:166-175`).
- **Each request takes an idle context and returns it** (`rknnpool.py:200-208`), so no two requests
  share one.
- **Upstream's advice** (`ml-hardware-acceleration.md` @v3.4.1):
  - "The contexts of a model share its weights, but each one needs its own working memory. Extra
    contexts therefore cost little for models that are mostly weights, such as CLIP, but for OCR
    detection each one can add close to the model's own memory again, more so at higher OCR
    resolutions."
  - "Raise Immich job concurrency (Smart Search, Face Detection, OCR) a bit above the number of NPU
    cores, e.g. `4`–`6`, so a prepared image is always waiting when a core frees up."
  - A working load logs `Loaded RKNN model ... threads sharing its weights`.
- **Why one thread was right at v3.3.1:**
  - Each thread loaded its own copy of every model.
  - The old pool returned wrong results under load. isac322/homelab #413 ran three threads with 12
    concurrent requests and got one all-null embedding and one at cosine 0.34.
  - A port of #23958 returned 12 identical results, in 1.29 GiB against 3.41 GiB.
  - v3.4.0's pool has the same design [I: nobody has published that test against v3.4.x].

### Speed

| Source | Model | Figure |
|---|---|---|
| PR #23958 (v3.4.0's pool, RK3588) | ViT-L-16-SigLIP2-512, visual | 3,500 ms on one context; 3,900 ms with all three busy |
| | ViT-L-16-SigLIP2-512, textual | 142 / 155 ms |
| | antelopev2 | detection 72 ms; recognition 37–40 ms |
| | PP-OCRv5 mobile | detection 110 ms at 736×736, 820 ms at 1920×1920; recognition 12–40 ms |
| | ViT-L-16-SigLIP2-512 + antelopev2, three contexts | "~60k photos / day" |
| PR #15241 (2025, an older export) | ViT-SO400M-16-SigLIP2-512 | 4–5.5 s per image |

- **SO400M-384 [I]:**
  - Its visual file is 1.34 times ViT-L-16-512's (889.8 MB against 661.9 MB).
  - At 384 px it has 56% of the patches.
  - So it needs about 0.75 times the compute: about 2.5–3 s per image on each context.
- **Measured on turingpi-rk1-02, 2026-11-15:**
  - 1.9 s end to end for one CLIP image on one context, from a lone 640×480 request.
  - 2.86 GiB of container memory with SO400M, antelopev2 and the OCR model all loaded at three
    contexts.
  - The README has the details.
- **Throughput [I]:**
  - Three contexts give about one image a second with faces and OCR, or 60–85k a day.
  - A full-library re-run takes about a day; July's OCR backfill was 50k images.
  - At v3.3.1's one thread the estimate was 25–40k a day.
- **OCR at job concurrency 1 (below) costs little:** it takes roughly 0.1–0.5 s of NPU time per image [I].

### Memory

- **Weights, one copy each** (the `v2` RK3588 files above): 1.91 GB for the three models, with OCR at
  736.
- **PR #23958's measurements,** in MiB at one, two and three contexts:

  | Model | v3.4.0's pool | the old pool |
  |---|---|---|
  | ViT-L-16-SigLIP2-512 visual | 733.8 / 813.6 / 893.3 | 1,357.8 / 2,715.6 / 4,073.4 |
  | ViT-L-16-SigLIP2-512 textual | 1,132.6 / 1,132.6 / 1,148.5 | 2,298.7 / 4,597.4 / 6,896.1 |
  | antelopev2 detection | 111.6 / 159.5 / 207.3 | not measured |
  | antelopev2 recognition | 175.4 / 175.4 / 191.4 | not measured |
  | PP-OCRv5 mobile detection, 736×736 | 143.5 / 223.3 / 271.1 | not measured |
  | PP-OCRv5 mobile detection, 1920×1920 | 558.3 / 989.0 / 1,435.0 | not measured |
  | PP-OCRv5 mobile recognition | 79.7 / 111.6 / 143.6 | not measured |

- **For the models in use [I]:**
  - Roughly 2.5–3.5 GB at three contexts, no more than v3.3.1 needed for one: the old pool took about
    twice the new pool's single-context figure (the table).
  - Part of the text tower's share is ordinary RAM, where `v2` keeps its token embeddings.
- **The NPU's address space:**
  - isac322's build notes say shared weights allow "more threads without hitting the ~4 GiB IOMMU IOVA
    cap" on the RK3588.
  - Whether that cap is per process is unknown, so the margin is unmeasured.
- **Measured elsewhere** (isac322/homelab #416):
  - At three threads, stock v3.3.1 failed to load a large `v2` CLIP model with
    `failed to malloc npu memory`.
  - The #23958 port ran it in 2.81 GiB.
- The board has 16 GB of RAM.

### An open crash: OCR on several NPU contexts (#32324)

- **The report** (2026-10-10, v3.3.1):
  - Hardware and OS: a Rock 5B+ (RK3588) on Armbian 26.8.3 (Ubuntu 24.04). Its log shows RKNPU driver
    0.9.8.
  - Settings: `MACHINE_LEARNING_RKNN_THREADS=3`, `v2`, PP-OCRv6_medium.
  - Re-running OCR on 35k photos gave "failed to submit!" errors, "and after some time, a kernel panic".
  - The reporter's update: `MACHINE_LEARNING_RKNN_THREADS=1` stops it, even at OCR concurrency 3.
- **Two more users:**
  - One hit kernel panics with PP-OCRv6 at two threads; OCR concurrency 1 stopped them.
  - The other crashed at three threads with OCR concurrency 2, "sometimes hanging the entire system".
    Their dmesg shows RKNPU job timeouts, then a kernel NULL-pointer dereference, on
    `6.1.115-vendor-rk35xx`. Concurrency 1 stopped it.
- **No maintainer reply and no linked fix** as of 2026-11-14.
- **Unknown here [I]:**
  - Whether v3.4.0's pool, `EN__PP-OCRv5_mobile` or kernel 6.1.172 changes it.
  - Whether the runtime version matters. The image's `librknnrt` (2.3.0) is older than the toolkit that
    compiled the `v2` models (2.3.2, in the issue's log), and Rockchip's error text says to update both.
- **Workaround:** OCR job concurrency 1, which keeps three contexts for smart search and faces.

## Re-indexing

- **Same model, different backend:** "You do not need to redo any machine learning jobs after enabling
  hardware acceleration" (`ml-hardware-acceleration.md`).
- **`main` and `v2` exports:** "numerically equivalent, so switching doesn't require re-running any
  tasks" (v3.3.0 notes). So media-01 on `main` and an RK1 on `v2` can share the URL list.
- **A different model:** "you must re-run the 'Smart Search' job for all images" (the admin UI's own
  text), and likewise Face Detection for a new face model.
- **fp16 RKNN against fp32 CUDA:** no published comparison. Duplicate detection, at a 0.01 distance, is
  the most drift-sensitive feature [I].

## More than one ML URL

- **Added in v1.122.0** (PR #14347).
- **No load balancing:** "While several URLs can be provided in the settings, they are tried
  sequentially; there is no attempt to distribute load across multiple containers"
  (`guides/remote-machine-learning.md:64` @v3.4.1).
- **Order:** healthy URLs first, in list order, checked every 30 s with a 2 s timeout (server code,
  read at v3.3.1).
- **Versions must match:** "Version mismatches between both hosts may cause bugs and instability" (line
  47).
- **This repo doesn't set the URL.** `templates/docker-compose-immich.yaml:10-16` never passes it to the
  server, so the list lives in Immich's admin settings [I].

## What Immich holds on the A4000

- **Idle:** models are unloaded after 300 s (`MACHINE_LEARNING_MODEL_TTL`). An idle CUDA instance
  holds little beyond its CUDA context [I].
- **Just after loading:** +1,491 MiB on an RTX A2000 for ViT-B-32, buffalo_l and PP-OCRv5 mobile
  (thaynes43/haynes-ops PR #3412, v3.2.4).
- **During jobs:** ONNX Runtime's pool grows and isn't released.
  - #31675 (v3.1.0/v3.2.2, 1080 Ti) measured 774 MB → 4,740 MB → 8,068 MB, failing at 8,830 MB.
  - It was closed as a duplicate on 2026-09-19.
- **For SO400M-384:** no VRAM figure is published. Its `v2` fp32 weights are 3.68 GiB (below).
- **media-01 runs the `main` exports at fp32** (above). #31750's lower memory and fp16 GPU path come
  with `v2`: "Fetching the new models is currently opt-in with `MACHINE_LEARNING_MODEL_REVISION=v2` and is
  needed to fully benefit from the changes."

## The Orin's GPU: possible only with an image built here

### No Immich image

- `-cuda` is amd64-only (above). Immich's CUDA build pins ONNX Runtime 1.27, from an index with no arm64
  wheels.
- PR #12456 (arm64 CUDA) was closed as stale. A GitHub search on 2026-11-14 found no arm64 CUDA or
  Jetson issue or PR filed since 2026-10-09.

### ONNX Runtime has an Orin build since 1.32.0

- **Since 1.29.0 (2026-08-12), PyPI's `onnxruntime-gpu` has shipped Linux aarch64 wheels, on CUDA 13.**
  The 1.29 notes list their architectures as `89;90a;120a;121a`, in `-real` form. So they don't run on
  the Orin's 8.7 [I].
- **1.32.0 (2026-11-13) "added `sm_87` (Jetson Orin), `sm_100`, `sm_103` (GB300), and `sm_110` (Jetson
  Thor) to Linux `aarch64` CUDA 13 packages".**
  - It has wheels for CPython 3.11–3.14.
  - Its `cuda` and `cudnn` extras pull the CUDA 13 runtime and cuDNN 9 for CUDA 13 (PyPI metadata).
- No run of it on an Orin has been published; it was a day old when this was written.

### JetPack 7.2.1 runs generic arm64 CUDA 13 images

- From JetPack 7.2 the Orin uses NVIDIA's server (SBSA) driver.
- NVIDIA staff say aarch64 NGC CUDA containers work on it.
- The container toolkit still runs in CSV mode on Tegra.
- Details: [speech.md](speech.md#how-jetson-containers-depend-on-the-host) and
  [../turing-pi-cluster/kubernetes-on-vendor-os.md](../turing-pi-cluster/kubernetes-on-vendor-os.md).

### What the image would be [I]

- **Immich's ML source** at the release the other hosts run.
  - Its `cuda` extra is replaced by `onnxruntime-gpu[cuda,cudnn]` 1.32.x from PyPI.
  - It is built on an arm64 CUDA 13 base.
- **The plain CUDA provider.**
  - TensorRT-RTX is installed on x86-64 only (`pyproject.toml:65`).
  - Its compute-capability list leaves out the Orin's 8.7 (read at v3.3.1).
- **What doesn't block it:**
  - Immich's NVIDIA device probe, which needs NVML and TensorRT-RTX, runs only for TensorRT-RTX
    (`sessions/ort.py:130-140`). The plain CUDA path skips it.
  - #32767's startup failure is in TensorRT-RTX's memory-pool arena, so it doesn't apply.
- **Telemetry:** a build from v3.3.6 or later keeps Immich's fix turning off the telemetry that ONNX
  Runtime enabled by default in 1.29 (#32956).
- **There is a precedent.** The owner's April 2026 project did this for JetPack 6 (L4T R36.5, CUDA 12.6,
  Python 3.11). It builds the current Immich release; its README shows v2.7.4.
  - It generated the Dockerfile from upstream's stages.
  - It compiled ONNX Runtime through jetson-containers. A PyPI wheel removes that compile.
- **Upkeep:** it has to be rebuilt for every Immich release, and kept on the other ML hosts' version.
- **The board needs a container runtime and NVIDIA's container toolkit.**
  - Docker's directories are already set to move to the NVMe.
  - No runtime is installed yet (`host_vars/turingpi-jetson-01/vars.yaml:6-11,22-25`) [I: from that
    comment; the board wasn't checked].

### Memory

- **The `v2` exports run at fp16 on a GPU.**
  - Every provider but the CPU runs at half precision unless the `main` exports are in use
    (`sessions/ort.py:155-157`).
  - The GPU then loads a narrowed `model_fp16.onnx` (`sessions/prepare.py:41-44`).
- **Weights:**
  - SO400M's `v2` fp32 weights are 3.68 GiB (visual 1,707,747,648 B, textual 2,241,342,624 B), so about
    1.84 GiB at fp16 [I].
  - antelopev2 is about 0.13 GiB at fp16, and OCR about 6 MB [I].
- **Plus** the CUDA context, cuDNN, ONNX Runtime's arena and the OS, in 8 GB shared with the CPU. And
  speech-to-text, if decision 2 puts it here.
- **The earlier out-of-memory run** was under JetPack 6 (owner, 2026-10-09).
  - The owner's Jetson build of that time built the then-current Immich, v2.7.4. That was before
    v3.3.0's fp16 path and bounded input shapes [I: that the run used it].
  - So it doesn't settle v3.4.1.
- **But GPU memory still grows at v3.3.1** (#32309).
  - `v3.3.1-cuda` with `v2` on 8 GB GPUs filled VRAM until ONNX Runtime's arena allocations failed.
  - The models were PP-OCRv6_medium for OCR and, from a second user, buffalo_l for faces.
  - It was closed as not planned under the project's AI-use policy, not fixed.
  - v3.4.1 sets no arena shrinkage (`sessions/ort.py:186-189,212-214`). #32533, which added it, was
    closed unmerged.
- **Release-note issue 5699079:** an oversized CUDA allocation can reboot the device. Set a container
  memory limit ([../turing-pi-cluster/kubernetes-on-vendor-os.md](../turing-pi-cluster/kubernetes-on-vendor-os.md)).

### Speed

No Immich figure has been published for any Orin. Unmeasured.

## The Mali GPU (ARM NN)

- The `-armnn` image needs `.armnn` model files.
- In the `v2` trees only antelopev2 has them; SO400M and the OCR model don't.
- So ARM NN can't serve two of the three models.

## Sources

- **Immich @v3.4.1:**
  - [release](https://github.com/immich-app/immich/releases/tag/v3.4.1); [v3.4.0 notes](https://github.com/immich-app/immich/releases/tag/v3.4.0); v3.3.0 notes
  - `.github/workflows/docker.yml`
  - `machine-learning/`: `Dockerfile`, `pyproject.toml`
  - `machine-learning/immich_ml/`:
    - `config.py`
    - `models/constants.py`, `models/base.py`, `models/ocr/detection.py`
    - `sessions/ort.py`, `sessions/prepare.py`, `sessions/rknn/__init__.py`, `sessions/rknn/rknnpool.py`
  - [`docker/hwaccel.ml.yml`](https://github.com/immich-app/immich/blob/v3.4.1/docker/hwaccel.ml.yml)
  - docs:
    - [`ml-hardware-acceleration.md`](https://github.com/immich-app/immich/blob/v3.4.1/docs/docs/features/ml-hardware-acceleration.md)
    - [`environment-variables.md`](https://github.com/immich-app/immich/blob/v3.4.1/docs/docs/install/environment-variables.md)
    - [`remote-machine-learning.md`](https://github.com/immich-app/immich/blob/v3.4.1/docs/docs/guides/remote-machine-learning.md)
  - `server/src/dtos/config.dto.ts`
- **Immich PRs:** [#23958](https://github.com/immich-app/immich/pull/23958), [#31750](https://github.com/immich-app/immich/pull/31750), #31742, #32533, #32956, #12456, #14347, [#15241](https://github.com/immich-app/immich/pull/15241)
- **Immich issues:** [#32324](https://github.com/immich-app/immich/issues/32324), [#32309](https://github.com/immich-app/immich/issues/32309), #32767, [#25057](https://github.com/immich-app/immich/issues/25057), [#31675](https://github.com/immich-app/immich/issues/31675), [#23462](https://github.com/immich-app/immich/issues/23462)
- **Hugging Face API trees** (`/tree/v2?recursive=true` and `/tree/main?recursive=true`):
  - [`immich-app/ViT-SO400M-16-SigLIP2-384__webli`](https://huggingface.co/immich-app/ViT-SO400M-16-SigLIP2-384__webli)
  - [`immich-app/antelopev2`](https://huggingface.co/immich-app/antelopev2)
  - [`immich-app/EN__PP-OCRv5_mobile`](https://huggingface.co/immich-app/EN__PP-OCRv5_mobile)
  - [`immich-app/ViT-L-16-SigLIP2-512__webli`](https://huggingface.co/immich-app/ViT-L-16-SigLIP2-512__webli), for comparison
- **ONNX Runtime:**
  - release notes for [v1.29.0](https://github.com/microsoft/onnxruntime/releases/tag/v1.29.0) and [v1.32.0](https://github.com/microsoft/onnxruntime/releases/tag/v1.32.0)
  - [PyPI `onnxruntime-gpu`](https://pypi.org/project/onnxruntime-gpu/)
- **Third party:**
  - isac322/homelab PRs [#413](https://github.com/isac322/homelab/pull/413) and [#416](https://github.com/isac322/homelab/pull/416), and [`tools/immich-ml-rknn/README.md`](https://github.com/isac322/homelab/blob/master/tools/immich-ml-rknn/README.md)
  - thaynes43/haynes-ops PR #3412
- **The owner's project:** [andyattebery/immich-machine-learning-jetson-docker](https://github.com/andyattebery/immich-machine-learning-jetson-docker)
- **This repo:**
  - `ansible/roles/docker_compose_immich/`
  - `ansible/playbook-nas-01.yaml`, `ansible/playbook-media-01.yaml`
  - `ansible/group_vars/turingpi/vars.yaml`, `ansible/host_vars/turingpi-jetson-01/vars.yaml`
  - `turingpi/nodes.md`
  - `research/turing-pi-cluster/rk1-gpu-npu.md`, `research/turing-pi-cluster/kubernetes-on-vendor-os.md`
  - [speech.md](speech.md)
