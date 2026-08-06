# Harness comparison results

Append rows; do not re-derive them next session. Methodology and the measurement
recipes live in [../docs/harness-comparison.md](../../docs/harness-comparison.md);
the input is [../queries.md](../queries.md).

**A row is only comparable to another row with the same model, the same SearXNG, and
the same query.** The metric is whether the harness searched at all.

## Part 1 — SearXNG full-content patch: DEPLOYED AND VERIFIED (2026-08-02)

The bug recorded under *"The evidence-depth arm is a no-op"* below is now fixed by a
`sitecustomize.py` wrapper shipped into the container
(`ansible/roles/docker_compose_local_deep_research/files/patches/`, guarded by
`test_patch.py`). Deployed with `--tags ldr`, `changed=5`, `failed=0`.

Measured at the ENGINE layer — one query, both arms, same process. Not a trial: the LLM is
not part of this claim, and measuring here removes it as a confound.

| arm | engine built | sources | median evidence per source | engine wall |
|---|---|---|---|---|
| `snippets_only=True` | `SearXNGSearchEngine` | 20 | 245 chars | **4.1 s** |
| `snippets_only=False` | `FullSearchResults` → `SearXNGSearchEngine` | 8 | **4192 chars** | **108.4 s** |

Full-content source lengths: `[0, 0, 2538, 4073, 4311, 4521, 4931, 7744]` — 6 of 8 fetched.
The drop from 20 sources to 8 is upstream's LLM URL-quality filter
(`full_search.py check_urls`, active because `QUALITY_CHECK_DDG_URLS` is true), not the patch.

**The 26× wall-clock cost is per SEARCH, not per trial**, and focused-iteration issues ~40
searches per trial. Round 2's grid must be sized from this number; guessing cost is what made
round 1's estimate 3× wrong.

Verification, all five checks: `[ldr-patch] applied:` in the container log; the wrapper built
only via the real path (`config/search_config.get_search`, not the factory's same-named
function); the gate above; `snippets_only=True` still yielding a bare engine so the setting is
respected rather than overridden; and +6 ms (21 → 27 ms) on a python process that never
imports LDR, against the 6,128 ms that importing the factory costs — which is why the hook is
lazy.

### Two harness defects this exposed

- **`extract_sources` was discarding the fetched text.** `base_citation_handler.py:157` builds
  the model's evidence as `result.get("full_content", result.get("snippet", ""))`, so under the
  full arm `full_content` *is* what the model read — and the harness kept only
  `link/title/snippet/engine`. Both arms would have recorded identically. Now records
  `full_content_chars` plus a 400-char audit head.
- **Storing it verbatim would have broken blinding.** 4000-char extracts in one arm against
  245-char snippets in the other identifies the arm with no configuration string present. The
  length and head therefore stay in the record and never enter a packet; `test_export.py`
  asserts both directions.

## SearXNG has only four working web engines, and they were all suspended (2026-08-02)

Found while verifying the above; **it changes how earlier zero-source rows should be read.**
Asked directly of SearXNG's JSON API from inside the LDR container:

```
brave      : too many requests        startpage  : Suspended: CAPTCHA
google cse : too many requests        duckduckgo : timeout (ConnectTimeout, html.duckduckgo.com)
```

`/config` reports 274 engines, of which **10 are enabled in `general` and only those four
search the web** — the rest are `currency`, `dictzone`, `lingva`, `mymemory translated`,
`wikidata`, `wikipedia`. Our own limiter is off (`settings.yml.j2:5`), so this is entirely
upstream throttling. With all four suspended the assistant returns **zero sources while every
trial still completes successfully** — indistinguishable, in the recorded data, from a strategy
that simply retrieves badly.

This does not explain round 1 on its own: the ~40-search arm had *fewer* zero-source trials
than the ~3-search arm, which is backwards for a rate-limit story. But it cannot be excluded
as a contributor, and it will corrupt any long sweep.

`preflight.py` now refuses to start a sweep when zero engines respond
(`parse_search_health`), verified against both the live outage and the verbatim response above.
Round 1 had no such gate.

## Round 1 — strategy comparison, STOPPED EARLY at 29/60 (2026-08-02)

3 strategies × SimpleQA (`seed=42`), gemma-4-12b-it, snippets-only, each strategy at its own
default `(iterations, questions)`. **Stopped deliberately at 9 complete question-cycles**: the
two things this round could settle were settled, and the one it could not settle would not
have been settled by finishing. Resumable — the 29 rows stand and `sweep.py --n 20` would
continue from here.

(29, not 28: one trial was already in flight when the sweep was stopped and completed
normally. Its cycle is incomplete, so the per-question table below still covers 9 cycles,
and zero-source rates are quoted over complete cycles only.)

| cell | n | proxy correct (95% CI) | med wall | med calls | zero-source | issues |
|---|---|---|---|---|---|---|
| focused-iteration | 10 | 4/10 = 43 ± 26% | 499 s | 10 | 2/9 (22%) | 2 |
| focused-iteration-standard | 9 | 3/9 = 38 ± 26% | 464 s | 9 | 3/9 (33%) | 4 |
| source-based | 10 | 1/10 = 21 ± 19% | **115 s** | 3 | **8/9 (89%)** | 10 |

`proxy correct` is a substring match against ground truth and **undercounts** — not a grade.
No trial failed; no trial truncated; every trial had a capture region.

### The finding: source-based retrieves almost nothing at its default settings

Sources retrieved, per question, complete cycles only:

| q | source-based | focused-iteration | focused-iteration-standard |
|---|---|---|---|
| 0000 | 8 | 41 | 104 |
| 0001 | 0 | 1 | 0 |
| 0002 | 0 | 1 | 0 |
| 0003 | 0 | 10 | 1 |
| 0004 | 0 | 2 | 5 |
| 0005 | 0 | 0 | 41 |
| 0006 | 0 | 42 | 22 |
| 0007 | 0 | 3 | 1 |
| 0008 | 0 | 0 | 0 |

**`source-based` returned zero sources on 8 of 9 questions.** Its low score is a *retrieval*
failure, not an answering one: on the single question where it found sources it answered
correctly (1/1). The others are "found nothing, declined to answer" — the correct behaviour,
and useless. Zero-source is close to binary and paired across identical questions, so 8/9
against 2/9 is a real difference, unlike the accuracy column.

> ### ⚠ Confounded with search budget — this does NOT show source-based is a worse algorithm
>
> Each strategy ran at its own default, so they did very different amounts of searching:
> source-based ≈ **3 searches** per trial (3 iterations × 1 realised question), focused
> variants ≈ **40** (8 × 5). Focused makes roughly **13× more retrieval attempts**, so finding
> sources more often is close to expected from budget alone. The wall-clock gap (115 s vs
> ~470 s) is the same confound, not independent evidence.
>
> Per-strategy defaults were chosen so neither ran at a value tuned for the other — but that
> trade means **round 1 cannot separate "better algorithm" from "better resourced."** Fixing
> this is the reason the round was stopped rather than finished.

### What is and is not supported

**Supported:** `source-based` **at its default configuration** is unusable on this question
set — 89% of questions produce no evidence at all. Whether raising its iterations fixes that
is untested and is the obvious next experiment.

**Not supported:** any ranking of `focused-iteration` vs `focused-iteration-standard`
(43±26% vs 38±26%, heavily overlapping — separating a gap this small needs ~200/config per
`BENCHMARKING.md`), or any claim about intrinsic strategy quality independent of budget.

**Also observed:** one genuinely dead question (`simpleqa-s42-0008`, zero sources in every
cell) — that one measures SearXNG. Peak prompt across all trials was **8,708 of 65,536 (13%)**,
consistent with the snippets-only ceiling.

## Smoke test — instrument validation + two gates (2026-08-02)

Six trials: **one** SimpleQA question (`simpleqa-s42-0000`, "At which university did Jurgen
Aschoff study medicine?", ground truth *University of Bonn*) across 3 strategies × 2 nominal
evidence depths, gemma-4-12b-it, Vulkan. **n=1 — nothing here is an accuracy result.** Its
job was to validate the chain and settle two gates before spending a pilot.

| cell | wall | sources | median source chars | peak total | answer correct |
|---|---|---|---|---|---|
| source-based / snippets | 198 s | 5 | 342 | 5,833 | yes |
| source-based / "full" | 235 s | 7 | 206 | 6,655 | yes |
| focused-iteration / snippets | 600 s | 214 | 161 | 13,393 | yes |
| focused-iteration / "full" | 416 s | 100 | 194 | 7,123 | yes |
| focused-iteration-standard / snippets | 316 s | 1 | 35 | 2,292 | **no** |
| focused-iteration-standard / "full" | 394 s | 31 | 240 | 3,756 | yes |

**Gate — configured `iterations` takes effect. PASS.** source-based asked 3 and ran 3;
focused-iteration asked 8 and ran 8. Two different values, two different behaviours, through
the settings snapshot. This was the blocker for the whole campaign.

**`questions_per_iteration` is controllable — but only on focused-iteration.** It asked 5 and
issued exactly 5 on every one of its 8 iterations (`focused_iteration_strategy.py:227` trims
to the cap). `source-based` asked 3 and issued **1** every iteration: the key is read, the
model simply under-fills. So `calls = f(i,q)` is fittable for focused-iteration and collapses
to `f(i)` for source-based.

**Cost, measured.** ~200 s per source-based trial against **400–600 s** for focused-iteration
at its own (8,5) default. A 3-strategy pilot at n=20 is therefore **~6 h**, not the ~2 h
estimated by pricing every cell at source-based's rate.

### The evidence-depth arm is a no-op, and the mechanism is not what was previously recorded

> **FIXED 2026-08-02 — see *Part 1* at the top.** Everything below is the diagnosis and stands
> as written; the arm is no longer a no-op. Two claims in it were superseded by measurement:
> the fix was *not* "one line in `get_search`" (that function is not the one the research path
> calls with a usable hook, and four other callers must not be widened), and the last paragraph's
> open questions on cost and crawl success are now partly answered — the crawl does succeed, at
> 26× the wall clock per search.

The two "depth" arms returned **snippet-sized source text in every cell** (35–400 characters;
a fetched page is thousands), and the first source of the source-based pair was byte-identical
across arms. Setting `search.snippets_only` changes nothing.

It is a **documented, first-class setting** (`docs/CONFIGURATION.md:605`, env
`LDR_SEARCH_SNIPPETS_ONLY`, default `true`), and the intended wiring exists — it just stops
one layer short. Traced end to end at v1.10.0:

1. `config/search_config.py:96-97` **does** read it from the snapshot
   (`get_setting_from_snapshot("search.snippets_only", …)`) and passes
   `search_snippets_only=` down to the factory. This is the `get_search` that
   `api/research_functions.py` actually imports — verified by resolving the symbol, not by
   assuming. So far, correct.
2. `search_engine_factory.py:get_search` then forwards that value into the engine's params
   **only for `tinyfish`, `sofya`, `wikinews`** — and as `use_full_search` for
   `duckduckgo/serpapi/google_pse/brave/mojeek`. **`searxng` appears in neither branch**, so
   the value is silently dropped one layer below where it was correctly read.
3. `SearXNGSearchEngine.__init__` never receives it — it has no such parameter, though it
   does `**kwargs` into `super()`, commented *"Pass through all other kwargs including
   search_snippets_only"*, so it **would** accept one. It falls through to
   `BaseSearchEngine`'s default: **`True`**.
4. `search_engine_base.py:697` short-circuits on that flag and returns snippets. The crawler
   **is** initialised — `include_full_content` is `True` (per
   `search.engine.web.searxng.default_params.include_full_content`, documented default
   `true`) and `full_search` exists on the engine — it is simply never reached.

**Measured through the real path**: with `search.snippets_only` set to `False` in the
snapshot, the constructed engine still reports `search_snippets_only = True`. The setting is
read and then discarded.

So this is a **localised upstream bug, and the fix is one line**: add `searxng` to the
per-engine forwarding branch in `get_search`. The engine already wants full content
(`include_full_content=True`) and already has the crawler built.

**Verified without patching anything**: constructing `SearXNGSearchEngine` directly with
`search_snippets_only=False` yields `engine.search_snippets_only == False`, so the value does
reach the engine through its `**kwargs` → `super()` passthrough. The only thing missing is the
factory supplying it.

**Not established, and deliberately not assumed:** whether fetching full content actually
improves correctness, what it costs in peak prompt (it would reopen G0 in the *expensive*
direction — Onyx's peak came from exactly this), and whether the crawl path succeeds end to
end under the egress policy. Those need a measurement, not a code read.

> **Two corrections, both mine, recorded so the reasoning is auditable.**
>
> 1. The G0 note below says `search_snippets_only` "wins outright over
>    `include_full_content`". True as far as it goes — `:697` does short-circuit — but it
>    implies the two flags are a deliberate precedence pair. They are not: one is
>    configuration that never arrives, the other a base-class default.
> 2. I first wrote that the key is **never read**. **Wrong** — `config/search_config.py:96`
>    reads it correctly. I had tested `search_engine_factory.get_search` directly, which is
>    *not* the function `research_functions` imports; the real one is the
>    `config/search_config.py` wrapper. Testing the wrong function produced a confident and
>    incorrect mechanism. The conclusion (no page content is fetched) was unaffected, because
>    it rests on the measured source text, not on the mechanism.
>
> The lesson worth keeping: **resolve the symbol before reasoning about the call.**
> `inspect.getsourcefile(rf.get_search)` would have settled it in one line, and two
> same-named functions in one package is exactly the shape that hides this.

Consequence: round 1 dropped from a 3×2 grid to **3×1** (`shootout.py`, `DEPTHS`), and the
arm is retained in code so it can be restored if the fetch path becomes reachable.

## End-to-end check on Vulkan (2026-08-01) — "Phase B"

**One real LDR trial, with llama-swap's upstream log captured.** Q1, `source-based`,
gemma-4-12b-it, on the newly deployed Vulkan backend. This is the query-level check the
backend A/B could not make
([`../llama-swap/results.md`](../llama-swap/results.md) measured synthetic single calls).

> ### ⚠ The configuration label on this row was wrong, and is corrected here (2026-08-02)
>
> It was recorded as `iterations=1, questions_per_iteration=2`. **It did not run at that.**
> Those were passed as keyword arguments to `quick_summary`, and keyword arguments for these
> two parameters **do nothing** — `AdvancedSearchSystem` is built without them, resolves
> `search.iterations` from the settings snapshot instead, and hands *that* to the strategy;
> the kwargs are then assigned to an attribute nothing re-reads
> (`api/research_functions.py:137-147` then `:154-156`; `search_system.py:148-166`, `:235-236`,
> LDR v1.10.0). Measured end-to-end four times across two strategies: asking for `i=2`
> returns `3`, the snapshot default.
>
> So this trial ran at the snapshot's **`search.iterations = 3`**, not 1. The realised
> questions-per-iteration is **unknown** — see the open question below. Treat the
> configuration as **unverified and not reproducible**; the *measurements* below stand,
> because they are what the GPU actually did.
>
> To set these, put them in the settings snapshot, not in kwargs. See
> [`capture_fixtures.py`](capture_fixtures.py) and `testdata/ldr-api.json`, which record the
> control matrix and fail if upstream fixes the bug.

| | measured |
|---|---|
| **generation** | **44.13 tok/s** (median over 5 calls, 44.0–45.8) |
| calls | **5** for one trial at `search.iterations = 3` (see the correction above) |
| peak prompt | **3,131** tokens |
| peak total | **5,912** tokens |
| prompt / decoded, whole trial | 9,572 / 8,509 |
| truncated | **0** |
| wall clock | 220.9 s, 14 sources |

**The backend decision holds at query level.** 44.13 tok/s on real multi-call traffic
against E1's ROCm-era **~38 tok/s** — about **+16%**, slightly better than the +10.3%
measured synthetically, and in the same direction. Wall clock is *not* the comparison: at
n=1 against the 374–450 s spread recorded below it would prove nothing.

**LDR's measured capacity is far smaller than Onyx's — but the comparison is not
like-for-like, and G0 is NOT settled by it.**

| harness | calls per question | peak prompt / total | fetched page content? |
|---|---|---|---|
| Onyx | 1–6 | 25,316 / 30,349 | **yes** — peak set by one 20,110-token crawl |
| local-deep-research | **5** | **3,131 / 5,912** | **no** — `search.snippets_only = True` |

> ### ⚠ This row was over-read, and the correction matters more than the number (2026-08-02)
>
> It previously concluded that "LDR issues more, *smaller* calls … so the many-call pipeline
> is bound by generation throughput, not context". **That reads a configuration as a property
> of the harness.**
>
> `search.snippets_only` is `True` in our snapshot, and it wins outright: the search engine
> returns snippets and **never fetches page content**
> (`web_search_engines/search_engine_base.py:697-701` — `if self.search_snippets_only: results
> = filtered_items`, else `_get_full_content(...)`). `include_full_content`, which the
> source-based strategy does set (`source_based_strategy.py:126-128`), only builds the fetch
> machinery at `:1187`; `run()` never reaches it.
>
> So Onyx's peak came from crawling a 20,110-token page and **LDR fetched nothing**. "LDR uses
> 9% of `-c 65536`" describes `snippets_only=True`, not local-deep-research.
> `../docs/harness-comparison.md:314-316` predicted exactly this and
> flagged it for checking; it was never checked.
>
> **G0 is reopened for LDR** until a full-content run is measured. `truncated = 0` holds for
> what was measured, and says nothing about a configuration that reads pages.

> **Further caveats, so this is not over-read.** One trial, one query, one config, and that
> config is now known to be mislabelled (above). E1's ~38 tok/s was measured on ROCm through
> Onyx at larger prompts; generation is flat with prompt size (measured 39.6/39.0/40.1 across
> 8k–22k), so the throughput comparison is fair, but it is not an A/B — ROCm is no longer
> deployed.

Capture and parse: [`upstream.py`](upstream.py), tested against the real log committed at
`testdata/upstream-Q1-i1-q2.log`.

## Q6 (ZFS vs btrfs, "Cite your sources") — the regression case

The question Onyx answered from model weights and then fabricated a four-entry
`Sources:` list for.

> ### ⚠ The local-deep-research rows below are NOT a controlled measurement
>
> They came from two ad-hoc runs made while checking the Python client worked, **before
> this runbook existed**. Specifically they were taken:
>
> - without asserting the preconditions in [README.md](README.md) — `gpu-mode` state and
>   ComfyUI contention were never checked
> - **without the upstream capture running**, so there is no capacity data for them at
>   all: calls per question, peak prompt and `truncated` are all unknown
> - at n=2, with `iterations=1, questions_per_iteration=2`
>
> Treat them as **directional evidence that the harness searches**, not as the Q6 result.
> Re-run properly and replace this block.

| harness | strategy / sampling | searched | sources | wall | citations |
|---|---|---|---|---|---|
| Onyx | agent loop, `temperature 0` (greedy) | **0/3** | 0 | 68 s | **fabricated** — 4 plausible titles, no URLs |
| Onyx | agent loop, `temperature 1.0` | **1/4** | 11 on the one that searched | 56–99 s | real when it searched |
| local-deep-research ⚠ | `source-based`, temp 1.0 | 2/2 | 17, 18 | 374 s, 450 s | inline `[n]` per claim |

**What can honestly be claimed from this:** local-deep-research searched on both attempts
and emitted per-claim inline citations, where Onyx searched on none and invented its
sources. The direction is not subtle. The *magnitude* — search rate, wall time, source
count — needs a controlled run before it belongs in an argument.

Not yet measured: the other six queries, the other strategies, capacity for either
local-deep-research run, and whether those 17–18 cited sources were genuinely fetched
(see the citation-integrity check — a fabricated list passed a naive grep once already).

## Full query-set runs

| harness | model | strategy | searched | mean wall | params |
|---|---|---|---|---|---|
| *(pending)* | | | | | |

## Capacity, per harness

`-c 65536` on Gemma. Onyx's numbers are from E1; see
[../llama-swap/results.md](../llama-swap/results.md).

| harness | calls per question | peak prompt / total | truncated | evidence depth |
|---|---|---|---|---|
| Onyx | 1–6 | 25,316 / 30,349 | 0 | full page crawls (7k–20k tokens each) |
| local-deep-research | **5** | **3,131 / 5,912** | **0** | **snippets only — no page ever fetched** |
| local-deep-research, full content | *(unmeasured)* | *(unmeasured)* | ? | the configuration this row needs |

**Measured 2026-08-01. The reading placed on it was wrong, corrected 2026-08-02.** LDR's
worst call used 5,912 of 65,536 tokens — 9% of the deployed context, against Onyx's 46%.
That was read as "LDR is less stressed, so one card is comfortably enough". **It is not a
harness property.** LDR ran with `search.snippets_only = True` and fetched no page content
at all, while Onyx's peak is set by a 20,110-token crawl — so the two rows measure different
workloads, not different harnesses.

**What can be claimed:** at snippets-only, LDR's peak is 9% of `-c`. **What cannot:** that one
16 GB card is enough for LDR *as a research assistant that reads its sources*. The third row
is the one that answers G0, and it is unmeasured. Full detail and the code path:
the correction in the end-to-end section above.
