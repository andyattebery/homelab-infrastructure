# Harness comparison — Onyx vs local-deep-research

> ## ⚠ Decision record. Closed 2026-07-31. Do not tune from this doc.
>
> This is **why local-deep-research was chosen over Onyx**, with the evidence that settled
> it. The decision is made; the harness is deployed. Nothing here should be read as
> guidance for the work that follows it.
>
> **In particular, the metric below is scoped to this decision and has been superseded.**
> *Search rate* answered "does this harness search at all", which was the question when
> Onyx was answering from model weights. It is **not** the metric for tuning LDR: on
> `source-based` the harness searches by construction, so measuring the rate measures a
> tautology. The live metric is **correctness of the information** —
> [ldr-tuning-methodology.md](ldr-tuning-methodology.md).
>
> Current work and status: [current-work.md](current-work.md).

Which application turns *search → crawl → cited answer* into something reliable on this
hardware. Parent doc: [README.md](README.md).

**This doc owns the cross-harness question.** [llm-tuning.md](llm-tuning.md)
stays scoped to llama-swap and Onyx configuration; the shared input is
[research/local-llm/bench/queries.md](../bench/queries.md).

## Why there is a comparison at all

Onyx delegates *"should I search?"* to the model, and a 12B model answers **no** most of
the time. Three of seven queries made zero tool calls, and the one that asked for
citations invented them. That is not a tuning defect — no available Onyx setting forces a
search:

| mechanism | result |
|---|---|
| `tool_choice: "required"` (what Onyx sends via litellm) | ignored by llama.cpp; no tool call |
| `tool_choice: {"type":"any"}` / `{"type":"tool","name":…}` | ignored; no tool call |
| `forced_tool_id` through Onyx | empty streaming delta, request hangs |
| **`response_format: json_schema`** (constrained decoding) | **works — 100% compliant** |

Constrained decoding is decoder-level: logits outside the grammar are masked, so prose is
not an available output. **Onyx cannot emit it.** Hence the selection criterion for an
alternative: *does it treat search as a pipeline stage rather than a model decision?*

## The metric — for this decision only, now superseded

**Search rate**, not answer quality. Quality needs judgement and does not settle
arguments; this defect is bounded and countable:

1. **Did it search?** Count tool calls / search invocations per question.
2. **Are the citations real?** Every cited source must correspond to a URL actually
   fetched.
3. **What did it cost?** Tokens and wall time per question.

### Baselines already measured

Same model (`gemma-4-12b-it`), same SearXNG, same card.

| harness | sampling | searched | notes |
|---|---|---|---|
| Onyx | greedy (`temperature 0`) | **0/3** | Failed *identically* every time — greedy makes the branch deterministic |
| Onyx | `temperature 1.0` | **1/4** | The one that searched made 2 tool calls, 11 citations, a good answer |
| local-deep-research ⚠ | `source-based`, temp 1.0 | **2/2** | 17 and 18 sources, inline `[n]` citations per claim, 374 s and 450 s |

⚠ **The LDR row is directional, not controlled.** Those two runs were made while checking
the Python client worked, before the runbook existed: no preconditions asserted, no
upstream capture attached, so there is no capacity data for them at all. They justify the
decision — the direction is not subtle — but they are not a result. Full caveat and the
rest of the numbers: [research/local-llm/bench/harness/results.md](../bench/harness/results.md).

Greedy was not a deliberate setting: Onyx's `GEN_AI_TEMPERATURE` defaults to 0 and
overrides llama-server's command line, so the publisher-recommended sampler never applied.
Fixed, but it changed the failure's *shape*, not its rate enough to matter.

## How to measure each harness

### Onyx

Read-only against its database. **Always open with the read-only guard** so a mistyped
statement errors instead of mutating:

```bash
docker exec onyx-postgres psql -U postgres -d postgres -F$'\t' -tAc "
SET default_transaction_read_only = on;
SELECT cs.description, cm.id, cm.token_count,
       coalesce(length(cm.reasoning_tokens),0) AS reason_chars,
       (SELECT count(*) FROM tool_call tc WHERE tc.parent_chat_message_id = cm.id) AS tcalls,
       CASE WHEN cm.citations IS NULL OR cm.citations::text IN ('null','{}') THEN 0
            ELSE (SELECT count(*) FROM jsonb_object_keys(cm.citations::jsonb)) END AS n_cit
FROM chat_message cm JOIN chat_session cs ON cs.id = cm.chat_session_id
WHERE cm.message_type = 'ASSISTANT' ORDER BY cs.time_created, cm.id;"
```

Schema facts worth not re-deriving: `reasoning_tokens` holds the reasoning **text**, not a
count; `citations` is a JSON **object**, so `jsonb_array_length` errors on it; `tool_call`
links by `parent_chat_message_id`; there is one `chat_message` row per **turn**, not per
LLM call, so cross-reference llama-swap's log for the intermediate calls.

Driving it programmatically needs a session, not an API key — key creation is
paywalled. `POST /api/auth/login` (form-encoded) then
`POST /api/chat/send-chat-message`, which is the same endpoint the UI uses. Sessions
expire; re-login on 403.

### local-deep-research

**No API key exists** — upstream removed keyless access in v1.0 and every endpoint needs
a session. The raw HTTP path would need the full cookie **plus CSRF** dance (scrape
`csrf_token` from the login HTML, POST form-encoded, then `GET /auth/csrf-token` and send
`X-CSRF-Token` on every state-changing call).

**Don't do that.** The package ships `LDRClient`, which handles login, CSRF and session
internally, **and it is installed inside the container** — so drive it with `docker exec`
and skip the entire problem:

```python
from local_deep_research.api import LDRClient
c = LDRClient()                    # base_url defaults to http://localhost:5000
c.login(username, password)        # -> bool
```

Verified signatures (`inspect.signature`, not the docs):

| method | signature |
|---|---|
| `LDRClient()` | `(base_url='http://localhost:5000')` |
| `login` | `(username, password) -> bool` |
| `quick_research` | `(query, model=None, search_engines=None, iterations=2, wait_for_result=True, timeout=300) -> dict` |
| `wait_for_research` | `(research_id, timeout=300) -> dict` |
| `get_history` | `() -> list[dict]` |
| `get_settings` / `update_setting` | `() -> dict` / `(key, value) -> bool` |

`quick_research` takes **`model` and `search_engines` per call**, so a model A/B needs no
settings change and no redeploy. Raise `timeout` above its 300 s default — Onyx's worst
query took 221 s and a multi-stage pipeline can exceed that.

**`get_settings()` is wrapped**: it returns `{"settings": {...}, "status": ...}`, and each
value is a descriptor dict (`value`, `options`, `editable`, …), not a bare value. Reading
`s[key]` instead of `s["settings"][key]["value"]` yields 2 keys and looks like an empty
instance.

**Credentials** live at `~/.config/ldr/claude-creds` (mode 600), same shape as the Onyx
pair:

```
LDR_URL=https://local-deep-research.<domain_name>
LDR_USER=...
LDR_PASSWORD=...
```

It is a **username, not an email**. The password is also the encryption key for that
user's database, so it is not merely an access token.

**Invocation pattern — keep the password out of `argv`.** Source the creds locally,
render a Python script, and pipe it over stdin; never interpolate the password into a
command line, where it would be visible in `ps` on both hosts:

```bash
set -a; . ~/.config/ldr/claude-creds; set +a
# render script with creds embedded, then:
ssh docker-01 'docker exec -i local-deep-research python3 -' < script.py
```

### Three access paths — and `LDRClient` is not the right one for this experiment

| path | control | cost |
|---|---|---|
| `LDRClient` (HTTP, wraps auth) | `model`, `search_engines`, `iterations` only | easiest; **cannot set `search_strategy`** |
| Raw HTTP `/api/start_research` | JSON-serialisable params | full session + CSRF dance |
| **Programmatic `quick_summary`** | *"full access to all features and parameters"* — including **`search_strategy`** | **no auth at all** — `programmatic_mode=True` bypasses login *and* database access |

Since `search_strategy` **is** the experiment (agentic vs pipeline), the programmatic API
is the one to use. It runs in-process inside the container, no HTTP hop.

**Use `create_settings_snapshot`, not the DB-session recipe.** `docs/api-quickstart.md`
shows `get_user_db_session` + `SettingsManager.get_all_settings()`; the working example in
`examples/api_usage/programmatic/search_strategies_example.py` uses a far simpler helper
that takes a dict of overrides:

```python
from local_deep_research.api import quick_summary          # or detailed_research
from local_deep_research.api.settings_utils import create_settings_snapshot

settings = create_settings_snapshot({"search.tool": "searxng"})
result = quick_summary(
    query=Q,
    settings_snapshot=settings,
    search_strategy="source-based",   # the variable under test
    iterations=2,
    questions_per_iteration=3,
    temperature=1.0,                  # per-call, unlike Onyx's global GEN_AI_TEMPERATURE
    programmatic_mode=True,           # required; absent from the api-quickstart doc
)
```

Every knob that matters is a **per-call argument** — strategy, iterations, questions per
iteration, and temperature — so nothing depends on global settings state and runs cannot
drift. That is strictly better instrumentation than Onyx, where temperature is an
env var requiring a redeploy.

**The credentials are not needed for trials.** `programmatic_mode=True` bypasses auth and
the per-user encrypted database entirely — upstream's own words: *"without requiring
authentication or database access"*. `~/.config/ldr/claude-creds` is only for the web UI
and the `LDRClient`/HTTP paths. If a call raises **"No settings context available"**, the
cause is a missing `settings_snapshot` **or** a missing `programmatic_mode=True`, not a
login problem.

`llm.model` must be in the snapshot, because we deliberately left `LDR_LLM_MODEL` unset
so the UI keeps its model selector. Omitting it fails with *"OpenAI-Compatible Endpoint
model not configured"*. That is a feature here: the model becomes a per-call override
too, so a model A/B is a dict key rather than a redeploy.

```python
create_settings_snapshot({
    "search.tool": "searxng",
    "llm.provider": "openai_endpoint",
    "llm.model": "gemma-4-12b-it",
})
```

**Result shape** (from the same example) gives the metric without touching a database:

| field | use |
|---|---|
| `sources` | **the search-rate metric** — `len(result["sources"])` |
| `questions` | dict keyed by iteration: what was actually searched |
| `findings` | per-finding detail |
| `summary`, `research_id` | the answer and its id |

### Built-in benchmarks — better instruments than the seven-query set

`examples/benchmarks/` ships **SimpleQA** and **BrowseComp** runners:

```bash
python run_simpleqa.py  --examples 10 --iterations 3 --questions 3 --search-tool searxng
python run_browsecomp.py --examples 5 --iterations 3 --questions 3
```

These are how upstream produced the 91.2% / 95.7% figures. **SimpleQA measures the exact
failure we have** — factual accuracy and whether the model abstains rather than
fabricating — on a real dataset instead of seven hand-written questions.

So the two instruments have different jobs, and both are worth running:

- **`research/local-llm/bench/queries.md`** — the controlled A/B. Same seven inputs, same model, same
  SearXNG, against Onyx's measured baselines. Answers *"is this harness better than Onyx
  at deciding to search?"*
- **SimpleQA** — the absolute measure of grounding, comparable to upstream's published
  numbers. Answers *"is this deployment any good?"*

**Grader caveat:** these runners take `--eval-model` / `--eval-provider`, i.e.
LLM-as-judge. Grading a 12B model's output with that same 12B model is weak, and upstream
itself flags "LLM-grader noise" and "SimpleQA contamination risk on newer base models".
Decide the grader deliberately before quoting any number.

### The examples directory is the real documentation — 66 files

`examples/` carries more usable detail than `docs/`, and the prose docs are stale in
places the examples are not. Worth knowing what is there before writing any code:

| path | why it matters |
|---|---|
| `api_usage/programmatic/README.md` | The map: which example does what, and the `programmatic_mode` contract |
| `api_usage/programmatic/search_strategies_example.py` | **The strategy question.** `source-based` vs `focused-iteration`, side by side, with the exact call shape |
| `api_usage/programmatic/searxng_example.py` | SearXNG config and error handling — our search backend |
| `api_usage/programmatic/advanced_features_example.py` | `generate_report`, export formats, **batch research** for multiple queries |
| `api_usage/programmatic/api_public_contract_guardrail.py` | Which API surface is contractually stable |
| `api_usage/programmatic/minimal_working_example.py` | Smallest end-to-end call |
| `benchmarks/run_simpleqa.py`, `run_browsecomp.py` | The benchmark runners behind upstream's published numbers |
| `benchmarks/claude_grading/` | Grading benchmark output with a **stronger external model** — the answer to the self-grading problem below |
| `optimization/strategy_benchmark_plan.py` | 21 KB specifically on benchmarking strategies against each other |
| `optimization/update_llm_config.py` | Utility upstream says to run **before** any benchmark |
| `llm_integration/` | Custom LLM wiring, incl. a mock LLM useful for harness tests without burning GPU |

**Stale references to expect:** the `api_usage/README.md` points at
`http/simple_http_example.py`, which now lives under `http/advanced/`; and
`optimization/README.md` names strategies that do not exist in this build.

### Parameter optimisation exists, and it is Optuna-based

`examples/optimization/run_optimization.py` explores `iterations`,
`questions_per_iteration`, `search_strategy` and `max_results`, scores each combination
against the benchmarks, and searches with Optuna. Modes: `balanced`, `speed`, `quality`,
`efficiency`. It accepts `--provider openai_endpoint --endpoint-url --model`, which is
exactly the llama-swap setup.

Default is `--trials 30`, each trial a full research run — on a local 12B that is hours,
so this is a *later* step, after the strategy question is settled.

**Do not trust that README's parameter values.** It lists strategies as `"standard"`,
`"rapid"`, `"iterdrag"` — **none of which exist in this deployment**. The live settings
enum is authoritative; the README is stale.

### The strategy setting is the whole experiment

`search.search_strategy` defaults to **`langgraph-agent`** — the mode where the LLM
decides what to search. **That is the same delegation that fails in Onyx**, so trialling
local-deep-research as-shipped would reproduce the defect and measure nothing.

**Confirmed in the code, 2026-08-02 (LDR v1.10.0) — it was previously an inference by
analogy from Onyx.** `advanced_search_system/strategies/langgraph_agent_strategy.py` builds a
plain tool-calling agent, `create_agent(model=…, tools=tools, system_prompt=…)` at `:1455-1459`,
with web search registered as a `@tool` at `:257-266` and the system prompt merely *instructing*
it to search (`:1440-1443`). Its own module docstring (`:4-6`) says the agent "autonomously
decides what to search". And the stream loop accepts a no-search answer outright:

```python
elif content:
    # No tool calls = final answer          # langgraph_agent_strategy.py:1554-1556
    final_content = content
```

There is no forced first search, no retry when zero tool calls are emitted, and
`MIN_ITERATIONS` / `recursion_limit` (`:1470-1471`) bound only the *maximum* depth. So the
mechanism is confirmed identical to Onyx's. **The rate is not:** Onyx measured 0/3 greedy and
1/4 at temp 1.0; LDR's prompt and toolset differ, and nobody has measured how often it fires
here. That measurement is worth taking, because this is the strategy the deployed web UI
serves by default.

| option | agentic? |
|---|---|
| `langgraph-agent` | **yes — the default** |
| `source-based` | no — the candidate pipeline mode |
| `focused-iteration`, `focused-iteration-standard`, `topic-organization` | to be characterised |

Settings that bear directly on the token cost measured for Onyx (`W`):

| setting | value | why it matters |
|---|---|---|
| `search.tool` | `searxng` | already pointed at the shared instance |
| `search.snippets_only` | `True` | snippets rather than full page crawls — Onyx's 7k–20k crawls are what set its peak |
| `search.fetch.mode` | `summary_focus_query` (also `summary_focus`, `full`, `disabled`) | the crawl-depth knob |
| `search.iterations` | `3` | upper bound on rounds |
| `search.questions_per_iteration` | `1` | searches per round |
| `search.max_results` / `max_filtered_results` | `50` / `20` | result-set size |

Because `snippets_only` is on by default, this harness may be **cheaper per turn** than
Onyx while searching *more* reliably — which would be the opposite trade-off from the one
the capacity table assumes.

## Citation integrity — the check that nearly failed

The fabricated answer ended with a `**Sources:**` list of four plausible titles. A regex
for `[1]`-style markers and for `source:` returned **clean** on it, because the list used
`1.` under a bold heading.

**Grepping for citation syntax does not find fabricated citations.** The reliable signal
is the tool-call count: read the tail of any answer that made zero calls.

## Capacity is per-harness, not per-card

"One 16 GB card is enough" is measured for **Onyx's agent loop** — 1–6 calls, n≤5
searches, peak 25,316-token prompt / 30,349 total against `-c 65536`. It is not a property
of the hardware.

A multi-stage research pipeline can issue far more calls and larger prompts. Re-derive
these per harness from `llama-swap`'s `/logs/stream/upstream`:

| term | Onyx | local-deep-research |
|---|---|---|
| calls per question | 1–6 (3·1·6·5·1·1·3 across Q1–Q7) | ? |
| peak prompt / peak total | 25,316 / 30,349 | ? |
| `truncated = 1` anywhere | 0 | ? |
| S (system + tool schemas) | ~1,430 | ? |
| W per search / per crawl | ~2,200 / 7k–20k | ? |

If peak total approaches `-c 65536`, or `truncated = 1` appears, **the hardware question
reopens for that harness** — which would not be surprising, since local-deep-research's
own published results use a 24 GB card with a 27B model.

**Deriving prompt size:** use `n_tokens − n_decoded` from the release line, **not** the
token count in `prompt eval time`, which excludes any cached prefix and under-reports by
thousands.
