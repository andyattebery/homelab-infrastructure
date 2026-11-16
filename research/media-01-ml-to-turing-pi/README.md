# Moving media-01's ML workloads onto the Turing Pi's accelerators

Researched 2026-10-09. The Immich ML findings were redone on 2026-11-14 at Immich v3.4.1; the speech and
other-workload findings are as of 2026-10-09. **[I]** marks inference.

**The question:** which of media-01's ML/AI workloads can move to the two Turing RK1s (`turingpi-rk1-01`,
`-02`) or to `turingpi-jetson-01`? On 2026-11-14 the owner asked it again for Immich's models alone, on
`turingpi-rk1-02` or `turingpi-jetson-01`.

**Scope:** only the boards' accelerators count: the RK1's NPU and Mali GPU, and the Orin's GPU. The
goal is to free media-01's RTX A4000 for work that needs its speed and its 16 GB. CPU options are out
of scope.

The owner had run the Wyoming speech services on this Orin before, under JetPack 6, and asked whether
the RK1 can run them. This is research: nothing has moved, and nothing was run on the boards.

**Bottom line**
- **Immich ML → an RK1's NPU: yes, for all three models in use, on Immich's own `-rknn` image.**
  - The owner confirmed the models unchanged on 2026-11-14.
  - The two RK1s are identical (`turingpi/nodes.md`), so this holds for `turingpi-rk1-02`.
  - All three have RK3588 builds in Immich's `v2` model exports:
    - `ViT-SO400M-16-SigLIP2-384__webli` (smart search)
    - `antelopev2` (faces)
    - `EN__PP-OCRv5_mobile` (OCR, enabled, at the default max resolution of 736)
  - `v2` is required for OCR on the NPU: the `main` exports have no RK3588 build of the OCR model, so
    under `main` OCR runs on the CPU.
  - Keeping the same models means nothing is re-indexed.
  - **v3.4.0 (2026-11-10) lifted the one-thread limit recommended here on 2026-10-09.**
    - A model's NPU contexts now share its weights.
    - Immich runs one context per NPU core by default, three on the RK3588.
    - At three contexts the three models take 2.86 GiB with all six model parts loaded (`docker stats`
      on turingpi-rk1-02, 2026-11-15).
  - **Speed:**
    - **Measured 2026-11-15 on turingpi-rk1-02:** one CLIP image takes 1.9 s end to end on a single
      context, from a lone 640×480 request.
    - The estimate was 2.5–3 s. With three contexts busy, about 1.5 images a second [I: concurrency
      not measured].
    - New uploads keep up easily, and a full-library re-run takes under a day [I].
  - **One open crash report, #32324.**
    - At v3.3.1, OCR running on several NPU contexts at once panicked RK3588 kernels. The driver was
      0.9.8, the RK1's version.
    - Nobody has tried it on v3.4.x.
    - Run OCR at job concurrency 1 until it has been tested here.
- **Immich ML → the Orin's GPU: possible only with an image built here, and unmeasured.**
  - Immich publishes no arm64 CUDA image. Its CUDA build pins ONNX Runtime 1.27, which has no arm64
    GPU wheel.
  - **A route now exists [I].**
    - ONNX Runtime 1.32.0 (2026-11-13) is the first arm64 CUDA 13 wheel built for the Orin (`sm_87`).
    - JetPack 7.2.1 runs generic arm64 CUDA 13 containers.
    - So an image of Immich's source on that wheel should work [I]. It would be rebuilt for every Immich
      release.
  - **Memory is the risk.**
    - The owner's out-of-memory run was under JetPack 6. Their Jetson build of that time built the
      then-current Immich, v2.7.4, at fp32 [I: that the run used it].
    - Since v3.3.0, Immich runs the `v2` exports at fp16 on a GPU, so SO400M's weights fall from 3.7 to
      about 1.8 GiB [I].
    - But at v3.3.1, OCR and face jobs still filled 8 GB discrete GPUs (#32309).
    - The Orin's 8 GB is shared with the OS, and decision 2 puts speech-to-text there too.
  - The RK1 needs none of this, so it stays the recommendation (decision 1).
- **Wyoming speech-to-text → the Orin's GPU: probably, with no new code, but two things need testing
  first.**
  - The route: NVIDIA's NeMo-Speech.cpp serves Parakeet TDT 0.6B v3 over an OpenAI-compatible
    `/v1/audio/transcriptions`. NVIDIA's docs pick its `cuda12` build for Orin, and an NVIDIA moderator
    calls it "verified on Jetpack 7.2+Orin". `wyoming_openai` (arm64) turns that endpoint into a Wyoming
    server.
  - Parakeet v3's published average WER is 6.32, against Whisper large-v3's 7.44.
  - The old Wyoming images were built on JetPack 6's L4T base, which is tied to its own L4T release.
    JetPack 7.2 moved the Orin onto NVIDIA's server (SBSA) driver, and NVIDIA publishes no L4T base
    images for 7.x. So the images need rebuilding on a standard arm64 CUDA base.
  - Turbo could stay, as faster-whisper rebuilt on that base, if a CUDA 12 base runs on JetPack 7.2.
    CTranslate2 supports CUDA 12 but not 13, and whether CUDA 12 runs there is untested (speech.md).
- **Wyoming speech-to-text → the RK1's NPU: possible, but worse than turbo.**
  - The best fit is SenseVoice on RKNN. Its accuracy is Whisper-small class, it takes about 0.5–0.7 s
    per command, and it needs a ~60–80-line patch to wyoming-faster-whisper [I].
  - On the RK3588 the NPU is no faster for it than one A76 core.
  - No Parakeet, Moonshine or Canary RKNN port exists, and no Wyoming server runs on the NPU.
- **Onyx isn't a workload to move: it isn't running** (owner). It lost to local-deep-research on
  2026-07-31. `playbook-media-01.yaml:167` still deploys it, though, so a full media-01 run would start
  it again on the A4000 (other-workloads.md).
- **The Mali GPU contributes nothing here.**
  - No speech result exists for it.
  - llama.cpp's Vulkan prefill on the RK3588 is slower than its CPU.
  - ARM NN has no build of Immich's CLIP or OCR model (immich-ml.md).
- **Stays on the A4000:** kohya_ss, ComfyUI and SwarmUI (the workloads the A4000 is being freed for),
  Tdarr and gpu-encoder-sweep (not ML), and dcgm-exporter (NVIDIA datacenter telemetry, not supported on
  Jetson).
- **Open WebUI doesn't use the A4000.** Its image is CPU-only and gets no GPU in
  `files/media-01/docker-compose-ai.yml`, so moving it frees nothing.

## Proposed placement

| Board | Takes | Accelerator |
|---|---|---|
| `turingpi-rk1-01` | Immich ML | NPU (`-rknn` image) |
| `turingpi-rk1-02` | Immich ML, as the second ML URL | NPU |
| `turingpi-jetson-01` | Wyoming STT | GPU |
| media-01 | Immich ML, as the last ML URL; everything that needs the A4000 | A4000 |

The two RK1s are identical, so either can take the first ML URL.

**As deployed,** both RK1s sit behind an HAProxy on nas-01 that spreads Immich's requests over them
(`docker_compose_haproxy` in `ansible/playbook-nas-01.yaml`). Immich's ML URLs are that balancer,
then media-01.

**What this frees on the A4000:**
- **Whisper:** turbo at `int8_float16` holds **1,216 MB** permanently (owner's `nvidia-smi`,
  2026-10-09). That's 7.5% of the card.
- **Immich:** it holds VRAM only while it works. It unloads models after 300 s idle
  (`MACHINE_LEARNING_MODEL_TTL`). During jobs its ONNX Runtime memory pool grows; #31675 measured
  774 MB → 4.7 GB → 8.1 GB on a 1080 Ti.

**The Orin's 8 GB, shared [I]:**
- Parakeet q8_0 weights: 0.71 GB.
- Plus CUDA contexts and the OS. That fits, but it's unmeasured.
- **The board is tight in practice.** Immich ML ran it out of memory when the owner tried it under
  JetPack 6 (immich-ml.md).
- **Set a memory limit on every container.** JetPack's release notes record that an oversized CUDA
  allocation can reboot the device (issue 5699079,
  [../turing-pi-cluster/kubernetes-on-vendor-os.md:239](../turing-pi-cluster/kubernetes-on-vendor-os.md)).

## Decisions

### 1. Immich ML: an RK1's NPU first, with the A4000 as the last resort

**The question:** where should Immich's ML run?
- On an RK1's NPU, which runs all three current models on Immich's own image.
- On the Orin's GPU, which needs an image built here.
- On media-01's A4000, as today.

Immich takes a list of ML URLs (since v1.122.0). They "are tried sequentially; there is no attempt to
distribute load across multiple containers" (remote ML guide @v3.4.1).

**The options:**
- **(a) RK1s only.**
  - For: the A4000 never sees Immich again.
  - Against: every bulk re-run happens at NPU speed, about a day for the library [I]. That includes a
    model change, which forces one. So does re-running OCR or faces "on all".
- **(b) `[rk1-01, rk1-02, media-01]`.**
  - For:
    - Day-to-day uploads and searches run on the NPU.
    - The second RK1 covers the first's upgrades and outages.
    - media-01 is used only if both are down, or when moved to the top of the list for a deliberate
      bulk re-run.
    - Backends are interchangeable for the same model, so failover doesn't corrupt anything.
    - An idle Immich ML on media-01 holds no model memory after 300 s.
  - Against:
    - Three ML deployments must stay on one Immich version. The role's `release` tag floats, and
      Immich warns: "Version mismatches between both hosts may cause bugs and instability".
    - #32324 hasn't been tested on these boards (immich-ml.md).
- **(c) The Orin's GPU.**
  - For: a GPU, so likely faster than the NPU on bulk re-runs [I]. It could take those off the A4000
    too.
  - Against:
    - There's no image to pull. It means an arm64 build of Immich's source on ONNX Runtime 1.32.0,
      rebuilt for every Immich release. That wheel came out on 2026-11-13, and no run of it on an Orin
      has been published.
    - Its 8 GB is shared with the OS. An 8 GB GPU filled up at v3.3.1 (#32309), and the owner's earlier
      attempt ran out of memory.
    - It would compete with speech-to-text, which decision 2 puts on the Orin.
    - The Orin has no container runtime yet.
    - Its speed is unmeasured.
- **(d) Keep it on media-01.**
  - For: the fastest option, and nothing to build.
  - Against: it's the one A4000 tenant that grows to several GB during jobs.

**Ruled out:**
- **The Mali GPU:** ARM NN has no build of the CLIP or the OCR model.
- **TensorRT on the Orin:** Immich supports only TensorRT-RTX, and installs it on x86-64 alone.

**Recommendation: (b).**
- It moves the steady-state work off the A4000 on Immich's own image, with the same models. Nothing is
  re-indexed, and there is no image to maintain here.
- Since v3.4.0 one RK1 should do about an image a second [I]. That covers new uploads with room to spare.
- The A4000 stays at the bottom of the list, for the bulk re-runs where its speed matters.
- (c) would buy speed the steady state doesn't need. Its costs are an image of our own for every release
  and a memory budget nobody has measured.

Settings:
- the `-rknn` image
- `MACHINE_LEARNING_MODEL_REVISION=v2`: required for OCR on the NPU, since `main` has no RK3588 build of
  the OCR model; under `main`, OCR runs on the CPU
- `MACHINE_LEARNING_RKNN_THREADS` and `MACHINE_LEARNING_WORKERS` left at their defaults: three contexts
  sharing weights, and one worker. Upstream: "each worker process still loads its own copy of the
  weights".
- Immich's job concurrency:
  - Smart Search and Face Detection at 4–6, upstream's advice for three contexts.
  - OCR at 1 until #32324 has been tested here.
- OCR max resolution kept at 736. Only values that round up to 736, 1088 or 1440 have an NPU build.
- the documented `security_opt` and `/dev/dri`, under Docker
  - Under k3s the pod must be privileged (#25057).
  - Docker vs k3s on the RK1s is still undecided (`group_vars/turingpi/vars.yaml:14`).
- all hosts on one pinned version

The role needs two changes first:
- **The ML image is hard-coded.** `docker-compose-immich-machine-learning.yaml.j2:4` always pulls
  `-cuda`.
- **No environment reaches the ML container.** So `v2` can't be set through the role today.
  - The template has no `environment:` or `env_file:`.
  - `docker_compose_envs` only fills the `.env` that compose reads for its own substitutions
    (`tasks/main.yaml:23-25`).

The URL list itself is set in Immich's admin settings, not the playbook [I] (Repo findings).

**What would change it:**
- **#32324 reproduces here at OCR concurrency 1, or hits smart search or faces at three contexts.** Then
  `MACHINE_LEARNING_RKNN_THREADS=1`, at about a third of the throughput [I], or (d).
- **SO400M takes much longer than ~3 s per image, or the three models don't fit the NPU's address space
  at three contexts.**
  - Then fewer contexts, (d), or a smaller CLIP model.
  - A smaller model means a full Smart Search re-run.
- **Immich publishes an arm64 CUDA image, and a test shows the Orin holds the three models alongside
  speech-to-text.** Then (c) costs nothing to maintain, and its speed may be worth having for re-runs.

### 2. Wyoming speech-to-text: the Orin, not the RK1

**The question:** which accelerator should take speech-to-text off the A4000?

**The options:**
- **(a) Orin: NeMo-Speech.cpp (Parakeet TDT 0.6B v3) behind `wyoming_openai`.**
  - For:
    - Accuracy at or above turbo on published benchmarks.
    - NVIDIA's own runtime, documented for Orin, with an OpenAI-compatible HTTP API.
    - Both containers are pulled; the work is compose and configuration.
    - Expected latency is tens of ms to ~150 ms per command [I], unmeasured.
  - Against:
    - Two things are unverified:
      - Does the published image contain an sm_87 build and the HTTP server? NGC's 0.1.0 page
        documents gRPC only, and its Dockerfile's CI target is Thor.
      - Does the `cuda12` (CUDA 12.8 SBSA) build run on R39's CUDA 13.2 driver?
    - Building the image with `CUDA_ARCH=87` is the fallback.
    - JetPack 7.2 has a known NvMap allocation crash with ggml-based runtimes, worked around with
      `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` [I that it applies here].
    - The Orin has no container runtime yet.
- **(a′) Orin: faster-whisper turbo, rebuilt on an arm64 CUDA 12 base, with CTranslate2 compiled for
  sm_87.**
  - For:
    - Today's model, settings and server, unchanged.
    - Turbo at `int8_float16` takes 1,216 MB (measured on the A4000).
    - It's the arm64 twin of the image media-01 already runs.
  - Against:
    - Only works if an SBSA CUDA 12 image runs on JetPack 7.2's driver, which is untested (speech.md).
    - CTranslate2 has to be compiled from source; there are no aarch64 CUDA wheels.
    - You maintain one more image.
- **(b) RK1: SenseVoice on the NPU, via a patch to wyoming-faster-whisper.**
  - For:
    - The model and the RKNN-enabled sherpa-onnx wheel are both published.
    - About 0.5–0.7 s for any command up to 10 s.
  - Against:
    - Whisper-small-class accuracy (LibriSpeech 3.15 / 7.18), clearly below turbo, with no biasing.
    - About 60–80 lines of new Python plus an image [I].
    - On the RK3588 one A76 core is faster than the NPU core for this model.
- **(c) RK1: RKLLAMA's `/v1/audio/transcriptions` with RKNN Whisper models, behind `wyoming_openai`.**
  - For: no code.
  - Against: every request is padded to 30 s, and it's unmeasured; expect over 1.5 s [I]. Turbo on the
    NPU takes 12 s for the encoder alone.
- **(d) Keep it on the A4000.** It holds 1,216 MB permanently.

**Recommendation: (a).** It needs nothing built and no new code, and its published accuracy is at or
above turbo's. (a′) would match today exactly, but rests on an untested CUDA 12 premise and a
CTranslate2 build. The two unknowns are a single test once the Orin has a container runtime: run the image,
POST a WAV, read the text. Wire it to Home Assistant only after that, as a second Assist pipeline to
compare against turbo.

**What would change it:**
- **Parakeet does worse than turbo on this household's commands.** Then (a′), if the CUDA 12 test
  passes. It keeps exactly today's behaviour, at the cost of a CTranslate2 build.
- **The NeMo-Speech image lacks sm_87, and a `CUDA_ARCH=87` build fails or crashes.** Then (a′), and
  failing that, whisper.cpp built for sm_87, with `whisper-server --inference-path
  /v1/audio/transcriptions` behind the same bridge [I].
- **No GPU route works on the Orin at all.** Then (b) is the accelerator option left, at a real
  accuracy cost.

### 3. The second RK1

With Immich on one RK1 and speech on the Orin, nothing from media-01 needs the other RK1's NPU except
as Immich's second ML URL. Immich tries the URLs in order and doesn't spread load, so it is a standby,
not extra throughput.

**As deployed, it isn't a standby.** The HAProxy on nas-01 spreads Immich's requests over both RK1s
(Proposed placement), so the second adds throughput once Immich's job concurrency keeps both busy.

## Open questions

- **SO400M-384 on the RK1's NPU at v3.4.x:**
  - Time per image with all three contexts busy. One context measured 1.9 s end to end on 2026-11-15.
  - Memory under load. Idle with all six model parts loaded, the container held 2.86 GiB (2026-11-15).
    isac322 cites a ~4 GiB NPU address limit on the RK3588; whether it is per process is unknown.
- **#32324 on these boards.** Does OCR at job concurrency above 1, on three contexts, still crash the
  kernel at v3.4.x? The case is `EN__PP-OCRv5_mobile` on vendor kernel 6.1.172. A panic needs a power
  cycle from the BMC.
- **The image's RKNN runtime is older than the models' compiler:** librknnrt 2.3.0 in the image, against
  toolkit 2.3.2 for the `v2` models (#32324's log). Whether that matters is unknown.
- **How the NPU appears inside a container** on the vendor 6.1 kernel (which `/dev/dri` node). That is
  untested here.
- **The Orin for Immich, if it's ever wanted:**
  - Whether ONNX Runtime 1.32.0's `sm_87` build runs on JetPack 7.2.1.
  - Peak memory for the three models with speech-to-text alongside.
- **Whether an SBSA CUDA 12 image runs on the Orin under JetPack 7.2.1:** one `deviceQuery` in an arm64
  `nvcr.io/nvidia/cuda:12.x` image. It decides option (a′), and whether CUDA 12-only software
  (CTranslate2) is usable on the Orin at all.
- **NeMo-Speech.cpp on the Orin:**
  - Whether the published image has sm_87 and the HTTP server.
  - Whether `language=en` is accepted.
  - Latency for a short command.
- **Parakeet's accuracy on this household's commands,** measured as a second Assist pipeline.
- **The Orin's power in slot 4:** whether it can draw 25 W is unverified (`turingpi/jetson/README.md:173`).

## Repo findings

Found while reading; not fixed here.
- **The Immich ML container gets no `MACHINE_LEARNING_*` variables.**
  - `templates/docker-compose-immich-machine-learning.yaml.j2` has no `environment:` or `env_file:`.
  - `docker_compose_envs` (`tasks/main.yaml:23-25`) only fills `.env` for compose's substitutions.
  - So media-01 runs Immich's defaults, including the `main` exports at fp32 [I: from the template; the
    container wasn't inspected].
  - #31750 says fetching the `v2` models "is needed to fully benefit from the changes", which include
    its lower memory use and fp16 on GPUs. So whether July's OCR leak is bounded on media-01 is open [I].
- **`docker_compose_immich` doesn't pass the ML URL to the server.**
  - `IMMICH_MACHINE_LEARNING_HOST` is written to `.env` (`tasks/main.yaml:11`).
  - But `templates/docker-compose-immich.yaml:10-16` never references it.
  - The playbook's `immich_machine_learning_host` therefore has no effect; the URL comes from Immich's
    admin settings [I].
- **`docker_compose_immich/README.md:27` is wrong** about `immich_machine_learning_cuda`. It says the
  variable selects the CUDA image, but the template always pulls `-cuda` (line 4). The variable only
  adds the NVIDIA runtime (lines 8-17).
- **`docker_compose_obico/README.md` has the same mismatch.** Lines 15 and 60-62 say
  `obico_machine_learning_cuda` selects the CUDA image. `templates/docker-compose-obico-ml.yaml.j2`
  keeps one image (line 3) and only adds the runtime (lines 12-22).
- **`docker_compose_immich/README.md:53-58` is out of date twice.**
  - It says OCR is disabled. The owner's admin settings show it enabled on 2026-10-09; the owner
    doesn't remember turning it on.
  - It calls the leak "upstream and unfixed". #23462 was closed 2026-09-28: "memory usage should be
    bounded as of #31742 and #31750", both in v3.3.0.
- **`playbook-media-01.yaml:167` still deploys Onyx,** which isn't running and lost its comparison
  on 2026-07-31. Its role runs `docker compose up --detach --wait`, so a full media-01 run starts it
  again, GPU model servers included.
- **`research/local-llm/docs/README.md:24` and `current-work.md:519` are out of date.** They say Onyx
  "stays up as the comparison baseline" and "stays deployed as a comparison baseline".
- **Onyx multipass on OpenSearch [I],** which matters only if Onyx comes back: see
  [other-workloads.md](other-workloads.md#multipass-on-the-opensearch-backend).

## Files

| File | What's in it |
|---|---|
| [immich-ml.md](immich-ml.md) | Immich v3.4.1's backends and image architectures; the RK3588 builds of the models in use, and why `v2` is required; the v3.4.0 shared-weights pool, its settings, speed and memory; the open OCR crash (#32324); re-indexing; multiple ML URLs; what Immich holds on the A4000; the Orin route on ONNX Runtime 1.32.0, its memory and its costs; ARM NN |
| [speech.md](speech.md) | Speech-to-text on the Orin's GPU under JetPack 7.2.1 (NeMo-Speech.cpp, wyoming_openai, whisper.cpp, TensorRT routes, why the old images and CTranslate2 don't work) and on the RK1's NPU and Mali GPU (SenseVoice, Whisper, Qwen3-ASR, RKLLAMA) |
| [other-workloads.md](other-workloads.md) | Onyx (not running; what moving it would take; the multipass problem on OpenSearch), kohya_ss, ComfyUI and SwarmUI, Open WebUI, Obico ML, dcgm-exporter |
