#!/usr/bin/env python3
"""Tests for the shootout runner and record validation.

    python3 test_shootout.py      # Mac, no GPU, no container, no LDR installed

Everything here exercises the real functions the sweep uses — `plan`, `Trial.key`,
`load_done`, `status_report`, `Capture`, `records.check` — not reimplementations of them.
"""

import json
import sys
import tempfile
from pathlib import Path

import records
import shootout

Q = [{"id": "q1", "question": "one?", "correct_answer": "1"},
     {"id": "q2", "question": "two?", "correct_answer": "2"}]


# --------------------------------------------------------------------------- the grid

def test_grid_is_every_strategy_times_every_depth():
    """Shape follows the constants rather than a hardcoded 6, because DEPTHS legitimately
    changed size: the snippets/full arm was measured to be a no-op and dropped to one value
    (see the comment on DEPTHS). A test asserting 6 would have to be edited to lie."""
    cs = shootout.cells()
    assert len(cs) == len(shootout.STRATEGIES) * len(shootout.DEPTHS), [c.label for c in cs]
    assert {c.strategy for c in cs} == set(shootout.STRATEGIES)
    assert {c.snippets_only for c in cs} == set(shootout.DEPTHS)
    # Distinct labels, or two cells collide in status_report and in the resume key.
    assert len({c.label for c in cs}) == len(cs)


def test_question_is_outermost_so_a_partial_run_stays_comparable():
    """The ordering claim, asserted rather than asserted-in-a-comment.

    Truncating the plan anywhere at a cell boundary must leave every cell within one trial of
    every other. Cell-outermost would finish cell 1 entirely before starting cell 2, so an
    interrupted pilot would have n=20 for one cell and n=0 for another — not a result.
    """
    p = shootout.plan(Q)
    assert len(p) == len(Q) * len(shootout.cells())

    # The first 6 trials are all of q1; only then does q2 begin.
    n = len(shootout.cells())
    assert {t.question_id for t in p[:n]} == {"q1"}
    assert {c.label for c in (t.cell for t in p[:n])} == {c.label for c in shootout.cells()}

    # And the invariant that matters: at ANY truncation point, per-cell counts differ by <=1.
    for cut in range(1, len(p) + 1):
        counts: dict[str, int] = {}
        for t in p[:cut]:
            counts[t.cell.label] = counts.get(t.cell.label, 0) + 1
        for c in shootout.cells():
            counts.setdefault(c.label, 0)
        assert max(counts.values()) - min(counts.values()) <= 1, (
            f"cut={cut} leaves cells unbalanced: {counts}")


def test_each_strategy_runs_at_its_own_default():
    """A shared (i,q) would handicap whichever strategy it does not suit —
    focused_iteration_strategy.py:65-66 calls (8,5) optimal for SimpleQA."""
    d = {c.strategy: c.defaults for c in shootout.cells()}
    assert d["focused-iteration"] != d["source-based"], (
        "the two strategies now share defaults; verify that is intended rather than a "
        "copy-paste, because it decides whether the comparison is fair")
    for s in shootout.STRATEGIES:
        assert d[s]["iterations"] > 0 and d[s]["questions"] > 0


# --------------------------------------------------------------------------- the key

def test_key_covers_the_whole_override_dict_not_a_hand_listed_tuple():
    """Two trials differing ONLY in a settings knob must not collide."""
    a = shootout.Trial(shootout.Cell("source-based", True), "q1", "one?")
    b = shootout.Trial(shootout.Cell("source-based", False), "q1", "one?")
    assert a.key != b.key, "snippets_only does not reach the key — the two depth arms would "\
                           "overwrite each other on resume"


def _record_as_the_runner_writes_it(t) -> dict:
    """Build a row the way ldr_trial.py actually does — from the trial's REAL model and
    search tool.

    Deliberately NOT `build_settings(strategy, "", "", ...)`. The previous version of this
    helper used those placeholders on both sides of the comparison, so the test was
    self-consistent and passed while resume was completely broken in production: the plan's
    key carried empty strings, the written row carried "gemma-4-12b-it"/"searxng", and
    nothing ever matched. A fixture must be built the way the real writer builds it, or it
    only tests itself.
    """
    import ldr_trial
    return {"strategy": t.cell.strategy, "question_id": t.question_id,
            "settings_overrides": ldr_trial.build_settings(
                t.cell.strategy, t.model, t.search_tool,
                t.cell.defaults["iterations"], t.cell.defaults["questions"],
                t.cell.snippets_only),
            "ok": True}


def test_key_round_trips_through_a_written_record():
    """`load_done` recovers the key from a row; if the two derivations drift, resume either
    re-runs everything or skips everything."""
    t = shootout.plan(Q, "gemma-4-12b-it", "searxng")[0]
    assert shootout.key_of_record(_record_as_the_runner_writes_it(t)) == t.key


def test_resume_matches_when_the_run_config_is_supplied():
    """THE regression. Round 1 wrote 3 rows and `--status` reported 0 done, because the
    plan's key used placeholder model/search_tool while the rows carried the real ones."""
    import tempfile, json as _json
    p = shootout.plan(Q, "gemma-4-12b-it", "searxng")
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "out.jsonl"
        f.write_text(_json.dumps(_record_as_the_runner_writes_it(p[0])) + "\n")
        done = shootout.load_done(str(f))
        assert p[0].key in done, "resume failed to recognise a row it just wrote"
        assert len([t for t in p if t.key not in done]) == len(p) - 1


def test_a_different_model_is_a_different_trial():
    """model is part of the config, so it must be part of the key — otherwise a re-run under
    a different model would be skipped as already done."""
    a = shootout.plan(Q, "gemma-4-12b-it", "searxng")[0]
    b = shootout.plan(Q, "qwen3.5-9b", "searxng")[0]
    assert a.key != b.key


# --------------------------------------------------------------------------- resume

def _write(path: Path, recs: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_completed_keys_are_skipped_and_a_truncated_line_is_tolerated():
    p = shootout.plan(Q, "gemma-4-12b-it", "searxng")
    first = p[0]
    rec = _record_as_the_runner_writes_it(first)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "out.jsonl"
        # A killed writer leaves a half line; it must be ignored, not crash the resume.
        f.write_text(json.dumps(rec) + "\n" + '{"strategy": "source-b')
        done = shootout.load_done(str(f))
        assert first.key in done
        assert len([t for t in p if t.key not in done]) == len(p) - 1


def test_failed_trials_are_retried_by_default_and_not_with_the_flag():
    """A failed trial holds no measurement — only that something went wrong once. Treating
    it as complete locks a transient blip into the file forever."""
    t = shootout.plan(Q, "gemma-4-12b-it", "searxng")[0]
    rec = {**_record_as_the_runner_writes_it(t), "ok": False, "error": "boom"}
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "out.jsonl"
        _write(f, [rec])
        assert t.key not in shootout.load_done(str(f), retry_failed=True)
        assert t.key in shootout.load_done(str(f), retry_failed=False)


def test_status_report_counts_per_cell():
    p = shootout.plan(Q)
    out = shootout.status_report(p, {p[0].key})
    assert "TOTAL" in out and f"1/{len(Q) * len(shootout.cells())}" in out.replace(" ", "")


# --------------------------------------------------------------------------- capture

def test_capture_region_is_none_when_there_is_no_capture():
    """No capture configured must yield UNKNOWN, never a zero-cost row."""
    c = shootout.Capture(None)
    assert c.region(0, 10) is None
    assert c.present() is False


def test_an_empty_capture_file_is_present_but_has_not_grown():
    """THE startup case. `?no-history` streams live only, so before the first query the
    file exists and is empty. A size-based startup check would abort every sweep on its
    first line, before a single trial ran."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "cap.log"
        f.write_text("")
        c = shootout.Capture(str(f))
        assert c.present() is True, "an empty capture must not block startup"
        assert c.grew() is False, "nothing captured yet"
        f.write_text("slot release: id 0 | task 0 | stop processing: n_tokens = 1, "
                     "truncated = 0\n")
        assert c.grew() is True, "growth after real traffic must be detected"


def test_capture_attributes_only_its_own_region():
    line = ("slot print_timing: id  0 | task {t} | prompt eval time = 1.0 ms / {p} tokens\n"
            "slot print_timing: id  0 | task {t} | n_decoded = {d}, tg = 44.0 t/s\n"
            "slot      release: id  0 | task {t} | stop processing: n_tokens = {n}, "
            "truncated = 0\n")
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "cap.log"
        f.write_text(line.format(t=0, p=100, d=50, n=150))
        c = shootout.Capture(str(f))
        start = c.mark()
        # A second trial's traffic appends, with ids RESET — as a llama-server restart does.
        with open(f, "a") as fh:
            fh.write(line.format(t=0, p=900, d=80, n=980))
        got = c.region(start, c.mark())
        assert got["calls"] == 1 and got["peak_prompt"] == 900, got


# --------------------------------------------------------------------------- records

def _good() -> dict:
    return {"question_id": "q1", "question": "one?", "strategy": "source-based",
            "settings_overrides": {"search.iterations": 3}, "summary": "an answer",
            "sources": [{"link": "https://x/y", "title": "T", "snippet": "s"}],
            "source_count": 1, "wall_s": 12.0, "ok": True,
            "requested_iterations": 3, "returned_iterations": 3,
            "requested_questions": 3, "observed_questions": [3, 3, 3], "searched": True}


def test_a_good_record_has_no_problems():
    assert records.check(_good()) == []
    assert records.usable(_good())


def test_silently_ignored_iterations_is_caught():
    """THE failure this project actually had: a healthy-looking row whose config is a lie."""
    r = _good() | {"requested_iterations": 1, "returned_iterations": 3}
    probs = records.check(r)
    assert any("NOT honoured" in p for p in probs), probs
    assert not records.usable(r), "a mislabelled row must not reach a score"


def test_empty_summary_is_flagged_not_dropped():
    r = _good() | {"summary": "   "}
    assert any("empty summary" in p for p in records.check(r))
    assert not records.usable(r)


def test_answered_without_searching_is_flagged_but_still_scorable():
    """For langgraph-agent this IS the measurement, so it must be visible without being
    treated as corruption."""
    r = _good() | {"searched": False}
    assert any("WITHOUT SEARCHING" in p for p in records.check(r))
    assert records.usable(r)


def test_under_filled_questions_flagged_but_not_fatal():
    r = _good() | {"observed_questions": [1, 1, 1]}
    probs = records.check(r)
    assert any("questions differ" in p for p in probs), probs
    assert records.usable(r), "an LLM generating fewer questions is a finding, not corruption"


def test_lost_source_urls_are_fatal():
    r = _good() | {"sources": [], "source_count": 4}
    assert any("cannot be recovered" in p for p in records.check(r))
    assert not records.usable(r)


def test_stringified_sources_are_caught():
    """`str(s)` on the dicts would produce exactly this, and a judge cannot check a repr."""
    r = _good() | {"sources": ["{'link': 'https://x'}"]}
    assert any("not dict" in p for p in records.check(r))


def test_truncated_and_missing_cost_are_both_reported():
    assert any("UNKNOWN, not zero" in p for p in records.check(_good() | {"cost": None}))
    assert any("truncated" in p
               for p in records.check(_good() | {"cost": {"truncated": 1}}))


def test_failed_record_needs_only_identity_and_a_reason():
    bad = {"question_id": "q1", "strategy": "source-based",
           "settings_overrides": {}, "ok": False, "error": "TimeoutExpired"}
    assert records.check(bad) == []
    assert not records.usable(bad)
    assert any("unattributable" in p
               for p in records.check(bad | {"error": ""}))


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
