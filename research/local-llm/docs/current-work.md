# Current work — self-hosted research assistant

**What is done, what is next, in what order, and what state each part is in.**

This doc turns over as the work does: finished steps collapse into a line in *Status* and
their detail moves to the doc that owns it. It is **not** a design record — it owns
**sequencing and status only**. When a step needs *how do I measure this*, it links out:

| for | read |
|---|---|
| goal, architecture, current deployment | [README.md](README.md) |
| inference layer — llama-swap, `-c`, VRAM, samplers, `gpu-mode` | [llm-tuning.md](llm-tuning.md) |
| why LDR over Onyx (closed decision) | [harness-comparison.md](harness-comparison.md) |
| how a round is measured and graded | [ldr-tuning-methodology.md](ldr-tuning-methodology.md) |
| the query set and run protocol | [research/local-llm/bench/queries.md](../bench/queries.md) |
| the runner, and how to drive it | [research/local-llm/bench/harness/README.md](../bench/harness/README.md) |

**Rule that keeps this doc from becoming a fifth copy of everything:** if a fact can be
measured, it belongs in `llm-tuning.md` or a `results.md`. If it is a *decision* or a
*status*, it belongs here. A number appears here only when it is the thing being tracked.

---

## Why any of this is happening

| | question | status |
|---|---|---|
| **G0** | Can this hardware serve a self-hosted web-research assistant? Is one 16 GB card enough? | **Answered for Onyx (peak turn 30,349 of 65,536). REOPENED for LDR 2026-08-02.** The LDR figure — 5 calls, peak total 5,912, 9% of `-c` — was measured with **`search.snippets_only = True`, i.e. no page content ever fetched** (`search_engine_base.py:697-701`). Onyx's peak comes from a 20,110-token crawl, so the two are not comparable. The number is real; the conclusion drawn from it was a property of the config, not the harness. Round 1's full-content arms re-derive it. [research/local-llm/bench/harness/results.md](../bench/harness/results.md) |
| **G1** | Which harness returns grounded, correctly-cited answers? | **Settled directionally → LDR.** Onyx delegates "should I search" to a 12B model that answers no (0/3 greedy, 1/4 at temp 1.0) and once fabricated a four-entry source list. LDR's `source-based` searches by construction: 2/2, 17–18 sources, inline citations |
| **G2** | **For LDR, which settings maximise answer correctness at tolerable speed?** | **The live work.** Nothing measured yet. **Reframed 2026-08-02: the lead variables are `search_strategy` and `search.snippets_only`, not the model** — see *Execution order* |

G1 is "directional" deliberately: those two LDR runs predate the runbook, asserted no
preconditions and had no capture attached. They justify choosing LDR; they are not results.

**The metric is correctness of the information.** Real citations are necessary but not
sufficient — an answer can cite a genuine page and still state a wrong number.

*Search rate* was G1's metric and was retired as a tautology — **but only for the pipeline
strategies.** That reasoning assumed `source-based` was pinned. Now that strategy is a
variable it is a tautology for `source-based` and `focused-iteration`, and emphatically not
for **`langgraph-agent`**, which `langgraph_agent_strategy.py:1554-1556` shows will accept a
zero-search answer as final — the Onyx mechanism, in the strategy the deployed web UI serves
by default. So search rate returns as a *per-strategy property to measure*, not as the
selection criterion it used to be.

---

## Execution order

**A step invalidates the measurements of every step after it.** That is the whole reason
for the order — switching backends after a measurement discards the measurement.

| # | step | status |
|---|---|---|
| **1** | Backend A/B: llama.cpp **Vulkan vs ROCm** | **DONE 2026-08-01 — Vulkan wins on every axis.** Deploying it is a separate change |
| **2** | **Model configuration** — qwen3.5-9b → MTP-repo `Q8_0`, MTP on/off, KV sizes from load logs | **partly done** — `Q8_0` deployed 2026-08-01 and KV sizes read from the load logs; MTP on/off is still step 8's |
| **3** | **Evaluate Gemma 4 26B-A4B** (MoE, 3.8B active) | not started |
| **4** | **Build the instrument** — `shootout.py` + `ldr_trial.py` + `records.py` + `preflight.py` + `sweep.py`, driven by `run_tests.py`; SimpleQA via upstream's loader | **DONE 2026-08-02** — 78 tests, 7 stages, all green on the Mac with no GPU/container/LDR |
| **5** | **Round 1 — strategy comparison**, n=20: 3 strategies, model held | **STOPPED EARLY at 29/60, 2026-08-02.** Gates passed; `source-based` eliminated at its default (89% zero-source). Stopped because the design **conflates strategy with search budget** and finishing would not have fixed that |
| **6** | **Round 2 — must control for search budget.** Round 1 ran source-based at ~3 searches/trial and the focused variants at ~40, so their retrieval gap is not attributable to the algorithm. Either equalise the budget or reframe deliberately as a **cost/quality frontier** | **needs re-planning before it runs** |
| **7** | **langgraph-agent search-skip probe** — zero-search rate on the 7 queries | independent of 5–6; cheap |
| **8** | **Then** — model shootout, `(i,q)` walk, temperature, on the winning cell | blocked on 6 |

Steps 1–3 are the inference stack, 4 the instrument, 5–8 the campaign.

**Reordered 2026-08-02, and the reason matters.** The old order put a `calls = f(i,q)` cost
model first and held strategy constant at `source-based`. Two findings inverted that:

- **`source-based` was never evaluated on the correctness metric.** It was chosen under
  *search rate*, for the Onyx comparison, and the pin survived the metric's retirement.
  Upstream reports it at ~70% on SimpleQA against ~95% for `focused-iteration`
  (`BENCHMARKING.md:49-50`) — a larger swing than any inference-layer gain measured so far.
- **`search.snippets_only = True` means the assistant never fetches the pages it cites**
  (`search_engine_base.py:697-701`). On a metric about misreading sources that is plausibly
  the single biggest lever, and it has been true of every measurement this project has taken.

Cost is now a by-product of the shootout rather than a phase of its own — every trial records
`calls`, peak prompt and `truncated` from the llama-swap capture anyway.

---

## Status

Update this table, not the prose. One row per step; a step is `done` only when its result
is written somewhere durable and that place is named here.

| step | state | date | result landed in |
|---|---|---|---|
| 1 — backend A/B | **DONE — switch to Vulkan** | 2026-08-01 | [research/local-llm/bench/llama-swap/results.md](../bench/llama-swap/results.md) → *Backend A/B — RESULT* |
| 2 — model configuration | **partly done** | 2026-08-01 | `playbook-htpc-01.yaml` (Q8_0 deployed) + [results.md](../bench/llama-swap/results.md) (KV shapes). MTP on/off remains |
| 3 — MoE evaluation | **not started** | — | `research/local-llm/bench/llama-swap/results.md`. **Re-quantise before measuring quality** — see *Step 3* below |
| 4 — instrument | **DONE** | 2026-08-02 | `research/local-llm/bench/harness/` — `run_tests.py` runs 78 tests in 7 stages |
| 5 — round 1 pilot | **stopped early, result recorded** | 2026-08-02 | [research/local-llm/bench/harness/results.md](../bench/harness/results.md) → *Round 1*. 29/60 trials, 9 complete cycles, 0 failures. Resumable if the remainder is ever wanted |
| 6 — round 2 | **blocked on 5** | — | `research/local-llm/bench/harness/results.md` |
| 7 — search-skip probe | **not started** | — | `research/local-llm/bench/harness/results.md` |
| 8 — model / (i,q) / temperature | **blocked on 6** | — | `research/local-llm/bench/harness/results.md` |

**Already done, for context** (not steps — completed work that produced the current state):

| what | when | where |
|---|---|---|
| E1 — measure `W`, `n`, peak prompt across the 7-query set | 2026-07-31 | [llm-tuning.md](llm-tuning.md), [research/local-llm/bench/llama-swap/results.md](../bench/llama-swap/results.md) |
| E2 — does the reasoning cap bind? (**no**, leave 4096) | 2026-07-31 | [llm-tuning.md](llm-tuning.md) |
| E5 — quality: found the fabricated-citation defect | 2026-07-31 | [llm-tuning.md](llm-tuning.md) |
| Harness decision: Onyx → local-deep-research | 2026-07-31 | [harness-comparison.md](harness-comparison.md) |
| LDR deployed on docker-01, `hf` CLI on htpc-01, qwen3.5-9b added | 2026-07-31 | `docker_compose_local_deep_research`, `playbook-htpc-01.yaml` |
| Doc set renamed and reconciled; this doc created | 2026-07-31 | this repo |

---

## Decisions taken — do not re-litigate

1. **Backend scope: llama.cpp Vulkan vs ROCm only.** Not other engines, not moving to the
   A4000. Engine stays llama.cpp.
2. **Evaluate RAGAS / DeepEval before building more grading** — before writing
   `merge-grades.py` or refining the rubric. An **API-key requirement is a preference
   against, not a dealbreaker**. The substantive question is whether they grade *truth* or
   only *faithfulness to retrieved context*; the latter is weaker than the stated metric,
   since an answer can faithfully reproduce a wrong source.
3. **qwen3.5-9b → `unsloth/Qwen3.5-9B-MTP-GGUF` / `Qwen3.5-9B-Q8_0.gguf` (9.11 GiB).**
   **DONE — deployed 2026-08-01.** The `sha256` this once waited on was never needed:
   `hf download` keys idempotency on `creates:` and nothing read `item.sha256`, so the key
   was dead config and has been deleted throughout.
4. **Grading = blind fresh-Claude thread, web-verifying.** Not upstream `claude_grading`,
   which needs a paid API key and grades from model memory.
5. **Tuning set = SimpleQA; confirmation set = the 7 queries.**
6. **Runs execute in tmux on docker-01**, scripts on the `/data` bind mount.
7. **Every swept parameter goes in the settings snapshot, never in `quick_summary` kwargs**
   (2026-08-02). `iterations=` / `questions_per_iteration=` as kwargs are **silently
   discarded** — an upstream defect affecting the programmatic API, `benchmarks/runners.py`,
   the web Benchmark UI and the Optuna optimizer alike. Full path and measurements:
   [research/local-llm/bench/harness/README.md](../bench/harness/README.md) warning box. `search_strategy`
   is the one exception — it is consumed at construction and does work as a kwarg.
8. **Reuse upstream's dataset and graders; do not reuse its runner** (2026-08-02). The
   installed package ships ~11,000 lines of benchmarking, and its SimpleQA/BrowseComp
   datasets, graders and `BENCHMARKING.md` sizing rules are adopted wholesale. Its
   `run_benchmark` is not: `runners.py:201-209` never passes `search_strategy` and passes
   `iterations` as a dead kwarg, so it can vary neither thing this campaign varies.
9. **Sample sizes follow `docs/BENCHMARKING.md:56-125`** (2026-08-02): n≥100 for a usable
   read, ≥200 to compare two configs, and no acting on differences under ~2–3pp. n=20 is for
   eliminating and for wiring, never for ranking. Every reported score carries N and its
   Wilson interval.

---

## Part 0 — Settle the inference stack before measuring anything through it

**This part came first because a backend change invalidates every number measured through
it — and on 2026-08-01 the backend did change, ROCm → Vulkan.** The throughput figures in
[llm-tuning.md](llm-tuning.md) are therefore ROCm-era unless stated otherwise; that file
carries a banner saying so. Current figures live in
[research/local-llm/bench/llama-swap/results.md](../bench/llama-swap/results.md).

### Step 1 — Backend A/B: Vulkan vs ROCm

**The engine was inherited, not chosen.** llama.cpp arrived in the original spec from a
previous thread, and every hour since went into tuning *within* that choice.

The case for testing Vulkan, in one line each:

- **Generation is 98% of wall time** (E1: 463 s generation vs 9.8 s prefill). Vulkan is
  reported **+20–23% on token generation** for RDNA4 — [discussion #15021](https://github.com/ggml-org/llama.cpp/discussions/15021)
  (gfx1201, Vulkan 220 vs ROCm 179 t/s), [vachsark](https://vachsark.com/blog/vulkan-beats-rocm/)
  (RX 9070 XT, RADV +20% on an 8B).
- **ROCm was chosen for prompt processing, and that reason may have expired.** Its pp
  advantage is attributed to the rocWMMA FlashAttention kernel; commit `fa72aeccb`
  (2026-07-24, PR #26046) **removed rocWMMA FA**, and our build `b10156` = `91f8c9c5f` is
  dated **2026-07-27** — three days later. [Issue #26220](https://github.com/ggml-org/llama.cpp/issues/26220)
  records the cost: 25.2% at 16k, 42.4% at 65k.
- **The trade is ~9:1 favourable.** Even assuming Vulkan loses prefill by the same 25%:
  −25 s of generation against +2.5 s of prefill ≈ **−22 s per turn**. Trading a percentage
  of 98% against a percentage of 2%.

> **The joining inference is mine and is not evidence.** Nobody has published a
> post-`fa72aeccb` ROCm-vs-Vulkan comparison on RDNA4. **That measurement does not exist;
> this experiment produces it.** A negative result is publishable and worth writing up.

**Counter-evidence, stated so the A/B is run honestly:** ROCm+rocWMMA led pp by ~21% on
Strix Halo (RDNA 3.5, Oct 2025 — different card, architecture, year *and* kernel);
[discussion #21043](https://github.com/ggml-org/llama.cpp/discussions/21043) gives ROCm the
win for dense >20B (both our models are dense, both under 20B); and Vulkan pp variance was
measured at 5,600–7,500 where ROCm held under 1% — predictability can beat speed on an
interactive path.

**Method and traps: [llm-tuning.md](llm-tuning.md) and
[research/local-llm/bench/llama-swap/README.md](../bench/llama-swap/README.md).** Do not restate them here.
The five that would waste the experiment, by name so they are not skipped:

1. **Force RADV** — `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json`. AMDVLK's
   prefill is ~4× slower on dense models; ICD auto-selection picking it is a **false
   negative for the whole experiment**.
2. **Load Qwen3-14B first, before benchmarking anything.** Its `extra_flags` carry q8_0 K
   *and* V, and llama.cpp hard-fails with `V cache quantization requires flash_attn`. If
   Vulkan's FA does not cover quantised KV it will not load at all — and it cannot fall
   back to `-fa 0`, which OOMs the compute buffer.
3. **`amd-smi` may not exist in the Vulkan image.** The whole VRAM protocol runs through
   it. Fall back to `amdgpu_top` or `/sys/class/drm/card*/device/mem_info_vram_used`, and
   **write down which method was used** — a slope is only valid within one method.
   *(Settled: it is absent, so both arms read host sysfs and `EVICTED` is `n/a` on Vulkan.)*

   **Do not reject a Vulkan config for free VRAM alone.** The 1.5 GB figure is a deployment
   margin, not a thrashing threshold —
   [llm-tuning.md](llm-tuning.md#the-15-gb-floor-is-a-margin-not-a-cliff).
4. **Re-measure VRAM per backend.** Allocators differ; the ~17 / ~33 / ~88 MB-per-1k slopes
   are ROCm measurements.
5. **`-fa 1`'s 8.3× win is ROCm-specific.** Re-run `-fa 0` vs `-fa 1` at `-c 16384`, where
   both sides have headroom and the thrashing confound is gone.

Also: the `:vulkan` llama-swap tag needs confirming before the quadlet is edited, and
**device wiring differs** — ROCm needed `/dev/kfd` *and* `/dev/dri`; Vulkan needs `/dev/dri`
and a Vulkan ICD in the image. Record the **Mesa/RADV version** alongside the build commit;
Mesa version alone moved RADV prefill 13% in one published test.

**Decision criteria**

| outcome | action |
|---|---|
| tg ≥ +10%, both models load, ≥1.5 GB free | **Switch.** Mark the backend on every prior measurement so rows are never mixed |
| tg ≥ +10% but Qwen3-14B will not load | Switch anyway — it is already out of the model comparison. Record the incompatibility |
| tg gain <10% | Compute end-to-end from the 98/2 split. Even ~5% is ~7 s/turn and probably still wins |
| **tg regresses** | **Stay on ROCm — and write it up.** New information that does not exist publicly |
| free VRAM < 1.5 GB | **Not disqualifying on its own.** 1.5 GB is a deployment margin; configs at 264 MB and 1,468 MB free both measured normal throughput, and the >900 s collapse was ComfyUI contention, not headroom. Record the figure, check `EVICTED` and wall time, and prefer a config with margin when the throughput is equal — see [llm-tuning.md](llm-tuning.md#the-15-gb-floor-is-a-margin-not-a-cliff) |

**A prefill-only win does not matter here** — prefill is 2% of wall time.

### Step 2 — Model configuration

Runs on whichever backend step 1 selects.

**Why this is a step and not a footnote: the model shootout (step 8) would otherwise be
confounded.** Gemma's
settings are the product of ~6 experiments — `-fa 1`, `-np 1`, `--no-context-shift`,
`-c 65536`, `--reasoning-budget 4096` sized against *measured* Gemma reasoning.
**qwen3.5-9b has had one trivial load test.** Comparing a tuned model against an untuned
one measures the tuning, not the model.

**The quant decision, and why two decisions collapse into one download.** The original
`UD-Q6_K_XL` was chosen to match Gemma's tier so the comparison would not be confounded by
quantisation — a *comparison* argument, not a quality one, and with 5,933 MB free there was
headroom to spend on precision. Take **`Q8_0` from the MTP repo** (9.11 GiB): Q8_0 because
the metric is factual correctness, and the **MTP** repo because it costs only +0.24 GiB
over the base Q8_0 and makes speculative decoding an `extra_flags` toggle instead of a
second 9 GiB download later.

**MTP is confirmed supported on this build, not assumed.** `llama-server --help` lists
`draft-mtp` among `--spec-type`'s values and provides `--spec-draft-n-max`; unsloth gives
the invocation as `--spec-type draft-mtp --spec-draft-n-max 6`, with **no separate draft
model** — the head is inside the GGUF. Claimed 1.5–2× faster generation.

Sequence:

1. Update `repo` / `file` / `sha256` in `playbook-htpc-01.yaml`, run `--tags models,llama-swap`.
2. **Load it with `--spec-type` unset and re-measure VRAM.** The ~5.0 GB-free figure is
   projected from a file-size delta. A model that does not fit produces a model shootout
   with nothing in it.
3. **Confirm it answers correctly in that baseline mode** — otherwise an MTP fault and a
   model fault are indistinguishable.
4. Step 8 then runs both arms, with and without
   `extra_flags: "--spec-type draft-mtp --spec-draft-n-max 6"`.

**What this step must settle**, with the evidence to collect:

| unverified | why it matters | evidence |
|---|---|---|
| `--reasoning-budget 4096` for qwen3.5-9b | Inherited from Gemma. Qwen3.5 is a thinking model whose card wants `presence_penalty 1.5` — different generation dynamics, plausibly longer reasoning. If 4096 binds, its quality score is an artefact of *our* config | reasoning/decode length distribution; any decode hitting exactly 4096 |
| whether MTP fits alongside `-c 65536` | The draft path may need extra buffers | free VRAM under real load, not a trivial prompt |
| real MTP speedup on *this* workload | Speculative decoding's gain depends on acceptance rate; 1.5–2× is a claim | generation tok/s, spec on vs off, one config |
| MTP is lossless | Distribution-preserving *in theory*; interaction with `temperature 1.0` + `presence_penalty 1.5` is not something we have evidence for | same prompt, spec on and off, compare outputs |
| throughput | Only ever measured on an 8 s trivial generation | generation tok/s at realistic prompt depth |

> **KV arithmetic from the model configs is unreliable, and this step should resolve why.**
> The calculation that predicts Qwen3.5-9B correctly (~33 MB/1k predicted, ~31 measured)
> predicts **~65 MB/1k for Gemma when the measurement is 17** — a 4× miss. It matters
> because step 8 needs to choose configs that fit `-c` *without* measuring each one.
> Cheap resolution: `llama-server` reports `KV self size` in its **load log**. Read it for
> both models instead of inferring from whole-device VRAM deltas, which also include
> compute buffers, the desktop and ComfyUI. One model load each, ~1 minute — and it likely
> explains the gap outright, since a device delta and a KV allocation are different
> quantities.

### Step 3 — Evaluate Gemma 4 26B-A4B (MoE)

**Possibly the biggest lever, and it was nearly missed.** The deployed model is a dense
12B, so every generated token reads all ~10 GiB of weights. **Gemma 4 26B-A4B activates
3.8B of 25.2B** — same family, same sliding-window attention — with `UD-Q3_K_XL` at
**12.9 GB** and `UD-IQ4_XS` at **13.6 GB**.

At a 98% generation share, activating ~3.8B instead of 12B should decode several times
faster *and* be a stronger model. That is larger than the backend switch or any tuning
parameter, and it **contradicts the earlier reasoning that "MoE is the thing 16 GB
blocks"** — Unsloth's low-bit quants bring a 25B MoE under the ceiling.

Unmeasured, and both could kill it: whether either quant leaves usable headroom at a usable
`-c`, and whether Q3/IQ4 quantisation costs enough factual accuracy to negate the gain —
which matters a great deal here, because **correctness is the metric** and low-bit quants
degrade exactly that.

> **Blocking for this step: it is deployed at the wrong quant, and the reason has evaporated.**
> `UD-Q3_K_XL` was chosen as a **throughput probe** for the backend A/B, because it was "most
> likely to leave the 1.5 GB VRAM floor free" (`playbook-htpc-01.yaml:113-116`). Three things
> void that now: it measured **1,468 MB free** (`:135`), so it missed its own criterion; the
> 1.5 GB floor has since been corrected to a deployment margin rather than a cliff; and it
> **stayed deployed**, where a throughput probe's quant is indefensible on a correctness
> metric. It also contradicts `ldr-tuning-methodology.md:43-49`, which leaves quant unmatched
> precisely *so each model competes at its best* — gemma runs `UD-Q6_K_XL` and qwen3.5 `Q8_0`,
> while the MoE sits two to three tiers below on the one axis low-bit quants damage most.
> **Re-quantise to `UD-IQ4_XS` (13.6 GB, fits) or better the QAT repo** — named as the right
> starting point in that same comment and never acted on. Measuring the MoE at Q3 would
> eliminate it on a handicap we imposed. *(The QAT repo's existence is inherited from that
> comment and has not been verified against Hugging Face.)*

After step 1 (the two would confound each other), before step 8 — tuning a slow dense
model is wasted effort if a fast MoE replaces it.

---

## Part 1 — The instrument — **DONE 2026-08-02**

Built, tested, and green. **How to drive it lives in
[research/local-llm/bench/harness/README.md](../bench/harness/README.md); this section owns only its state.**

```
sweep.py ── sync ─→ preflight ─→ start capture ─→ tmux ─→ shootout.py
   (Mac)                                                      │
                                                     ldr_trial.py (subprocess, bounded)
                                                              │
                          upstream.py ── byte-offset ──→ shootout.jsonl ─→ records.check
```

| script | job |
|---|---|
| `ldr_trial.py` | one trial. **All swept parameters via the settings snapshot** (decision 7) |
| `shootout.py` | the grid — resumable, question-outermost, per-trial subprocess timeout |
| `records.py` | validates a row *before* it reaches a score, incl. asking-vs-happened |
| `upstream.py` | llama-swap capture → calls, peak prompt, `truncated`, tok/s |
| `preflight.py` | cross-host go/no-go; the only thing that can see both hosts |
| `sweep.py` | launcher: sync → preflight → start capture → tmux |
| `make_questions.py` | SimpleQA via upstream's loader, `seed=42` |
| `capture_fixtures.py` | records LDR's real API to `testdata/ldr-api.json` |
| `run_tests.py` | one entry point; 7 stages, 76 tests, Mac-only |

**Superseded and deleted from the plan:** `run-matrix.py`, `run-ldr.py`, `summarise.py`,
`merge-grades.py`, `selftest.sh`, `queries.json`. The first two could not vary strategy or
evidence depth; grading now has ground truth from SimpleQA, so the export/merge pair is not
on the critical path; `selftest.sh` became `run_tests.py`.

**Three design points worth not re-deriving:**

- **Question outermost, cells inner.** There is no reload cost to order around — the model is
  held and both swept knobs are per-call. What ordering decides is what a *partial* run is
  worth: question-outermost leaves all six cells at equal n when interrupted, which is the
  only way a killed pilot is still comparable.
- **Byte-offset capture attribution, not task ids.** A llama-server restart resets task ids
  to 0, and the parser keys by id — so a region spanning a restart silently *merges* two
  calls and loses one, lowering the peak and raising the per-call average. Both flattering.
- **The API fixture is a live regression guard.** `test_ldr_api.py` asserts the upstream
  kwargs defect *still exists*; the day it is fixed, the test fails and tells us the
  workaround can go.

---

## Part 2 — The measurement campaign

### Two sets, two graders — deliberately

The seven queries were designed to measure Onyx's *search rate*; most have no ground truth,
so they are weak for grading correctness.

| set | role | grading |
|---|---|---|
| **SimpleQA subset** | **tuning** — the sweep runs against this | blind thread, **against supplied ground truth**. Cheap per item, repeatable, comparable to upstream's 91.2% for Qwen3.5-9B |
| **the 7 queries** | **confirmation** — winning config only | blind thread, **web-verifying**. Covers multi-source synthesis, which SimpleQA cannot score |

This spends the expensive grading only where it is irreplaceable. A config that wins on
SimpleQA but produces bad synthesis is caught by the 7-query confirmation set; the reverse
ordering would burn
judge time on configs the cost model would have rejected.

**Blind judging.** `export-for-grading.py` holds model and parameters back in `KEY.json` so
the judge cannot anchor, and the rubric requires web verification rather than recall.

### SimpleQA — resolved, verified in the installed package

- **Dataset is a plain public CSV** at
  `openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv`. No HuggingFace
  token, no dataset API — docker-01 needs only outbound HTTPS.
- **Use the dataset loader, not the benchmark runner** (revised 2026-08-02).
  `DatasetRegistry.create_dataset("simpleqa", num_examples=n, seed=42)` owns the download,
  the CSV parsing, the `problem`/`answer` normalisation and the **seeded sampling** — all
  reused by `make_questions.py`. Upstream's `run_benchmark` is not used: it cannot vary
  strategy or `(i,q)` (decision 8).
- **No API key needed:** grading is optional (`runners.py:46`, `run_evaluation=False`). Keep
  the answers plus their ground truth and grade them ourselves.

**Consequence 1 — "mechanical grading" was wrong.** SimpleQA answers are short but
free-form, so scoring needs semantic equivalence, which is why upstream ships an LLM
grader. Corrected: SimpleQA grading is **cheap because the judge is given the ground-truth
answer**, not because it is string matching. The 7-query grading is expensive because the
judge must *research* the truth first.

**~~Consequence 2 — temperature cannot be swept on this path.~~ Withdrawn 2026-08-02.** That
rested on `evaluate_simpleqa` taking no `temperature` — but we drive `quick_summary`
directly, where `temperature` **is** a named parameter and genuinely honoured (unlike
`iterations`). Temperature is back on the table; it is deferred to step 8 to keep round 1 to
one grid, not excluded. `llm-tuning.md:1252-1256` calls it "the most likely remaining
quality win".

**~~Naming trap.~~ Resolved** — see open question 3.

### Use existing tooling rather than inventing method

The experimental design is ours; the machinery should not be. LDR ships **Optuna**
(`examples/optimization/`) plus SimpleQA and BrowseComp runners.

> **Optuna is out for now (2026-08-02), and for a specific reason.**
> `optuna_optimizer.py` sweeps `iterations` and `questions_per_iteration` by handing a
> `system_config` to `benchmark_evaluator.evaluate()`, which reaches `quick_summary` as
> **kwargs** (`runners.py:201-209`) — the channel that does nothing (decision 7). So the
> optimizer is searching over a dimension that has no effect, and its trial scores differ
> only by noise and by whatever the settings snapshot happened to hold. Revisit if upstream
> fixes the parameter path; `test_ldr_api.py` will say when.

**RAGAS / DeepEval — evaluate before building more grading.** Deferred rather than dropped:
SimpleQA supplies ground truth, so the tuning set does not need them, and the decision only
becomes load-bearing for the 7-query confirmation set. The questions that decide it:

| question | why it decides |
|---|---|
| Do their metrics need an **LLM judge with an API key**? | A preference, not a dealbreaker. Many accept an OpenAI-compatible endpoint, which **llama-swap already is** — so a local judge may be possible (weak, but free) |
| Do they grade **faithfulness to retrieved context**, or **truth**? | Faithfulness is weaker: an answer can faithfully reproduce a wrong source. The metric is *correctness* |
| Can they consume our JSONL, or do they demand their own pipeline? | Adopting one that demands its own runner discards the resumable runner and the tmux model |
| Do they add **answer-relevance, context-precision/recall**? | Real published metrics we have no equivalent for — the strongest reason to adopt |

The rubric was written because nothing else was to hand. That is not the same as it being
the right tool, and this evaluation has to actually settle it.

### Phases

**Order and status live here; method lives in
[ldr-tuning-methodology.md](ldr-tuning-methodology.md).** Do not restate the method here.

**Restructured 2026-08-02.** The old Phase 0–3 numbering assumed a cost model first and
strategy held constant; both assumptions are gone. Rounds map to *Execution order* steps 5–8.

| round | question it answers | what it unblocks | status |
|---|---|---|---|
| **1** | Of 3 strategies × {snippets, full content}, which produce correct answers — and does configured `iterations` even take effect? | Everything. It is also the **gate**: if `iterations` does not vary, no correctness comparison means anything | next, n=20 |
| **2** | Which of the top 2 cells is actually better, at a defensible N? | The recommended `(strategy, evidence depth)` | blocked on 1, n=100 |
| **probe** | How often does `langgraph-agent` — the deployed UI default — answer without searching? | Whether to change the deployed default | independent, cheap |
| **later** | Model, `(i,q)`, temperature on the winning cell | The final config | blocked on 2 |

**A round that cannot change what happens next should not run.** Round 1 at n=20 has a
±17–21% Wilson margin (`BENCHMARKING.md:71`) — enough to eliminate a badly-losing cell and to
prove the wiring, never enough to rank two close ones. Ranking is round 2's job.

**Cost is no longer a phase.** Every trial records `calls`, peak prompt, `truncated` and
tok/s from the llama-swap capture regardless, so the cost model falls out of the shootout
instead of costing its own ~10 trials.

**Binding constraint: ~220 s per trial**, *measured* (2026-08-01, Q1 at the settings default)
— not the "~6–8 min" previously extrapolated from two runs. Full-content arms fetch pages and
will be slower; round 1 measures that too. `gpu-mode` is exclusive and htpc-01 sleeps, so
wall-clock is a real cost.

### Done looks like

A recommended `(strategy, evidence depth)` with measured correctness, **its N and Wilson
interval**, wall time, calls per query and peak prompt — plus **an honest answer to G0 for
this harness**: does a pipeline that actually *reads its sources* still fit one 16 GB card.
The existing 9%-of-`-c` figure does not answer that, because it was measured with page
fetching off. `truncated = 1` anywhere is a failure, not a trade-off.

Model, `(i,q)` and temperature are then tuned on the winner. The cheapest good outcome is
that this ends in a one-line settings change.

Every results row carries **N alongside any score**, plus cost and fit. A quality number
without its cost and its N cannot support a decision — the point is the frontier, not a
single best score.

---

## Open questions

**Blocking — resolve before round 1 starts**

| # | question | why it blocks |
|---|---|---|
| 1 | **htpc-01 sleeps.** `ttl: 900` unloads the model after 15 min idle and the sleep-inhibitor only holds while a model is resident | **Partly resolved 2026-08-02: accept and monitor.** During a *continuous* sweep llama-swap keeps a model resident (ttl 900 s ≫ the measured ~220 s per trial), so the stock `llama-swap.sh` inhibitor check reports busy throughout. The exposure is a **stall** longer than `ttl` + the inhibitor's 300 s grace. `preflight.py` now asserts `sleep-inhibitor` is active before a run; resume recovers if it does happen. Revisit only if a sweep is observed stalling |
| ~~13~~ | ~~**Is `search.snippets_only` the dominant correctness lever?**~~ | **Answered 2026-08-02 — it cannot currently be set, so it is not a lever we can pull.** It is a documented setting (`CONFIGURATION.md:605`, default `true`) and `config/search_config.py:96` reads it correctly — but `search_engine_factory.get_search` forwards it only for tinyfish/sofya/wikinews, and **`searxng` is in neither branch**, so the value is dropped one layer below where it was read. The engine falls back to `BaseSearchEngine`'s `True` and `search_engine_base.py:697` returns snippets before the crawler (which *is* built) runs. Verified by setting it to `False` through the real path and observing `True` on the engine. The arm was dropped from round 1. Full trace: [research/local-llm/bench/harness/results.md](../bench/harness/results.md) |
| **15** | **NEW — is `source-based` bad, or just under-resourced?** | It returned zero sources on 8/9 questions at its default (3 iterations × 1 realised question ≈ 3 searches), against ~40 for the focused variants. On the single question where it retrieved, it answered correctly. Until it is run at a comparable search budget, "source-based is worse" is not a supported claim — only "source-based at its default is unusable here" |
| **14** | **NEW — should we make LDR fetch page content at all?** | Unreachable today (see 13), so every measurement *and the deployment* is capped at ~200-char snippets, on a metric about misreading sources. The gap is localised and the fix is **one line** — add `searxng` to the per-engine forwarding branch in `get_search`. **Verified 2026-08-02**: constructing the engine directly with `search_snippets_only=False` does set the flag, so the value reaches it; only the factory fails to supply it. Options: patch locally, file upstream, or accept the ceiling. **Does not block round 1**, which measures the deployment as it actually behaves. NOT yet established: whether fetching materially improves correctness, or what it costs in peak prompt (it would reopen G0 in the *expensive* direction) |
| ~~2~~ | ~~**Does `sources` contain URLs, or objects/titles?**~~ | **Answered 2026-08-02: neither — they are dicts.** Keys `[category, engine, id, index, link, snippet, title]`. So `str(s)` (`run-matrix.py:154`, `export-for-grading.py:110`) writes a dict repr into the grading packet. Extract `link` + `title`, and keep `snippet` — it is the only record of what the model actually read under `snippets_only`. Captured in `research/local-llm/bench/harness/testdata/ldr-api.json` |
| ~~3~~ | ~~**`source-based` vs `source_based`**~~ | **Answered 2026-08-02.** The live settings enum has five hyphenated members: `source-based`, `focused-iteration`, `focused-iteration-standard`, `topic-organization`, `langgraph-agent`. `_init_search_system`'s own default is `source_based` (underscore) and both forms resolve — passing `"source-based"` was verified to construct `SourceBasedSearchStrategy`. Preflight now validates every strategy name against the live enum rather than against docs, which are stale (`harness-comparison.md:287-289`) |
| ~~4~~ | ~~The MTP `Q8_0` sha256~~ | **Closed 2026-08-01 — not a blocker and never was.** `sha256` was dead config: `hf download` uses `creates:`. The model is deployed |
| ~~5~~ | ~~**Does `quick_summary` accept a timeout?**~~ | **Answered 2026-08-02: no.** Its 12 named parameters carry none; the `timeout=300` that caused the confusion belongs to `LDRClient.quick_research`, a different function on a different access path. The bound must therefore be **external** — each trial runs as a subprocess under `timeout=`. Signature committed to `research/local-llm/bench/harness/testdata/ldr-api.json` |
| **12** | **NEW, blocking — is `questions_per_iteration` controllable at all?** | `iterations` is (via the snapshot). `q` never moved off 1 in any probe, but the probe query was too trivial to need more, so "ignored" and "the LLM generated one" are indistinguishable. The strategies read *different keys* — `source_based_strategy.py:210` reads `search.questions` (absent from defaults → hardcoded 3); `focused.py:87-89` uses the constructor value seeded from `search.questions_per_iteration`. Round 1 settles it on real queries. If `q` is not controllable, `calls = f(i,q)` collapses to `f(i)` |

**Expected to be answered by step 8 (model / MTP work)**

6. VRAM with `--spec-type draft-mtp` enabled — the draft path may need extra buffers, so the
   ~5.0 GB projection covers the baseline arm only.
7. Whether MTP interacts badly with `--reasoning-budget` — speculative decoding on a
   thinking model is not a combination we have evidence for either way.
8. Whether `--spec-type` passes cleanly through llama-swap's `cmd` templating.
9. Whether `llm.model: qwen3.5-9b` in the settings snapshot routes correctly — proven for
   gemma, untested for this id.

**Deferred, flagged so they are not surprises**

10. Whether the blind judge can grade 100+ items in one thread or needs batching — a context
    limit mid-grading would be discovered at the worst moment.
11. `gpu-mode` exclusivity means ComfyUI and gaming are unavailable for the duration of
    every phase.

---

## Out of scope

- Re-litigating G1. Onyx stays deployed as a comparison baseline; it is not being tuned.
- **Qwen3-14B** — kept configured, out of the model comparison. It is dense over 40 layers,
  costs ~88 MB per 1k of context, and caps near 48k on this card.
- Gemma's own inference settings — tuned over ~6 experiments, not re-opened, **except** the
  `-fa` decision, which is ROCm-specific and must be re-tested on Vulkan.
- Tuning `--spec-draft-n-max`. Step 8 measures MTP on/off at the documented `6`; tuning
  draft depth is a later knob at most, and only if MTP earns its place.
- Local-document RAG. There are no connectors and nothing is indexed.
