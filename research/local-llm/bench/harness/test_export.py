#!/usr/bin/env python3
"""Tests for the blind grading export.

    python3 test_export.py      # Mac, no GPU, no container

Blinding is the property that cannot be checked by looking at the output later: once a
grading thread has read an anchored packet, the grades are contaminated and nothing about the
files afterwards reveals it. So it is asserted here, mechanically, against the real packet
builder.
"""

import json
import sys
import tempfile
from pathlib import Path

import export


def _rec(**kw):
    base = {
        "ok": True, "strategy": "focused-iteration", "snippets_only": True,
        "question_id": "simpleqa-s42-0000", "question": "Which university?",
        "correct_answer": "University of Bonn.",
        "summary": "He studied medicine at the University of Bonn.",
        "source_count": 2, "wall_s": 200.0, "returned_iterations": 8, "searched": True,
        "sources": [{"link": "https://en.wikipedia.org/wiki/X", "title": "X — Wikipedia",
                     "snippet": "He studied at Bonn."},
                    {"link": "https://example.org/y", "title": "Y", "snippet": "More."}],
        "settings_overrides": {"search.tool": "searxng", "llm.model": "gemma-4-12b-it",
                               "llm.provider": "openai_endpoint",
                               "search.iterations": 8, "search.questions_per_iteration": 5,
                               "search.snippets_only": True},
    }
    return {**base, **kw}


# --------------------------------------------------------------------------- blinding

def test_packet_carries_no_configuration_string():
    """THE property. A judge that sees `focused-iteration` anchors on it, and this campaign
    exists because the strategy was previously chosen on reputation."""
    r = _rec()
    text = export.packet(r, "abc1234567")
    assert export.leaks(text, export.config_terms(r)) == [], text[:400]
    for term in ("focused-iteration", "source-based", "gemma", "searxng", "snippets_only"):
        assert term.lower() not in text.lower(), f"{term!r} leaked into the packet"


def test_fetched_page_text_never_reaches_a_packet():
    """The depth arm is the one axis a judge could identify WITHOUT any config string being
    present: 4000-char page extracts in one arm and 245-char snippets in the other is a
    tell. Measured at the engine layer: median 245 vs 4192 chars on the same query. So
    `extract_sources` records full_content's LENGTH and a short head for auditing, and
    neither may ever be rendered into a packet."""
    r = _rec(sources=[{"link": "https://en.wikipedia.org/wiki/X", "title": "X — Wikipedia",
                       "snippet": "He studied at Bonn.",
                       "full_content_chars": 4192,
                       "full_content_head": "GUSTAV NACHTIGAL PAGE TEXT " * 15}])
    text = export.packet(r, "t")
    assert "GUSTAV NACHTIGAL PAGE TEXT" not in text, "fetched page text leaked into a packet"
    assert "4192" not in text, "the fetched-content length leaked into a packet"


def test_packets_are_the_same_shape_in_both_depth_arms():
    """Same sources, one arm with fetched content and one without, must render identically —
    otherwise packet length alone separates the arms."""
    srcs = [{"link": "https://e.org/a", "title": "A", "snippet": "short snip",
             "full_content_chars": 0, "full_content_head": None}]
    deep = [{**srcs[0], "full_content_chars": 5000, "full_content_head": "x" * 400}]
    assert export.packet(_rec(sources=srcs), "t") == export.packet(
        _rec(sources=deep, snippets_only=False), "t")


def test_leak_detector_actually_detects():
    """A blinding check that cannot fail is theatre — prove it fires."""
    assert export.leaks("ran with focused-iteration", ["focused-iteration"]) \
        == ["focused-iteration"]
    assert export.leaks("nothing here", ["focused-iteration"]) == []


def test_config_terms_covers_every_string_override():
    """Derived from the record, so a new string knob is covered without editing this test."""
    terms = export.config_terms(_rec())
    assert "focused-iteration" in terms and "gemma-4-12b-it" in terms and "searxng" in terms


def test_a_leaking_packet_is_refused_not_written(tmp=None):
    """If a packet would leak, it must be dropped and reported — never written. An anchored
    grade looks measured and is not, which is worse than a missing one."""
    r = _rec(summary="I used the focused-iteration strategy and found the University of Bonn.")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.jsonl"
        src.write_text(json.dumps(r) + "\n")
        out = Path(d) / "out"
        import subprocess
        p = subprocess.run([sys.executable, str(Path(__file__).parent / "export.py"),
                            "--in", str(src), "--out", str(out)],
                           capture_output=True, text=True)
        assert "REFUSED" in p.stdout, p.stdout
        assert not list((out / "answers").glob("*.md")), "a leaking packet was written"


# --------------------------------------------------------------------------- identity

def test_tid_is_stable_across_exports():
    assert export.tid_of(_rec()) == export.tid_of(_rec())


def test_two_cells_differing_only_in_a_knob_do_not_collide():
    """The failure that would silently overwrite one cell's answer with another's."""
    a = _rec()
    b = _rec(settings_overrides={**a["settings_overrides"], "search.snippets_only": False})
    assert export.tid_of(a) != export.tid_of(b)


def test_different_questions_differ():
    assert export.tid_of(_rec()) != export.tid_of(_rec(question_id="simpleqa-s42-0001"))


# --------------------------------------------------------------------------- content

def test_packet_gives_the_judge_what_the_rubric_asks_for():
    text = export.packet(_rec(), "t")
    for needed in ("## Question", "## Known correct answer",
                   "## The assistant's response", "University of Bonn"):
        assert needed in text, needed
    # ground truth must be present: the whole reason SimpleQA grading is cheap
    assert "Known correct answer" in text


def test_sources_render_as_url_and_title_not_a_dict_repr():
    """Sources are dicts; `str(s)` would put `{'link': ...}` in front of a judge, which
    cannot be used to check a citation."""
    text = export.packet(_rec(), "t")
    assert "https://en.wikipedia.org/wiki/X" in text
    assert "{'link'" not in text and '{"link"' not in text


def test_ungradable_trials_are_skipped_and_counted():
    assert not export.gradable(_rec(ok=False))
    assert not export.gradable(_rec(summary="  "))
    assert not export.gradable(_rec(correct_answer=""))
    assert export.gradable(_rec())


def test_end_to_end_writes_the_four_artifacts_and_withholds_the_key():
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.jsonl"
        src.write_text("\n".join(json.dumps(_rec(question_id=f"q{i}")) for i in range(3)))
        out = Path(d) / "out"
        p = subprocess.run([sys.executable, str(Path(__file__).parent / "export.py"),
                            "--in", str(src), "--out", str(out)],
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        assert (out / "RUBRIC.md").exists() and (out / "KEY.json").exists()
        assert len(list((out / "answers").glob("*.md"))) == 3
        grades = [json.loads(l) for l in
                  (out / "grades.template.jsonl").read_text().splitlines() if l.strip()]
        assert len(grades) == 3 and all(g["correct"] is None for g in grades)
        # The key holds the config; the answers must not.
        key = json.loads((out / "KEY.json").read_text())
        assert all("strategy" in v for v in key.values())
        for f in (out / "answers").glob("*.md"):
            assert "focused-iteration" not in f.read_text()


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
