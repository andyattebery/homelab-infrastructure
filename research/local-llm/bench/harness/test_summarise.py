#!/usr/bin/env python3
"""Tests for the shootout summary.

    python3 test_summarise.py       # Mac, no GPU, no container

The interesting test is `test_wilson_reproduces_upstreams_published_table`: it checks the
confidence-interval maths against **upstream's own numbers**, not against my arithmetic.
Reimplementing a formula and then testing it with values computed by the same
reimplementation proves only self-consistency — the failure mode that let a broken resume key
pass its unit test earlier today.
"""

import json
import sys
import tempfile
from pathlib import Path

import summarise


# docs/BENCHMARKING.md:67-75 — "95% confidence margin of error by sample size".
# Rows are (n, accuracy, published ±). Upstream rounds to whole points.
PUBLISHED = [
    (20, 0.70, 21), (20, 0.85, 17), (20, 0.91, 14), (20, 0.95, 10),
    (50, 0.70, 13), (50, 0.85, 10), (50, 0.91, 8), (50, 0.95, 6),
    (100, 0.70, 9), (100, 0.85, 7), (100, 0.91, 6), (100, 0.95, 4),
    (200, 0.70, 6), (200, 0.85, 5), (200, 0.91, 4), (200, 0.95, 3),
    (500, 0.70, 4), (500, 0.85, 3), (500, 0.91, 3), (500, 0.95, 2),
]


def test_wilson_reproduces_upstreams_published_table_for_n_50_and_above():
    """Cross-check against upstream's numbers, not against my own arithmetic.

    **Every row at n>=50 matches within a point of rounding.** That is the meaningful
    validation: it pins the implementation to an independently published table.
    """
    bad = []
    for n, p, expected in PUBLISHED:
        if n < 50:
            continue
        _, half = summarise.wilson(round(p * n), n)
        if abs(half - expected) > 1.0:
            bad.append(f"n={n} p={p:.0%}: got ±{half:.1f}, table says ±{expected}")
    assert not bad, "Wilson interval disagrees with BENCHMARKING.md:\n  " + "\n  ".join(bad)


def test_upstreams_n20_row_disagrees_with_upstreams_own_formula():
    """Recorded rather than papered over: at n=20 the published table matches **neither**
    the Wilson formula the same document states (`BENCHMARKING.md:60-65`) nor the normal
    approximation.

        n=20    published   Wilson   normal
        70%       21%        18.7     20.1
        85%       17%        15.4     15.6
        95%       10%        11.4      9.6

    It is not a systematic variant — published is *wider* at 70/85 and *narrower* at 95 — so
    that row appears independently derived or hand-rounded. Everything at n>=50 agrees, where
    the two methods have converged and the table cannot distinguish them.

    We follow the stated formula, which makes our n=20 interval ~2 points **narrower** than
    the table, i.e. marginally less conservative. It changes nothing operationally: the whole
    point of `BENCHMARKING.md` is that n=20 is for elimination, not ranking. This test exists
    so the discrepancy is a known, deliberate position rather than a silent one.
    """
    for n, p, published in [(20, 0.70, 21), (20, 0.85, 17), (20, 0.95, 10)]:
        _, half = summarise.wilson(round(p * n), n)
        assert abs(half - published) > 1.0, (
            f"n={n} p={p:.0%} now agrees with the table (±{half:.1f} vs ±{published}) — "
            f"upstream may have corrected it; re-read BENCHMARKING.md and drop this test")
        assert abs(half - published) < 4.0, (
            f"n={n} p={p:.0%}: ±{half:.1f} vs published ±{published} — a gap this large "
            f"suggests our formula is wrong, not merely a different rounding")


def test_wilson_stays_inside_zero_and_one_hundred():
    """Why Wilson and not the normal approximation: at 20/20 the naive interval runs past
    100%, which is how a 'better than perfect' score gets published."""
    centre, half = summarise.wilson(20, 20)
    assert centre + half <= 100.0001, (centre, half)
    centre, half = summarise.wilson(0, 20)
    assert centre - half >= -0.0001, (centre, half)


def test_wilson_of_nothing_is_not_a_crash():
    assert summarise.wilson(0, 0) == (0.0, 0.0)


# --------------------------------------------------------------- scoring proxy

def _rec(**kw):
    base = {"ok": True, "strategy": "source-based", "snippets_only": True,
            "correct_answer": "University of Bonn.", "summary": "He studied at the "
            "University of Bonn, then moved on.", "wall_s": 200.0,
            "cost": {"peak_total": 5000, "calls": 5, "truncated": 0}}
    return {**base, **kw}


def test_proxy_matches_ground_truth_ignoring_case_and_trailing_period():
    assert summarise.is_correct(_rec()) is True
    assert summarise.is_correct(_rec(summary="he studied at the university of bonn")) is True


def test_proxy_is_none_when_the_trial_cannot_be_scored():
    """Unscorable must not silently count as wrong — that would deflate every cell."""
    assert summarise.is_correct(_rec(ok=False)) is None
    assert summarise.is_correct(_rec(summary="   ")) is None
    assert summarise.is_correct(_rec(correct_answer="")) is None


def test_proxy_undercounts_semantic_equivalents_and_that_is_documented():
    """The known weakness, pinned so nobody mistakes the proxy for a grade: a correct answer
    phrased differently scores as wrong."""
    assert summarise.is_correct(
        _rec(summary="He studied at Rheinische Friedrich-Wilhelms-Universität.")) is False
    assert "UNDERCOUNTS" in summarise.__doc__ or "undercounts" in summarise.__doc__


# --------------------------------------------------------------- aggregation

def test_failed_and_unscorable_trials_do_not_enter_the_denominator():
    rows = [_rec(), _rec(summary="wrong answer entirely"),
            _rec(ok=False, error="boom"), _rec(summary="")]
    agg = summarise.summarise(rows)["source-based/snippets"]
    assert agg["trials"] == 4 and agg["failed"] == 1
    assert agg["scored"] == 2, "an empty summary or a failure must not count as incorrect"
    assert agg["hits"] == 1


def test_verdict_refuses_to_name_a_winner_when_intervals_overlap():
    """At n=20 nearly everything overlaps; the summary must say so rather than rank."""
    rows = ([_rec(strategy="a") for _ in range(7)]
            + [_rec(strategy="a", summary="no") for _ in range(3)]
            + [_rec(strategy="b") for _ in range(6)]
            + [_rec(strategy="b", summary="no") for _ in range(4)])
    v = summarise.verdict(summarise.summarise(rows))
    assert "NO WINNER" in v, v


def test_verdict_names_a_leader_only_when_intervals_separate():
    rows = ([_rec(strategy="a") for _ in range(60)]
            + [_rec(strategy="b", summary="no") for _ in range(60)])
    v = summarise.verdict(summarise.summarise(rows))
    assert "leads" in v and "PROXY" in v, v


def test_truncation_and_missing_capture_are_surfaced():
    rows = [_rec(cost={"peak_total": 9, "calls": 1, "truncated": 1}), _rec(cost=None)]
    agg = summarise.summarise(rows)["source-based/snippets"]
    assert agg["truncated"] == 1
    assert agg["capture_missing"] == 1, "a missing capture must be counted, not ignored"


def test_zero_search_answers_are_counted():
    """The Onyx failure mode. A cell answering without searching must be visible even if it
    scores well on the proxy."""
    agg = summarise.summarise([_rec(searched=False), _rec(searched=True)])
    assert agg["source-based/snippets"]["no_search"] == 1


def test_zero_source_trials_are_counted_separately():
    """Searched-but-found-nothing is not the same as did-not-search, and neither is a
    strategy defect. Observed live: some SimpleQA questions return nothing from SearXNG."""
    agg = summarise.summarise([_rec(source_count=0), _rec(source_count=5)])
    assert agg["source-based/snippets"]["no_sources"] == 1


def test_dead_questions_are_those_no_cell_could_answer():
    """A question where every cell got zero sources measures the search engine. It must be
    surfaced, because otherwise every cell silently scores wrong on it and the comparison
    quietly loses a sample."""
    rows = [_rec(question_id="q1", strategy="a", source_count=0),
            _rec(question_id="q1", strategy="b", source_count=0),
            _rec(question_id="q2", strategy="a", source_count=0),
            _rec(question_id="q2", strategy="b", source_count=7)]
    assert summarise.dead_questions(rows) == ["q1"], "q2 had sources in one cell"


def test_dead_questions_ignores_incomplete_cycles():
    """THE mid-run trap. A question with only one finished cell that retrieved nothing is
    indistinguishable from a genuinely dead one until every cell has had its turn — this
    produced a wrong 'dead question' reading against live partial data."""
    rows = [_rec(question_id="q1", strategy="a", source_count=0),
            _rec(question_id="q2", strategy="a", source_count=0),
            _rec(question_id="q2", strategy="b", source_count=0),
            _rec(question_id="q2", strategy="c", source_count=0)]
    # grid inferred as 3 cells from q2; q1 has only 1 and must not be judged
    assert summarise.dead_questions(rows) == ["q2"]
    # and with the width supplied explicitly
    assert summarise.dead_questions(rows, n_cells=3) == ["q2"]


def test_dead_questions_ignores_failed_trials():
    rows = [_rec(question_id="q1", source_count=0, ok=False, error="boom")]
    assert summarise.dead_questions(rows) == []


def test_load_tolerates_a_truncated_final_line():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.jsonl"
        f.write_text(json.dumps(_rec()) + "\n" + '{"strategy": "sou')
        assert len(summarise.load(str(f))) == 1


def test_render_reports_n_and_interval_for_every_cell():
    """No bare percentages: BENCHMARKING.md's whole point is that a score without its N and
    interval invites a decision the data cannot support."""
    out = summarise.render(summarise.summarise([_rec(), _rec(summary="no")]))
    assert "±" in out and "1/2" in out


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
