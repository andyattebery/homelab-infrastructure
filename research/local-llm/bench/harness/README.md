# Harness runbook

> # ⚠ Read first: `iterations=` and `questions_per_iteration=` do nothing
>
> **Passing these as keyword arguments to `quick_summary` has no effect.** They are silently
> discarded, the settings-snapshot value is used instead, and nothing warns. Every trial this
> project ran before 2026-08-02 was therefore mislabelled.
>
> **Set them in the settings snapshot instead:**
>
> ```python
> settings = create_settings_snapshot({
>     "search.tool": "searxng",
>     "llm.provider": "openai_endpoint",
>     "llm.model": "gemma-4-12b-it",
>     "search.iterations": 2,          # <- the ONLY thing that controls iterations
> })
> r = quick_summary(query=q, settings_snapshot=settings,
>                   search_strategy="source-based",   # this one IS honoured
>                   programmatic_mode=True)
> ```
>
> **Why** (LDR v1.10.0, read end to end — the wrong answer is easy to reach from a partial
> read). `_init_search_system` constructs `AdvancedSearchSystem` **without** `max_iterations`
> (`api/research_functions.py:137-147`), so `__init__` falls back to the snapshot
> (`search_system.py:148-166`) and passes *that* to the strategy (`:235-236`). Only afterwards
> does `research_functions.py:154-156` run `system.max_iterations = iterations` — commented
> *"Override default settings with user-provided values"* — by which time the strategy is
> already built and never re-reads it. `source_based_strategy.py:208` additionally re-reads
> `search.iterations` at run time.
>
> **Measured**, not deduced: asking for `iterations=2` returns `3` (the snapshot default) on
> both `source-based` and `focused-iteration`; setting `search.iterations=2` in the snapshot
> returns `2`. Four end-to-end calls.
>
> **This is upstream of every caller**, so it is not something we did wrong — upstream's own
> example (`examples/api_usage/programmatic/search_strategies_example.py:44-47`) and docs
> (`docs/api-quickstart.md:116-117`) both use the kwarg form, and so do
> `benchmarks/runners.py:201-209`, `benchmarks/web_api/benchmark_service.py:759-775` and the
> Optuna optimizer that drives them. **Upstream's benchmark and optimizer cannot vary
> `iterations`.**
>
> **`questions_per_iteration` is worse and still unresolved:** the strategies read *different*
> keys — `source_based_strategy.py:210` reads `search.questions` (which is **not** in the
> default snapshot, so it falls through to a hardcoded 3), while `focused.py:87-89` uses the
> constructor value seeded from `search.questions_per_iteration`.
>
> **Measured 2026-08-02:** it is controllable on **focused-iteration** — asked 5, issued
> exactly 5 on every iteration (`:227` trims to the cap) — and **not** on **source-based**,
> which was asked 3 and issued 1 each time. The key is read there; the model simply
> under-fills. So `calls = f(i,q)` is fittable for focused-iteration and collapses to `f(i)`
> for source-based. `ldr_trial.QUESTIONS_KEY` encodes the per-strategy mapping.
>
> **Separately: `search.snippets_only` cannot be set at all**, so LDR never fetches the pages
> it cites. Same shape of defect one layer lower — the setting is read correctly at
> `config/search_config.py:96` and then dropped by the factory, which forwards it only for
> tinyfish/sofya/wikinews. Full trace and the one-line fix: [results.md](results.md).
>
> `capture_fixtures.py` records this as a live control matrix in `testdata/ldr-api.json`, so
> the day upstream fixes it the tests fail and this box comes down.

## The scripts

| script | job |
|---|---|
| **[sweep.py](sweep.py)** | **the launcher — start here.** sync → preflight → start capture → tmux, from the Mac |
| [shootout.py](shootout.py) | the grid, in the container: resumable, question-outermost, per-trial subprocess timeout |
| [ldr_trial.py](ldr_trial.py) | one trial. Every swept parameter goes through the settings snapshot |
| [records.py](records.py) | validates a row *before* it reaches a score, incl. asked-vs-happened |
| [upstream.py](upstream.py) | llama-swap capture → calls, peak prompt, `truncated`, tok/s |
| [preflight.py](preflight.py) | cross-host go/no-go; the only thing that sees both hosts |
| [make_questions.py](make_questions.py) | SimpleQA via upstream's loader, `seed=42` |
| [capture_fixtures.py](capture_fixtures.py) | records LDR's real API to `testdata/ldr-api.json` |
| [run_tests.py](run_tests.py) | one entry point — 78 tests in 7 stages, Mac-only |

> **Superseded, kept only so nothing is lost: `run-ldr.py`, `run-matrix.py`,
> `export-for-grading.py`.** Do not run them and do not copy from them — they pass
> `iterations` / `questions_per_iteration` as kwargs, which is the defect described above,
> and `run-matrix.py` cannot vary `search_strategy` at all. `shootout.py` replaces both.
> (This directory is untracked in git, so they are left on disk rather than deleted.)

### Driving it

```bash
python3 research/local-llm/bench/harness/run_tests.py         # everything local: no GPU, no container, no LDR
python3 research/local-llm/bench/harness/run_tests.py --remote  # + sync and the live preflight

python3 research/local-llm/bench/harness/sweep.py --n 20      # launch a sweep, detached in tmux
python3 research/local-llm/bench/harness/sweep.py --status    # per-cell progress
python3 research/local-llm/bench/harness/sweep.py --stop      # kill the sweep and its capture
```

**`sweep.py` owns *starting* the capture**, because it has to be running before the first
query — by the time the runner is up, trial one is already in flight. `shootout.py` stops it
in a `finally`, because the process holding a resource is the one that can reliably release
it. Results land on `/data` in the container, a bind mount, so they survive `docker rm`.

**Resumable:** one fsync'd JSONL line per completed trial, keyed on the **full
settings-override dict** plus strategy and question id, with completed keys skipped on start.
Kill it and re-run the identical command to continue. Failed trials are retried by default —
a failure carries no measurement, only that something went wrong once.

**Budget it: ~200 s per source-based trial, 400–600 s for focused-iteration** at its own (8,5)
default — measured, not extrapolated. A 3-strategy run at n=20 is ~6 h of exclusive GPU.
Sizing rules (n≥100 for a usable read, ≥200 to compare) come from upstream's
`docs/BENCHMARKING.md`. Order and status:
[../docs/current-work.md](../../docs/current-work.md);
method: [../docs/ldr-tuning-methodology.md](../../docs/ldr-tuning-methodology.md).

---

## Comparison runbook

How to run a harness against the fixed query set and record a comparable result.
Methodology and the *why* live in
[../docs/harness-comparison.md](../../docs/harness-comparison.md); this is the
procedure. Rows go in [results.md](results.md).

This exists because the LDR calls were hand-written three times in one session before
anyone wrote them down — the same mistake [../llama-swap/](../llama-swap/README.md) was
created to stop.

## Preconditions — now enforced, not remembered

**`preflight.py` checks all of these and `sweep.py` runs it before committing the GPU.** A
guard that errors must stop the run
([README.md:341](../../docs/README.md)), so they are blocking, not advisory.
The list below is kept because it explains *why* each one matters — but it is no longer a
checklist anyone has to work through by hand.

Worth knowing about one of them: `gpu-mode status` reports `CONTENDED` when ComfyUI **and**
llama-swap are both up. A naive "is llama-swap running?" check passes in that state, and it is
exactly the state that measured a >900 s prompt against 45 s, with 772,000 ms of eviction.

Both harnesses share one GPU host, so a run is only valid if:

1. `ssh htpc-01 'bash -c "gpu-mode status"'` → mode `llm`, ComfyUI **inactive**.
   Contention voids the run.
2. The model is the same on both sides. llama-swap serves one at a time:
   `sudo podman exec llama-swap curl -s localhost:8080/running`
3. Nothing else is driving llama-swap. Check its request log for other clients:
   `sudo podman exec llama-swap curl -s localhost:8080/logs | tail`
4. Start the token capture **before** the first query, so capacity can be derived:
   ```bash
   curl -Ns "https://llama-swap.htpc-01.$DOMAIN/logs/stream/upstream?no-history" > run.log
   ```
   The capture has died mid-run before (curl exit 56) — check it is still alive at the
   end, and treat a dead capture as "no capacity data", never as "no traffic".

## local-deep-research

No credentials needed: `programmatic_mode=True` bypasses auth and the per-user database.

**To run a sweep, use `sweep.py`** (above) — not a script piped over stdin. Piping dies with
the ssh connection and cannot be reattached, which is why the launcher exists.

To run a **single** trial by hand, against one question:

```bash
ssh docker-01 'bash -c "docker exec local-deep-research python3 /data/bench/ldr_trial.py \
    --strategy source-based --question-id adhoc --question \"…\" \
    --iterations 3 --questions 3 --snippets-only true"'
```

It prints one JSON record on stdout. Note `--snippets-only` currently has no effect on the
result — see the warning box at the top.

**Smoke-test the wiring with a throwaway query, not with a real one.** A single real
query is 3–10 minutes of GPU depending on the strategy and, if it lands on a question from
the set, it burns that question under uncontrolled conditions. To check only that the client
works:

```bash
ssh docker-01 'docker exec -i local-deep-research python3 -' <<'PY'
from local_deep_research.api import quick_summary
from local_deep_research.api.settings_utils import create_settings_snapshot
s = create_settings_snapshot({"search.tool": "wikipedia", "llm.provider": "openai_endpoint",
                              "llm.model": "gemma-4-12b-it"})
r = quick_summary(query="What is the capital of France?", settings_snapshot=s,
                  search_strategy="source-based", iterations=1, questions_per_iteration=1,
                  programmatic_mode=True)
print(sorted(r), len(r.get("sources") or []))
PY
```

Wikipedia rather than SearXNG and a one-line question: this answers "does the client
return a populated dict" in a fraction of the time, without consuming a query from the
set or a slot on the shared GPU.

**Budget the time.** One Q6 run took **374–450 s**, with individual completions ~2 min at
the proxy. The full seven-query set at these settings is on the order of an hour. Run it
detached and collect the output rather than watching it.

**Output is buffered.** `docker exec` does not allocate a tty, so Python buffers stdout —
an empty output file mid-run means "still running", not "produced nothing". The runner
passes `flush=True` per row so progress does appear as each query completes.

### Strategy is the variable under test

`langgraph-agent` is the **default and is agentic** — the model decides whether to
search, which is exactly the Onyx failure. Running it as-shipped measures nothing.

| strategy | note |
|---|---|
| `source-based` | Pipeline-ish; "detailed citations for all claims". **Measured: searched 2/2 on Q6, 17–18 sources** |
| `focused-iteration` | The other "main" strategy; iterative refinement. Not yet measured |
| `focused-iteration-standard`, `topic-organization` | Not yet characterised |
| `langgraph-agent` | **Agentic default.** Only run it to quantify the delegation failure |

## Onyx

Driven over its HTTP API with a session cookie (API keys are paywalled). See the
methodology doc for the login flow and the read-only SQL that extracts tool-call and
citation counts. Sessions expire — re-login on 403.

## What to record

Per query: searched (yes/no), source count, wall time, and the outcome. Then:

1. **Check citations are real, not merely present.** The Onyx failure ended with a
   `**Sources:**` list of four plausible titles and no URLs, and a grep for `[1]`-style
   markers returned *clean* on it. Read the tail of any answer whose source count is 0,
   and spot-check that cited URLs were actually fetched.
2. **Derive capacity from the captured log**, per harness — calls per question, peak
   prompt (`n_tokens − n_decoded`, **not** the `prompt eval time` count, which excludes
   cached prefix), and any `truncated = 1`.
3. Append one row to [results.md](results.md). The runner prints a paste-ready row.

## Save the raw output

The runner prints the full result objects after the summary. Save them next to the
capture:

```
research/local-llm/bench/harness/runs/<date>-<harness>-<strategy>.json
research/local-llm/bench/harness/runs/<date>-<harness>-<strategy>-upstream.log
```

Onyx's E1 capture is at `research/local-llm/bench/onyx/runs/` and stays there — it predates this layout.
