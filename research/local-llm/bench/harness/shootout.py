#!/usr/bin/env python3
"""Strategy x evidence-depth shootout. Resumable, bounded, and honest about what it did not
measure.

Runs INSIDE the LDR container, launched detached by `sweep.py`:

    python3 shootout.py --n 20 --out /data/bench/shootout.jsonl \
        --capture /data/bench/upstream.log

    python3 shootout.py --dry-run          # expand the plan, call nothing
    python3 shootout.py --status --out …   # what is done, what is left

WHAT IT VARIES, AND WHY ONLY THIS
---------------------------------
Round 1 is a 3 x 2 grid -- three strategies against snippets-vs-full-content -- with the
model held. `search.snippets_only` is in the grid because every measurement this project has
taken ran with it True, i.e. the assistant never fetched a page it cited
(search_engine_base.py:697-701). On a metric about misreading sources that is plausibly a
larger lever than strategy, and it also re-derives G0's peak prompt, which is currently a
property of the config rather than of LDR.

WHY THIS RUNNER EXISTS AT ALL
-----------------------------
Upstream ships a benchmark runner and we use its dataset and graders -- but not its runner:
`benchmarks/runners.py:201-209` never passes `search_strategy` (so it always benchmarks one
strategy) and passes `iterations` as a kwarg, which does nothing. It cannot vary either of
the two things this experiment varies.

QUESTION OUTERMOST, CELLS INNER
-------------------------------
The usual reason to order a grid is reload cost; there is none here, since the model is held
and both swept knobs are per-call. What ordering decides is what a PARTIAL run is worth:
question-outermost means an interruption leaves all six cells at the same n and still
comparable, where cell-outermost leaves some finished and others empty -- which at n<20 is
not a result at all. The pilot is the run most likely to be interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import ldr_trial
import records
import upstream

HERE = Path(__file__).resolve().parent

# 5.4x the measured 220.9 s for a real trial. `quick_summary` accepts no timeout of its own
# (testdata/ldr-api.json), so this subprocess bound is the only one that exists. Full-content
# trials fetch pages and are slower, hence the generous multiple.
TRIAL_TIMEOUT_S = 1200

STRATEGIES = ["source-based", "focused-iteration", "focused-iteration-standard"]

# search.snippets_only. **Currently ONE value, because the other arm was measured to be a
# no-op** (smoke test, 2026-08-02): setting `search.snippets_only: False` changes nothing,
# because nothing reads that key.
#
#   get_search(search_snippets_only: bool = False, ...)   search_engine_factory.py:624-631
#       — a plain parameter; NO code path resolves it from the settings snapshot
#   _init_search_system calls get_search(...) with fixed args and no **kwargs passthrough,
#       so quick_summary cannot reach it either
#   measured on the live engine: search_snippets_only is True in BOTH programmatic and
#       non-programmatic mode, so search_engine_base.py:697 short-circuits and returns
#       snippets before _get_full_content is ever called
#   the crawler IS initialised (`full_search` exists) — it is simply never reached
#
# Confirmed empirically: source text was snippet-sized (35-400 chars) in every arm, where a
# fetched page would be thousands. Sweeping it would have burned half of round 1 measuring
# the same configuration twice under two different labels.
#
# Left as a list so the arm can be restored the moment the fetch path is reachable.
DEPTHS = [True]

# Each strategy at ITS OWN default, not a shared value: focused_iteration_strategy.py:65-66
# calls (8,5) "OPTIMAL FOR SIMPLEQA", while source-based's own defaults are far lower. A
# shared (i,q) would handicap whichever strategy it does not suit and the shootout would
# measure the handicap. Recorded per trial so the comparison stays legible.
STRATEGY_DEFAULTS = {
    "source-based": {"iterations": 3, "questions": 3},
    "focused-iteration": {"iterations": 8, "questions": 5},
    "focused-iteration-standard": {"iterations": 8, "questions": 5},
}


@dataclass
class Cell:
    strategy: str
    snippets_only: bool

    @property
    def label(self) -> str:
        return f"{self.strategy}/{'snippets' if self.snippets_only else 'full'}"

    @property
    def defaults(self) -> dict:
        return STRATEGY_DEFAULTS[self.strategy]


@dataclass
class Trial:
    cell: Cell
    question_id: str
    question: str
    correct_answer: str | None = None
    model: str = ""
    search_tool: str = ""

    @property
    def key(self) -> tuple:
        """Identity of a trial for resume purposes.

        Keyed on the FULL settings-override dict, not a hand-listed tuple. Adding a knob
        without adding it to a key is how two different configurations silently collide into
        one row; deriving the key from the thing that actually configures the run makes that
        impossible.

        **`model` and `search_tool` must be the REAL values**, not placeholders. An earlier
        version passed "" for both, so this key never equalled `key_of_record` — which reads
        the actual overrides off the written row — and resume silently matched nothing,
        re-running every completed trial. The unit test missed it by building its fixture
        with the same placeholders, i.e. it was self-consistent and wrong. `--status`
        reporting 0 done against a non-empty JSONL is what exposed it.
        """
        overrides = ldr_trial.build_settings(
            self.cell.strategy, self.model, self.search_tool,
            self.cell.defaults["iterations"], self.cell.defaults["questions"],
            self.cell.snippets_only)
        return (self.cell.strategy, self.question_id,
                json.dumps(overrides, sort_keys=True))


def cells() -> list[Cell]:
    return [Cell(s, d) for s in STRATEGIES for d in DEPTHS]


def plan(questions: list[dict], model: str = "", search_tool: str = "") -> list[Trial]:
    """Every trial, question outermost. Pure -- `--dry-run` and the tests use exactly this.

    `model`/`search_tool` are part of each trial's resume key, so they must be the values the
    run will actually use.
    """
    out = []
    for q in questions:
        for c in cells():
            out.append(Trial(c, q["id"], q["question"], q.get("correct_answer"),
                             model=model, search_tool=search_tool))
    return out


def key_of_record(rec: dict) -> tuple:
    """The same key, recovered from a written row."""
    return (rec["strategy"], rec["question_id"],
            json.dumps(rec["settings_overrides"], sort_keys=True))


def load_done(path: str, retry_failed: bool = True) -> set:
    """Completed trial keys. A truncated final line (killed mid-write) is ignored.

    `retry_failed` defaults True: a failed trial carries no measurement, only the fact that
    something went wrong once. Treating it as complete locks a transient llama-swap blip into
    the JSONL for the life of the file. The failure row is preserved either way -- the file
    is append-only -- so nothing is lost by re-running it.
    """
    done = set()
    if not os.path.exists(path):
        return done
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
                if not rec.get("ok") and retry_failed:
                    continue
                done.add(key_of_record(rec))
            except Exception:
                continue
    return done


# --------------------------------------------------------------------------- the capture

class Capture:
    """Byte-offset attribution against llama-swap's upstream log.

    `sweep.py` starts the capture before the first query; this only reads it. Offsets rather
    than task ids because a llama-server restart resets ids to 0, and `parse_tasks` keys by
    id -- so a region spanning a restart silently merges two calls into one and loses the
    other (upstream.py, `test_task_id_slicing_misattributes_when_ids_reset`).
    """

    def __init__(self, path: str | None):
        self.path = path
        self.start_size = self._size()

    def _size(self) -> int | None:
        if not self.path or not os.path.exists(self.path):
            return None
        return os.path.getsize(self.path)

    def present(self) -> bool:
        """Does the capture file exist at all?

        **Existence, not size.** The capture is started with `?no-history`, which streams
        live only — so before the first query the file is legitimately EMPTY. An earlier
        version of this checked `size > 0` at startup and would have aborted every sweep on
        its first line, before a single trial ran.
        """
        return self._size() is not None

    def grew(self) -> bool:
        """Has anything been captured since this object was created?

        The end-of-run check. False after real trials means the capture died mid-run (curl
        exit 56 has happened before, README.md:61) and the cost columns are UNKNOWN — not
        zero, and not something to quietly publish.
        """
        now = self._size()
        return now is not None and self.start_size is not None and now > self.start_size

    def mark(self) -> int | None:
        return self._size()

    def region(self, start: int | None, end: int | None) -> dict | None:
        """Cost facts for one trial, or None if the capture is unusable.

        None, never zeros: `README.md:61` records the capture dying mid-run (curl exit 56),
        and "no capacity data" must never read as "no traffic".
        """
        if self.path is None or start is None:
            return None
        try:
            with open(self.path, "rb") as fh:
                raw = fh.read()
        except OSError:
            return None
        return upstream.summarise(upstream.slice_range(raw, start, end))


# --------------------------------------------------------------------------- running

def run_trial(t: Trial, model: str, search_tool: str, timeout: int,
              python: str = sys.executable) -> dict:
    """One trial as a subprocess, so a hang is survivable."""
    d = t.cell.defaults
    argv = [python, str(HERE / "ldr_trial.py"),
            "--strategy", t.cell.strategy,
            "--question-id", t.question_id,
            "--question", t.question,
            "--model", model,
            "--search-tool", search_tool,
            "--iterations", str(d["iterations"]),
            "--questions", str(d["questions"]),
            "--snippets-only", "true" if t.cell.snippets_only else "false"]
    if t.correct_answer is not None:
        argv += ["--correct-answer", t.correct_answer]

    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"question_id": t.question_id, "strategy": t.cell.strategy,
                "settings_overrides": ldr_trial.build_settings(
                    t.cell.strategy, model, search_tool, d["iterations"],
                    d["questions"], t.cell.snippets_only),
                "ok": False, "wall_s": round(time.time() - t0, 1),
                "error": f"TimeoutExpired: killed after {timeout}s"}
    if p.returncode != 0 or not p.stdout.strip():
        return {"question_id": t.question_id, "strategy": t.cell.strategy,
                "settings_overrides": ldr_trial.build_settings(
                    t.cell.strategy, model, search_tool, d["iterations"],
                    d["questions"], t.cell.snippets_only),
                "ok": False, "wall_s": round(time.time() - t0, 1),
                "error": f"rc={p.returncode} stderr={p.stderr.strip()[:400]}"}
    return json.loads(p.stdout)


def append(path: str, rec: dict) -> None:
    """Append + flush + fsync BEFORE the next trial starts. This is what makes the run
    resumable; buffering here would lose everything on a kill."""
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def status_report(todo: list[Trial], done: set) -> str:
    """Per-cell progress. Pure, so `--status` and the tests share it."""
    per: dict[str, list[int]] = {}
    for t in todo:
        c = per.setdefault(t.cell.label, [0, 0])
        c[1] += 1
        if t.key in done:
            c[0] += 1
    width = max((len(k) for k in per), default=10)
    lines = [f"  {k.ljust(width)}  {v[0]:3}/{v[1]:<3} done" for k, v in sorted(per.items())]
    total_done = sum(v[0] for v in per.values())
    total = sum(v[1] for v in per.values())
    lines.append(f"  {'TOTAL'.ljust(width)}  {total_done:3}/{total:<3}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="/data/bench/shootout.jsonl")
    ap.add_argument("--capture", default=None,
                    help="llama-swap upstream capture, started by sweep.py. Without it the "
                         "run has NO GPU cost data and says so per trial")
    ap.add_argument("--questions-file", default="/data/bench/questions.json")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--model", default="gemma-4-12b-it")
    ap.add_argument("--search-tool", default="searxng")
    ap.add_argument("--timeout", type=int, default=TRIAL_TIMEOUT_S)
    ap.add_argument("--dry-run", action="store_true",
                    help="expand the plan and write synthetic records; calls no LLM")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-retry-failed", action="store_true")
    a = ap.parse_args()

    qs = json.loads(Path(a.questions_file).read_text())[: a.n]
    todo_all = plan(qs, a.model, a.search_tool)
    done = load_done(a.out, retry_failed=not a.no_retry_failed)

    if a.status:
        print(f"=== {a.out} ===\n{status_report(todo_all, done)}")
        return 0

    todo = [t for t in todo_all if t.key not in done]
    print(f"{len(todo_all)} trials ({len(qs)} questions x {len(cells())} cells), "
          f"{len(done)} already done, {len(todo)} to run", flush=True)

    if a.dry_run:
        for t in todo:
            print(f"  DRY {t.question_id:22} {t.cell.label}")
        print(f"\nDRY RUN — {len(todo)} trial(s) listed, nothing executed")
        return 0

    out_dir = os.path.dirname(a.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    cap = Capture(a.capture)
    if a.capture and not cap.present():
        # Blocking, deliberately. Every trial would record None cost and the sweep would
        # still finish looking healthy -- Phase 0's cost model half missing, discovered later.
        # Presence only: `?no-history` means the file is empty until the first query, so a
        # size check here would abort every run before it started.
        print(f"FATAL: capture {a.capture} does not exist. sweep.py starts it before the "
              f"first query; without it there is no GPU cost data.", file=sys.stderr)
        return 2

    problems = 0
    for n, t in enumerate(todo, 1):
        start = cap.mark()
        print(f"[{n}/{len(todo)}] {t.question_id} {t.cell.label}", flush=True)
        rec = run_trial(t, a.model, a.search_tool, a.timeout)
        rec["cost"] = cap.region(start, cap.mark())
        rec["capture_grew"] = cap.grew()

        bad = records.check(rec)
        rec["record_problems"] = bad
        problems += bool(bad)
        append(a.out, rec)
        print(f"    ok={rec.get('ok')} searched={rec.get('searched')} "
              f"iters={rec.get('returned_iterations')} "
              f"peak={(rec.get('cost') or {}).get('peak_total')} "
              f"wall={rec.get('wall_s')}s" + (f"  PROBLEMS: {bad}" if bad else ""),
              flush=True)

    print(f"\ndone. {problems} trial(s) with record problems.")
    if a.capture and not cap.grew():
        print("WARNING: the capture died during the run — cost data after that point is "
              "UNKNOWN, not zero.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
