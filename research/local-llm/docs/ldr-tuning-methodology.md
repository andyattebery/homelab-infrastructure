# Tuning local-deep-research for this deployment

How to find, per model, the LDR settings that maximise **answer correctness** at tolerable
speed on one 16 GB card.

**This doc is *method*, not sequencing.** For what runs next, what it depends on, and what
state each phase is in, read [current-work.md](current-work.md).

Start of the doc set: [README.md](README.md). Why LDR was chosen, and how to reach its
API: [harness-comparison.md](harness-comparison.md). Runner and results:
[research/local-llm/bench/harness/](../bench/harness/README.md).

## The goal, stated precisely

**Correctness of the information is the quality metric.** Real citations are necessary but
not sufficient — a model can cite a genuine page and still state a wrong number, misread
the source, or attribute a claim to the wrong place. "It searched" and "the URLs resolve"
are hygiene checks, not the target.

That has a consequence that shapes everything below: **correctness needs ground truth**,
and most of our seven queries do not have any. So the tuning set and the regression set are
different things and are graded differently.

Search rate is *not* a metric here. `source-based` searches by construction — measuring it
would be measuring a tautology. That question belonged to Onyx, where searching was a
decision the model made and got wrong.

## Variables

**Tuned** (all are per-call arguments to `quick_summary`, so nothing depends on global
state — see harness-comparison.md):

| knob | speed effect | quality effect |
|---|---|---|
| `iterations` × `questions_per_iteration` | **dominant** — multiplies LLM calls | coverage |
| `search_strategy` | different call pattern | `source-based` cites per claim; `focused-iteration` refines |
| `temperature` | none | determinism vs exploration |
| `search.max_results` / `max_filtered_results` | prompt size | recall |
| `search.snippets_only`, `search.fetch.mode` | tokens per result | evidence depth |

**Held constant:** the SearXNG instance, the query set, and `-c 65536`.

**Quant tier is deliberately *not* held constant.** Both models started at `Q6_K_XL` so a
comparison would not be confounded by quantisation — but that is a *comparison* argument,
not a quality one, and the metric here is factual correctness. qwen3.5-9b moves to `Q8_0`
(from the MTP repo) because it has 5,933 MB free to spend on precision and Gemma does not.
**Each model competes at its best rather than at a matched handicap**; the trade-off is
that a model delta and a quant delta can no longer be separated, which is accepted. See
[current-work.md](current-work.md) → Part 0 step 2.

**Model is a variable, not a constant:** `gemma-4-12b-it` (incumbent) vs `qwen3.5-9b`
(10,371 MB used / 5,933 MB free at 65k — 2.4 GB more headroom, and the only one with a
published SimpleQA figure in this harness). A third candidate, the **Gemma 4 26B-A4B**
MoE, may enter before Phase 1 — see [current-work.md](current-work.md).

**Constraint, not a trade-off:** peak prompt must fit `-c 65536` with no `truncated = 1`.
A config that scores well but truncates is a failure, not a point on the frontier.

## How to judge correctness — four options

| option | validity | cost | scales? |
|---|---|---|---|
| **A. SimpleQA-style ground truth** | high for factual recall | very low — exact/semantic match | yes |
| **B. External LLM judge** | high, incl. long-form | API spend per grade | yes |
| **C. Local model as judge** | **low** | free | yes |
| **D. Operator rubric** | highest | your time | no |

**A is the primary.** LDR ships `examples/benchmarks/run_simpleqa.py`; questions have known
short answers, so grading is mechanical, repeatable, and directly comparable to upstream's
published numbers (Qwen3.5-9B 91.2%). It measures exactly the failure mode we care about —
stating things that are not true — and it is cheap enough to run across a parameter sweep.

**B for the long-form case, but not via upstream's script.** SimpleQA cannot score "is this
ZFS-vs-btrfs comparison correct and well-sourced". LDR ships
`examples/benchmarks/claude_grading/`, but its README requires *"a valid Claude API key
stored in the local database"* — paid API access, and it grades from the model's own
memory.

**Use a fresh Claude Code thread instead.** It costs nothing extra, and it is *better* for
this metric: it can **web-search each factual claim**, which is what "is the information
correct" actually requires. Several of these questions concern software versions and
hardware specs where any model's training data may be stale — grading from memory would
reproduce the exact failure being measured.

Two requirements make it trustworthy rather than theatre:

- **Blind it.** [research/local-llm/bench/harness/export-for-grading.py](../bench/harness/export-for-grading.py)
  writes one answer per file under an opaque `tid`, with the model and parameters held
  back in `KEY.json`. A judge that can see `qwen3.5-9b` next to an answer anchors on it.
- **Persist the source URLs, not just a count.** `sourced` is unGradable otherwise — the
  judge has to check that cited pages exist and support the claim, which is precisely how
  the earlier fabricated source list would have been caught.

**C is rejected as a primary.** Grading a 12B model's output with that same 12B model
measures agreement, not truth, and shares its blind spots. Acceptable only as a cheap
pre-filter to discard obviously broken configs before spending A or B on them.

**D is the tiebreaker.** Reserve for the handful of finalist configs where A and B
disagree, or for the long-form answers where you are the actual customer.

Upstream's own caveat applies to A and B both: *"small samples, LLM-grader noise, and
SimpleQA contamination risk on newer base models."* Report N alongside every score.

## How each phase is measured

> **This doc owns *method*: what a phase varies, how many points it needs, how it is
> graded, and what a valid row looks like.** It does **not** own ordering, dependencies or
> status — those live in [current-work.md](current-work.md), which is
> the tracker. If you want to know *what runs next*, read that; if you want to know *how to
> run it*, read this.

The binding constraint is time: **~6–8 minutes per query** at `iterations=1,
questions_per_iteration=2` on Gemma, ~2 min per LLM call. A naive grid is tens of hours and
monopolises the GPU (`gpu-mode` is exclusive, and htpc-01 sleeps).

**Phase 0 — cost model. No grading.** Vary `iterations × questions_per_iteration` on one
fixed query, per model. Derive `calls ≈ f(i, q)` and tokens/call, and record peak prompt.
This *predicts* every config's cost, so later phases only grade configs that are affordable
and that fit `-c`.

**It is a fit, not a grid.** Cost is near-deterministic — `calls ≈ i × q + overhead` — so
it needs *fitting*:

| measurement | points | why |
|---|---|---|
| `calls = f(i, q)` per model | **4** — `(1,1) (1,3) (3,1) (2,2)` | Three establish whether it is separable and linear; the fourth checks the fit predicts an interior point. Add points only if the residual is large |
| **MTP speed delta** | **2** — one config, spec on vs off | Speculative decoding is distribution-preserving, so it changes *speed only*, and a ratio does not need re-measuring at every grid point |
| reasoning length, KV size, `truncated` | free | fall out of the runs above |

**≈10 trials, ~1–1.5 h**, against 27 for the full cross-product — for the same information.
If MTP proves lossless, every later quality run is MTP-on only; there is no second arm to
carry.

**Phase 1 — model shootout at one fixed config.** Both models, identical settings, SimpleQA
subset. Answers "does model choice matter here at all" before any effort is spent tuning
the wrong model. ~1–2 h.

**Phase 2 — tune the winner.** Sweep only the knobs Phase 0 showed are expensive *and*
Phase 1 suggests matter. Grade with A. **Temperature is excluded** — `evaluate_simpleqa`
cannot set it.

**Also not a grid.** Quality against search effort is expected to **saturate**, which makes
this a 1-D walk along "total searches" rather than a 2-D enumeration of `(i, q)`: step
outward until the score stops improving, then stop. A grid spends most of its budget past
the knee. If it turns out non-monotonic, LDR ships **Optuna** (`examples/optimization/`),
which does TPE sampling over exactly this space — but only then, since its default 30
trials is hours at this per-trial cost. Size it from Phase 0, not in advance.

**Phase 3 — confirm.** Best config against the full seven-query set plus the long-form
grader (B), and re-check the `-c` constraint. ~1 h plus judging.

## Resumability is a requirement, not a nicety

Runs are hours long, the GPU host sleeps, and a laptop closing should not cost a night of
compute. The runner therefore:

- writes **one JSONL line per completed trial, immediately** (`flush=True`) — never
  buffering results until the end
- keys each trial by `(model, strategy, iterations, questions, temperature, query_id)`
- on start, **reads existing results and skips completed keys**
- is safe to kill and re-invoke with the same arguments

That makes the natural failure modes — timeout, sleep, Ctrl-C, a dropped ssh — cost one
trial rather than the whole run. `examples/benchmarks/run_resumable_parallel_benchmark.py`
upstream does the same thing; ours is smaller because it only has to drive one host.

## Reporting

Every row records model, all tuned parameters, the metric **and its N**, wall time, calls,
peak prompt, and whether anything truncated. A quality number without its cost and its N is
not usable for a decision — the entire point is the frontier, not a single best score.
