#!/usr/bin/env python3
"""Turn a shootout JSONL into a per-cell table: correctness, cost, and capacity.

    python3 summarise.py --in runs/round1.jsonl
    python3 summarise.py --in runs/round1.jsonl --md      # paste-ready for results.md

Pure apart from reading the file, so `test_summarise.py` runs on the Mac.

WHAT THIS DOES NOT DO: GRADE
----------------------------
The `correct` column is a **substring proxy** — does the ground-truth answer appear in the
summary — and it is labelled as such everywhere it is printed. SimpleQA answers are short but
free-form, so real scoring needs semantic equivalence (`docs/BENCHMARKING.md`, and why
upstream ships an LLM grader): "Bonn" vs "the University of Bonn" vs "Rheinische
Friedrich-Wilhelms-Universität" are all correct and only one matches a substring test. The
proxy therefore **undercounts, and by an unknown amount**.

It is here to rank cells cheaply and to catch a cell that is broken rather than merely worse.
The real grade is a blind fresh-thread pass over the exported answers
(`current-work.md` decision 4), and no cell should be chosen on the proxy alone.

EVERY NUMBER CARRIES ITS N AND ITS INTERVAL
-------------------------------------------
`docs/BENCHMARKING.md:56-125`: at n=20 the 95% Wilson margin is ±17-21 points. A bare
percentage at that N invites a decision the data cannot support, so the interval is printed
next to every score and the summary refuses to name a winner when the intervals overlap.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

Z95 = 1.96


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval, as (centre, half-width), both in percent.

    The formula is `docs/BENCHMARKING.md:60-65` verbatim. Wilson rather than the normal
    approximation because it behaves correctly near 0% and 100% — which is exactly where a
    20-example cell lands, so the naive interval would produce nonsense like 103%.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre * 100, half * 100)


def is_correct(rec: dict) -> bool | None:
    """Substring proxy. None when the trial cannot be scored at all."""
    if not rec.get("ok"):
        return None
    truth = (rec.get("correct_answer") or "").strip().rstrip(".")
    summary = rec.get("summary") or ""
    if not truth or not summary.strip():
        return None
    return truth.lower() in summary.lower()


def load(path: str) -> list[dict]:
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # truncated final line from a killed writer
    return out


def cell_of(rec: dict) -> str:
    depth = "snippets" if rec.get("snippets_only") else "full"
    return f"{rec.get('strategy')}/{depth}"


def summarise(rows: list[dict]) -> dict:
    """Per-cell aggregate. Pure — the tests drive this directly."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[cell_of(r)].append(r)

    out = {}
    for cell, rs in sorted(by.items()):
        scored = [r for r in rs if is_correct(r) is not None]
        hits = sum(1 for r in scored if is_correct(r))
        ok = [r for r in rs if r.get("ok")]
        walls = [r["wall_s"] for r in ok if r.get("wall_s")]
        peaks = [(r.get("cost") or {}).get("peak_total") for r in ok]
        peaks = [p for p in peaks if p]
        calls = [(r.get("cost") or {}).get("calls") for r in ok]
        calls = [c for c in calls if c]
        centre, half = wilson(hits, len(scored))
        out[cell] = {
            "trials": len(rs),
            "ok": len(ok),
            "failed": len(rs) - len(ok),
            "scored": len(scored),
            "hits": hits,
            "proxy_pct": centre,
            "proxy_halfwidth": half,
            "median_wall_s": statistics.median(walls) if walls else None,
            "total_wall_s": sum(walls),
            "median_calls": statistics.median(calls) if calls else None,
            "peak_total_max": max(peaks) if peaks else None,
            "truncated": sum((r.get("cost") or {}).get("truncated") or 0 for r in ok),
            "no_search": sum(1 for r in ok if r.get("searched") is False),
            # Searched but the engine returned nothing. NOT a strategy failure — it is a
            # property of the question against this SearXNG instance, and it lands on every
            # cell alike because the grid is question-outermost. Counted separately so a cell
            # is never marked wrong for a question no cell could answer.
            "no_sources": sum(1 for r in ok if not r.get("source_count")),
            "problems": sum(1 for r in rs if r.get("record_problems")),
            "capture_missing": sum(1 for r in ok if r.get("cost") is None),
        }
    return out


def dead_questions(rows: list[dict], n_cells: int | None = None) -> list[str]:
    """Questions where **every** cell got zero sources.

    These measure the search engine, not the strategy: no cell had anything to answer from,
    so all of them score wrong and the comparison learns nothing. They still consume a slot
    in n, so the honest denominator excludes them — reported rather than silently dropped.

    **Only questions whose full cycle has completed are considered.** On a partial run a
    question with one finished cell that happened to retrieve nothing looks identical to a
    genuinely dead one — which produced a wrong "1 dead question" reading mid-run here. A
    question is judged only once every cell has had its turn.
    """
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("ok"):
            by_q[r.get("question_id")].append(r)
    if n_cells is None:
        # Infer the grid width from the data: the most cells any question has been through.
        n_cells = max((len({(r.get("strategy"), r.get("snippets_only")) for r in rs})
                       for rs in by_q.values()), default=0)
    out = []
    for q, rs in by_q.items():
        cells = {(r.get("strategy"), r.get("snippets_only")) for r in rs}
        if len(cells) < n_cells:
            continue                      # cycle incomplete — cannot judge yet
        if all(not r.get("source_count") for r in rs):
            out.append(q)
    return sorted(out)


def overlapping(a: dict, b: dict) -> bool:
    """Do two cells' Wilson intervals overlap? If so they are a tie at this N."""
    lo_a, hi_a = a["proxy_pct"] - a["proxy_halfwidth"], a["proxy_pct"] + a["proxy_halfwidth"]
    lo_b, hi_b = b["proxy_pct"] - b["proxy_halfwidth"], b["proxy_pct"] + b["proxy_halfwidth"]
    return lo_a <= hi_b and lo_b <= hi_a


def verdict(agg: dict) -> str:
    """Name a winner only when the data supports one."""
    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["proxy_pct"])
    if len(ranked) < 2:
        return "only one cell — nothing to compare"
    (n1, c1), (n2, c2) = ranked[0], ranked[1]
    if overlapping(c1, c2):
        return (f"NO WINNER at this N: {n1} ({c1['proxy_pct']:.0f}±{c1['proxy_halfwidth']:.0f}%) "
                f"and {n2} ({c2['proxy_pct']:.0f}±{c2['proxy_halfwidth']:.0f}%) overlap. "
                f"BENCHMARKING.md: treat as a tie and raise N before deciding.")
    return (f"{n1} leads {n2} with non-overlapping intervals "
            f"({c1['proxy_pct']:.0f}±{c1['proxy_halfwidth']:.0f}% vs "
            f"{c2['proxy_pct']:.0f}±{c2['proxy_halfwidth']:.0f}%) — "
            f"still a PROXY score; confirm with a blind grade before deploying.")


def render(agg: dict, md: bool = False) -> str:
    lines = []
    head = ("cell", "n", "proxy correct (95% CI)", "med wall", "med calls",
            "peak", "no-search", "issues")
    if md:
        lines.append("| " + " | ".join(head) + " |")
        lines.append("|" + "---|" * len(head))
    else:
        lines.append(f"{head[0]:34} {head[1]:>4}  {head[2]:>24} {head[3]:>9} "
                     f"{head[4]:>10} {head[5]:>7} {head[6]:>10} {head[7]:>7}")
        lines.append("-" * 118)
    for cell, c in sorted(agg.items(), key=lambda kv: -kv[1]["proxy_pct"]):
        score = f"{c['hits']}/{c['scored']} = {c['proxy_pct']:.0f} ± {c['proxy_halfwidth']:.0f}%"
        row = (cell, str(c["trials"]), score,
               f"{c['median_wall_s']:.0f}s" if c["median_wall_s"] else "-",
               f"{c['median_calls']:.0f}" if c["median_calls"] else "-",
               str(c["peak_total_max"] or "-"), str(c["no_search"]),
               str(c["problems"] + c["failed"] + c["capture_missing"]))
        if md:
            lines.append("| " + " | ".join(row) + " |")
        else:
            lines.append(f"{row[0]:34} {row[1]:>4}  {row[2]:>24} {row[3]:>9} "
                         f"{row[4]:>10} {row[5]:>7} {row[6]:>10} {row[7]:>7}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--md", action="store_true", help="markdown, for results.md")
    a = ap.parse_args()

    rows = load(a.src)
    if not rows:
        print(f"no usable rows in {a.src}", file=sys.stderr)
        return 1
    agg = summarise(rows)

    dead = dead_questions(rows)
    print(f"{len(rows)} trials across {len(agg)} cells\n")
    print(render(agg, a.md))
    print()
    print("`proxy correct` is a SUBSTRING match against SimpleQA ground truth — it")
    print("UNDERCOUNTS by an unknown amount (semantic equivalents miss). Not a grade.")
    print()
    print(verdict(agg))

    if dead:
        print(f"\n!! {len(dead)} question(s) returned ZERO sources in every cell — they "
              f"measure SearXNG, not the strategy, and every cell scores wrong on them:")
        for q in dead[:10]:
            print(f"     {q}")
        print("   Effective N is lower than it looks. Re-run summarise on a filtered file, "
              "or report both denominators.")

    trunc = sum(c["truncated"] for c in agg.values())
    if trunc:
        print(f"\n!! {trunc} trial(s) TRUNCATED — those rows measured the context ceiling, "
              f"not the workload. Exclude them before drawing any conclusion.")
    missing = sum(c["capture_missing"] for c in agg.values())
    if missing:
        print(f"\n!! {missing} trial(s) have NO capture region — their GPU cost is UNKNOWN, "
              f"not zero.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
