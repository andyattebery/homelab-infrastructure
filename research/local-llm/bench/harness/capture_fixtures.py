#!/usr/bin/env python3
"""Record local-deep-research's REAL API surface as a committed fixture.

Runs INSIDE the LDR container. Emits one JSON object on **stdout**; every diagnostic goes
to stderr, so the whole thing is:

    ssh docker-01 'docker exec -i local-deep-research python3 -' \
        < research/local-llm/bench/harness/capture_fixtures.py \
        > research/local-llm/bench/harness/testdata/ldr-api.json

WHY THIS EXISTS
---------------
Everything the harness believes about LDR's interface -- that `quick_summary` takes no
`timeout`, that `iterations`/`questions_per_iteration` reach the search system through
`**kwargs`, that `sources` holds stringifiable URLs, which strategy names are real -- was
read once with `inspect.signature` and then written down **in prose**. Prose cannot be
tested against, and the image is `latest`
(docker-compose-local-deep-research.yml:10), so an upstream rename would be swallowed
silently by `**kwargs` and Phase 0 would fit `calls = f(i,q)` to a constant.

The llama-swap harness lost days to exactly this shape -- a parser written against an
*imagined* log format, which matched nothing and reported the silence as a valid empty
result. Its fix was `capture_fixtures.py`, and this is the same fix.

WHAT IT MUST NOT DO
-------------------
Mutate anything. `programmatic_mode=True` bypasses auth and the per-user encrypted
database entirely (README.md:66), so the one live call below writes no research record.
The query is a throwaway against **wikipedia**, not SearXNG, and not one of the seven
(README.md:76-79: a real query costs 6-8 min of GPU and burns a question from the set).

EVERY probe is individually guarded. A capture that dies half way through is worth less
than one that records nine facts and an exception for the tenth -- and "the probe raised"
is itself a finding worth committing.
"""

from __future__ import annotations

import argparse
import inspect
import json
import platform
import re
import sys
import traceback

# Truncate anything free-form. This lands in a committed file; a 6,000-character answer
# would make the diff unreadable and proves nothing the length does not.
MAX_REPR = 300

# The throwaway probe: a one-line question that is not one of the seven, so it costs a
# fraction of a real trial and burns nothing from the set (README.md:76-79).
#
# SearXNG, not wikipedia. README.md:81-91's smoke test uses `search.tool: wikipedia` to
# avoid the shared instance -- but measured on 2026-08-02 that returns **zero results**
# ("Searched with 1 questions, found 0 results" across every iteration), so it cannot
# answer what `sources` holds: an empty list has no element to inspect. SearXNG is also
# what every real trial uses, which makes the captured shape the shape that matters.
PROBE_QUERY = "What is the capital of France?"
PROBE_SEARCH_TOOL = "searxng"
# One iteration, one question -- the cheapest real trial. Set through the SETTINGS
# SNAPSHOT, because that is the only channel the strategy reads; see CONTROL_ARMS below.
# Passing these as kwargs is what everything did before 2026-08-02, and it silently ran
# (3, 3) instead.
PROBE_ITERATIONS = 1
PROBE_QUESTIONS = 1
# Wiring only -- NO iteration keys. `control_matrix` builds its arms on this base, and if
# the base pinned `search.iterations` then the "kwargs only" arm would inherit the right
# answer from the base and report that kwargs work. That false positive was observed
# during development, which is exactly why the two dicts are separate.
PROBE_BASE_SETTINGS = {
    "search.tool": PROBE_SEARCH_TOOL,
    "llm.provider": "openai_endpoint",
    "llm.model": "gemma-4-12b-it",
}
PROBE_SETTINGS = {
    **PROBE_BASE_SETTINGS,
    "search.iterations": PROBE_ITERATIONS,
    "search.questions": PROBE_QUESTIONS,
}
PROBE_KWARGS = dict(
    search_strategy="source-based",
    programmatic_mode=True,
)


def clip(obj: object) -> str:
    r = repr(obj)
    return r if len(r) <= MAX_REPR else r[:MAX_REPR] + f"...<+{len(r) - MAX_REPR} chars>"


def probe(name: str, fn) -> dict:
    """Run one capture step. A raised exception is recorded, never propagated.

    The alternative -- letting it crash -- costs the other nine probes, and this script is
    delivered over stdin to a container, so a retry is not free.
    """
    try:
        return {"probe": name, "ok": True, "value": fn()}
    except Exception as e:                                   # noqa: BLE001 -- deliberate
        print(f"  probe {name!r} FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return {"probe": name, "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-2000:]}


# --------------------------------------------------------------------- signatures

def describe_signature(fn) -> dict:
    """Parameter names, KINDS and defaults.

    The kind is the load-bearing part, not decoration: `test_ldr_api.py` has to tell a
    named parameter from one that merely lands in `**kwargs`, because those two cases have
    completely different failure modes. A misspelled named parameter raises TypeError
    immediately; a misspelled kwarg is accepted and silently ignored.
    """
    sig = inspect.signature(fn)
    params = []
    for p in sig.parameters.values():
        params.append({
            "name": p.name,
            "kind": p.kind.name,                    # POSITIONAL_OR_KEYWORD, VAR_KEYWORD, ...
            "has_default": p.default is not inspect.Parameter.empty,
            "default": None if p.default is inspect.Parameter.empty else clip(p.default),
            "annotation": (None if p.annotation is inspect.Parameter.empty
                           else clip(p.annotation)),
        })
    names = [p["name"] for p in params]
    return {
        "qualname": getattr(fn, "__qualname__", None),
        "module": getattr(fn, "__module__", None),
        "text": str(sig),
        "parameters": params,
        "named": [p["name"] for p in params
                  if p["kind"] not in ("VAR_KEYWORD", "VAR_POSITIONAL")],
        "accepts_var_keyword": any(p["kind"] == "VAR_KEYWORD" for p in params),
        # The headline fact this whole design rests on. Stated explicitly so a test can
        # assert it rather than re-deriving it from the parameter list.
        "accepts_timeout": "timeout" in names,
        **source_location(fn),
    }


def source_location(fn) -> dict:
    """File and line of a function, **after unwrapping decorators**.

    The plan cites the kwargs-forwarding site as ':143-149' with **no filename recorded**,
    which makes it unresolvable. This is what fixes that.

    `inspect.unwrap` is load-bearing, and the first capture proved it: `quick_summary` is
    wrapped in `utilities/db_utils.py`, so `getsourcefile` on the wrapper reported
    `db_utils.py:165` while `signature()` -- which follows `__wrapped__` by itself --
    reported the real parameters. Grepping the wrapper for `_init_search_system` returned
    **zero hits**, which reads exactly like "the forwarding does not exist".
    """
    out = {}
    try:
        target = inspect.unwrap(fn)
        out["was_wrapped"] = target is not fn
        if out["was_wrapped"]:
            out["wrapper_file"] = inspect.getsourcefile(fn)
        file = inspect.getsourcefile(target)
        _, line = inspect.getsourcelines(target)
        return {**out, "source_file": file, "source_line": line}
    except (OSError, TypeError) as e:
        return {**out, "source_file": None, "source_line": None, "source_error": str(e)}


def grep_source(fn, needles: tuple[str, ...]) -> dict:
    """Line numbers where each needle appears in the DEFINING MODULE's source.

    Records where `**kwargs` actually goes. A test cannot check this, but a human reading
    a failure can -- and it turns 'observed at :143-149' into a resolvable citation that
    re-derives itself on every capture.

    Unwraps first, for the reason in `source_location`.
    """
    fn = inspect.unwrap(fn)
    file = inspect.getsourcefile(fn)
    if not file:
        raise OSError("no source file for the function")
    with open(file) as fh:
        lines = fh.read().splitlines()
    hits: dict[str, list] = {n: [] for n in needles}
    for i, text in enumerate(lines, 1):
        for n in needles:
            if n in text:
                hits[n].append({"line": i, "text": text.strip()[:200]})
    return {"file": file, "total_lines": len(lines), "hits": hits}


# --------------------------------------------------------------------- settings

def describe_settings(create_settings_snapshot) -> dict:
    """The snapshot's own account of the strategy setting, recorded VERBATIM.

    Deliberately does not assume a shape. `get_settings()` on the HTTP client returns
    descriptor dicts rather than bare values (harness-comparison.md:134-137), and this
    helper may or may not do the same -- so every key mentioning 'strateg' is dumped as
    found, and whoever reads the fixture decides what the enum looks like.

    This is the check that stops a sweep silently running `langgraph-agent`, the agentic
    default the whole experiment exists to avoid (harness-comparison.md:293-295), and it is
    the structural form of open question 3, `source-based` vs `source_based`.
    """
    snap = create_settings_snapshot({})
    out = {"type": type(snap).__name__}
    if not isinstance(snap, dict):
        out["repr"] = clip(snap)
        return out
    out["key_count"] = len(snap)

    def descriptor(k: str) -> object:
        """Pull `value` and `options` out STRUCTURALLY rather than clipping the dict.

        The first capture clipped each descriptor at MAX_REPR and cut off `options` --
        which IS the strategy enum, the thing this probe exists to record. A repr is not a
        substitute for the field.
        """
        if k not in snap:
            return "<ABSENT>"
        v = snap[k]
        if not isinstance(v, dict):
            return {"raw": clip(v), "descriptor": False}
        return {"descriptor": True, "value": v.get("value"), "options": v.get("options"),
                "type": v.get("type"), "editable": v.get("editable"),
                "min_value": v.get("min_value"), "max_value": v.get("max_value"),
                "other_fields": sorted(set(v) - {"value", "options", "type", "editable",
                                                 "min_value", "max_value"})}

    out["strategy_keys"] = {k: descriptor(k) for k in snap if "strateg" in k.lower()}
    # Phase 2 sweeps these, so they must be real keys with real defaults
    # (ldr-tuning-methodology.md:38-39). "Absence is not evidence": a missing key means the
    # name is wrong, not that the default is off.
    out["known_keys"] = {k: descriptor(k) for k in (
        "search.tool", "search.max_results", "search.max_filtered_results",
        "search.snippets_only", "search.fetch.mode", "search.iterations",
        "search.questions_per_iteration", "llm.provider", "llm.model", "llm.temperature")}
    out["sample_keys"] = sorted(snap)[:60]
    return out


# ------------------------------------------- WHICH MECHANISM ACTUALLY CONTROLS i AND q

# Measured 2026-08-02, and it inverts how every trial so far was invoked.
#
# `source_based_strategy.py:208-210` reads its own loop bounds straight from the settings
# snapshot and never consults the system object:
#
#     iterations_to_run      = self.get_setting("search.iterations", 2)
#     questions_per_iteration = self.get_setting("search.questions", 3)
#
# `_init_search_system` DOES accept `iterations=` and assigns `system.max_iterations`
# (research_functions.py:123) -- but by then `AdvancedSearchSystem.__init__` has already
# built the strategy, having resolved `search.iterations` from the snapshot itself
# (search_system.py:148-156, passed on at :235). So the kwarg lands on an attribute the
# strategy never reads.
#
# Worse for `q`: **`search.questions` is not a key in the default snapshot at all** --
# the real key is `search.questions_per_iteration`, which nothing reads. So `get_setting`
# falls through to its hardcoded 3 and questions-per-iteration is pinned at 3 no matter
# what the caller does, unless the odd key is injected explicitly.
#
# This is the exact silent-kwargs failure the harness was designed to catch: nothing
# raises, nothing warns, and Phase 0 fitting `calls = f(i, q)` from kwargs would have
# fitted a CONSTANT. Left as a live probe rather than a comment so an upstream fix (or a
# regression) is caught on the next capture instead of being assumed.
CONTROL_ARMS = [
    ("kwargs only (what every trial did until 2026-08-02)",
     {}, {"iterations": 1, "questions_per_iteration": 2}),
    ("snapshot search.iterations", {"search.iterations": 1}, {}),
    ("snapshot search.questions_per_iteration (the DECOY key)",
     {"search.questions_per_iteration": 2}, {}),
    ("snapshot search.questions (the key the strategy reads)",
     {"search.questions": 2}, {}),
    ("snapshot both, i=4 q=5", {"search.iterations": 4, "search.questions": 5}, {}),
]


def control_matrix(init_search_system, create_settings_snapshot, strategy: str) -> dict:
    """For each way of asking for `i` and `q`, what will the strategy ACTUALLY use.

    Builds the system but never calls the model, so the whole matrix is free -- no GPU, no
    search, no LLM. `get_setting` on the constructed strategy is the same call the loop
    itself makes, so this reads the real answer rather than predicting it.
    """
    rows = []
    for label, overrides, kwargs in CONTROL_ARMS:
        try:
            # PROBE_BASE_SETTINGS, never PROBE_SETTINGS: the base must not pin the very
            # keys each arm is trying to isolate.
            snap = create_settings_snapshot({**PROBE_BASE_SETTINGS, **overrides})
            system = init_search_system(search_strategy=strategy, programmatic_mode=True,
                                        settings_snapshot=snap, **kwargs)
            st = system.strategy
            rows.append({
                "arm": label, "overrides": overrides, "kwargs": kwargs,
                "strategy_class": type(st).__name__,
                "system_max_iterations": getattr(system, "max_iterations", None),
                # The two `get_setting` calls source_based_strategy.py:208-210 makes.
                "effective_iterations": st.get_setting("search.iterations", 2),
                "effective_questions": st.get_setting("search.questions", 3),
            })
        except Exception as e:                               # noqa: BLE001
            rows.append({"arm": label, "overrides": overrides, "kwargs": kwargs,
                         "error": f"{type(e).__name__}: {e}"})
    out = {"strategy": strategy, "arms": rows,
           "reads_iterations_from": "settings_snapshot['search.iterations']",
           "reads_questions_from": "settings_snapshot['search.questions']"}
    # The headline booleans, so a test asserts them instead of re-deriving them.
    by = {r["arm"]: r for r in rows if "error" not in r}
    kw = by.get(CONTROL_ARMS[0][0])
    if kw:
        out["kwargs_control_iterations"] = kw["effective_iterations"] == 1
        out["kwargs_control_questions"] = kw["effective_questions"] == 2
    both = by.get(CONTROL_ARMS[4][0])
    if both:
        out["snapshot_controls_both"] = (both["effective_iterations"] == 4
                                         and both["effective_questions"] == 5)
    return out


# ------------------------------------------- the SAME question, end to end through the API

# `control_matrix` above builds a system and asks the strategy what it *would* read. That is
# one step removed from the truth: it never runs `analyze_topic`, so it cannot see anything
# the loop does to settings on the way in. These arms close that gap by going through
# `quick_summary` itself and counting what actually happened.
#
# Distinguishing values matter. The first kwarg probes used `iterations=1` and got 3 back --
# but 3 is also the `search.iterations` default, so "ignored" and "clamped to the default"
# are indistinguishable. **2 is neither the default (3) nor the earlier request (1)**, so an
# arm asking for 2 and receiving 3 can only mean the request was discarded.
#
# Upstream documents the kwarg form and nothing else: `examples/api_usage/programmatic/
# search_strategies_example.py:44-47` (v1.10.0) passes `iterations=2,
# questions_per_iteration=3` to `quick_summary` for `source-based`, and `docs/
# api-quickstart.md:116-117` does the same. So if these arms show the kwargs being dropped,
# that is an upstream defect against upstream's own example -- not us holding it wrong.
LIVE_CONTROL_ARMS = [
    ("kwargs i=2 q=2 (upstream's documented form)",
     {}, {"iterations": 2, "questions_per_iteration": 2}),
    ("snapshot search.iterations=2 search.questions=2",
     {"search.iterations": 2, "search.questions": 2}, {}),
]

_SEARCHED_WITH = re.compile(r"Searched with (\d+) questions")


def observed_questions(findings: object) -> list:
    """How many questions each iteration actually issued.

    `findings` phases carry 'Searched with N questions, found M results' verbatim -- the
    only place the realised `q` is visible, since `questions` comes back EMPTY on
    source-based (run-ldr.py:87-88, and reproduced here).
    """
    out = []
    if isinstance(findings, list):
        for f in findings:
            if isinstance(f, dict):
                m = _SEARCHED_WITH.search(str(f.get("content", "")))
                if m:
                    out.append(int(m.group(1)))
    return out


def live_controls(quick_summary, create_settings_snapshot, strategy: str) -> list:
    """Run each arm for real and record what came back. Costs one research call per arm."""
    rows = []
    for label, overrides, kwargs in LIVE_CONTROL_ARMS:
        print(f"    arm: {label}", file=sys.stderr)
        row = {"arm": label, "overrides": overrides, "kwargs": kwargs,
               "strategy": strategy}
        try:
            snap = create_settings_snapshot({**PROBE_BASE_SETTINGS, **overrides})
            r = quick_summary(query=PROBE_QUERY, settings_snapshot=snap,
                              search_strategy=strategy, programmatic_mode=True, **kwargs)
            findings = r.get("findings") if isinstance(r, dict) else None
            row.update(
                requested_iterations=(kwargs.get("iterations")
                                      or overrides.get("search.iterations")),
                requested_questions=(kwargs.get("questions_per_iteration")
                                     or overrides.get("search.questions")),
                returned_iterations=r.get("iterations") if isinstance(r, dict) else None,
                observed_questions_per_iteration=observed_questions(findings),
                search_phases=len(observed_questions(findings)),
                questions_dict_len=(len(r.get("questions") or {})
                                    if isinstance(r, dict) else None),
                sources=len(r.get("sources") or []) if isinstance(r, dict) else None,
            )
            row["iterations_honoured"] = (row["requested_iterations"]
                                          == row["returned_iterations"])
            qs = set(row["observed_questions_per_iteration"])
            row["questions_honoured"] = (qs == {row["requested_questions"]}) if qs else None
        except Exception as e:                               # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    return rows


# --------------------------------------------------------------------- the live call

def describe_result(result: object) -> dict:
    """The result dict's real shape.

    Two things ride on this. `records.py` must persist EVERY key -- a field the record
    never captured cannot be recovered later, it is a re-run at ~4 min of exclusive GPU.
    And `sources[0]`'s type is open question 2 (current-work.md:464): `export-for-grading`
    and the whole `sourced` score assume stringifiable URLs, and only a *count* has ever
    been observed. If they are titles, citation-integrity grading is impossible as designed.
    """
    out = {"type": type(result).__name__}
    if not isinstance(result, dict):
        out["repr"] = clip(result)
        return out

    out["keys"] = sorted(result)
    out["by_key"] = {}
    for k, v in sorted(result.items()):
        entry = {"type": type(v).__name__}
        if isinstance(v, (list, tuple, dict, str)):
            entry["len"] = len(v)
        if isinstance(v, dict):
            entry["dict_keys"] = sorted(map(str, v))[:20]
        if not isinstance(v, str) or len(v) <= MAX_REPR:
            entry["repr"] = clip(v)
        else:
            entry["repr"] = clip(v[:MAX_REPR])
        out["by_key"][k] = entry

    srcs = result.get("sources")
    src = {"present": srcs is not None, "type": type(srcs).__name__,
           "len": len(srcs) if isinstance(srcs, (list, tuple)) else None}
    if isinstance(srcs, (list, tuple)) and srcs:
        first = srcs[0]
        src["element_type"] = type(first).__name__
        src["element_repr"] = clip(first)
        # THE question. A str that starts with http is a URL we can hand a judge; a dict
        # means export-for-grading's `str(s)` produces something unusable, and a bare title
        # means the `sourced` score cannot be graded at all.
        src["element_is_str"] = isinstance(first, str)
        src["element_looks_like_url"] = (isinstance(first, str)
                                         and first.strip().lower().startswith("http"))
        if isinstance(first, dict):
            src["element_dict_keys"] = sorted(map(str, first))
        src["all_element_types"] = sorted({type(s).__name__ for s in srcs})
        # What export-for-grading.py:110 would actually write into the grading packet.
        src["str_of_first"] = clip(str(first))
    out["sources_detail"] = src
    return out


# --------------------------------------------------------------------- provenance

def provenance(image_id: str | None) -> dict:
    """A fixture without provenance cannot be known stale.

    The image id is not visible from inside the container, so the caller supplies it;
    everything else is read here.
    """
    out = {"image_id": image_id, "python": sys.version.split()[0],
           "platform": platform.platform(), "node": platform.node()}
    try:
        from importlib.metadata import version
        out["local_deep_research_version"] = version("local-deep-research")
    except Exception as e:                                   # noqa: BLE001
        out["local_deep_research_version"] = f"<unavailable: {type(e).__name__}: {e}>"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--image-id", default=None,
                    help="docker image id of this container, supplied by the caller "
                         "because it is not visible from inside")
    ap.add_argument("--live-controls", action="store_true",
                    help="also run LIVE_CONTROL_ARMS end to end through quick_summary "
                         "(~1-2 min per arm). This is the only probe that observes the "
                         "loop rather than predicting it, and the only one that can "
                         "convict upstream's documented kwarg form")
    ap.add_argument("--strategy", default="source-based",
                    help="strategy for the live probes. The kwarg finding is scoped to "
                         "source-based; other strategies take their bounds through "
                         "different parameter names (search_system.py:238,241,244)")
    ap.add_argument("--no-live-call", action="store_true",
                    help="skip the wikipedia probe: signatures and settings only. Use when "
                         "the GPU is busy — but note it leaves open question 2 unanswered, "
                         "since only the live call reveals what `sources` holds")
    a = ap.parse_args()

    print("=== capture_fixtures: recording LDR's real API ===", file=sys.stderr)

    from local_deep_research.api import quick_summary
    from local_deep_research.api.settings_utils import create_settings_snapshot

    captured: dict = {"provenance": provenance(a.image_id), "probes": {}}

    def add(name: str, fn) -> None:
        r = probe(name, fn)
        captured["probes"][name] = r
        print(f"  {'ok  ' if r['ok'] else 'FAIL'} {name}", file=sys.stderr)

    add("quick_summary_signature", lambda: describe_signature(quick_summary))
    add("create_settings_snapshot_signature",
        lambda: describe_signature(create_settings_snapshot))

    # The forwarding TARGET. Without it, "is this kwarg real?" is unanswerable: a name like
    # `search_strategy` is not a parameter of quick_summary at all -- it rides `**kwargs` and
    # is named only here. Capturing just the caller's signature would make a legitimate
    # forwarded kwarg indistinguishable from a typo, which is the whole failure this
    # fixture exists to catch.
    def init_sig() -> dict:
        from local_deep_research.api.research_functions import _init_search_system
        return describe_signature(_init_search_system)
    add("init_search_system_signature", init_sig)
    # Where **kwargs actually goes, and where settings_snapshot is recognised.
    add("quick_summary_forwarding",
        lambda: grep_source(quick_summary,
                            ("_init_search_system", "settings_snapshot", "kwargs",
                             "search_strategy", "questions_per_iteration")))
    add("settings_snapshot_shape", lambda: describe_settings(create_settings_snapshot))

    # Also record LDRClient's signatures, because harness-comparison.md:125 documents
    # `quick_research(..., timeout=300)` and that 300 was once mistaken for
    # quick_summary's. Recording both together is what stops the confusion recurring.
    def client_signatures() -> dict:
        from local_deep_research.api import LDRClient
        out = {}
        for name in ("quick_research", "wait_for_research", "login", "get_settings"):
            m = getattr(LDRClient, name, None)
            out[name] = describe_signature(m) if m else "<ABSENT>"
        return out
    add("ldrclient_signatures", client_signatures)

    # The most valuable probe here, and free -- no model call. See CONTROL_ARMS.
    def controls() -> dict:
        from local_deep_research.api.research_functions import _init_search_system
        return control_matrix(_init_search_system, create_settings_snapshot, a.strategy)
    add("control_matrix", controls)

    if a.live_controls:
        print(f"  running {len(LIVE_CONTROL_ARMS)} live control arms on {a.strategy!r} "
              "(~1-2 min each)...", file=sys.stderr)
        add("live_controls",
            lambda: live_controls(quick_summary, create_settings_snapshot, a.strategy))

    if a.no_live_call:
        print("  skipped the live call (--no-live-call): result shape NOT captured",
              file=sys.stderr)
        captured["probes"]["live_call"] = {
            "probe": "live_call", "ok": False,
            "error": "skipped by --no-live-call — result shape and sources[0] unknown"}
    else:
        def live() -> dict:
            settings = create_settings_snapshot(PROBE_SETTINGS)
            r = quick_summary(query=PROBE_QUERY, settings_snapshot=settings, **PROBE_KWARGS)
            out = {"request": {"query": PROBE_QUERY, "settings": PROBE_SETTINGS,
                               **{k: clip(v) for k, v in PROBE_KWARGS.items()}},
                   "result": describe_result(r)}
            # THE silent-kwargs tell, recorded as a first-class fact rather than left for a
            # reader to spot. `iterations`/`questions_per_iteration` land in `**kwargs`; if
            # they are not forwarded, the settings default applies instead and the returned
            # `iterations` will match THAT, not what was asked for. Phase 0 fitting
            # `calls = f(i,q)` to a constant is the failure this catches.
            if isinstance(r, dict):
                out["iterations_requested"] = PROBE_ITERATIONS
                out["iterations_returned"] = r.get("iterations")
                out["iterations_agree"] = (PROBE_ITERATIONS == r.get("iterations"))
            return out
        print(f"  running the wikipedia probe ({PROBE_QUERY!r})...", file=sys.stderr)
        add("live_call", live)

    failed = [n for n, r in captured["probes"].items() if not r["ok"]]
    captured["summary"] = {"probes": len(captured["probes"]),
                           "failed": failed, "ok": not failed}

    json.dump(captured, sys.stdout, indent=2, sort_keys=False, default=str)
    sys.stdout.write("\n")

    print(f"\n{len(captured['probes']) - len(failed)}/{len(captured['probes'])} probes ok"
          + (f", failed: {failed}" if failed else ""), file=sys.stderr)
    # Exit 0 even with failures: the JSON is still worth keeping, and a recorded failure is
    # a finding. The caller checks `summary.ok`.
    return 0


if __name__ == "__main__":
    sys.exit(main())
