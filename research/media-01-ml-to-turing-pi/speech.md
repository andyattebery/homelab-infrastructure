# Speech-to-text on the Orin's GPU and the RK1's NPU

Researched 2026-10-09. **[I]** marks inference. Nothing here was run on the boards.

**What runs today:**
- **media-01:** `docker_compose_wyoming_faster_whisper`, with `--model turbo --compute-type int8_float16
  --language en --beam-size 5 --vad-filter`, holding 1,216 MB of VRAM (owner's `nvidia-smi`, 2026-10-09). Home
  Assistant 2026.9.1 uses it as the Assist speech-to-text on port 10300.
- **Not on media-01:** TTS and wake word, so they're out of scope here.
- **Before:** jetson-01 ran faster-whisper and Piper from locally built JetPack 6 images
  (`r36.5.tegra-aarch64-cu126-22.04`).

## Orin (L4T R39.2.1 / JetPack 7.2.1: CUDA 13.2.2, TensorRT 10.16.2, sm_87, 8 GB shared)

### How Jetson containers depend on the host

**Up to JetPack 6, more than a regular CUDA container does.**
- **On x86,** NVIDIA's container toolkit injects the driver's user-mode libraries and `/dev/nvidia*`.
  The CUDA runtime lives in the image, and an older runtime runs on a newer driver [I: standard CUDA
  backward compatibility].
- **On a Jetson,** the runtime's CSV mode bind-mounts "the platform specific libraries providing
  hardware dependencies and select device nodes for a particular device … from the underlying host"
  (NGC `l4t-base` page). Those are the L4T driver libraries and the Tegra device nodes.
- **Until JetPack 5,** CUDA, cuDNN and TensorRT came from the host too: "Starting with the r34.1
  release (JetPack 5.0 Developer Preview), the l4t-base will not bring CUDA, CuDNN and TensorRT from the
  host file system" (same page).
- **Each L4T image is tied to one L4T release:** "the l4t-base:r34.1 container is intended to be run on
  devices executing the l4t r34.1 release" (same page).
- **jetson-01's images are of this kind.** They were built for r36.5, with JetPack 6's Jetson build of
  CUDA 12.6.

**From JetPack 7.2, the Orin uses the same driver model as an Arm server.**
- NVIDIA staff (AastaLLL, forum 379812):
  - 2026-08-12: "We don't have JetPack 7.x container."
  - 2026-08-13: "We don't have a plan for this."
  - 2026-08-17: "From JetPack 7.2, both Thor and Orin can use the SBSA driver, so the container on our
    NGC server with `aarch64` support can work", naming `nvcr.io/nvidia/cuda:13.0.0-devel-ubuntu24.04`
    as a base.
- **What's still Jetson-specific:** the toolkit runs in CSV mode on Tegra, which still supplies the
  Tegra device nodes. Toolkit 1.19.0 adds "CUDA Forward Compatibility on Tegra-based systems. On
  Orin-based systems, this requires specific compat libraries in the container" (release notes).
- **So a JetPack 7.2 container is an ordinary arm64 CUDA image,** with the driver supplied by the
  host [I].

**Why the old images fail.** A JetPack 7.2 setup guide (darin5, NVIDIA forum, 2026-06-06) reports
JetPack 6 jetson-containers failing with error 801, "operation not supported". It reads that as the
CUDA 12.6 runtime not bridging to the 13.2 driver. That is the guide's explanation, not NVIDIA's.
- The more likely cause is that the images carry the L4T build of CUDA, tied to the JetPack 6
  driver, and JetPack 7.2 replaced that driver with the SBSA one [I].
- One `docker run` of the old r36.5 image settles whether they fail at all.

**The question that decides faster-whisper: does an SBSA CUDA 12 image run on JetPack 7.2's driver?**
- **What hints yes:** that is the normal backward-compatibility rule on SBSA [I]. NeMo-Speech.cpp's own
  install doc picks its `cuda12` build (CUDA 12.8.1 SBSA, sm_87) for Orin. It doesn't say which
  JetPack.
- **What points the other way:** migration guides say JetPack 6 binaries don't carry over (Juxi
  wiki, Seeed blog). None of them tests an SBSA CUDA 12 image.
- **Not found:** any report either way.
- **The test:** one CUDA sample, such as `deviceQuery`, in an arm64 `nvcr.io/nvidia/cuda:12.x` image.

### What no longer works

- **The JetPack 6 images,** for the reasons above.
- **faster-whisper on CUDA 13.**
  - CTranslate2 has no CUDA 13 support: issue #1933 is open, and its newest CUDA note is 12.8 (4.6.3).
  - Its PyPI wheels link `libcublas.so.12`, and there are no aarch64 CUDA wheels. The role's README says
    the same: CUDA 12.x only (`README.md:115-120`).
  - **If an SBSA CUDA 12 image runs** (above), this stops being a blocker. The route becomes CTranslate2
    built from source for sm_87 against CUDA 12, in an arm64 CUDA 12 image: the arm64 twin of the
    `faster-whisper-cuda-docker` image media-01 runs today [I].
- **jetson-containers.** #1736 (JetPack 7.2 on Orin): the `jp7/cu132` index returns "410 Gone", and a
  commenter calls the repo "in a very unstable state currently". jetson-ai-lab has no jp7 index.
- **whisper_trt.** It fails on JetPack 7.2 with `module 'tensorrt' has no attribute 'CalibrationAlgoType'`
  (forum 378252).
- **Riva.** 2.26.0 supports Jetson Thor only.

### The route: NeMo-Speech.cpp behind wyoming_openai

**NeMo-Speech.cpp** is NVIDIA's speech runtime: Apache-2.0 code, with GitHub releases v0.1.0 and
v0.2.0 (2026-10-02).
- **Orin is the documented target.**
  - `docs/install.md` @v0.2.0: "`cuda12` for Jetson Orin and `cuda13` for Jetson Thor or DGX Spark."
  - An NVIDIA moderator (forum 378939, 2026-08-07): "verified on Jetpack 7.2+Orin".
- **HTTP API** (`docs/api.md` @v0.2.0): `POST /v1/audio/transcriptions` takes:
  - `model`: "accepted for client compatibility; this server uses its one loaded ASR model"
  - `file`
  - `language`
  - `response_format`: `json`, `verbose_json`, `text`, `srt`, `vtt`
  - `automatic_punctuation`, `verbatim`, `speech_contexts` (word boosting), and `prompt`, which is
    "one boosted phrase at boost 10"

  "Mono or stereo PCM16 and float32 WAVs at 8-96 kHz are accepted".
- **Models** (`models/index.json` @v0.2.0):

  | Model | Size | English WER |
  |---|---|---|
  | **Parakeet TDT 0.6B v3** | q8_0, 713,975,456 B | LibriSpeech 1.93 / 3.59; CC-BY-4.0 |
  | Nemotron streaming EN 0.6B | | average 6.93 |
  | Parakeet CTC 1.1B | | average 7.4; lowercase, no punctuation |

  The Open ASR Leaderboard paper (arXiv 2510.06961v3, Table 3) gives averages of **Parakeet TDT v3
  6.32** and Whisper large-v3 7.44. Turbo isn't in the table; its card claims only "minor quality
  trade-offs" against large-v3.
- **What's unverified:**
  - The NGC image `nvcr.io/nvidia/nemo-speech.cpp:0.1.0` (143 MB, amd64 + arm64, updated 2026-08-05)
    is documented with gRPC on 50051 only, and predates the GitHub v0.1.0 tag.
  - Its `docker/Dockerfile` pins CUDA 13.0, and the comment says CI passes architecture 110 (Thor).
  - The GitHub `release.yml` @v0.2.0 builds the aarch64 `cuda12` archive on CUDA 12.8.1 SBSA with
    `87-real;87-virtual`.
  - Whether that CUDA 12.8 build runs on R39's 13.2 driver isn't documented [I].
  - The fallback is building the image with `--build-arg CUDA_ARCH=87`. That build doesn't need a GPU
    [I].
- **Speed:** no Orin Nano figure is published. Embedl's TensorRT Parakeet v3 encoder took 34–36 ms
  on an AGX Orin under JetPack 6, with a 30 s static input. An Orin Nano has about half that GPU, so
  expect tens of ms to ~150 ms for a command [I].
- **A JetPack 7.2 trap with ggml-based runtimes:** NvMap allocator crashes, fixed with
  `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` (forum 380334, llama.cpp). Whether it hits NeMo-Speech.cpp is
  unknown [I].

**wyoming_openai** v0.7.0 (2026-10-01), `ghcr.io/roryeckel/wyoming_openai`, amd64 + arm64:
- Settings: `STT_OPENAI_URL` (any base URL), `STT_MODELS` (required) and an optional `STT_OPENAI_KEY`.
- "Standard Batch Processing: Accumulates audio chunks until receiving an `AudioStop` event, then
  uploads the complete audio file".
- Tested back-ends: OpenAI, Speaches, LocalAI, Voxtral and Groq. NeMo-Speech.cpp isn't among them.
- `STT_BACKEND` overrides auto-detection. NeMo-Speech answers `GET /health`, which the bridge uses to
  recognise Speaches, so set `--stt-backend OPENAI` (round-2 agent's reading of `compatibility.py`
  @v0.7.0).

**Fallbacks:**
- **whisper.cpp built with `-DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES=87`.** v1.9.5 publishes no Linux
  aarch64 CUDA binary. `whisper-server` serves `/inference`, but `--inference-path` can expose
  `/v1/audio/transcriptions` for the same bridge [I]. No JetPack 7 report was found for whisper.cpp;
  ggml with CUDA does run there (Ollama with `OLLAMA_IGPU_ENABLE=1`, forum 372521).
- **TensorRT.**
  - embedl's int8 Parakeet v3 encoder builds natively with JetPack's TensorRT. Its licence says "no
    redistribution as a hosted service".
  - TensorRT Edge-LLM v0.10.0 (benchmarked on JetPack 7.2 / CUDA 13.2 / TRT 10.16) runs Qwen3-ASR
    0.6B and 1.7B. NVIDIA's moderator recommended it for Orin Nano speech recognition (forum 378252).
  - Both are a CLI or a library, so a Wyoming wrapper would have to be written.

## RK1 NPU (rknpu 0.9.8, librknnrt 2.3.2, RKLLM 1.3.1)

**Every RKNN model has a fixed input window.** A 3–5 s command costs as much as the whole window.

| Candidate | English WER (LibriSpeech clean / other) | Time per command | What's needed | Version risk |
|---|---|---|---|---|
| **sherpa-onnx SenseVoice RKNN, 10 s variant (2024-07-17)** | 3.15 / 7.18 (SenseVoice paper; about Whisper-small's 3.13 / 7.37) | 0.52–0.72 s on one NPU core | prebuilt `sherpa-onnx` 1.13.8 rk-npu wheel, plus a ~60–80-line patch to wyoming-faster-whisper [I] | exported with toolkit 2.1.0; sherpa says librknnrt 2.2.0 is "known to work" [I: 2.3.2 loads it] |
| rknn_model_zoo Whisper base, 20 s window (v2.3.2) | 5.01 / 12.85 | ~1.4 s (Radxa: a 5.855 s clip in 1,373 ms) | a server, which you'd write | matches 2.3.2 |
| RKLLAMA `/v1/audio/transcriptions` with danielferr85 RKNN Whisper (tiny → turbo, toolkit 2.3.2) | by model size | unmeasured; pads every request to 30 s, so expect over 1.5 s for small [I] | RKLLAMA plus wyoming_openai; no code | matches |
| Qwen3-ASR 1.7B on RKLLM (happyme531) | 1.63 / 3.38 | ~2–2.5 s [I] (encoder 89.6 ms per 1 s of audio, decode 7.5 tok/s) | a server; ~5 GB | built for RKLLM 1.2.3; we run 1.3.1 |
| Whisper turbo on RKNN | turbo class | encoder alone 12 s (happyme531) | — | RKNNAI's build needs runtime 2.4.0, which isn't public |

- **The NPU doesn't beat the CPU for SenseVoice.** sherpa-onnx's own table: NPU RTF 0.129, against
  0.100 for the int8 model on one A76 core. On the RK3588 the NPU's value is only in taking load off
  the CPU.
- **sherpa-onnx's RKNN API:**
  - `OfflineRecognizer.from_sense_voice(model=…/model.rknn, tokens=…, num_threads=<core mask>,
    provider="rknn", language="en")`
  - `num_threads` doubles as the NPU core mask (`csrc/rknn/utils.cc` @v1.13.8).
  - RKNN back-ends: offline SenseVoice and Paraformer, streaming Zipformer, Silero VAD and keyword
    spotting.
  - No Whisper, Parakeet or Moonshine on RKNN.
- **Where the patch goes.** wyoming-faster-whisper v3.8.1's sherpa handler builds only
  `from_transducer(..., model_type="nemo_transducer")`, and `_resolve_provider` returns only `cuda` or
  `cpu`. The patch would add an `rknn` device, a SenseVoice transcriber, and model routing [I]. With
  `en` and no `--model`, the server would otherwise pick Parakeet on the CPU.
- **Not found:** RKNN ports of Parakeet, Canary or Moonshine; any Wyoming server that uses the NPU.

## RK1 Mali-G610

No whisper.cpp or other speech-to-text result on the Mali-G610 was found, success or failure.
- ggml's OpenCL backend verifies Adreno only.
- On RK3588, llama.cpp's Vulkan prefill ran at 3.3 tok/s, against 35.9 on the CPU (#22682, panvk).
- Open issue #28637 is a correctness race at subgroup size 16, which the G610 reports.

## Sources

- **NeMo-Speech.cpp** @v0.2.0: [`docs/install.md`](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/v0.2.0/docs/install.md), [`docs/api.md`](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/v0.2.0/docs/api.md), `models/index.json`, `.github/workflows/release.yml`, `docker/Dockerfile` @v0.1.0; [NGC container](https://catalog.ngc.nvidia.com/orgs/nvidia/-/containers/nemo-speech.cpp)
- **Containers on Jetson:** [NGC `l4t-base`](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/l4t-base); [forum 379812, "Docker container Jetpack 7.x?"](https://forums.developer.nvidia.com/t/docker-container-jetpack-7-x/379812); [Container Toolkit release notes](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/release-notes.html) (1.17.7, 1.19.0, 1.19.1); [Juxi wiki, JetPack 6 → 7.2.1](https://wiki.juxitech.com/tutorials/jetson-orin-nano/jetpack-6-to-7)
- **NVIDIA forums:** [378939](https://forums.developer.nvidia.com/t/nvidia-riva-support-for-jetson-orin-nano-with-jetpack-7-2/378939), [378252](https://forums.developer.nvidia.com/t/tensorrt-accelerated-whisper-asr-on-jetson-orin-nano-jetpack-7-2-tensorrt-11/378252), [380334](https://forums.developer.nvidia.com/t/nvmap-allocator-crash-on-jetson-orin-nano-running-llama-cpp-vlm-gemma-3-4b-root-cause-found-jetpack-7-2-7-2-1/380334), [372521](https://forums.developer.nvidia.com/t/jetpack-7-2-gpu-acceleration-issue/372521), [darin5's JetPack 7.2 guide](https://forums.developer.nvidia.com/t/setting-up-the-nvidia-jetson-orin-nano-super-dev-kit-on-jetpack-7-2-a-practical-guide-june-2026/372490)
- **Model cards and benchmarks:** [parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3); [Open ASR Leaderboard paper](https://arxiv.org/html/2510.06961v3); [whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo); [whisper-base](https://huggingface.co/openai/whisper-base); [SenseVoice paper](https://arxiv.org/html/2407.04051); [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- [roryeckel/wyoming_openai](https://github.com/roryeckel/wyoming_openai) v0.7.0 (README, `handler.py`, `compatibility.py`)
- **whisper.cpp** v1.9.5 README; [embedl/parakeet-tdt-0.6b-v3-quantized-tensorrt](https://huggingface.co/embedl/parakeet-tdt-0.6b-v3-quantized-tensorrt); TensorRT Edge-LLM v0.10.0
- **CTranslate2** [#1933](https://github.com/OpenNMT/CTranslate2/issues/1933); jetson-containers [#1736](https://github.com/dusty-nv/jetson-containers/issues/1736); [pypi.jetson-ai-lab.io](https://pypi.jetson-ai-lab.io/)
- **sherpa-onnx** v1.13.8: [RKNN models](https://k2-fsa.github.io/sherpa/onnx/rknn/models.html), [RKNN install](https://k2-fsa.github.io/sherpa/onnx/rknn/install.html), `csrc/rknn/utils.cc`, `build-wheels-aarch64-rknn.yaml`
- **wyoming-faster-whisper** v3.8.1: `models.py`, `sherpa_handler.py`, `device.py`
- **Rockchip:** [rknn_model_zoo whisper](https://github.com/airockchip/rknn_model_zoo/tree/main/examples/whisper) v2.3.2; [Radxa whisper](https://docs.radxa.com/en/rock5/rock5b/app-development/ai/whisper)
- **RKNN ports:** [RKLLAMA](https://github.com/NotPunchnox/rkllama); [danielferr85/whisper-models-rknn](https://huggingface.co/danielferr85/whisper-models-rknn); [happyme531/Qwen3-ASR-1.7B-RKLLM](https://huggingface.co/happyme531/Qwen3-ASR-1.7B-RKLLM); [happyme531/whisper-large-v3-turbo-RKNN2](https://huggingface.co/happyme531/whisper-large-v3-turbo-RKNN2)
- **llama.cpp** [#22682](https://github.com/ggml-org/llama.cpp/issues/22682), [#28637](https://github.com/ggml-org/llama.cpp/issues/28637); ggml `docs/backend/OPENCL.md`
- **This repo:** `ansible/roles/docker_compose_wyoming_faster_whisper/README.md`, `ansible/files/jetson-01/docker-compose-home-assistant-wyoming.yml`
