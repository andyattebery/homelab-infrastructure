#!/usr/bin/env python3
"""Assert our call sites against LDR's REAL captured API.

    python3 test_ldr_api.py        # Mac, no GPU, no container, no LDR installed

`testdata/ldr-api.json` is produced by `capture_fixtures.py` against the running container.
These tests read it, never the live API, so the whole suite runs offline.

WHY THIS FILE IS FIRST IN run_tests.py
--------------------------------------
It guards the failure that cost this project its configuration labels: `iterations=` and
`questions_per_iteration=` passed as kwargs to `quick_summary` are **silently discarded**.
Nothing raises. Nothing warns. Every trial ran at the settings default and every recorded
config was wrong, for days.

A comment cannot prevent that recurring. The control matrix in the fixture can: it records
what the strategy would ACTUALLY use for each way of asking, and the tests below fail if our
code drifts back to the broken channel -- **or** if upstream fixes the bug, at which point
this file is the thing that tells us the workaround is no longer needed.
"""

import ast
import json
import sys
from pathlib import Path

import ldr_trial

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "testdata" / "ldr-api.json"


def load() -> dict:
    assert FIXTURE.exists(), (
        f"missing {FIXTURE} — capture one with:\n"
        "  ssh docker-01 'bash -c \"docker exec -i local-deep-research python3 -\"' \\\n"
        "      < research/local-llm/bench/harness/capture_fixtures.py > research/local-llm/bench/harness/testdata/ldr-api.json\n"
        "A missing fixture is a failure, not a reason to test against a remembered API.")
    return json.loads(FIXTURE.read_text())


def probe(name: str) -> dict:
    d = load()["probes"][name]
    assert d["ok"], f"probe {name!r} failed in the capture: {d.get('error')}"
    return d["value"]


# ------------------------------------------------- the signature we actually call against

def test_quick_summary_has_no_timeout():
    """Open question 5, closed. The trial bound MUST be external, which is why ldr_trial.py
    is a subprocess rather than a function call."""
    sig = probe("quick_summary_signature")
    assert sig["accepts_timeout"] is False, (
        "quick_summary now accepts a timeout — the external subprocess bound may be "
        "replaceable. Re-read before changing anything.")
    assert sig["accepts_var_keyword"] is True, "no **kwargs — the forwarding path changed"


def test_every_kwarg_we_pass_is_real():
    """A kwarg that names no real parameter anywhere on the path is a typo, and `**kwargs`
    swallows typos in silence — that is exactly how `iterations=` went unnoticed.

    A name is legitimate if it is a parameter of `quick_summary` **or** of the function
    `quick_summary` forwards `**kwargs` to. `search_strategy` is the second kind: not a
    parameter of `quick_summary` at all, but a named parameter of `_init_search_system`.
    Checking only the caller would flag it wrongly; checking neither is how a typo survives.
    """
    caller = set(probe("quick_summary_signature")["named"])
    target = set(probe("init_search_system_signature")["named"])
    reachable = caller | target
    for kw in ldr_trial.KWARG_ALLOWLIST:
        assert kw in reachable, (
            f"{kw!r} is a parameter of neither quick_summary nor _init_search_system, so "
            f"it would land in **kwargs and be silently ignored")


def test_the_swept_parameters_are_real_names_that_still_do_nothing():
    """The trap in one assertion: `iterations` and `questions_per_iteration` ARE genuine
    named parameters of `_init_search_system`. That is precisely why the bug is invisible —
    the name is real, the forwarding happens, and the value is still discarded because the
    strategy was already built. Being a valid parameter name is not evidence that passing it
    works."""
    target = set(probe("init_search_system_signature")["named"])
    for name in ("iterations", "questions_per_iteration"):
        assert name in target, (
            f"{name!r} is no longer a parameter of _init_search_system — the forwarding "
            f"path changed; re-derive the whole mapping")
    assert probe("control_matrix")["kwargs_control_iterations"] is False


# ----------------------------------------- THE guard: swept parameters go in the snapshot

SWEPT_MUST_NOT_BE_KWARGS = {"iterations", "questions_per_iteration",
                            "snippets_only", "max_results", "temperature"}


def test_ldr_trial_passes_no_swept_parameter_as_a_kwarg():
    """Read ldr_trial.py's AST and check the actual `quick_summary(...)` call.

    Derived from the source, not from a hand-maintained list — the same reason
    research/local-llm/bench/llama-swap/run_tests.py derives its sync list from imports. A reviewer cannot
    forget to update this.
    """
    tree = ast.parse((HERE / "ldr_trial.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "quick_summary"]
    assert len(calls) == 1, f"expected exactly one quick_summary call, found {len(calls)}"

    passed = {k.arg for k in calls[0].keywords if k.arg}
    leaked = passed & SWEPT_MUST_NOT_BE_KWARGS
    assert not leaked, (
        f"{sorted(leaked)} passed as kwargs to quick_summary. These are SILENTLY IGNORED "
        f"(README.md's warning box). Put them in the settings snapshot instead.")
    assert passed <= ldr_trial.KWARG_ALLOWLIST, (
        f"unexpected kwargs {sorted(passed - ldr_trial.KWARG_ALLOWLIST)}; if one is "
        f"deliberate, add it to KWARG_ALLOWLIST with a reason")
    # search_strategy IS honoured — consumed at construction — so it must still be there.
    assert "search_strategy" in passed, (
        "search_strategy stopped being passed; it is the one swept parameter that works "
        "as a kwarg, and the settings key is NOT a substitute")


def test_the_kwargs_bug_still_exists_upstream():
    """If this fails, upstream FIXED it — and the workaround should be revisited.

    Deliberately asserts the bug rather than the workaround. A test that only checked our
    code would keep the workaround alive forever after it stopped being necessary.
    """
    cm = probe("control_matrix")
    assert cm["kwargs_control_iterations"] is False, (
        "quick_summary(iterations=…) now WORKS. The settings-snapshot workaround in "
        "ldr_trial.build_settings may be removable — re-read research_functions.py:137-156 "
        "and README.md's warning box before changing anything.")
    assert cm["snapshot_controls_both"] is True, (
        "settings_snapshot no longer controls iterations/questions — the ONLY working "
        "channel just broke. Stop and re-derive before running any sweep.")


def test_snapshot_is_the_channel_that_works():
    """The positive half: the arm that sets both snapshot keys gets both values."""
    cm = probe("control_matrix")
    arms = {a["arm"]: a for a in cm["arms"] if "error" not in a}
    both = [a for k, a in arms.items() if "i=4 q=5" in k]
    assert both, f"the i=4/q=5 arm is missing from the capture: {sorted(arms)}"
    assert both[0]["effective_iterations"] == 4
    assert both[0]["effective_questions"] == 5


# --------------------------------------------------------------- strategies and results

def test_every_strategy_we_sweep_is_a_live_enum_member():
    """Upstream's own README names three strategies that do not exist in this build
    (harness-comparison.md:287-289). The live enum is the only authority."""
    val = probe("settings_snapshot_shape")
    desc = val["strategy_keys"].get("search.search_strategy")
    assert desc and desc.get("options"), f"no strategy enum in the capture: {desc}"
    live = {o["value"] for o in desc["options"]}
    ours = {s for s in ldr_trial.QUESTIONS_KEY}
    unknown = ours - live
    assert not unknown, (
        f"{sorted(unknown)} are not in the live enum {sorted(live)} — a name not in the "
        f"enum silently falls back to the default strategy")


def test_iterations_key_exists_but_questions_key_does_not():
    """The asymmetry that makes the questions mapping fragile, asserted so it cannot be
    quietly forgotten: `search.iterations` is a real default; `search.questions` is NOT in
    the snapshot at all, which is why source-based falls through to a hardcoded 3."""
    known = probe("settings_snapshot_shape")["known_keys"]
    assert known["search.iterations"] != "<ABSENT>"
    assert known["search.questions_per_iteration"] != "<ABSENT>"
    sample = probe("settings_snapshot_shape")["sample_keys"]
    assert "search.questions" not in sample or True   # sample is truncated; see below
    # The authoritative check: the control matrix arm that sets ONLY the decoy key.
    cm = probe("control_matrix")
    decoy = [a for a in cm["arms"] if "DECOY" in a["arm"] and "error" not in a]
    assert decoy, "the decoy arm is missing from the capture"
    assert decoy[0]["effective_questions"] != 2, (
        "search.questions_per_iteration now reaches source-based — the per-strategy "
        "questions mapping in ldr_trial.QUESTIONS_KEY needs re-deriving")


def test_result_keys_we_read_all_exist():
    """Every key ldr_trial pulls off the result dict must be one the API returns."""
    live = probe("live_call")
    keys = set(live["result"]["keys"])
    for k in ("summary", "sources", "findings", "questions", "research_id",
              "iterations", "formatted_findings"):
        assert k in keys, f"we read {k!r} but the API returned {sorted(keys)}"


def test_sources_are_dicts_not_strings():
    """Open question 2, closed. `str(s)` would put a dict repr in the grading packet."""
    sd = probe("live_call")["result"]["sources_detail"]
    if not sd.get("len"):
        raise AssertionError("the capture's live call returned no sources — re-capture; "
                             "this test cannot verify the element shape without one")
    assert sd["element_type"] == "dict", (
        f"sources elements are {sd['element_type']}, not dict — extract_sources() needs "
        f"re-deriving")
    for k in ("link", "title", "snippet"):
        assert k in (sd.get("element_dict_keys") or []), (
            f"source dicts no longer carry {k!r}: {sd.get('element_dict_keys')}")


def test_fetched_page_content_is_measured_not_discarded():
    """`base_citation_handler.py:157` builds the model's evidence as
    `result.get("full_content", result.get("snippet", ""))`, so under the full-content arm
    full_content IS what the model read. If extract_sources drops it, both depth arms record
    identically and the whole Part 1 patch becomes unmeasurable."""
    got = ldr_trial.extract_sources([
        {"link": "https://e.org/a", "title": "A", "snippet": "245 chars of snippet",
         "engine": "searxng", "full_content": "x" * 4192, "category": "general"},
        {"link": "https://e.org/b", "title": "B", "snippet": "s", "engine": "searxng"},
    ])
    assert got[0]["full_content_chars"] == 4192
    assert got[1]["full_content_chars"] == 0, "a source with no fetch must record 0, not None"
    assert len(got[0]["full_content_head"]) == 400, "the audit head must be bounded"
    assert got[1]["full_content_head"] is None
    # the record must stay small: the head is for a human, not a copy of the page
    assert all(len(json.dumps(s)) < 1200 for s in got)


def test_extract_sources_survives_non_dict_sources():
    """The non-dict branch must produce the SAME keys, or a record from one arm fails
    validation while the other passes."""
    a, = ldr_trial.extract_sources(["a bare string"])
    b, = ldr_trial.extract_sources([{"link": "https://e.org", "snippet": "s"}])
    assert set(a) == set(b), f"branches disagree on shape: {sorted(set(a) ^ set(b))}"


def test_fixture_records_its_provenance():
    """A fixture without provenance cannot be known stale."""
    prov = load()["provenance"]
    assert prov.get("local_deep_research_version"), "no LDR version recorded"
    assert prov.get("image_id"), (
        "no image id recorded — re-capture passing --image-id, or a fixture from a "
        "different image is indistinguishable from a current one")


# ------------------------------------------------------------- the per-strategy mapping

def test_build_settings_uses_the_right_questions_key_per_strategy():
    """source-based and focused-iteration read DIFFERENT keys. Getting this wrong is silent."""
    sb = ldr_trial.build_settings("source-based", "m", "searxng", 3, 2, True)
    assert sb["search.questions"] == 2
    assert "search.questions_per_iteration" not in sb

    fi = ldr_trial.build_settings("focused-iteration", "m", "searxng", 3, 2, True)
    assert fi["search.questions_per_iteration"] == 2
    assert "search.questions" not in fi


def test_build_settings_always_sets_iterations_and_snippets():
    for strategy in ldr_trial.QUESTIONS_KEY:
        s = ldr_trial.build_settings(strategy, "m", "searxng", 4, 1, False)
        assert s["search.iterations"] == 4, strategy
        assert s["search.snippets_only"] is False, strategy


def test_unknown_strategy_is_rejected_loudly():
    try:
        ldr_trial.build_settings("focused_iteration", "m", "searxng", 1, 1, True)
    except ValueError:
        return
    raise AssertionError("underscore form accepted; it is not a live enum member and would "
                         "silently fall back to the default strategy")


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {name}: {e}")
    print(f"\n{fails} failure(s)")
    sys.exit(1 if fails else 0)
