# media-01's other workloads

Researched 2026-10-09. **[I]** marks inference. Nothing here was run on the boards.

These are the workloads in `ansible/playbook-media-01.yaml` and `files/media-01/docker-compose-ai.yml`
other than Immich ML ([immich-ml.md](immich-ml.md)) and speech-to-text ([speech.md](speech.md)).

## Onyx: not running

- **Not running.** The owner says Onyx isn't running on media-01 (2026-10-09). It lost the harness
  comparison to local-deep-research on 2026-07-31
  ([../local-llm/docs/harness-comparison.md](../local-llm/docs/harness-comparison.md)). So it isn't a
  workload to move.
- **The playbook would bring it back.** `playbook-media-01.yaml:167` still lists `docker_compose_onyx`,
  and that role runs `docker compose up --detach --wait` (`roles/docker_compose_onyx/tasks/main.yaml:87`).
  A full media-01 run therefore starts it again, GPU model servers included.
- **The local-llm docs are out of date on it.** `../local-llm/docs/README.md:24` says it "stays up as
  the comparison baseline", and `current-work.md:519` says it "stays deployed as a comparison
  baseline".

**If it ever comes back** (Onyx v4.9.0, read 2026-10-09):
- **The model servers run one model,** `nomic-ai/nomic-embed-text-v1` (0.1B, fp32).
- **The arm64 image is CPU-only.** Every `nvidia-*-cu12` dependency is gated to x86_64.
- **On the Orin** it would need the image rebuilt from source with CUDA PyTorch (`cu132`, 2.12.1).
  NVIDIA staff confirm those wheels on JetPack 7.2.1 Orin (forum 379752).
- **The RK1 has no accelerator route:** there is no NPU port of nomic, and llama.cpp's Vulkan on the
  RK3588 is slower than its CPU (#22682).

### Multipass on the OpenSearch backend

Read from the v4.9.0 source and not verified on a running index. It matters only if Onyx runs again.
- **The large chunk reuses a chunk id.** `indexing/chunker.py` `_combine_chunks` builds it with
  `chunk_id=chunks[0].chunk_id`, appended under `if self.enable_multipass and self.enable_large_chunks`.
- **The OpenSearch writer ignores everything multipass adds.**
  `document_index/opensearch/opensearch_document_index.py` `_convert_onyx_chunk_to_opensearch_document`
  writes only `content_vector=chunk.embeddings.full_embedding`, `title_vector` and
  `chunk_index=chunk.chunk_id`. `large_chunk`, `multipass` and `mini_chunk` appear nowhere in the file.
- **The two chunks then share an id:**
  - `opensearch/schema.py`: `max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE`, which the converter never
    sets.
  - `opensearch/client.py`: the `_id` is `get_opensearch_doc_chunk_id(tenant_state,
    document.document_id, document.chunk_index, document.max_chunk_size)`.
  - So a large chunk and regular chunk 0, 4, 8 and so on share an `_id`.
- **What happens next isn't settled from the code.** `index()` bulk-writes with default arguments, then
  retries with `update_if_exists=True`. Either the large chunk is rejected as a duplicate, or it
  overwrites the regular chunk.
- **The mini-chunk vectors are computed and never stored.**
- No upstream issue was found.
- Multipass is switched on at install when the model servers have a GPU (`onyx/setup.py`).

## Stay on the A4000

- **kohya_ss:** its `docker_publish.yml` @v25.2.2 builds `linux/amd64` only, with x86-only pins.
- **ComfyUI:** its base image is amd64-only. SwarmUI is its front-end. Both are commented out today.
- **Why these stay:** they are what the A4000 is being freed for.
  - On the Orin's 8 GB shared, SDXL runs only with swap, at 90–120 s per image (stable-diffusion.cpp,
    JetPack 7.2), and LoRA training doesn't fit [I].
  - On the RK1's NPU, RKNN SD1.5 LCM takes ~34 s per image, and RKNN can't train.
- **Tdarr and gpu-encoder-sweep** also use the A4000, but aren't ML.
- **dcgm-exporter:** NVIDIA staff on the Orin: "NVML library is not supported on Jetson" (forum
  332969). It stays with the A4000.

## Don't use the A4000

- **Open WebUI:** `:main` is built with `USE_CUDA=false`, and `files/media-01/docker-compose-ai.yml`
  gives it no GPU. Moving it frees nothing.
- **Obico ML (commented out):** upstream obico-server has `ml_api/Dockerfile.base_rk3588`, pinned to
  librknnrt 2.3.2, with comments naming the Turing Pi RK1. If it comes back, the RK1's NPU can host it.

## Sources

- **Onyx @v4.9.0:** [releases](https://github.com/onyx-dot-app/onyx/releases); `backend/requirements/model_server.txt`; `onyx/setup.py`; `onyx/indexing/chunker.py`; `onyx/document_index/opensearch/{opensearch_document_index.py,schema.py,client.py}`
- **NVIDIA forums:** [379752](https://forums.developer.nvidia.com/t/jetpack-7-2-jetson-orin-nano-super-8gb-pytorch-for-compute-capability-8-7/379752), 332969
- **llama.cpp:** [#22682](https://github.com/ggml-org/llama.cpp/issues/22682)
- **Other workloads:** kohya_ss v25.2.2 `docker_publish.yml`; Open WebUI v0.11.4 `Dockerfile`; [obico-server](https://github.com/TheSpaghettiDetective/obico-server) `ml_api/Dockerfile.base_rk3588`; [dcgm-exporter](https://github.com/NVIDIA/dcgm-exporter)
- **This repo:** `ansible/playbook-media-01.yaml`, `ansible/roles/docker_compose_onyx/tasks/main.yaml`, `ansible/files/media-01/docker-compose-ai.yml`, `research/local-llm/docs/{README.md,current-work.md,harness-comparison.md}`
