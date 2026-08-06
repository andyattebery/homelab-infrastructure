#!/usr/bin/env python3
"""One local-deep-research trial. Emits a single JSON object on stdout.

Runs INSIDE the LDR container. `shootout.py` invokes it as a subprocess so the trial can be
bounded -- `quick_summary` accepts **no `timeout`** (verified, testdata/ldr-api.json), so an
external bound is the only one available. In-process there is no way to interrupt a hung
call; as a child it is killed, recorded failed, and the sweep continues.

    python3 ldr_trial.py --strategy source-based --question-id simpleqa-0007 \
        --question "..." --iterations 3 --questions 1 --snippets-only false

EVERYTHING SWEPT GOES IN THE SETTINGS SNAPSHOT, NOT IN KWARGS
-------------------------------------------------------------
Passing `iterations=` / `questions_per_iteration=` to `quick_summary` is silently ignored --
see the warning at the top of README.md for the full path and the measurements. This module
is the single place that knows the correct channel, which is why the mapping below is *data*:
a test can assert it without running anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

# --------------------------------------------------------------------------- the mapping

# Which settings key each strategy actually reads for questions-per-iteration.
#
# NOT cosmetic, and NOT guesswork -- the strategies genuinely differ:
#   source-based        `self.get_setting("search.questions", 3)`   source_based_strategy.py:210
#   focused-iteration   constructor arg, seeded by AdvancedSearchSystem from
#                       `search.questions_per_iteration`            focused_iteration_strategy.py:87-89
#
# `search.questions` is **absent from the default snapshot**, so on source-based the lookup
# falls through to a hardcoded 3 unless we inject the key explicitly.
#
# HONEST STATUS: the *keys* are read from source and certain. That setting them actually
# changes the number of questions issued is **not yet confirmed end to end** -- every probe so
# far generated one question regardless, on a query too trivial to need more. Round 1 settles
# it; until then a trial records what it asked for AND what was observed, and the two are
# compared rather than assumed equal.
QUESTIONS_KEY = {
    "source-based": "search.questions",
    "focused-iteration": "search.questions_per_iteration",
    "focused-iteration-standard": "search.questions_per_iteration",
    # langgraph-agent takes its bound as `max_steps` (search_system.py:241) and is measured
    # by the search-skip probe, not the shootout. No questions key applies.
    "langgraph-agent": None,
    "topic-organization": "search.questions_per_iteration",
}

ITERATIONS_KEY = "search.iterations"

# `search_strategy` is the ONE swept parameter that is correctly a kwarg: it is consumed at
# construction (research_functions.py:137-147 -> strategy_name), before any settings lookup.
# Named here so `test_ldr_api.py` can allow it explicitly rather than by a blanket rule.
KWARG_ALLOWLIST = {"search_strategy", "programmatic_mode", "query", "settings_snapshot"}


def build_settings(strategy: str, model: str, search_tool: str, iterations: int,
                   questions: int, snippets_only: bool) -> dict:
    """The settings-override dict for one cell. Pure -- no LDR import, so it is testable."""
    if strategy not in QUESTIONS_KEY:
        raise ValueError(f"unknown strategy {strategy!r}; "
                         f"known: {sorted(QUESTIONS_KEY)}")
    overrides = {
        "search.tool": search_tool,
        "llm.provider": "openai_endpoint",
        "llm.model": model,
        ITERATIONS_KEY: iterations,
        # THE evidence-depth knob. `search_snippets_only` wins outright over
        # `include_full_content` in the engine (search_engine_base.py:697-701), so this alone
        # decides whether the assistant reads the pages it cites.
        "search.snippets_only": snippets_only,
    }
    qkey = QUESTIONS_KEY[strategy]
    if qkey:
        overrides[qkey] = questions
    return overrides


def observed_questions(findings: object) -> list[int]:
    """Questions actually issued per search phase, parsed from the findings' own text.

    The only place the realised `q` is visible: `questions` comes back EMPTY on source-based
    (measured, and noted upstream too). Phase content reads
    'Searched with N questions, found M results.'
    """
    import re
    out = []
    if isinstance(findings, list):
        for f in findings:
            if isinstance(f, dict):
                m = re.search(r"Searched with (\d+) questions", str(f.get("content", "")))
                if m:
                    out.append(int(m.group(1)))
    return out


def extract_sources(sources: object) -> list[dict]:
    """Sources are **dicts**, not strings (measured; testdata/ldr-api.json).

    Keys: category, engine, id, index, link, snippet, title -- plus **full_content** once the
    SearXNG patch is active. `str(s)` would write a dict repr into the grading packet, which is
    unusable for checking whether a citation is real. Keep `link` and `title` for grading, and
    **keep `snippet`** -- under `snippets_only=True` it is the only record of what the model
    actually read.

    WHY full_content IS SUMMARISED, NOT STORED
    ------------------------------------------
    `base_citation_handler.py:157` builds the model's evidence as
    `result.get("full_content", result.get("snippet", ""))` -- so under the full arm
    full_content IS what the model read, and dropping it would leave the two arms
    indistinguishable in the records. Measured at the engine layer: median 245 chars of
    snippet vs 4192 chars of full_content on the same query.

    But storing it verbatim would (a) bloat every record by ~30 KB and (b) hand `export.py` a
    blinding leak: 4000-char page text in one arm and 245-char snippets in the other identifies
    the configuration at a glance, which is the one thing the blinded packets exist to prevent.
    So keep the LENGTH (the depth measurement) and a short head (human audit only, never
    exported). test_export.py asserts neither reaches a packet.
    """
    out = []
    for s in (sources or []):
        if isinstance(s, dict):
            rec = {k: s.get(k) for k in ("link", "title", "snippet", "engine")}
            fc = s.get("full_content")
            rec["full_content_chars"] = len(fc) if isinstance(fc, str) else 0
            rec["full_content_head"] = fc[:400] if isinstance(fc, str) else None
            out.append(rec)
        else:
            out.append({"link": None, "title": None, "snippet": str(s), "engine": None,
                        "full_content_chars": 0, "full_content_head": None})
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--strategy", required=True)
    p.add_argument("--question-id", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--model", default="gemma-4-12b-it")
    p.add_argument("--search-tool", default="searxng")
    p.add_argument("--iterations", type=int, required=True)
    p.add_argument("--questions", type=int, required=True)
    p.add_argument("--snippets-only", required=True, choices=("true", "false"))
    p.add_argument("--correct-answer", default=None,
                   help="SimpleQA ground truth, carried through into the record so grading "
                        "needs nothing but this file")
    a = p.parse_args()

    snippets_only = a.snippets_only == "true"
    overrides = build_settings(a.strategy, a.model, a.search_tool,
                               a.iterations, a.questions, snippets_only)

    rec = {
        "question_id": a.question_id,
        "question": a.question,
        "correct_answer": a.correct_answer,
        "strategy": a.strategy,
        # The full override dict IS the configuration key. Recording it whole means a trial
        # can never be mis-keyed by a knob someone forgot to add to a tuple.
        "settings_overrides": overrides,
        "requested_iterations": a.iterations,
        "requested_questions": a.questions,
        "snippets_only": snippets_only,
    }

    from local_deep_research.api import quick_summary
    from local_deep_research.api.settings_utils import create_settings_snapshot

    t0 = time.time()
    try:
        settings = create_settings_snapshot(overrides)
        r = quick_summary(
            query=a.question,
            settings_snapshot=settings,
            search_strategy=a.strategy,     # honoured as a kwarg; see KWARG_ALLOWLIST
            programmatic_mode=True,
        )
        findings = r.get("findings") or []
        obs = observed_questions(findings)
        rec.update(
            ok=True,
            wall_s=round(time.time() - t0, 1),
            summary=r.get("summary") or "",
            sources=extract_sources(r.get("sources")),
            source_count=len(r.get("sources") or []),
            findings=findings,
            questions_dict=r.get("questions") or {},
            research_id=r.get("research_id"),
            formatted_findings=r.get("formatted_findings") or "",
            # The two honesty checks: what was asked for vs what happened.
            returned_iterations=r.get("iterations"),
            iterations_honoured=(a.iterations == r.get("iterations")),
            observed_questions=obs,
            questions_honoured=(set(obs) == {a.questions}) if obs else None,
            # THE search-skip signal. Zero search phases means it answered without searching.
            search_phases=len(obs),
            searched=bool(obs) and any(n > 0 for n in obs),
        )
    except Exception as e:                                   # noqa: BLE001
        # A failed trial is a data point, not a reason to abort the sweep.
        rec.update(ok=False, wall_s=round(time.time() - t0, 1),
                   error=f"{type(e).__name__}: {e}"[:500])

    json.dump(rec, sys.stdout, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
