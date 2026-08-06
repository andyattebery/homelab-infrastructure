#!/usr/bin/env python3
"""Export shootout trials as BLIND grading packets for a fresh Claude Code thread.

    python3 export.py --in runs/round1.jsonl --out runs/round1-grading/

Writes:
    <out>/RUBRIC.md              what to grade and how — give this to the judge
    <out>/answers/<tid>.md       one trial per file, blinded
    <out>/KEY.json               tid -> cell. **DO NOT give this to the judge**
    <out>/grades.template.jsonl  one pre-filled line per trial

WHY A BLIND THREAD AND NOT THE PROXY
------------------------------------
`summarise.py` prints a substring proxy that undercounts by an unknown amount — "Rheinische
Friedrich-Wilhelms-Universität" is a correct answer to "which university" that no substring
test against "University of Bonn" will ever match. It ranks cells cheaply; it cannot be the
result.

WHY BLIND
---------
A judge that can see `focused-iteration` next to an answer anchors on it, and this campaign
exists to test a strategy choice that was previously made on reputation rather than
measurement. The cell lives only in `KEY.json`, which stays out of the grading thread.

WHY THIS IS CHEAP HERE
----------------------
SimpleQA ships ground truth, so the judge is *given* the answer and only has to decide
equivalence — no web research per item. That is the whole reason the tuning set is SimpleQA
and the seven queries are kept for confirmation (`current-work.md` decision 5).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

RUBRIC = """# Grading — local-deep-research, SimpleQA tuning set

Each file in `answers/` holds one question, the **known correct answer**, and a research
assistant's response. Decide whether the response gets the answer right.

**You do not know which configuration produced which answer. That is deliberate — do not
speculate about it, and do not let writing style or verbosity sway the score.**

## The judgement

You are given ground truth, so this is an equivalence decision, not research. Mark `correct`:

| value | meaning |
|---|---|
| `1` | The response states the correct answer. Different phrasing, extra detail, a fuller official name, or a translation all still count |
| `0` | The response states something else, hedges without committing, or says it could not find an answer |

**Equivalence examples that are `1`:** "Bonn" / "the University of Bonn" / "Rheinische
Friedrich-Wilhelms-Universität Bonn" are the same institution. "1998" and "in 1998" are the
same year.

**`0` even though it looks close:** naming a *different* entity of the same type; giving a
range or list that merely contains the right answer without committing to it; answering a
different question.

## Also record

| field | values |
|---|---|
| `correct` | 0 or 1, as above |
| `stated_answer` | the specific claim the response actually made, quoted briefly — this is what makes a disputed grade re-checkable |
| `hedged` | true if it never commits to an answer |
| `sources_support` | 0-2: 2 = the listed sources plausibly contain the answer, 1 = unclear, 0 = the answer is not supported by anything listed |
| `notes` | anything the numbers miss |

`sources_support` is a **weak** signal here: each source is shown as a short search snippet,
never the full page, whatever the assistant itself read. Judge what is shown, and do not
penalise an answer for a snippet being short or for omitting detail the snippet lacks.

## Output

Complete `grades.template.jsonl` — one JSON object per line, `tid` exactly as given. Return
only that file's contents.
"""


def tid_of(rec: dict) -> str:
    """Stable, opaque id: the same trial gets the same tid across exports.

    Derived from the FULL settings-override dict plus strategy and question, i.e. the same
    identity the runner resumes on. A hand-listed tuple would let two cells that differ only
    in a knob collide into one answer file, silently overwriting one of them.
    """
    raw = json.dumps({"strategy": rec.get("strategy"),
                      "question_id": rec.get("question_id"),
                      "overrides": rec.get("settings_overrides")}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def gradable(rec: dict) -> bool:
    return bool(rec.get("ok") and (rec.get("summary") or "").strip()
                and (rec.get("correct_answer") or "").strip())


def packet(rec: dict, tid: str) -> str:
    """One blinded answer file. Contains NOTHING identifying the configuration."""
    body = [f"# Trial {tid}", "",
            "## Question", "", rec.get("question", "(missing)"), "",
            "## Known correct answer", "", rec.get("correct_answer", "(missing)"), "",
            "## The assistant's response", "", rec.get("summary") or "(empty)", "",
            f"## Sources the assistant listed ({rec.get('source_count', 0)})", ""]
    srcs = rec.get("sources") or []
    if not srcs:
        body.append("_(none listed)_")
    for s in srcs[:25]:
        title = (s.get("title") or "").strip() or "(untitled)"
        link = (s.get("link") or "").strip() or "(no url)"
        snippet = " ".join((s.get("snippet") or "").split())[:300]
        body.append(f"- **{title}** — {link}")
        if snippet:
            body.append(f"  > {snippet}")
    if len(srcs) > 25:
        body.append(f"\n_({len(srcs) - 25} further sources omitted for length.)_")
    return "\n".join(body) + "\n"


def leaks(text: str, terms: list[str]) -> list[str]:
    """Configuration strings that must never appear in a blinded packet."""
    low = text.lower()
    return sorted({t for t in terms if t and t.lower() in low})


def config_terms(rec: dict) -> list[str]:
    """Every string that would identify this trial's cell to a judge."""
    out = [rec.get("strategy") or ""]
    for k, v in (rec.get("settings_overrides") or {}).items():
        if isinstance(v, str):
            out.append(v)
    return [t for t in out if t]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    a = ap.parse_args()

    out = Path(a.out)
    (out / "answers").mkdir(parents=True, exist_ok=True)

    key, templates, skipped, leaked = {}, [], 0, []
    for line in Path(a.src).read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue                       # truncated final line
        if not gradable(rec):
            skipped += 1                   # counted, never silently dropped
            continue
        tid = tid_of(rec)
        text = packet(rec, tid)

        bad = leaks(text, config_terms(rec))
        if bad:
            # Refuse rather than emit an anchored packet. A leaked strategy name makes the
            # grade worth less than no grade, because it looks measured and is not.
            leaked.append((tid, bad))
            continue

        (out / "answers" / f"{tid}.md").write_text(text)
        key[tid] = {k: rec.get(k) for k in
                    ("strategy", "snippets_only", "question_id", "wall_s",
                     "source_count", "returned_iterations", "searched")}
        key[tid]["settings_overrides"] = rec.get("settings_overrides")
        templates.append({"tid": tid, "correct": None, "stated_answer": "",
                          "hedged": None, "sources_support": None, "notes": ""})

    (out / "RUBRIC.md").write_text(RUBRIC)
    (out / "KEY.json").write_text(json.dumps(key, indent=2))
    with (out / "grades.template.jsonl").open("w") as fh:
        for t in templates:
            fh.write(json.dumps(t) + "\n")

    print(f"exported {len(templates)} answers to {out}/answers/")
    if skipped:
        print(f"skipped {skipped} ungradable trial(s) (failed, empty summary, or no ground "
              f"truth) — counted here so they are not silently missing from the denominator")
    if leaked:
        print(f"REFUSED {len(leaked)} packet(s) that leaked their configuration:")
        for tid, bad in leaked:
            print(f"   {tid}: {bad}")
    print(f"give the judge: RUBRIC.md + answers/ + grades.template.jsonl")
    print(f"KEEP BACK:      KEY.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
