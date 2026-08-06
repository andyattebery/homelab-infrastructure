# Self-hosted web research

**Goal:** a self-hosted research assistant that answers questions from the live web —
search, crawl the results, synthesise a cited answer — running entirely on hardware
already owned.

**The question behind it:** is one 16 GB card enough (RX 9070 XT in htpc-01, or the
5060 Ti 16 GB in another machine), or is a second card earned? Everything here is
ultimately evidence for that decision.

**Start here, then go to [current-work.md](current-work.md)** for
what is being worked on and what state it is in. This file is the map; that one is the
work queue.

**Explicitly not the goal:** indexing local documents. There are no connectors and
nothing is in the index. Anything that only matters for local-document RAG — multipass
indexing, embedding quality, connector tuning — is out of scope, and mistaking that for
the goal has already cost real time.

---

## Architecture

**Two harnesses are deployed.** local-deep-research is the chosen one; Onyx stays up as
the comparison baseline. Both drive the same SearXNG and the same llama-swap.

```
        browser                                   browser
           │ https://local-deep-research.$DOMAIN     │ https://onyx.$DOMAIN
           ▼                                         ▼
  ┌──────────────────────── docker-01      ┌──────────────────── media-01 (24/7, Ubuntu)
  │  traefik ──► local-deep-research       │  traefik ──► onyx-nginx ──► onyx-web-server
  │              (search → crawl →         │                    └──────► onyx-api-server
  │               cited answer, fixed      │                             (agent loop)
  │               pipeline stages)         │  onyx-background · postgres · opensearch
  │                                        │  onyx-{inference,indexing}-model-server
  │  SearXNG  ◄────────────────────────────┤  onyx-code-interpreter
  │  (JSON API, no key)                    │
  └──────────┬─────────────────────────────┴──────────┬──────────────────────────────
             │ web search (both harnesses)            │ chat completions (both)
             ▼                                        ▼
        SearXNG on docker-01              htpc-01: llama-swap ──► llama-server
                                          (Caddy + TLS, RX 9070 XT 16 GB)
                                          gemma-4-12b-it · qwen3.5-9b · qwen3-14b
                                          (hot-swapped — never two at once)
```

**Why LDR:** Onyx makes "should I search?" a model decision, and a 12B model answers *no*
most of the time — three of seven queries made zero tool calls and one fabricated its
sources. LDR's `source-based` strategy searches as a pipeline stage. Full evidence:
[harness-comparison.md](harness-comparison.md).

**One Onyx research turn** is an agent loop, not a single call — this is the shape all the
token accounting below refers to:

```
S + Q                                 -> reasoning + tool_call(web_search)
S + Q + R₁ + tc₁ + W₁                 -> reasoning + tool_call(web_search)
S + Q + R₁ + tc₁ + W₁ + R₂ + tc₂ + W₂ -> reasoning + cited answer
```

Each iteration re-sends the whole conversation, so **crawled results (W) accumulate
inside a single turn**. That is the central constraint of this deployment, and it caused
failure #2 below. (Failure #1 was different — unbounded reasoning on an 11,173-token
prompt, where W was never the constraint.)

**Across turns, nothing accumulates** — and not because of truncation. Onyx replaces
every prior turn's tool result with the stub *"This tool call completed but the results
are no longer accessible"* (`chat_utils.py:645-651`, hardcoded to 20 tokens). Measured:
a follow-up on the 30,349-token Q7 turn started at **3,599 tokens**. Good for capacity —
the peak is one turn, never a session. The cost for research: **a follow-up cannot
re-read a page the previous turn already crawled**, so refining an answer forces a fresh
search against a different result set. Measured once: it re-searched and the corrected
answer was right, so this is a repeated-work cost rather than a correctness one.
Upstream behaviour; no knob here changes it.

Notable properties, all verified rather than assumed:

- **htpc-01 sleeps.** Onyx stays up; only generation fails while it is asleep. Wake is
  Wake-on-LAN (MAC from `ip link` on the host), ~12 s.
- **The GPU has three exclusive consumers** — ComfyUI, llama-server, gaming. They cannot
  share 16 GB. `gpu-mode` arbitrates; boot policy persists via a Quadlet `[Install]`
  drop-in.
- **Only one model loads per query.** Onyx resolves a single model id per conversation,
  so no ~10 GiB swap happens mid-query.
- **The A4000 on media-01 does almost nothing** for this workload. It exists to embed
  documents during indexing, and nothing is indexed.

---

## Current state

**Deployment: three hosts working.**

| | htpc-01 | docker-01 | media-01 |
|---|---|---|---|
| service | llama-swap (**Vulkan/RADV** since 2026-08-01), `gpu-mode llm`, ComfyUI stopped | **local-deep-research** + SearXNG + traefik | Onyx, 10 containers healthy |
| role | inference for both harnesses | **the chosen harness** | comparison baseline |
| models | gemma-4-12b-it (default) · qwen3.5-9b (`Q8_0`) · **gemma-4-26b-a4b** · qwen3-14b | — (model is a per-call argument) | — |
| context | gemma **65536** · qwen3.5-9b **65536** · gemma-4-26b-a4b **65536** · qwen3-14b **32768** | — | `max_input_tokens` 55296 / 22528, per model |
| key flags | `-fa 1`, `-np 1`, `--no-context-shift`, `--reasoning-budget 4096`, `ttl 900` | `programmatic_mode=True` needs no auth | `LLM_SOCKET_READ_TIMEOUT 300`, `GEN_AI_TEMPERATURE 1.0` |
| verified | suspend/resume, `pqup`, cross-host TLS, hot-swap, no VRAM thrashing, `hf` CLI downloads | healthy behind traefik; `source-based` searched 2/2 | GPU passthrough, seeding, SearXNG reachable |

Also on htpc-01: the **`hf` CLI 1.24.0** via Homebrew, token at
`/root/.cache/huggingface/token` (0600) — model downloads are authenticated and the
`--tags models` run is idempotent in ~13 s.

Onyx operator-completed: admin account, SearXNG web-search provider. The default
`Assistant` persona already has `web_search` + `open_url`. LDR credentials live at
`~/.config/ldr/claude-creds` and are only needed for the web UI — the programmatic API
bypasses auth entirely.

**Both failures are closed, and the hardware question is answered.**

| # | failure | limit hit | status |
|---|---|---|---|
| 1 | `EmptyLLMResponseError` — no text or tool calls | `-c`, via unbounded reasoning: one call decoded 17,534 tokens, `truncated = 1`, 472 s | **fixed** — `--reasoning-budget 4096`; did not recur in E1, including on the query that caused it |
| 2 | `ValueError: Not enough tokens … Required: 23572, Available: 19667` | Onyx's `max_input_tokens`, applied globally when only Qwen3 needed it | **fixed** — per-model: gemma 55296 |

**E1 is done (2026-07-31).** The seven-query set ran end to end, 21 agent calls,
**zero truncation**:

| term | measured |
|---|---|
| **S** system + tool schemas | ~1,430 tokens |
| **n** searches per turn | 0, 0, 0, 1, 2, 2, 4, 5 — median 2, max 5 |
| **W** tokens per search | **bimodal**: ~2,200 for a result set, **7k–20k for a page crawl** |
| peak turn | **25,316 prompt / 30,349 total** — 46% of `-c 65536` |
| worst-case VRAM | 12,815 MB used, **3,489 MB free** |

> ## One 16 GB card is enough — for Onyx's agent loop.
>
> The worst turn — crawling a 20,110-token page and writing a 5,033-token comparison
> table — used under half the deployed context. A second card would buy Qwen3 at a
> comparable context, or ComfyUI running concurrently; neither is a web-research
> capability gap.
>
> **This does not transfer to local-deep-research, and LDR is now the deployment.** The
> verdict is a property of *a harness*, not of the hardware: Onyx makes 1–6 calls per
> question, and LDR was observed making at least four on a single question. Peak prompt
> and `truncated` are **unmeasured** for it. More importantly the binding constraint
> changes — a many-call pipeline is limited by *generation throughput*, not context — so
> the question G0 asks is reopened rather than settled. Tracked as G0 in
> [current-work.md](current-work.md).

---

## The defect that drove the harness switch

Capacity is solved; **grounding is not.** Verified against the chat transcripts, three of
seven queries made **zero tool calls** — and the one that asked *"Cite your sources"*
(ZFS vs btrfs) answered from model weights and then **fabricated a four-entry "Sources:"
list**: plausible titles, no URLs, nothing fetched. Onyx recorded zero citations for it.

That is precisely the failure this deployment exists to prevent, and it is worse than a
missing search because it presents as sourced. It reproduces **on demand** — 3 of 3 API
runs of the ZFS question made zero tool calls.

## The four questions — all closed

These were the operator's framing while Onyx was the deployment. **All four are now
answered**, and together they are why the work moved to local-deep-research. Kept because
each was expensive to establish and the evidence should not have to be re-derived.

**Live work is not here** — it is [current-work.md](current-work.md).

### 1. Can Onyx be changed to fix the non-searching behaviour? — **NO**

**Answered: no, not structurally.** Every lever was tried; none forces a search. That is
what made the harness switch necessary rather than optional.

| lever | status |
|---|---|
| `tool_choice: required` (via `forced_tool_id`) | **Worse than useless.** llama-server returns an empty streaming delta ~2 s in; Onyx logs `LLM packet is empty … Skipping` and the request hangs until the client gives up |
| `forced_tool_id` from the UI | Does not exist — API-only field |
| **`GEN_AI_TEMPERATURE`** | **Was 0, now 1.0. Explains the *consistency*, does not fix the defect** — measured below |
| Deep Research mode | Untested. `dr_loop.py:518` uses `REQUIRED`, so it may hit the same empty-packet problem |
| Persona instructions | Untested. Exhortation, not structural |
| `allowed_tool_ids` (drop the internal `SearchTool` on an empty index) | Untested cleanly |
| **Detection** — flag any assistant message with 0 tool calls | The only *structural* option, and it catches the failure after the fact rather than preventing it |

**Measured: temperature changes the failure's shape, not its rate enough to matter.**
Same ZFS question, repeated:

| condition | runs | searched | note |
|---|---|---|---|
| `temperature: 0` (greedy — as deployed since day one) | 3 | **0** | Failed *identically* every time; the branch could not vary |
| `temperature: 1.0` | 4 | **1** | The one that searched made 2 tool calls and returned 11 citations |

So greedy decoding explains why the defect was perfectly reproducible, and raising
temperature restores variance — but a **25% search rate is unusable**, and with n=4 the
rate itself is noisy. The capability is intact (the searching run produced a good, cited
6,882-char answer); **the model's decision to search is what fails.** Keep
`GEN_AI_TEMPERATURE: 1.0` because greedy was wrong on its own terms, but do not count it
as the fix.

### 2. Is there a better application or harness? — **YES: local-deep-research**

**Answered, and it is deployed.** The selection criterion came from the forcing test
below: *does the harness treat search as a pipeline stage rather than a model decision?*
LDR's `source-based` strategy does. Measured on the question Onyx fabricated sources for,
it searched **2/2** with 17–18 sources and inline per-claim citations, at roughly 6× the
wall time. Full comparison and its caveats: [harness-comparison.md](harness-comparison.md).

Two things that decision did **not** settle, both now live work: LDR's own capacity (it
issues far more calls per question, so "one 16 GB card is enough" must be re-derived for
it), and which model and settings it should run — see
[current-work.md](current-work.md).

**Can a model be made to search reliably? Yes — but only by constrained decoding.**
Tested directly against llama-swap with the real `web_search` schema, on the same ZFS
question that fails through Onyx:

| mechanism | tool call emitted? |
|---|---|
| no `tool_choice` | no |
| `tool_choice: "required"` (OpenAI string, what Onyx/litellm sends) | no — and burned all 4,000 tokens, `finish=length` |
| `tool_choice: {"type":"any"}` (a shape llama.cpp's own README lists) | no |
| `tool_choice: {"type":"tool","name":"web_search"}` | no |
| **`response_format: {"type":"json_schema", …}`** | **yes — 5 well-formed queries, 100% compliant** |

`tool_choice` is a *request* the model may decline, and this llama.cpp build does not
enforce it in any documented shape. Constrained decoding is **decoder-level** — logits
outside the grammar are masked, so prose is not an available output. It is the only
structural mechanism, and it already works on the deployed model.

It constrains *shape*, not *judgment*: forcing a search on every turn would make Q5
("explain flash attention") search too, which was correctly answered from weights. The
right pattern is a **constrained decision step** — a forced yes/no on "does this need
current information?" — or search as a fixed first stage.

So the question to ask of any alternative:

- Does it drive llama.cpp's `grammar` / `json_schema` directly, instead of delegating to
  the model's tool-call judgment?
- Is it a **pipeline** (search → crawl → answer as fixed stages) rather than an **agent**
  that decides whether to search?

**Onyx is an agent that delegates the decision, and cannot force it** — it sends
OpenAI-style `tool_choice` through litellm, which is ignored end to end.

### 3. Are llama-swap and the OpenAI-compatible API limiting parameters? — **NO, the reverse**

**Answered — it runs the other way.** Onyx *overrides* the model's sampler.

`GEN_AI_TEMPERATURE` defaults to 0 (`configs/model_configs.py:92`) and was unset, and a
request parameter beats llama-server's command line. Verified directly: with no
`temperature` in the request the same prompt returned a different word list each time;
with `"temperature": 0` it returned byte-identical output twice — and the same question
asked twice **through Onyx** was byte-identical.

So llama-swap's `--temp 1.0 --top-p 0.95 --top-k 64` was **dead config for every Onyx
query** and the model ran greedy. Fixed by setting `GEN_AI_TEMPERATURE: 1.0` in the Onyx
role, matching what llama-swap already passes. Nothing was limiting the model *downward*
in the llama-swap direction — the sampler simply never arrived.

### 4. Are there better models — MoE, or larger? — **the question that stayed open**

**This is the one that can reopen the hardware verdict**, and it is now tracked rather than
speculated about. The verdict above is conditional on Gemma 4 12B at `-c 65536` fitting in
16 GB. Two candidates are queued:

- **`qwen3.5-9b`** — deployed, measured at 10,371 MB used / 5,933 MB free at `-c 65536`.
  2.4 GB more headroom than Gemma, and the only candidate with a published figure in the
  LDR harness. Not yet tuned or compared.
- **Gemma 4 26B-A4B** — an MoE activating **3.8B of 25.2B**, with low-bit quants at
  12.9–13.6 GB. At a 98% generation share this is potentially a larger lever than any
  parameter, and it contradicts the earlier belief that MoE is what 16 GB blocks.

Also queued: a **backend A/B** (llama.cpp Vulkan vs ROCm), because generation throughput —
not context — is the binding constraint for a many-call pipeline, and the engine was
inherited rather than chosen.

All three, with order and status: [current-work.md](current-work.md).

E3 (reduce W) is an efficiency item only; E4 (context ceiling) is dropped.

**Known-open, not blocking:** `kohya-ss` crash-looping on media-01 (3,400 restarts since
2026-07-27, unrelated); `internal_search` still on the `Assistant` persona despite an
empty index; reboot persistence on htpc-01 untested because it drops the gaming session.

---

## Documents

**Five docs, one job each.** The split is deliberate: this set previously had two docs each
claiming to be "the working document", and two asserting opposite metrics.

| doc | its one job | read it when |
|---|---|---|
| **README.md** *(this file)* | **Index + goal.** Architecture, deployed state, the closed questions. Carries no detail | you are new, or you forgot what this is |
| **[current-work.md](current-work.md)** | **What is in flight.** Execution order, decisions taken, and per-step **status**. Turns over as work completes | you are deciding what to do next |
| **[llm-tuning.md](llm-tuning.md)** | **Inference layer.** llama-swap, `-c`, VRAM, samplers, `gpu-mode`, and every measurement behind them. Its Onyx experiments E1–E5 are history | you are changing a flag, a model, or a context size |
| **[harness-comparison.md](harness-comparison.md)** | **Decision record, frozen 2026-07-31.** Why LDR over Onyx. Its metric — *search rate* — is scoped to that decision and superseded | you want to know why Onyx was abandoned |
| **[ldr-tuning-methodology.md](ldr-tuning-methodology.md)** | **Method.** What each phase varies, how many points it needs, how correctness is graded, why the runner must be resumable | you are about to run or grade a phase |

Order and status live in current-work.md; *how to measure* lives in the methodology. If you find
both describing the same thing, that split has broken.

Supporting material:

| | |
|---|---|
| [research/local-llm/bench/queries.md](../bench/queries.md) | The fixed seven-query set and the run protocol. Shared across harnesses |
| [research/local-llm/bench/harness/README.md](../bench/harness/README.md) | The LDR runner — how to drive it, resume it, and grade its output |
| [research/local-llm/bench/llama-swap/README.md](../bench/llama-swap/README.md) | Inference benchmark harness, and the traps it guards against |
| [research/local-llm/bench/llama-swap/results.md](../bench/llama-swap/results.md) | Every inference measurement, with the build commit each belongs to |
| [research/local-llm/bench/harness/results.md](../bench/harness/results.md) | Harness comparison results |

History — accurate as of their dates, **not corrected as things changed**.
These are local working notes under `handoffs/`, which is gitignored, so they are not
in this repository; the summaries below are what carried forward:

| | |
|---|---|
| `onyx-llama-swap-status.md` | Deployment history, the compose rework and why, failure modes for a redeploy |
| `llamacpp-gemma4-htpc01-spec.md` | Original spec. Several claims since disproved — see llm-tuning.md's corrections |
| `llama-swap-htpc-01-followup.md` | Review of the first tuning pass |
| `llama-swap-htpc-01-preonyx-validation.md` | Pre-Onyx validation. Its `-ub` and FA items are settled; its instrumentation advice mostly holds |
| `vulkan-backend-evaluation.md` | The Vulkan-vs-ROCm argument. Its reasoning is carried forward into current-work.md; its ordering advice is superseded |

Config lives in
[playbook-htpc-01.yaml](../../../ansible/playbook-htpc-01.yaml) (llama-swap, gpu-mode),
[docker_compose_local_deep_research](../../../ansible/roles/docker_compose_local_deep_research/)
(LDR) and [docker_compose_onyx](../../../ansible/roles/docker_compose_onyx/) (Onyx,
`max_input_tokens`).

---

## Working rules for this project

Each of these was learned by breaking it.

- **Docs before source.** llama-swap's README documents `/ui`, `/metrics` and the log
  endpoints; Onyx's docs give the admin UI paths. Source is for when docs are silent or
  provably stale — not the first move.
- **Read before you mutate.** These are production hosts; a mutation is not an
  experiment and there is no cheap undo.
- **Never write to the database.** Every setting has a UI or an API. If one appears not
  to, stop and ask — that is a signal, not a reason to reach for `psql`.
- **Query-level or it didn't happen.** Per-request success proves nothing: the query
  that failed returned HTTP 200 on every call.
- **A guard that errors must stop the run.** A pre-flight check that fails and lets the
  script continue is worse than no check at all.
