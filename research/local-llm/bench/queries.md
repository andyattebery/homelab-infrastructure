# Web-research query set

The fixed input for the experiments in [../research/local-llm/docs/llm-tuning.md](../docs/llm-tuning.md)
and for the cross-harness comparison in
[../research/local-llm/docs/harness-comparison.md](../docs/harness-comparison.md).

**Shared across harnesses.** These questions are not Onyx-specific — they are the common
input that makes Onyx and local-deep-research comparable, which is why this file sits at
`bench/` rather than under `research/local-llm/bench/onyx/`.

**Do not vary these between runs.** E1 derives `n` (searches per turn) and `W` (tokens
per search result set), and those two numbers set `-c`, `max_input_tokens`, and the
answer to whether a second GPU is earned. A query set that drifts between runs measures
the drift.

Chosen to span the range of `n`, because `n` is what multiplies `W`.

---

## Protocol

The preconditions below apply to **any** harness, because they are about the shared GPU
host. The recording table that follows is the **Onyx** procedure; local-deep-research
needs its own equivalent — finding where it records "did this answer come from a search"
is a prerequisite to trialling it, not an afterthought. See
[../research/local-llm/docs/harness-comparison.md](../docs/harness-comparison.md).

Per run, before anything:

1. `gpu-mode llm` on htpc-01 — ComfyUI stopped. Contention voids the run.
2. `EVICTED_TIME` 0. Non-zero voids the run.
3. Record the build commit (`system_fingerprint` from any completion) and the deployed
   `ctx` per model. Rows from different builds are not comparable — see the tuning doc's
   build-provenance section.
4. Start capture **before** the first query:

```bash
curl -Ns "https://llama-swap.htpc-01.$DOMAIN/logs/stream/upstream?no-history" > run.log
```

Then run the seven queries **in order, each in a new Onyx chat session**. A new session
matters: it isolates the turn, and it makes the auto-naming call attributable (one
~300-token prompt against the *default* model, fired once per session — expect it in the
log and do not count it as a search iteration).

Record per query:

| field | source |
|---|---|
| `n` | count of `web_search` tool calls in the turn |
| `prompt_tokens[]` | `prompt eval time = … / N tokens`, per call |
| `W[]` | `promptᵢ₊₁ − promptᵢ − Rᵢ` |
| `R[]` | `n_decoded` per call |
| `A` | `n_decoded` on the final call |
| `truncated[]` | **any `truncated = 1` voids that turn's numbers** — the loop hit the ceiling and you measured the ceiling, not `W` |
| wall time | client-side |
| outcome | answer / `EmptyLLMResponseError` / `ValueError` / other |

---

## The queries

### 1. Single-fact current-events lookup — expect `n` = 1

> What is the most recent stable release of Home Assistant, and what was its headline
> feature?

Floor case. Establishes `S + Q` and a single `W` in isolation, which is the cleanest
measurement of `W` in the whole set.

### 2. Comparison of two named things — expect `n` = 2

> Compare Caddy and Traefik for reverse-proxying a homelab: config format, ACME
> certificate handling, and Docker service discovery.

This is the shape that produced failure #2 (`Required: 23572, Available: 19667`). If any
query reproduces that error, it should be this one.

### 3. Multi-hop, second search depends on the first — expect `n` ≥ 3

> Who maintains llama.cpp's HIP/ROCm backend, and what have they merged in the last
> month?

The model cannot form the second query until the first returns. This is the case that
drives `n` upward, and `n` is the term that multiplies `W`.

### 4. No good answer available — does `n` grow without bound?

> What is the measured p99 query latency of Onyx's OpenSearch backend on an RTX A4000
> with a 50,000-document index?

Nothing on the web answers this. The question is whether the loop gives up or keeps
searching. **This is the query most likely to blow the context**, and its `n` is the
number that sizes the worst case rather than the typical one.

### 5. Answerable from model knowledge — does it skip the tool?

> Explain the difference between flash attention and standard scaled dot-product
> attention, and why flash attention uses less memory.

Expect `n` = 0. If the model searches anyway, every turn pays `W` whether it needs to or
not, and that changes the budget for the entire deployment.

### 6. Long synthesis — stresses `A`

> Summarize the tradeoffs between ZFS and btrfs for a home NAS: data integrity
> guarantees, RAID/parity options, memory requirements, and the snapshot and
> send/receive workflow. Cite your sources.

`A` is the one term the tuning doc has never measured — the 8192-token output reserve is
sized against a guess. This query is where a real cited synthesis reveals it.

### 7. The regression case — the query that produced failure #1

> Research to make a table comparing the intel arc battlemage gpu models including the pro ones

Recovered from the Onyx chat history 2026-07-31. This is the query that returned
`EmptyLLMResponseError` on 2026-07-30 — one call decoded 17,534 tokens of reasoning over
472 s and hit `n_tokens = 32767, truncated = 1`.

**It is the regression test for `--reasoning-budget 4096`, and it passes.** Queries 1–6
exercise the loop but none is known to trigger unbounded reasoning, so without this one a
clean run proves the loop works rather than that the specific failure is fixed. In E1 it
ran end to end: 2 searches, a 20,110-token crawl, a 5,033-token table, peak 25,316 prompt
/ 30,349 total, **zero truncation** — and it set the peak for the whole set.

---

## Reading the results

| observation | what it means |
|---|---|
| `truncated = 1` anywhere | The run measured the ceiling. Raise `-c` and re-run; do not derive `W` from it |
| `n` p95 ≤ 3 and `W` small | `-c 32768` was never the real problem; `max_input_tokens` was |
| `W` > ~6k per search | `W` dominates. Go to E3 (reduce at source) before raising `-c` — `W` multiplies by `n`, `-c` costs VRAM linearly |
| `R` frequently exactly 4096 | E2: the cap binds. Check whether capped answers still conclude before raising it |
| query 5 issues a search | Every turn pays `W`. Re-budget for `n` ≥ 1 on all queries |
