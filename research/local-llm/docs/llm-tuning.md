# The inference layer — llama-swap and llama.cpp on htpc-01

**Every knob that affects generation quality and latency, and the measurement behind each
one.** This is the layer *underneath* whichever harness is running: llama-swap's config,
per-model contexts, VRAM, samplers, `gpu-mode`. Both Onyx and local-deep-research talk to
it, so a change here moves both.

Two settings live elsewhere and are documented here because they are coupled to `-c`:
`max_input_tokens` (the Onyx role on media-01) and the size of crawled search results (a
SearXNG/crawler setting).

**The Onyx experiments E1–E5 near the end are closed** — they are why the harness changed,
not live work. For what is being worked now, see [current-work.md](current-work.md); for
the map, [README.md](README.md).

Hardware: RX 9070 XT (gfx1201), 16,304 MB VRAM. Image
`ghcr.io/mostlygeek/llama-swap:vulkan`, llama.cpp build `b10200` (`5f55650a7`).

> # ⚠ The backend changed on 2026-08-01: ROCm → Vulkan/RADV
>
> **Most throughput numbers below are ROCm-era and were measured on build `b10156`.** They
> are kept because the *reasoning* still holds — why `-fa 1`, why `-np 1`, why per-model
> `-c`, how the KV cache splits — but **do not quote a tok/s figure from this document as
> current** without checking it against
> [research/local-llm/bench/llama-swap/results.md](../bench/llama-swap/results.md) → *Backend A/B — RESULT*.
>
> What the switch measured (18 rows, both arms, same build each side, A-B-A drift −0.26%):
>
> | | ROCm | Vulkan | Δ |
> |---|---|---|---|
> | gemma-4-12b-it generation | 38.7 | **42.7** | +10.3% |
> | qwen3.5-9b generation | 48.0 | **51.1** | +6.5% |
> | gemma-4-26B-A4B generation | 67.4 | **91.1** | +35.2% |
> | gemma-4-12b-it prefill | 1,134.9 | **1,734.6** | +52.8% |
>
> **Prefill is why ROCm was originally chosen, and Vulkan now wins it outright** — see the
> build-provenance section immediately below, which predicted exactly this.
>
> Still valid as written: the `-fa 1` decision (re-measured on Vulkan at **12.3×**, larger
> than ROCm's 7.6×), `-np 1`, `--no-context-shift`, `--reasoning-budget 4096`, the
> `max_input_tokens` arithmetic, and the KV-shape findings. **Re-measure before trusting:**
> the VRAM-per-1k slopes, the deployed-footprint table, and every prefill/generation figure.
> Resident VRAM barely moved — gemma measured 12,529 MB on Vulkan against 12,534 on ROCm.

Related local notes, not in this repository (`handoffs/` is gitignored):
`llamacpp-gemma4-htpc01-spec.md` (original spec), `onyx-llama-swap-status.md`
(deployment state).

**Every number in this document was measured on this machine.** Where something is
reasoned rather than measured, it says so.

## Build provenance — read before trusting or re-running any prefill number

Build `b10156` is llama.cpp commit **`91f8c9c5f`, dated 2026-07-27**
(`system_fingerprint` in any completion response gives you this; `gh api
repos/ggml-org/llama.cpp/commits/<sha>` dates it).

**This build already carries the open RDNA4 flash-attention prefill regression.**
Commit `fa72aeccb` (2026-07-24, PR #26046, *"HIP: remove rocWMMA FlashAttention"*)
replaced the rocWMMA FA kernel with the native `fattn-mma-f16` kernel, whose tiling
appears tuned for CDNA/NVIDIA rather than RDNA4's wave32. Our build postdates it by
three days, so **every prefill number here is on the degraded kernel.**

Reported regression, from [issue #26220](https://github.com/ggml-org/llama.cpp/issues/26220)
(open as of 2026-07-28): **25.2% slower at 16k, 42.4% at 65k, 49.2% at 127k** prompt
processing; token generation unaffected (+3.9%). It scales with KV depth.

Three consequences, and note the second inverts an argument that looks obvious:

1. **This workload's exposure is ~25%, not the 2× headline.** The 2× figure is at 127k;
   RAG prompts here are 10–25k, which sits at the shallow end of the curve.
2. **Pinning the image forward would lock the regression in.** The intuitive reading —
   "a floating tag on a prefill-critical workload with a live regression is dangerous" —
   is backwards here, because we are already on the bad side. The issue is open, so an
   upstream fix arrives *via* `AutoUpdate=registry`. The only pinning that would help is
   pinning *backwards*, to an image built before 2026-07-24.
3. **`-fa 1` still wins 8.3× on the degraded kernel**, so nothing about the config
   changes. This is a "there may be ~25% more available later" note, not a defect.

If you benchmark prefill and get numbers materially different from this document, check
the build commit against `fa72aeccb` before concluding anything about your flags.

---

## Before you touch anything: how to run these tests

These trip up every session:

- **Remote shells are fish.** `ssh htpc-01 'cmd'` runs under fish, so `$?`, `$(...)`
  and `$"` break. Use `ssh htpc-01 'bash -c "..."'` or pipe: `ssh htpc-01 'bash -s' < script.sh`.
- **Nothing is published to the host.** llama-swap has no `PublishPort=`; Caddy reaches
  it by container name. So all probing goes through `sudo podman exec llama-swap curl ...`
  against `localhost:8080`.
- **Use `amd-smi`, not `rocm-smi`** (deprecated, its per-process numbers disagree with
  everything else). It exists only inside the container:
  `sudo podman exec llama-swap amd-smi metric -g 0 --mem`
- **Iterate with the playbook tag, not a full run.** `--tags llama-swap` applies config
  and restarts in **52 s**; a full run re-hashes ~20 GB of GGUFs because `get_url` has a
  checksum. `--tags models` for the downloads, `--tags gpu-mode` for that script.
  The tag on `Deploy llama-swap quadlet` needs `apply: tags:` — a tag on `include_role`
  selects only the include itself, and without `apply` the run reports `ok=3, changed=0`
  and silently changes nothing.
- **llama-swap endpoints — the ones that exist, verified against its README:**
  - `GET /logs/stream/upstream` — **llama-server's own per-request output**:
    `prompt eval time = … / N tokens`, `n_decoded`, `total time`, and crucially
    `truncated`. Works at `logLevel: info`; raising to `debug` is not needed.
    Sends buffered history first; add `?no-history` for live-only.
  - `GET /logs` — llama-swap's proxy log: per-request client, status, duration.
  - `/ui` — web UI with token metrics, request/response inspection, live log streaming.
  - `GET /metrics` — Prometheus **system and GPU telemetry only** (util, VRAM, power,
    temps). Nothing per-request; it cannot answer "how did that query behave".
  - `/api/metrics` and `/logs/upstream` **do not exist** (404). Both are paths I guessed
    before reading the README.
- **`amd-smi process -g 0` has `EVICTED_TIME`** — that field is how VRAM thrashing was
  diagnosed. Non-trivial values mean the driver is swapping VRAM to GTT.
- **`USED_VRAM` is whole-device**, including ComfyUI's ~1 GB and the desktop. Subtract a
  baseline before attributing it to llama-server.
- To test a config without deploying, run llama-server directly, bypassing llama-swap:
  ```
  sudo podman exec llama-swap timeout 120 /app/llama-server --port 5800 \
    -m /models/Qwen3-14B-UD-Q5_K_XL.gguf --jinja -ngl 999 -c 32768 -fa 1
  ```
  `rc=124` means *timeout killed a healthy server*, i.e. success. A real failure exits
  in ~2 s with an error.
- **llama-swap at `logLevel: info` does not relay llama-server's stderr** — you get
  `starting <model> failed: upstream command exited prematurely` and nothing else. Run
  the command manually as above to see the actual error.

---

## Tuning loop mechanics

| step | command | cost |
|---|---|---|
| change llama-swap settings | edit `playbook-htpc-01.yaml` vars | — |
| apply | `ansible-playbook playbook-htpc-01.yaml --tags llama-swap` | **52 s** |
| change `max_input_tokens` | edit `docker_compose_onyx/defaults/main.yaml` | — |
| apply | `ansible-playbook playbook-media-01.yaml --tags onyx` | ~2 min, recreates containers |
| capture | `curl -Ns …/logs/stream/upstream?no-history > run.log` | — |
| run queries | Onyx UI (needs your session) | — |

Preconditions for any measurement run:

- `gpu-mode llm` — ComfyUI stopped. Contention invalidates everything.
- `EVICTED_TIME` 0 before and after; non-zero voids the run.
- Note whether the GGUF was page-cached; cold load is ~39 s.

---

## The workload these values are tuned for

Onyx research queries: web search → crawl page bodies → pack top-k retrieved chunks into
the prompt → synthesize a cited answer.

**Generation dominates, not prefill.** The spec (§2.1) called this workload
"prefill-heavy", and that was right for single-shot RAG — one big prompt, a short
answer. It is **wrong for the agent loop with extended thinking**, and the measurement
is unambiguous:

| the failing call | |
|---|---|
| prefill | 9.8 s for 11,173 tokens |
| generation | ~463 s for 17,534 tokens |
| **prefill share of wall time** | **2%** |

Even bounded, reasoning runs 1,764–1,921 tokens typical; at ~38 tok/s that is ~50 s of
generation against ~10 s of prefill for an 11k prompt. So when trading, **spend prefill
to save generated tokens, not the reverse.** The earlier guidance here said the
opposite; it was inherited from the spec and never rechecked against real traffic.

**More context is not automatically better, but it is now necessary.** Spec §2.4 cites
RULER fidelity degrading past ~64k, and retrieved top-k beating full context (Qwen3-14B,
0.758 → 0.896 EM, arXiv 2606.06758). That argues against *padding* the prompt. It does
not argue against raising `-c`, because `-c` must cover prompt **plus** reasoning
**plus** answer, and the loop's own tool results are not padding — they cannot be
dropped. Raising `-c` to 65536 keeps the usable *prompt* well under the ~64k concern
while giving the loop room to finish.

---

## The workflow, as token accounting

An Onyx research turn is an agent loop. Each iteration appends to the *same* prompt,
which is re-sent in full on the next call:

```
call 1:  S + Q                                   -> R₁ + tool_call₁
call 2:  S + Q + R₁ + tc₁ + W₁                   -> R₂ + tool_call₂
call 3:  S + Q + R₁ + tc₁ + W₁ + R₂ + tc₂ + W₂   -> R_f + A
```

| term | what it is | binding on |
|---|---|---|
| **S** | system prompt + tool schemas | fixed overhead |
| **Q** | user question | negligible |
| **Rᵢ** | reasoning emitted at iteration i | `--reasoning-budget` |
| **tcᵢ** | tool call | negligible |
| **Wᵢ** | crawled web results returned to the model | SearXNG `num_results` + crawler |
| **R_f, A** | final reasoning + answer | `--reasoning-budget`, output room |
| **n** | number of search iterations | model behaviour |

Two limits apply to the **last** call, and they are different limits:

```
Onyx:     S + Q + Σᵢ(Rᵢ + tcᵢ + Wᵢ)              ≤ max_input_tokens − S_overhead
llama.cpp: (all of the above) + R_f + A          ≤ -c
```

**The binding unit is one turn, not the conversation** — and the reason is stronger than
budget truncation. On a follow-up, **every prior turn's tool results are discarded and
replaced by a fixed stub**:

```
This tool call completed but the results are no longer accessible.
```

`_build_tool_call_response_history_message` returns `TOOL_CALL_RESPONSE_CROSS_MESSAGE`
for every tool except image generation (`chat/chat_utils.py:645-651`,
`prompts/chat_prompts.py:95-97`), and the replayed message is hardcoded to
`token_count=20` (`chat_utils.py:846-849`). This is unconditional — not budget-driven.
`construct_message_history` *also* truncates from the top when the budget is tight, but
that never gets a chance to matter for tool output.

**Measured in E1.** The 8th interaction was a follow-up on Q7, whose turn had crawled
20,110 tokens and written a 5,033-token table. The follow-up's first prompt was
**3,599 tokens** — S (~1,430) plus ~2,169 of prior *answer text*. Roughly 25k of crawled
sources were gone, despite ~50k of unused budget.

Two consequences, and they pull in opposite directions:

- **Capacity: good.** Context cannot accumulate across a conversation, so the peak is
  set by the single worst turn. `-c` never needs to cover a long session.
- **Quality: a cost, not a failure.** The operator's follow-up asked for data missing
  from the first table. The model could not re-read the page it had already crawled, so
  it re-searched (n=1, W=2,645) — **and the corrected table was right.** So the loss is
  a repeated search and a different source set, not a wrong answer. Do not overstate
  this: on the one case measured, recovery worked. What is *not* possible is refining an
  answer against the exact sources the previous turn used.

Not tunable from here: no llama.cpp flag, `-c` value, or `max_input_tokens` changes it.
It is upstream v4.4.7 behaviour.

Both failures observed so far are this model being violated:

| failure | which limit | evidence |
|---|---|---|
| `EmptyLLMResponseError` | `-c`, via unbounded R | one call decoded 17,534 tokens, `n_tokens = 32767, truncated = 1`, 472 s |
| `ValueError: Not enough tokens` | `max_input_tokens` | `Required: 23572, Available: 19667`, turn with **n=2** |

---

## Known terms (measured, do not re-derive)

| term | value | source |
|---|---|---|
| S_overhead | ~2,861 tokens | 22,528 `max_input_tokens` − 19,667 reported available |
| S + Q + Σ(R+tc+W) at n=2 | **23,572 tokens** | the `ValueError` |
| R, capped | ≤ 4,096 | `--reasoning-budget 4096`, verified accepted (parser is `stoi`) |
| R, uncapped | 17,534+ | the truncation failure |
| R, typical | 1,764–1,921, one >3,000 | bench harness, synthetic RAG prompts |
| prefill | ~1,134 tok/s @ 11k prompt | upstream log, task 1815 |
| generation | ~38 tok/s, flat | upstream log |
| Gemma VRAM | 12,267 MB @ 32k, **+17 MB per 1k** | context sweep, 4 points, linear |
| Qwen3 VRAM | 14,135 MB @ 41k, **+88 MB per 1k** (q8 KV) | context sweep, 2 points |
| VRAM floor | 1.5 GB free — a **deployment margin**, not a thrashing threshold | see [The 1.5 GB floor is a margin, not a cliff](#the-15-gb-floor-is-a-margin-not-a-cliff) before using it to reject a config |

### The 1.5 GB floor is a margin, not a cliff

**Read this before rejecting a config for "not enough free VRAM".** The 1.5 GB figure has
twice been used to throw away a configuration that measures perfectly well, and once to
redesign a whole benchmark row around a non-problem.

**What actually collapsed.** The `EVICTED_TIME` 772,000 ms event — an 8k prompt taking
>900 s instead of 45 s — happened **with ComfyUI resident on the card** (see
[gpu-mode](#gpu-mode--enforcing-single-consumer-access-to-the-card)). That is contention
between two GPU consumers. It is *not* evidence about how much free VRAM a single model may
leave, and it has been repeatedly misread as though it were.

**What low headroom actually measured.** Two independent runs, both far below the floor:

| free VRAM | result |
|---|---|
| **264 MB** — Qwen3, f16 KV at `-c 32768`, needle test (table below) | prefill 1,191 / 1,174 / 956 tok/s, gen 31.9 tok/s — **normal** |
| **1,468 MB** — Gemma 4 26B-A4B at `-c 65536` ([results.md](../bench/llama-swap/results.md)) | 420 ms eviction, throughput **unaffected**: 67.2 vs 67.4 tok/s against the 1,804 MB run |

So **headroom alone has never been measured to cause thrashing on this card.** The guard
that matters is **GPU exclusivity** — `gpu-mode llm`, with ComfyUI stopped — and that is a
precondition of every measurement run, checked automatically by
[`research/local-llm/bench/llama-swap/preflight.py`](../bench/llama-swap/preflight.py).

**Keep 1.5 GB as a deployment margin.** It is conservative headroom for a config we intend
to ship, and every table in this document is written against it. What it is *not* is a
reason to refuse a measurement: the benchmark harness therefore separates
`VRAM_FLOOR_MB` (1500, deployment) from `BENCH_FLOOR_MB` (500, the point below which a
throughput number stops being one). A config between them runs and is flagged.

**If you are about to write "below the floor, so it will thrash" — don't.** Say what was
measured: free VRAM, `EVICTED_TIME`, and whether throughput moved. `EVICTED` is also not a
pure function of headroom — a Gemma row at 4,184 MB free showed 163 ms, and a `-fa 0` row at
3,600 MB free showed 333 ms.

---

**Measured by E1 on 2026-07-31** (7-query set, `-c 65536`, 21 agent calls, zero
truncation — see [results.md](../bench/llama-swap/results.md)):

| term | value |
|---|---|
| **S** | **~1,430 tokens** — the cached prefix on every agent call. (Onyx's own S_overhead of ~2,861 is its accounting, not llama.cpp's) |
| **n** | 0, 0, 0, 1, 2, 2, 4, 5 → **median 2, max 5**. Three of seven queries did not search at all |
| **W** | **bimodal.** 11 of 14 searches in **1,736–2,645** (median 2,203); 3 outliers at **7,392 · 13,651 · 20,110** |
| **A** | 679–5,033 tokens of final decode (reasoning + answer combined) |
| peak prompt / total | **25,316 / 30,349** |

**W's two modes are the finding.** A search-result set costs ~2,200 tokens and is
strikingly consistent. A page crawl costs 7k–20k and is what sets the peak. An average
across both models neither, so budget against the *outlier*, not the median.

**Still unknown:**

- **R alone** — the upstream log's `n_decoded` is reasoning **plus** answer; it cannot
  separate them. See E2 for what can still be concluded.

---

## What the model already tells us without more measurement

Rearranging for the last call:

```
-c  ≥  S + Q + Σᵢ(Rᵢ + Wᵢ) + R_f + A
```

**E1 settled this by measurement.** The worst turn observed (Q7, n=2 with one 20,110-token
crawl) reached a **25,316-token prompt and 30,349 total**:

```
1,430 (S) + 26 (Q) + 879 + 1,973 (W₁) + 898 + 20,110 (W₂)  = 25,316 prompt
                                          + 5,033 decoded  = 30,349 total
```

So `-c 32768` **could not have run this query set**: 30,349 clears it by only 2,419
tokens, and the largest input budget 32,768 permits (22,528, after the 8,192 output and
2,048 reserve) was exceeded twice. `-c 65536` is earned, not precautionary.

Each additional iteration costs `R + W`. **W is what decides the hardware question**,
because it multiplies by n — and E1 found W is bimodal, so the peak is set by whether a
turn happens to crawl a large page, not by how many searches it runs. Q3 ran **5**
searches and stayed at 14,008 tokens; Q7 ran **2** and hit 25,316.

Capacity, from the measured VRAM slopes:

| model | projected `-c` | free VRAM there | why |
|---|---|---|---|
| Gemma | 131k *(projected from 4 linear points)* | ~2.4 GB | sliding-window attention, ~17 MB/1k |
| Qwen3 | ~48k *(measured: 49k already leaves 1,449 MB)* | at the floor | dense, ~88 MB/1k |

The 1.5 GB floor is not what caps Gemma — linearly that would be nearer 180k. 131k is a
deliberately conservative stopping point, and the extrapolation is untested that far
(compute buffers do not have to stay linear). Gemma's trained context is 262,144, so the
real ceiling may be VRAM or may be the model. **E4 is not needed:** E1's peak turn used
30,349 of 65,536, so the headroom above the deployed context is already 2.2×.

**Gemma is viable on 16 GB in a way Qwen3 is not**, and that is an architecture
property, not a hardware one. Any "do I need a second card" conclusion drawn from
Qwen3's limits would be answering the wrong question.

---

## Coupling rules — change one, change the other

Read this before editing any value.

| If you change… | You must also… |
|---|---|
| `-c` (context) | Update `max_input_tokens` in [docker_compose_onyx/defaults/main.yaml](../../../ansible/roles/docker_compose_onyx/defaults/main.yaml). It must stay **below** `-c`, because `-c` covers prompt **plus** generation **plus** thinking tokens |
| a model, quant, or `-c` | Re-measure VRAM headroom, and measure *throughput* alongside it. Do **not** reject a config on free VRAM alone — see [the floor section](#the-15-gb-floor-is-a-margin-not-a-cliff); the >900 s collapse was ComfyUI contention, and configs at 264 MB and 1,468 MB free both measured normal |
| `-fa` | **Setting `-fa 0` makes Qwen3's `extra_flags` invalid, not merely expensive.** llama.cpp hard-fails context creation with `V cache quantization requires flash_attn`. Verified: `-fa 0` + q8_0 K *and* V exits rc=1 in ~2 s; q8_0 K *alone* loads fine. Separately, Qwen3 does not load at `-c 32768 -fa 0` anyway — the compute buffer OOMs |
| a model id | It must match on both sides: the key in `llama_swap_models[].id` and the `name` in `onyx_llm_models`. llama-swap advertises its config keys on `/v1/models` and routes on them |
| `--reasoning-budget` | Reconsider `max_input_tokens` — thinking tokens come out of the same `-c` budget |
| any config file content | The unit does **not** restart on its own. `llama-swap.yaml.j2` is opted into `restart_service: true` in the playbook; that is what makes a config edit take effect |

---

## Global flags

Everything here is global except `-c`, which is **per-model** —
`llama_swap_models[].ctx` in the playbook. The three deployed models no longer share a
value; see the per-model table below.

| Value | Setting | Status |
|---|---|---|
| `-fa 1` | flash attention on | **Measured.** Biggest win here, and a reversal |
| `-c` **per-model**: gemma **65536**, qwen3.5-9b **65536**, qwen3-14b **32768** | context, `llama_swap_models[].ctx` | Reasoned from spec §5.4 + RULER data; E1 raised Gemma to 65536. Qwen3-14B stays at 32768 because it is dense (~88 MB/1k) and caps near 48k on this card |
| `-ngl 999` | all layers on GPU | Both models fit in VRAM |
| `--no-context-shift` | fail instead of truncate | Reasoned; over-length failure verified |
| `-np 1` | one server slot | Reasoned from prompt size vs cache size |
| `--reasoning-budget 4096` | thinking capped | **Measured.** `-1` broke a real query |
| `--jinja` | use the GGUF chat template | Required for correct role/thinking tags |
| `ttl: 900` | unload after 15 min idle | Releases ~14 GB so ComfyUI/gaming can use the card |
| `healthCheckTimeout: 900` | startup grace | A cold load reads ~10 GiB from disk |

### `-fa 1` — flash attention on (reverses the original `-fa 0`)

The config originally set `-fa 0`, taken from the llama.cpp ROCm scoreboard's `pp512`
figure for this card (5055 → 4903, FA slightly *hurting*). **That does not transfer.**
Measured with a ~4.1–4.5k-token prompt:

| | VRAM used | free | prefill | gen |
|---|---|---|---|---|
| Gemma 32k `-fa 0` | 15,266 MB | 1,038 MB | 151.7 tok/s | 31.9 tok/s |
| Gemma 32k `-fa 1` | 13,497 MB | 2,807 MB | **1,264.9 tok/s** | 33.4 tok/s |
| Qwen3 16k `-fa 0` | 14,670 MB | 1,634 MB | 360.2 tok/s | 35.4 tok/s |
| Qwen3 16k `-fa 1` | 13,464 MB | 2,840 MB | **1,881.0 tok/s** | 44.3 tok/s |

8.3× prefill on Gemma, 5.2× on Qwen3, **~1.8 GB less VRAM**, generation slightly better.
No axis on which `-fa 0` wins.

The scoreboard is not wrong, it measures something else: 512 tokens on Llama-2-7B Q4_0,
and a llama.cpp collaborator notes in that thread it "doesn't reflect actual usage much."
Mechanistically: naive attention is O(n²), so at `pp512` the quadratic term is
negligible and FA's kernel overhead can dominate; at 4–25k the quadratic term *is* the
cost. **Generalizable lesson: a published benchmark for a card is not a substitute for
measuring the actual model at the actual context length.**

**The 8.3× was challenged as a thrashing artifact, and re-measurement upheld it.** The
original `-fa 0` Gemma baseline ran at 1,038 MB free, which at the time was read as low
enough to suspect the figure was part driver thrashing rather than absence of FA. (On the
evidence now in [the floor section](#the-15-gb-floor-is-a-margin-not-a-cliff) that suspicion
was probably unfounded — headroom alone has never been shown to thrash here — but the
re-measurement was worth doing and settles it either way.) Re-run at `-c 16384`, where
`-fa 0` has ample headroom:

| `-c 16384` | free VRAM | `EVICTED_TIME` | prefill | gen |
|---|---|---|---|---|
| `-fa 0` | 2,222 MB | 0–6 ms | 152.8 tok/s | 32.0 tok/s |
| `-fa 1` | 3,079 MB | 0–6 ms | **1,268.9 tok/s** | 39.6 tok/s |

Same 8.3×, with the confound eliminated (>1.5 GB free, near-zero eviction on both
sides). The figure is real.

**Qwen3-14B does not load at all without it.** At `-c 32768 -fa 0`:

```
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 2668.01 MiB on device 0: cudaMalloc failed: out of memory
graph_reserve: failed to allocate compute buffers
llama_init_from_model: failed to initialize the context: failed to allocate compute pp buffers
```

Weights loaded fine — the **compute buffer** was the binding constraint, not the KV
cache. Flash attention removes the materialized attention matrix, which is what that
2.67 GiB was.

Note for future-me: I predicted from arithmetic that Qwen3 at 32k with an f16 KV cache
could not fit, and testing showed it does. The KV cache was never the problem. Test,
don't compute.

### `--no-context-shift` — fail loudly

llama.cpp defaults to *shifting*: on overrun it silently drops the oldest tokens and
continues. Fine for chat. **In RAG the oldest tokens are the retrieved source
documents**, so the model answers confidently from evidence that was thrown away — the
exact failure this deployment exists to prevent.

Verified through llama-swap on the deployed config — a 34,512-token prompt against a
32k context returns HTTP 400 with a precise, actionable body rather than a truncated
answer:

```json
{"error":{"code":400,"message":"request (34512 tokens) exceeds the available context size (32768 tokens), try increasing it","type":"exceed_context_size_error","n_prompt_tokens":34512,"n_ctx":32768}}
```

### `-np 1` — one server slot

llama.cpp defaults to `-np -1` ("auto"), which picked **4 slots sharing one unified KV
cache** — visible in the startup log as
`n_slots = 4, n_ctx_slot = 32768, kv_unified = 'true'`. Wrong here: a RAG prompt is
~25k tokens, so two concurrent Onyx requests need ~50k of a 32k cache.

With one slot each request gets the full context and concurrent requests queue. A queued
request is slower; a KV-exhausted one fails. This was never a deliberate choice before —
it was an unexamined default.

Fewer slots also means smaller compute buffers: Gemma's resident footprint dropped from
13,497 MB (4 slots) to 12,534 MB (1 slot), ~960 MB of extra headroom for free. Qwen3
measured 13,680 → 13,746 MB, i.e. unchanged within noise, so treat the Gemma saving as
a measurement rather than a general rule.

### Deployed footprint — the authoritative numbers

Measured on the running config after deploy. Use these rather than the `-fa` comparison
tables earlier in this section, which predate `-np 1`. `USED_VRAM` is whole-device and
includes the ~1,060 MB ComfyUI/desktop baseline.

| state | used | free |
|---|---|---|
| nothing loaded (baseline) | 1,060 MB | 15,244 MB |
| `gemma-4-12b-it` resident | 12,534 MB | **3,770 MB** |
| `qwen3-14b` resident | 13,746 MB | **2,558 MB** |

Both sit comfortably above the deployment margin. Unloading returns the device
to 1,060 MB exactly, so llama-swap is releasing everything it took.

**Do not difference these against the context-vs-VRAM table below.** That sweep ran at a
15,510 MB baseline, 266 MB above this one — which is exactly why it reads 12,267 MB for
the same Gemma `-c 32768` that shows 12,534 MB here. Both are whole-device `USED_VRAM`;
the 267 MB gap is what else was on the card, not the model. **A slope is only valid
within one baseline**, and mixing the two produced a published number that was wrong by
3.6× (see below).

### `--reasoning-budget 4096` — thinking on, but bounded

Set explicitly rather than inherited, because the build's default is not stated in
`--help` (only "-1 for unrestricted, 0 for immediate end"). Thinking is wanted: this is
multi-source research synthesis, not chat.

**Cost, measured on a realistic RAG prompt: 1,764–1,921 completion tokens** (Gemma, 22k
context, `finish_reason: stop`). An earlier figure of 128–220 in this document was
measured on a trivial `Reply with exactly: OK` prompt and wrongly generalized to
retrieval queries — it is roughly 9× off. The 8192-token output reserve still has ~4×
headroom, but size that reserve against ~2k, not ~200.

Those tokens are billed against the same `-c` budget as the prompt — hence
`max_input_tokens` sitting below the context size.

**`--reasoning-budget` is 4096, not `-1`, and that change came from a production
failure.** With `-1` a real Onyx query generated **17,534+ tokens of reasoning** at
38 tok/s for **472 s**, filled the context (`n_tokens = 32767, truncated = 1`), and
returned with no `content` and no tool call — Onyx raised `EmptyLLMResponseError`. The
prompt was only 11,173 tokens, so the input budget was never the constraint.

4096 sits above measured reasoning (1,764–1,921 typical, one outlier >3,000). The
parser is `stoi`, so any integer is accepted — verified: `4096`, `0`, `-1` all parse,
`abc` fails with `error while handling argument "--reasoning-budget": stoi`.

**Correction to the `--no-context-shift` claim above.** It protects the *prompt* case
only. When **generation** fills the remaining context, the slot stops with
`truncated = 1` inside a normal **200** stream — silent to the caller. The clean 400 is
only ever for an over-long prompt. This is what made the failure hard to spot.

### Context size vs VRAM — measured, both models

`gpu-mode llm`, ComfyUI stopped, `-fa 1 -np 1`, **baseline free 15,510 MB**. `Δ` is
against the row above it, within this table only — see the baseline warning in the
deployed-footprint section.

| config | used | free | Δ | slope |
|---|---|---|---|---|
| gemma `-c 32768` | 12,267 MB | 4,037 MB | — | — |
| gemma `-c 40960` | 12,403 MB | 3,901 MB | +136 MB / 8.2k | 16.6 MB/1k |
| gemma `-c 49152` | 12,539 MB | 3,765 MB | +136 MB / 8.2k | 16.6 MB/1k |
| gemma `-c 65536` | 12,811 MB | 3,493 MB | +272 MB / 16.4k | 16.6 MB/1k |
| qwen3 `-c 40960` q8_0 KV | 14,135 MB | 2,169 MB | — | — |
| qwen3 `-c 49152` q8_0 KV | 14,855 MB | **1,449 MB** — under the 1.5 GB *deployment* margin | +720 MB / 8.2k | 87.9 MB/1k |

**Gemma ~17 MB per 1k context; Qwen3 ~88 MB per 1k** — a ~5.3× difference in slope per
token of KV, because Gemma uses sliding-window attention on most layers and Qwen3-14B is
dense over 40. Gemma is linear across all four points, so ~131k is *projected* to fit on
this card (~13.9 GB, ~2.4 GB free) — projected, not measured.

**Qwen3's slope rests on two points, both in this table**, and that is deliberate: there
is no Qwen3 `-c 32768` row here. The 13,746 MB figure in the deployed-footprint table was
taken at a different baseline and cannot be differenced against these rows. An earlier
version of this document did exactly that and published **~24 MB/1k**, which is wrong by
3.6× and is not derivable from any pair of numbers here.

**Consequence for the hardware question:** Gemma is viable on 16 GB in a way Qwen3 is
not. Qwen3 caps near **48k** if you hold the 1.5 GB deployment margin — from 2,169 MB free
at 41k, that allows only ~7k more context. The hard ceiling is further out and unmeasured;
48k is where we stop *shipping*, not where it breaks. That is an architecture property, not
a hardware limit, and any "is one card enough" conclusion must not be drawn from Qwen3's
ceiling.

**Spec §6.1's gotcha does not manifest — but a lookalike does.** §6.1 warns Gemma 4 can
return the reply in `reasoning_content` with `content` empty. Measured on the deployed
config, both models populate `content` correctly alongside `reasoning_content`:

| model | `max_tokens` | `finish_reason` | completion tokens | `content` |
|---|---|---|---|---|
| gemma-4-12b-it | 64 | stop | 36 | `'OK'` |
| gemma-4-12b-it | 512 | stop | 120 | `'OK'` |
| qwen3-14b | 64 | **length** | 64 | `''` |
| qwen3-14b | 512 | stop | 106 | `'OK'` |

The trap is the third row. **Thinking tokens are spent before `content` is emitted**, so
an output budget too small to cover the reasoning returns empty `content` with
`finish_reason: "length"` — which looks identical to the §6.1 gotcha and will send you
chasing the wrong bug. A trivial "Reply with exactly: OK" costs 106–120 completion
tokens with thinking on.

**Always check `finish_reason` before concluding anything from an empty `content`.**
Onyx's 8192-token output budget is far above this, so it is not a risk in production —
it is a risk when hand-testing with a small `max_tokens`.

Still unverified: how Onyx's UI *renders* `reasoning_content`. The API contract is
correct; the display has not been seen.

---

## Per-model values

**Three models are deployed, and they no longer share a context.** Values here mirror
`llama_swap_models` in [playbook-htpc-01.yaml](../../../ansible/playbook-htpc-01.yaml); that
file is the source of truth and carries the per-entry reasoning.

**Four models are deployed as of 2026-08-01**, all on the Vulkan backend.

| Model | Quant | `-c` | Sampler | Extra |
|---|---|---|---|---|
| `gemma-4-12b-it` | `UD-Q6_K_XL` (9.95 GiB) | **65536** | `--temp 1.0 --top-p 0.95 --top-k 64` | — |
| `qwen3.5-9b` | **`Q8_0`** (9.11 GiB, MTP repo) | **65536** | `--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 1.5` | — |
| `gemma-4-26b-a4b` | `UD-Q3_K_XL` (12.9 GiB) | **65536** | `--temp 1.0 --top-p 0.95 --top-k 64` | — |
| `qwen3-14b` | `UD-Q5_K_XL` (9.82 GiB) | **32768** | `--temp 0.6 --top-p 0.95 --top-k 20 --min-p 0` | `--cache-type-k q8_0 --cache-type-v q8_0` |

`qwen3.5-9b` moved from `UD-Q6_K_XL` to the MTP repo's `Q8_0` — current-work.md decision 3.
`--spec-type` is deliberately unset, so the MTP head is inert and this is the plain Q8_0
baseline that Phase 0 measures speculative decoding against.

`gemma-4-26b-a4b` is new, added for step 3. Its `-c 65536` is measured, not assumed: at
65536 it leaves 1,468 MB free with **less** eviction than at 49152 (216 vs 271 ms) and
identical throughput, so the smaller context bought nothing and only made it incomparable
to the other two.

Samplers are each publisher's own recommendation. **Qwen3.5's is not Qwen3's** — it wants
`temperature 1.0` and `presence_penalty 1.5` where Qwen3 wants `0.6` and no penalty.
Copying one onto the other is an easy and invisible mistake. Qwen3's card explicitly warns
against greedy decoding.

**Comparable weight sizes do not imply comparable VRAM footprints**, and the three models
span a 5× range in what context costs:

| model | attention | VRAM per 1k of `-c` |
|---|---|---|
| `gemma-4-12b-it` | 40 sliding-window (1024) + 8 full, of 48 layers | **~17 MB** |
| `qwen3.5-9b` | 24 linear + 8 full, of 32 layers | **~33 MB** |
| `qwen3-14b` | dense over 40 layers | **~88 MB** |

That is why only Qwen3-14B carries a KV-quantisation flag despite the near-identical file
sizes, and why it alone stays at `-c 32768`. Do not "simplify" this into one shared
setting.

Qwen3-14B at `Q6_K` (11.29 GiB) rejected: no room left for KV plus compute buffers.

`qwen3.5-9b` was added for the local-deep-research harness comparison
([harness-comparison.md](harness-comparison.md)) — it is the only candidate with a
published figure in *that* harness. **Its `-c 65536` is measured, not projected**:
10,371 MB used / 5,933 MB free at a 15,657 MB baseline
([results.md](../bench/llama-swap/results.md), 2026-07-31). Its sampler, reasoning budget
and throughput under a real multi-call load are **not** yet characterised — see
[current-work.md](current-work.md) → Part 0.

`extra_flags` is optional per model; omitting it leaves llama.cpp defaults (f16 KV).

### Why Qwen3 gets a q8_0 KV cache and Gemma does not

Gemma already leaves 2,807 MB free at 32k. Qwen3 with f16 KV leaves **264 MB**, which is
nearly nothing — and the reason to prefer q8_0 is that margin plus the 2.4 GB it returns,
**not** thrashing. The needle table below was run at that very 264 MB and measured normal
throughput; the 772,000 ms collapse this was once attributed to had ComfyUI resident. See
[the floor section](#the-15-gb-floor-is-a-margin-not-a-cliff).

KV quantization is known to degrade *long-context retrieval* specifically — exactly the
capability this deployment needs — so it was measured, not assumed.
Needle-in-a-haystack at ~25k tokens, three depths (10/50/90%), varied seeded filler so
the needle is not trivially anomalous:

| KV | VRAM free | recall | prefill | gen |
|---|---|---|---|---|
| f16 | 264 MB | **3/3** | 1191 / 1174 / 956 tok/s | 31.9 tok/s |
| q8_0 | **2,624 MB** | **3/3** | 1176 / 1173 / 940 tok/s | 28.0 tok/s |

Identical recall, identical prefill, 12% slower generation (~2 s on a typical answer),
2.4 GB more headroom. q8_0 wins.

**Caveat — do not overclaim this.** Both variants scored perfect, so it is a
ceiling-effect result. It rules out gross degradation; it does **not** establish
equivalence. If long-context answer quality ever looks suspect, re-test with a harder
probe (more needles, multi-hop questions, distractors) before blaming anything else.

---

## Onyx-side values

In [docker_compose_onyx/defaults/main.yaml](../../../ansible/roles/docker_compose_onyx/defaults/main.yaml).

| Value | Setting | Why |
|---|---|---|
| `max_input_tokens` | **55296** gemma / **22528** qwen3 | Per-model, always `ctx − 8192 out − 2048 reserve` — see below |
| provider | `openai_compatible` | `multi_llm.py` treats it as a passthrough and sends the model name unprefixed, which is what llama-server expects |
| `api_base` | `https://llama-swap.htpc-01.$DOMAIN/v1` | Cross-host via htpc-01's Caddy |
| `LLM_SOCKET_READ_TIMEOUT` | **300** | Raised from upstream's 60 — see below |
| model names | `gemma-4-12b-it`, `qwen3-14b` | Must match llama-swap's config keys exactly |

`max_input_tokens` is the easy one to get wrong, and it has been wrong twice.

**First error:** set to 32768, equal to `-c`. llama.cpp's `-c` covers prompt **and**
generation, and thinking tokens come from the same budget, so a full-32768 input budget
leaves nothing to answer with.

**Second error:** 24576 in / 8192 out. That sums to *exactly* 32768 — zero slack for the
chat template, BOS, system/tool scaffolding, or any disagreement between Onyx's token
count and llama-server's. Onyx enforces the limit with its own tokenizer; each model
counts in its own vocabulary (Gemma 4 ~262k, Qwen3 ~151k). Under `--no-context-shift`
that discrepancy is a hard 400, not a graceful trim.

**Third error — and the one that caused failure #2: it must be per-model.** Both models
carried 22528 while only Qwen3 ran `-c 32768`. E1 measured two real calls at **23,180 and
25,316 tokens**, so Gemma was refusing turns its own context could hold comfortably.

**Current split, one rule applied twice — `ctx − 8192 out − 2048 reserve`:**

| model | `ctx` | in | out | reserve |
|---|---|---|---|---|
| `gemma-4-12b-it` | 65536 | **55296** | 8192 | 2048 |
| `qwen3-14b` | 32768 | **22528** | 8192 | 2048 |

Recompute a model's value whenever its `ctx` changes in the playbook — the two live in
different files in the same repo and nothing enforces the relationship.

The 8192 output reserve is now measured rather than assumed: E1's largest decode was
**5,033** tokens (Q7's comparison table), leaving 3,159 of headroom. The 2048 reserve
covers what neither number accounts for — chat template, BOS, and the disagreement
between Onyx's tokenizer and each model's vocabulary.

**Do not raise Gemma's beyond 55296 without raising `-c` first.** Above that, Onyx would
accept a prompt llama.cpp cannot answer within its context, converting a clean Onyx-side
`ValueError` into a silent `truncated = 1` mid-generation — which is failure #1's
signature and far harder to spot.

The old warning that "raising this does not buy more retrieved context" was written when
`-c` was the binding limit. With 65536 deployed and a measured peak of 30,349, the input
budget is no longer the scarce resource; per E1, nothing in this workload is.

---

### `LLM_SOCKET_READ_TIMEOUT` — raised to 300, and why 60 would have bitten

`onyx/configs/chat_configs.py:30` defaults it to **60**. The comment at
`onyx/llm/multi_llm.py:358` is the important part: it is the **max gap between response
chunks, not a total request timeout**. The first chunk cannot arrive until llama-swap has
cold-loaded the model *and* finished prefill:

```
cold load (39 s measured) + prefill of a 22.5k prompt (~18 s at 1180 tok/s) ≈ 57 s
```

Three seconds of margin. And htpc-01 has 32 GB RAM against 20 GB of GGUFs, so after a
sleep, a reboot, or a model swap the weights genuinely come off disk rather than page
cache. Set to 300 in `docker_compose_envs`, which reaches both `api_server` and
`background` because upstream's compose gives each `env_file: - path: .env` and the
`docker_compose` role writes exactly that file.

Cost of the larger value: a genuinely hung llama-swap ties a request up for 5 minutes
instead of 1. Acceptable — llama-swap's own `healthCheckTimeout` is already 900.

**Three load figures appear in this document. They are three different conditions, and
only the first one sizes this timeout:**

| figure | condition | what it means |
|---|---|---|
| **39 s** | cold, GGUF read from disk | The worst case, and the one the timeout is sized against. htpc-01 has 32 GB RAM against ~20 GB of GGUFs, so after a reboot or a model swap the weights genuinely come off disk |
| **7 s** | after suspend/resume | Warm. Suspend-to-RAM preserves the page cache, so a resume is *not* a cold-start test |
| **23.3 s** | end-to-end completion, page-cached | Not a load time at all — load **plus** prefill of a 20,830-token prompt, measured from media-01 through Caddy |

Do not use 7 s or 23.3 s to argue the timeout could be lower.

### Suspend / resume — verified, clean

htpc-01 sleeps, so the question was whether ROCm and llama-swap survive a resume well
enough to load a model. Tested by actually suspending it and waking it over the network:

| Step | Result |
|---|---|
| Sleep with no model loaded | Suspends normally — the only inhibitors present were `delay`-mode system ones (NetworkManager, UPower, ModemManager, HandheldDaemon); `sleep-inhibitor.sh` correctly did **not** block |
| Wake-on-LAN | Woke in **~12 s**. `enp7s0`, `Wake-on: g` already armed (get the MAC from `ip link`) |
| Containers | `llama-swap`, `comfyui`, `caddy` all still `Up` across the cycle; `sleep-inhibitor` still active |
| GPU after resume | `amd-smi` works; device reports full 14,937 MB free |
| Model load after resume | Succeeded in **7 s** — a *warm* load: suspend-to-RAM preserves the page cache, so the GGUF never came off disk. Not comparable to the 39 s cold figure. Completion returned `content='OK'`, `finish=stop`, **gen 42.3 tok/s** — normal |
| Eviction on the new process | **`EVICTED_TIME: 0 ms`** on the 11.2 GB llama-server process |

**Reading `EVICTED_TIME` correctly after a resume:** three small processes (281/149/149 MB
— ComfyUI and the desktop compositor) show ~9.6 s of eviction, because they were resident
*through* the suspend and their VRAM was saved and restored. That is a historical
counter, not live thrashing: a second completion left all three values byte-identical.
Attribute eviction to the process that owns it, and compare across two samples before
concluding anything.

**Do not read prefill tok/s from a trivial prompt after a wake.** The verification
completion was 21 tokens and reported 174 then 78 tok/s, which is per-request overhead,
not throughput. Generation rate is the useful health signal at that size.

**Wake path, for future sessions:** the host is on the same L2 as the Mac
(same /24 as the workstation), so a broadcast magic packet to the subnet broadcast works
directly. Confirm `Wake-on: g` with `ethtool` *before* suspending anything remotely —
without it there is no way back short of walking to the machine.

### The path Onyx actually uses — verified end to end

Everything else in this document was measured through `podman exec` on htpc-01. These
were run **from media-01**, cross-host through Caddy over TLS, which is what Onyx does:

| Check | Result |
|---|---|
| DNS + TLS | Resolves to htpc-01's LAN address; `ssl_verify_result=0`; `/v1/models` in 66 ms |
| Model ids | `gemma-4-12b-it`, `qwen3-14b` — match `onyx_llm_models` exactly (a mismatch is a 404 at query time) |
| Cold start, non-streaming | 23.3 s for a 20,830-token prompt at 1,180 tok/s prefill — **but with the GGUF in page cache**, so not the worst case |
| Streaming | **Not buffered.** 299 chunks, first at 3.42 s, last at 10.37 s. No Caddy `flush_interval` tuning needed |
| Over-length | HTTP 400 in 0.2 s, same precise `exceed_context_size_error` body as locally — the proxy does not mangle it |

### Does one Onyx query touch both models? (the swap trap) — inspected, v4.4.7

Weights are ~10 GiB each on a 16 GB card, so the models **cannot be co-resident**;
llama-swap stops one and cold-loads the other on every switch. If a single query
resolved more than one model id, each query would cost a ~40 s cold load and the
deployment would be unusable. Checked by reading the v4.4.7 source
(`git clone --depth 1 --branch v4.4.7`), not by inference:

| Path | Finding |
|---|---|
| Fast/primary two-tier split | **Does not exist in v4.4.7.** `AGENT_ANSWER_GENERATION_BY_FAST_LLM` is defined in `configs/agent_configs.py` but has **zero consumers** — dead config. (`fast_default_model_name`, from older versions, is gone) |
| Normal chat turn | One model. `get_llm_for_persona` → llm_override (the UI dropdown) → persona's `default_model_configuration_id` → `get_default_llm()` |
| Deep Research | One model. `deep_research/dr_loop.py` has **no** `get_default_llm` calls; it takes `llm: LLM` as a parameter and threads it through every sub-call |
| Contextual RAG (indexing-time LLM) | Off — `enable_contextual_rag` defaults to `False` (`db/models.py:2160`) |
| Vision | `get_default_llm_with_vision`, indexing pipeline only, and only for images |

**Which model is the default:** `_seed_llms` (`ee/onyx/server/seeding.py:117`) picks
`visible_configs[0]` — the **first visible entry in `onyx_llm_models`**. Gemma is listed
first, so Gemma is the default. This is positional: reordering that list changes the
default.

**The one real swap source — chat auto-naming.** `PUT /rename-chat-session`
(`chat_backend.py:415`) calls `get_default_llm()` **unconditionally**, ignoring the
session's model. The frontend fires it automatically once per new session, ~200 ms after
the first response, gated on the session having no description
(`useChatController.ts:285`, `useChatSessionController.ts:440`).

So a new chat on the **non-default** model costs two extra cold loads:

```
select qwen3 → load qwen3 (answer) → load gemma (≤3000-token name) → reload qwen3 (next message)
```

On the default model it costs nothing. Consequences:

- **Not a blocker**, and it is per *session*, not per query.
- **List the model you actually use first** in `onyx_llm_models` — first-visible becomes
  the default, and the naming call always uses the default.
- If the churn is annoying, set the second model `is_visible: false`. It stays in
  llama-swap for manual A/B via curl; it just leaves Onyx's dropdown and the default
  selection. That is the cost of the "A/B as a dropdown" design.

## gpu-mode — enforcing single-consumer access to the card

ComfyUI, llama-server and gaming cannot share 16 GB (measured: the same 8k prompt took
>900 s with ComfyUI resident vs 45 s without, `EVICTED_TIME` 772,000 ms → 52 ms).

> **This is the origin of the "thrashing" figure, and it is about contention, not
> headroom.** Two GPU consumers on one card is what collapsed; a single model leaving little
> free VRAM has never reproduced it. The measurement has been misread as a free-VRAM
> threshold more than once — see
> [The 1.5 GB floor is a margin, not a cliff](#the-15-gb-floor-is-a-margin-not-a-cliff).
> Exclusivity, not headroom, is the precondition that protects a measurement run.
[files/htpc-01/gpu-mode.sh](../../../ansible/files/htpc-01/gpu-mode.sh) installs as
`/usr/local/bin/gpu-mode` and takes `game` / `comfy` / `llm` / `status`. Switching is
exclusive by design — `gpu-mode comfy` stops llama-swap, and vice versa.

It stops the llama-swap **container**, not just the loaded model, because Onyx can
trigger a load at any moment and would otherwise pull ~10 GiB back onto the card.

### Boot persistence uses a Quadlet `[Install]` drop-in, not mask/disable

Getting this right needed the manual, and two earlier attempts were wrong:

- **`systemctl disable` does nothing.** podman-systemd.unit(5): Quadlet services "are
  considered transient by systemd ... it is not possible to `systemctl enable` them";
  the generator "manually applies the `[Install]` section ... during generation".
  Verified: `disable` prints nothing and `UnitFileState` stays `generated`.
- **`systemctl mask` works but is a hack.** It leaves the unit un-startable and makes
  Ansible's `state: started` fail the play.
- **The documented mechanism is a drop-in**: "The Install section can be part of the
  main file, or it can be in a separate drop-in file ... The latter allows you to
  install an non-enabled unit and then later enabling it by installing the drop-in."

So `comfyui.container` and `llama-swap.container` carry **no `[Install]`**, and gpu-mode
writes/removes `<name>.container.d/50-gpu-mode.conf`. Verified with the documented
dry-run generator rather than by mutating `/etc`:

```bash
QUADLET_UNIT_DIRS=<dir> /usr/lib/systemd/system-generators/podman-system-generator --dryrun
```

no drop-in → no `WantedBy`; drop-in → `WantedBy=multi-user.target`. On the live host the
`multi-user.target.wants` symlink appears and disappears to match.

**Consequence, deliberate:** on a freshly provisioned host neither GPU container starts
at boot until `gpu-mode` has been run once. Picking a GPU owner is a decision, not a
default. Caddy keeps its own `[Install]`, so ingress is unaffected.

### The role checks state instead of forcing it

`podman_quadlet` would otherwise re-start whatever gpu-mode turned off on the next
playbook run. It now skips a unit that **exists, is inactive, and has an empty
`WantedBy`** — deliberately uninstalled — and says so in the run output rather than
skipping silently. The check is narrow on purpose: it does not fire for a brand-new
unit (so first deploys still start), for a running unit, or for `.network`/`.volume`
oneshots (which sit `active (exited)`).

### ComfyUI can only be stopped by SIGKILL — and that is fine

`/runner-scripts/entrypoint.sh` ends with `python3 ./ComfyUI/main.py ...` **without
`exec`**, so PID 1 is bash with python as a foreground child, and a non-interactive
bash waiting on a foreground child does not act on SIGTERM until that child returns.
Python never sees the signal; podman always escalates to SIGKILL (exit 137).

Therefore:

- Raising `StopTimeout` buys nothing — it only makes each switch slower. It is pinned
  at 10 with a comment so nobody "fixes" it upward.
- `RunInit=true` would not help: catatonit would forward SIGTERM to bash, and bash
  still would not forward it to python.
- `SuccessExitStatus=137` makes the unit report success. **This is not new breakage
  gpu-mode introduced** — the journal shows every prior stop also logged
  `status=137` / `Failed with result 'exit-code'`; it was invisible because a
  successful start clears a failed state and every previous stop was followed by one.
  `Restart=always` does not re-trigger after an explicit `systemctl stop`, which is why
  gpu-mode's stop is the first to leave it sitting in `failed`.
- Nothing durable is lost to the kill: the shutdown `finally` only runs
  `asset_seeder.shutdown()` and `cleanup_temp()`, and `cleanup_temp()` (an rmtree of
  the temp dir) also runs at startup (`main.py:497`).

Verified after the fix: `ActiveState=inactive`, `SubState=dead`, `Result=success`.

# ACTIVE WORK — end-to-end tuning

Everything above is settled and measured. Everything below is open.

## Experiments

Each names the term it resolves. Run in order; each feeds the next.

### ~~E1 — measure W and n~~ — **DONE, 2026-07-31**

Full results in [results.md](../bench/llama-swap/results.md); terms folded into "Known
terms" above. Method used: capture `/logs/stream/upstream` across the query set, derive
each call's **full** prompt as `n_tokens − n_decoded` (not `prompt eval time`'s token
count, which excludes the cached prefix), then `Wᵢ = promptᵢ₊₁ − promptᵢ − Rᵢ`.

```bash
curl -Ns "https://llama-swap.htpc-01.$DOMAIN/logs/stream/upstream?no-history" > run.log
```

Headline: **S ≈ 1,430; n median 2, max 5; W bimodal at ~2,200 or 7k–20k; peak turn
25,316 prompt / 30,349 total; zero truncation.** Config was `-c 65536` with
`max_input_tokens` 55,296 so the loop revealed its natural size rather than dying at a
ceiling.

**Two traps worth keeping**, both of which produced wrong numbers on the first pass:

1. **Group sessions by the auto-naming call, not by time gaps.** Pasted queries land
   10 s apart; a gap threshold splits turns mid-loop and yields *negative* W, which is
   the tell that the grouping is wrong.
2. **`prompt eval time = … / N tokens` is tokens *processed*, not prompt size.** With a
   cached prefix it under-reports by thousands — one call showed 21,525 processed on a
   25,316-token prompt. Use `n_tokens − n_decoded`.

### E2 — does the reasoning cap bind? — **ANSWERED: no. Leave 4096**

The upstream log's `n_decoded` is reasoning **plus** answer and cannot separate them. The
Onyx database can: **`chat_message.reasoning_tokens` stores the reasoning *text*** — the
column name says tokens, the contents are the string.

Reasoning length for each turn's final call, in characters:

| turn | reasoning chars | turn | reasoning chars |
|---|---|---|---|
| Q1 Home Assistant | 1,249 | Q5 flash attention | 2,931 |
| Q2 Caddy vs Traefik | 2,524 | Q6 ZFS vs btrfs | 3,220 |
| Q3 ROCm maintainer | 4,349 | **Q7 Battlemage** | **7,401** |
| Q4 unanswerable p99 | 1,417 | Q7 follow-up | 1,345 |

Converting needs a ratio, and the ratio is not stable: dividing `n_decoded` by
(reasoning + answer) chars gives **3.94 / 3.71 / 3.66** chars per token for Q2 / Q5 / Q6
but **2.39** for Q7, whose answer is a dense markdown table. So the worst case, 7,401
chars, is **~1,900 tokens at the prose ratio and ~3,100 at the table ratio.**

**Under the 4,096 cap either way — but by 24% in the worst case, not the wide margin
`n_decoded` implied.** Leave it at 4096; do not lower it. Failure #1's 17,534-token
runaway did not recur, including on the query that caused it.

Caveat: only the **final** call's reasoning is persisted — `chat_message` holds one row
per turn, not per LLM call. Intermediate calls are unmeasured, but their total decodes
were 203–898 tokens, so they cannot have approached the cap.

### E3 — reduce W at the source — **not needed for capacity; open as an efficiency item**

E1's peak turn used 30,349 of 65,536, so nothing is capacity-bound and the doc's
"W > ~6k → go to E3" trigger is met only by the crawl mode, not the search mode.

What E1 does show is where the cost is: **a search-result set is ~2,200 tokens and a page
crawl is 7k–20k.** Q7 spent 221 s largely on one 20,110-token crawl. So the lever is the
crawler's per-page content, **not** SearXNG's `num_results` — which is the opposite of
what this experiment originally assumed. Worth doing for latency; not for fit.

### ~~E4 — context ceiling~~ — **not needed**

E1's peak turn was 30,349 tokens against `-c 65536`. Skip, per this experiment's own
precondition.

### E5 — quality — **the only experiment that matters, and it found a real defect**

Capacity is settled; quality is not. Verified against the transcripts (see "Reading the
transcripts" below), **not** inferred from the llama.cpp log:

| turn | tool calls | citations | outcome |
|---|---|---|---|
| Q1 Home Assistant | 2 | 4 | sourced |
| **Q2 Caddy vs Traefik** | **0** | **0** | answered from weights, no sources claimed |
| Q3 ROCm maintainer | 5 | 9 | sourced |
| Q4 unanswerable p99 | 4 | 7 | sourced |
| Q5 flash attention | 0 | 0 | correct — no search needed |
| **Q6 ZFS vs btrfs** | **0** | **0** | **fabricated a "Sources:" list of four references** |
| Q7 Battlemage | 2 | 8 | sourced |
| Q7 follow-up | 1 | 5 | sourced, 16 s |

**The defect: Q6 invented its citations.** It asked for a ZFS/btrfs comparison and ended
with *"Cite your sources"*. The model never searched — zero tool calls, zero citations
recorded by Onyx — and closed the answer with:

```
**Sources:**
1. *OpenZFS Documentation - RAID-Z and ARC.*
2. *Btrfs Documentation - RAID levels and Checksumming.*
3. *Ars Technica: "ZFS vs. btrfs: Which is better for your NAS?"*
4. *ServeTheHome: "Comparing ZFS and btrfs for Home Lab Storage."*
```

Plausible titles, no URLs, nothing fetched. **This is the exact failure the deployment
exists to prevent**, and it is worse than not searching: it presents as sourced. Q2 also
skipped the search but did not fake sources, and Q5 was right to skip it — so the trigger
is specifically *"asked to cite" + "did not search"*.

**Detection note, because it nearly slipped past:** a regex for `[1]`-style markers and
`source:` returned **clean** on this answer. The fabricated list uses `1.` under
`**Sources:**`. Grepping for citation syntax does not find fabricated citations — read
the tail of any answer whose tool-call count is zero.

**Forcing the tool does not work on this stack — measured, then confirmed in the docs.**
Sent directly to llama-swap with a `web_search` tool defined and `max_tokens: 4000`
(600 was not enough — thinking alone filled it and returned `finish_reason: length`):

| `tool_choice` | result |
|---|---|
| `"required"` | **no tool call**, prose answer — identical to auto |
| `"auto"` (control) | no tool call, prose answer |

The llama.cpp server README at our build commit (`91f8c9c5f`) lists the accepted values
as `{"type":"auto"}`, `{"type":"any"}` and `{"type":"tool","name":"…"}` — **`"required"`
is not among them.** Onyx sends OpenAI-style `"required"` through litellm, so the server
ignores it. Onyx's own fallback (`llm_loop.py:186`, extract a tool call from the response
text) cannot help either, because the model returned an ordinary prose answer with
nothing tool-call-shaped in it.

Two further paths are closed:

- **`forced_tool_id` is API-only.** `llm_loop.py:775-781` does set `REQUIRED` and narrow
  the tool list — but the field comes from `CreateChatMessageRequest`
  (`query_and_chat/models.py:105`), there is **no** persona column for it and **no**
  reference anywhere in `web/src`. Only the eval harness sets it.
- **Deep Research's orchestrator uses `REQUIRED`** (`dr_loop.py:518`), which runs into
  the same llama-server limitation — though its loop is structured around a separate
  search phase, so it may still search. **Untested; worth one run of Q6 in DR mode.**

So there is no structural way to force a search from this deployment today. What is
available, honestly labelled:

| lever | structural? |
|---|---|
| **Detect it**: flag any assistant message with 0 tool calls (query in "Reading the transcripts") | **Yes** — a visible artifact, catches every occurrence after the fact |
| Persona instructions: "search before answering; never cite a source you did not retrieve" | **No** — exhortation. May help a lot; cannot be verified fixed |
| Remove `internal_search` from the persona (empty index anyway) | Partly — removes a competing tool, does not compel the remaining one |
| Lower `--temp` | **No** — see below |

Then, in order:

- Whether `--temp 1.0 --top-k 64` (Google's *chat* recommendation) hurts grounded
  synthesis. Compare 1.0 vs ~0.3 on citation accuracy — does each claim trace to the
  source cited — not on needle recall.

  **Do not expect temperature to fix fabricated sources.** Temperature rescales the
  logits; it changes *which* of the likely continuations gets picked, not *what the
  model knows*. Once the model is already writing an answer under "cite your sources"
  having never searched, the highest-probability continuation after `**Sources:**` is a
  plausible-looking citation — so `--temp 0` would emit fabricated sources
  **deterministically** rather than not at all. Lower temperature buys consistency, not
  grounding.

  Where it *might* matter is one step earlier: emitting a tool call is itself token
  sampling, so temperature does shift the search/no-search branch. That makes it worth
  measuring as a **rate** (how often does Q6 search at 1.0 vs 0.3, over n runs) — and
  worth being clear that a rate is all you get. It cannot be verified fixed, which is
  exactly why the detection query above is the enforcement mechanism and the sampler is
  not.
- Gemma vs Qwen3 last. **The comparison is no longer like-for-like**: Gemma runs `-c
  65536` and Qwen3 cannot follow past ~48k.

---

## The hardware verdict — **answered: one card is enough**

| E1 result | verdict |
|---|---|
| **p95 turn fits in ≤65k** ← **measured: peak 30,349 of 65,536** | **One 16 GB card is enough. A second card is not earned.** |
| p95 needs 65k–130k | One card still works on Gemma; Qwen3 is out. Second card buys model choice, not capability |
| p95 exceeds ~130k | 16 GB is genuinely the limit — and E3 (reduce W) should be exhausted first |

The worst turn in the query set — a research task that crawled a 20,110-token page and
wrote a 5,033-token comparison table — used **46% of the deployed context** and left
3,489 MB of VRAM free. Nothing in this workload is capacity-bound.

Both original failures were configuration, not capacity: an arbitrary `-c 32768` from the
spec, and an unbounded reasoning budget. E1 confirms it — the same seven queries now run
end to end with zero truncation on the same card.

**What a second card would actually buy:** Qwen3 at a comparable context (it caps at
~48k on 16 GB), or running ComfyUI concurrently instead of `gpu-mode`'s exclusivity.
Neither is a web-research capability gap.

---

## Fixed query set

**Committed at [`research/local-llm/bench/queries.md`](../bench/queries.md)** — seven queries with
the run protocol and the per-turn fields to record. Do not vary them between runs.
Chosen to span the range of `n`, since `n` is what multiplies W:

1. Single-fact current-events lookup — expect n=1
2. Comparison of two named things — expect n=2 (the shape that produced failure #2)
3. Multi-hop, where the second search depends on the first — expect n≥3
4. Question with no good answer — does n grow without bound?
5. Question answerable from model knowledge — does it skip the tool?
6. Long synthesis — stresses A, the one term never measured
7. The exact question that produced failure #1 — the regression case

**Query 7 is a blank that only the operator can fill.** It exists solely in the Onyx chat
history and has to be copied out before the first E1 run; without it the
`--reasoning-budget 4096` fix has no regression test, since none of queries 1–6 is known
to trigger unbounded reasoning.

---

## Rejected / not set

| Option | Decision |
|---|---|
| `-fa 0` | Rejected on measurement. Was the original value |
| Qwen3 f16 KV at 32k | Works, and measured normally at 264 MB free — but q8_0 returns 2.4 GB for identical recall and ~12% slower generation, so there is no reason to run this close to the edge |
| Qwen3 `Q6_K` quant | 11.29 GiB leaves no room for KV plus compute buffers |
| `--cache-reuse N` | Not set. Onyx sends different retrieved context per query, so prefix reuse has little to work with. Reuse still happens automatically for identical prefixes — visible in the needle test, where consecutive prompts sharing a prefix reported ~12.5k processed tokens instead of ~24.8k |
| `-ub` (physical batch) | **Left at the default 512 — measured, not assumed.** Both review docs ranked a `-ub` sweep as the highest-value untested lever. It is a no-op on this hardware: at a 21,828-token prompt, prefill was 1151.2 / 1163.9 / 1136.8 tok/s for `-ub` 512 / 1024 / 2048 — a ~2% non-monotonic spread, i.e. noise. The VRAM cost is real though: free VRAM fell 3,622 → 3,306 → 2,672 MB, so `-ub 2048` gives up 950 MB for nothing |
| **MTP drafter** | **No longer rejected — now a planned measurement.** Speculative decoding matters here because a many-call research pipeline makes *generation* the binding constraint (E1: 98% of wall time). `--spec-type draft-mtp --spec-draft-n-max 6` is supported by this build (`llama-server --help` lists `draft-mtp`) and needs **no separate draft model** — the head ships inside `unsloth/Qwen3.5-9B-MTP-GGUF`. See [current-work.md](current-work.md) → Part 0 |
| `mmproj` vision | Out of scope — spec §6.4. Both Gemma 4 and Qwen3.5 are multimodal, but our GGUFs ship no `mmproj`, so they run text-only. Deliberate, not accidental |
| Pinning the image tag | `latest` + `AutoUpdate=registry`, consistent with every other service. llama-swap only spawns llama-server on the **first request**, so a flag broken by an update surfaces on the next chat rather than at container start — always run a completion after `pqup` |

---

## How to re-measure

### VRAM + speed for a candidate config

Start the server directly, query it, read VRAM, kill it:

```bash
sudo podman exec -d llama-swap /app/llama-server --port 5800 \
  -m /models/<gguf> --jinja -ngl 999 -c 32768 -fa 1 <candidate flags>
# wait for health
sudo podman exec llama-swap curl -sf localhost:5800/health
sudo podman exec llama-swap amd-smi metric -g 0 --mem | grep -E 'USED_VRAM|FREE_VRAM'
# timings come back in the response itself
sudo podman exec llama-swap curl -s localhost:5800/v1/chat/completions \
  -H 'Content-Type: application/json' -d @/tmp/prompt.json | jq .timings
sudo podman exec llama-swap pkill -f llama-server
```

`timings.prompt_per_second` is prefill; `timings.predicted_per_second` is generation.

**Two instrumentation traps that produced wrong conclusions before:**

1. `timings.prompt_n` is *tokens actually processed*, excluding any cached prefix. In the
   needle test, consecutive prompts sharing a prefix reported 12,478 instead of 24,802 —
   that is prefix cache reuse, not a shorter prompt.

   **This silently destroys "run it 3× and take the median."** Repeating the *same*
   prompt against a *running* server gives `prompt_n=1` and a meaningless
   ~0.2 tok/s prefill on runs 2 and 3 — a total cache hit. Restarting between
   *configurations* is not enough; you must restart (or vary the prompt) between
   *repeats*. **Gate every run on `prompt_n` matching the corpus file's recorded token
   count, and discard any run that comes back short.**
2. Benchmark at a **realistic prompt size**. Early numbers were taken at 4.5k tokens,
   which says little about 25k — throughput is non-monotonic in prompt length. And a
   prompt believed to be "8k tokens" was actually ~36k and returned HTTP 400.

Estimate ~16.5 tokens per line of generated filler text, not 10 — that error made a
"24k" test actually 38k, which overran the context.

### Reading the transcripts — what the llama.cpp log cannot tell you

The upstream log gives token counts; it cannot say whether an answer was *sourced*. That
lives in Onyx's database, and reading it is a `SELECT` — **never anything else.** Guard
the session structurally rather than by intention:

```bash
docker exec onyx-postgres psql -U postgres -d postgres -tAc "
SET default_transaction_read_only = on;
SELECT cs.description, cm.id, cm.message_type, cm.token_count,
       length(cm.reasoning_tokens) AS reason_chars,
       left(cm.citations::text, 60) AS citations,
       (SELECT count(*) FROM tool_call tc WHERE tc.parent_chat_message_id = cm.id) AS tcalls
FROM chat_message cm JOIN chat_session cs ON cs.id = cm.chat_session_id
ORDER BY cs.time_created, cm.id;"
```

`SET default_transaction_read_only = on` makes the connection refuse writes, so a
mistyped statement errors instead of mutating. Use it on every call.

Schema facts worth not re-deriving:

- **`chat_message.reasoning_tokens` holds the reasoning *text***, not a count. It is the
  only source that separates reasoning from answer — E2 depends on it.
- `chat_message.citations` is a JSON **object** (`{"2": 133, ...}`), not an array;
  `jsonb_array_length` errors on it. Count keys with `jsonb_object_keys`.
- `tool_call` links by **`parent_chat_message_id`**, not `message_id`.
- One `chat_message` row per turn, not per LLM call — the agent loop's intermediate
  calls exist only in the llama.cpp log. Cross-reference the two.
- `processing_duration_seconds` reads 0 for turns that made no tool call.

### Needle-in-a-haystack recall

**The harness is committed** — [`research/local-llm/bench/llama-swap/`](../bench/llama-swap/README.md),
with needle mode built in: `./run-remote.sh --model gemma --needle --variants 3`. Do not
rebuild it. It generates varied seeded filler, inserts the needle at a chosen depth, and
scores both fields; varied filler matters because repeated identical lines make the
needle trivially findable.

Check **both** fields: with thinking on, a correct answer can appear in
`reasoning_content` while `content` is empty, and scoring only `content` would report a
false miss.

---

## Open items

- **Gemma's `--temp 1.0 --top-k 64`** is Google's general-purpose chat recommendation.
  For grounded synthesis over retrieved text, high temperature tends toward hallucination
  and citation drift. Left at the publisher default because lowering it on a thinking
  model is not obviously safe and **has not been measured**. This is the most likely
  remaining quality win.
- **q8_0 KV ceiling effect** — see caveat above.
- **`reasoning_content` rendering in Onyx's UI** — the API contract is verified correct
  for both models; how Onyx *displays* the reasoning block has not been seen.
- **A 16k-token prompt once failed with an HTTPError** while 8k and 24k succeeded either
  side of it. One data point, no explanation, recorded under `-fa 0`; may not reproduce
  now that the flags have changed.
- ~~Three-way GPU exclusivity~~ — **solved.** `gpu-mode` is written, deployed and
  verified; see the section above. Left here only so the item is not mistaken for open.

## Out of scope

- Multipass indexing — disabled in the v4.4.7 UI, and irrelevant without connectors.
- Connectors / local documents — different workload.
- `-ub`, KV-quant sweeps — settled; see the results above.
- RDNA4 flash-attention regression (#26220) — real, ~25% at our depths, scales with KV
  depth so it worsens as `-c` grows. Upstream's to fix; re-measure after image updates.
