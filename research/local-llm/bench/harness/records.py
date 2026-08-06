"""Validate a trial record before anything downstream trusts it.

Pure: no I/O, no imports beyond the stdlib, so `test_records.py` runs on the Mac.

TWO JOBS, AND THE SECOND IS THE IMPORTANT ONE
---------------------------------------------
1. Catch a malformed row before it reaches a score.
2. Catch a row that is *well-formed and wrong* — the failure mode that actually bit this
   project. A trial whose requested iterations were silently ignored looks perfectly healthy:
   `ok=True`, a summary, sources, a wall time. Nothing about its shape says the configuration
   label is a lie. So the checks below compare **what was asked for against what happened**,
   not merely that fields are present.

`check()` returns a list of problems rather than raising. A failing trial is a data point;
the sweep records it and continues, and the problems travel with the row so nothing has to be
re-derived at analysis time.
"""

from __future__ import annotations

# Keys `ldr_trial.py` promises on a successful record. Absence of any of these means the
# writer changed and something downstream is about to read None.
REQUIRED_OK = ("question_id", "question", "strategy", "settings_overrides", "summary",
               "sources", "wall_s", "returned_iterations", "observed_questions")


def check(rec: dict) -> list[str]:
    """Everything wrong with one record, most-load-bearing first. Empty list = usable."""
    problems: list[str] = []

    if not rec.get("ok"):
        # A failed trial only has to be identifiable and re-runnable.
        for k in ("question_id", "strategy", "settings_overrides"):
            if rec.get(k) in (None, ""):
                problems.append(f"failed record missing {k!r}, so it cannot be re-keyed")
        if not rec.get("error"):
            problems.append("ok=False with no error string — the failure is unattributable")
        return problems

    for k in REQUIRED_OK:
        if k not in rec:
            problems.append(f"missing {k!r}")

    # --- the configuration actually applied ------------------------------------------
    req_i, got_i = rec.get("requested_iterations"), rec.get("returned_iterations")
    if req_i is not None and got_i is not None and req_i != got_i:
        problems.append(
            f"iterations NOT honoured: asked {req_i}, ran {got_i}. The settings-snapshot "
            f"channel has stopped working — every row in this run is mislabelled")

    obs = rec.get("observed_questions") or []
    req_q = rec.get("requested_questions")
    if obs and req_q is not None and set(obs) != {req_q}:
        # NOT fatal: the question count is LLM-generated and can legitimately come in under
        # the cap on an easy query. Recorded so the fit knows `q` was not what was asked.
        problems.append(
            f"questions differ from requested: asked {req_q}, observed {obs} "
            f"(may be the model under-filling, not a config failure)")

    # --- the answer itself -------------------------------------------------------------
    if not (rec.get("summary") or "").strip():
        # Not dropped silently: export-for-grading.py:98 skips empty summaries and prints
        # only the EXPORTED count, so a trial that cost minutes of GPU vanishes unremarked.
        problems.append("empty summary — gradable content is missing, flag rather than drop")

    if rec.get("wall_s") is not None and rec["wall_s"] <= 0:
        problems.append(f"wall_s={rec['wall_s']} is not a duration")

    # --- sources ------------------------------------------------------------------------
    srcs = rec.get("sources")
    if srcs is None:
        problems.append("missing 'sources'")
    else:
        if rec.get("source_count", 0) > 0 and not srcs:
            problems.append("source_count > 0 but no sources persisted — the URLs a judge "
                            "needs to check citations are gone and cannot be recovered")
        for i, s in enumerate(srcs or []):
            if not isinstance(s, dict):
                problems.append(f"source[{i}] is {type(s).__name__}, not dict — "
                                f"extract_sources() was bypassed")
                break
            if not s.get("link") and not s.get("snippet"):
                problems.append(f"source[{i}] has neither link nor snippet, so it is "
                                f"unusable for citation checking")
                break

    # --- did it search at all -----------------------------------------------------------
    if rec.get("searched") is False and (rec.get("summary") or "").strip():
        # THE Onyx failure: a confident answer with no search behind it. Not invalid — for
        # langgraph-agent it is the measurement — but it must never pass unremarked.
        problems.append("ANSWERED WITHOUT SEARCHING — read the tail for fabricated sources "
                        "(harness-comparison.md:320-325: grepping for citation syntax does "
                        "not catch them)")

    # --- GPU cost -----------------------------------------------------------------------
    if "cost" in rec and rec["cost"] is None:
        problems.append("no capture region for this trial — GPU cost is UNKNOWN, not zero")
    elif isinstance(rec.get("cost"), dict):
        if rec["cost"].get("truncated"):
            problems.append(f"truncated={rec['cost']['truncated']} — the run hit the context "
                            f"ceiling, so this measured the ceiling and not the workload")

    return problems


def usable(rec: dict) -> bool:
    """A record safe to include in a score.

    Deliberately narrower than "no problems": a zero-search answer and an under-filled
    question count are both *findings* worth scoring, not corruption.
    """
    if not rec.get("ok"):
        return False
    fatal = [p for p in check(rec)
             if p.startswith(("missing", "iterations NOT honoured", "empty summary"))
             or "not dict" in p or "cannot be recovered" in p]
    return not fatal
