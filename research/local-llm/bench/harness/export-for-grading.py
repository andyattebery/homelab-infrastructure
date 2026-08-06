#!/usr/bin/env python3
"""
Export sweep results as BLIND grading packets for a fresh Claude Code thread.

    python3 research/local-llm/bench/harness/export-for-grading.py \
        --in runs/ldr-matrix.jsonl --out runs/grading/

Writes:
    <out>/RUBRIC.md            what to grade and how -- give this to the judge
    <out>/answers/<tid>.md     one answer per file, blinded
    <out>/KEY.json             tid -> config. DO NOT give this to the judge.
    <out>/grades.template.jsonl one pre-filled line per trial for the judge to complete

Why blind: a judge that can see "qwen3.5-9b" or "iterations=3" next to an answer will
anchor on it. The config lives only in KEY.json, which stays out of the grading thread.
Merge grades back by tid afterwards.

Why a fresh thread rather than examples/benchmarks/claude_grading: that path needs a paid
Claude API key in LDR's database, and grades from the model's own memory. A fresh thread
can WEB-SEARCH each factual claim, which is what "is the information correct" actually
requires.
"""

import argparse
import hashlib
import json
import os

RUBRIC = """# Grading rubric — local-deep-research answers

You are grading answers produced by a self-hosted research assistant. Each file in
`answers/` contains a question, the assistant's answer, and the sources it says it used.
**You do not know which model or settings produced which answer. That is deliberate — do
not speculate about it.**

## What actually matters

**Correctness of the information is the metric.** Real citations are necessary but not
sufficient: an answer can cite a genuine page and still state a wrong number, misread the
source, or attribute a claim to the wrong place.

**Verify factual claims against live sources.** Search the web. Do not grade from memory —
several of these questions concern software versions and hardware specifications where
your training data may be stale or wrong, and that is precisely the failure being measured.

## Scores — for each answer emit

| field | values | meaning |
|---|---|---|
| `correct` | 0-3 | 3 = all substantive claims verified true. 2 = minor error not affecting the conclusion. 1 = a materially wrong claim. 0 = mostly wrong, or confidently answers something unanswerable |
| `sourced` | 0-3 | 3 = claims traceable to the cited sources. 2 = mostly. 1 = citations present but largely decorative. 0 = **fabricated** — cited sources that do not exist or do not contain the claim |
| `useful` | 0-3 | would this answer the question for a technical reader |
| `wrong_claims` | list of strings | quote each incorrect claim and state what is actually true |
| `notes` | string | anything the numbers do not capture |

`sourced = 0` is the specific failure this project exists to prevent — an earlier harness
invented a four-entry source list. **Check that cited URLs exist and support the claim**,
rather than trusting that a list is present.

## Special cases

- One question is **deliberately unanswerable** (a p99 latency figure nobody has
  published). The correct behaviour is saying so. Confidently inventing a number is
  `correct = 0`, no matter how well written.
- One question is **answerable from general knowledge** and needs no search. Searching
  anyway is not wrong, but a wrong answer is still wrong.

## Output

Complete `grades.template.jsonl` — one JSON object per line, keeping `tid` exactly as
given. Return only that file's contents.
"""


def tid_of(rec: dict) -> str:
    """Stable, opaque id: same trial always gets the same tid across exports."""
    raw = "|".join(str(rec.get(k)) for k in
                   ("model", "strategy", "iterations", "questions",
                    "temperature", "query_id"))
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="out", required=True)
    args = p.parse_args()

    os.makedirs(os.path.join(args.out, "answers"), exist_ok=True)

    key, templates, n = {}, [], 0
    with open(args.src) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue                      # tolerate a truncated final line
            if not r.get("ok") or not r.get("summary"):
                continue                      # failed trials are cost data, not gradable
            tid = tid_of(r)
            key[tid] = {k: r.get(k) for k in
                        ("model", "strategy", "iterations", "questions",
                         "temperature", "query_id", "wall_s", "sources", "research_id")}

            # Blinded packet: question + answer + sources. No model, no parameters.
            body = [f"# Trial {tid}", "",
                    "## Question", "", r.get("question", "(see query_id in the set)"), "",
                    "## Answer", "", r["summary"], "",
                    f"## Sources the assistant reported ({r.get('sources', 0)})", ""]
            for s in (r.get("source_list") or [])[:40]:
                body.append(f"- {s}")
            if not r.get("source_list"):
                body.append("_(URLs not captured in this run — grade `sourced` on whether "
                            "the answer's own inline citations check out.)_")
            with open(os.path.join(args.out, "answers", f"{tid}.md"), "w") as fh:
                fh.write("\n".join(body) + "\n")

            templates.append({"tid": tid, "correct": None, "sourced": None,
                              "useful": None, "wrong_claims": [], "notes": ""})
            n += 1

    with open(os.path.join(args.out, "RUBRIC.md"), "w") as fh:
        fh.write(RUBRIC)
    with open(os.path.join(args.out, "KEY.json"), "w") as fh:
        json.dump(key, fh, indent=2)
    with open(os.path.join(args.out, "grades.template.jsonl"), "w") as fh:
        for t in templates:
            fh.write(json.dumps(t) + "\n")

    print(f"exported {n} answers to {args.out}/answers/")
    print(f"give the judge: RUBRIC.md + answers/ + grades.template.jsonl")
    print(f"KEEP BACK:      KEY.json  (it maps tid -> model/config)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
