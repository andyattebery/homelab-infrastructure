#!/usr/bin/env python3
"""Tests for the test orchestrator. It is a script like any other.

    python3 test_run_tests.py

The plan is data (`plan()`), so its shape can be asserted without executing a single stage —
which is the point: the orchestrator's mistakes (a stale sync list, a remote command fish
will mangle, stages in an order that hides a failure) are exactly the ones that stay
invisible until they cost a live run.
"""

import ast
import sys
from pathlib import Path

import run_tests

HERE = Path(__file__).resolve().parent


def test_local_plan_needs_nothing_remote():
    """The default invocation must be runnable on a plane. If a bare `run_tests.py` reaches
    for ssh or scp, the fast edit loop is gone."""
    for s in run_tests.plan(remote=False, capture=False):
        joined = " ".join(s.argv)
        assert "ssh" not in joined and "scp" not in joined, f"{s.name}: {joined}"
        assert not s.gpu, f"{s.name} is marked gpu but is in the local plan"


def test_the_api_guard_runs_first():
    """Stage order is load-bearing. `test_ldr_api.py` guards the silently-ignored-kwargs
    bug; if our call site drifted back to the broken channel, every later result is
    mislabelled and running them wastes the time and produces misleading output."""
    first = run_tests.plan()[0]
    assert "test_ldr_api.py" in " ".join(first.argv), first.argv


def test_every_test_file_is_in_the_plan():
    """A suite that exists but is never run is worse than no suite — it reads as coverage."""
    on_disk = {p.name for p in HERE.glob("test_*.py")}
    in_plan = {a for s in run_tests.plan(remote=True, capture=True)
               for a in s.argv if a.startswith("test_")}
    missing = on_disk - in_plan
    assert not missing, f"test files never executed by run_tests.py: {sorted(missing)}"


def test_sync_list_is_closed_under_local_imports():
    """Derived from the AST, not from trusting the comment next to SYNC.

    Anything that runs in the container must arrive with everything it imports. A missing
    module fails at import time mid-sweep, after the GPU has already been reserved.
    """
    local_modules = {p.stem for p in HERE.glob("*.py")}
    synced = set(run_tests.SYNC)

    def imports_of(name: str) -> set:
        tree = ast.parse((HERE / name).read_text())
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                out.add(node.module.split(".")[0])
        return out & local_modules

    missing = {}
    for entry in ("shootout.py", "ldr_trial.py"):      # the remote entry points
        needed = {f"{m}.py" for m in imports_of(entry)}
        gap = needed - synced
        if gap:
            missing[entry] = sorted(gap)
    assert not missing, f"SYNC is not closed under imports: {missing}"


def test_remote_command_strings_survive_fish():
    """Both hosts run fish as the login shell. A remote string containing shell syntax fish
    parses differently fails with a `fish:` error that reads like the remote program
    crashed — and the ssh call still exits non-zero, so it looks like a real failure."""
    for s in run_tests.plan(remote=True, capture=True):
        if s.remote:
            assert run_tests.SHELL_SAFE.match(s.remote), (
                f"{s.name}: remote command has shell syntax fish may mangle: {s.remote!r}")


def test_capture_stage_is_opt_in_and_marked_gpu():
    """Re-capturing costs GPU time and overwrites a committed fixture. It must never happen
    as a side effect of running the tests."""
    default = run_tests.plan()
    assert not any("capture_fixtures" in " ".join(s.argv) for s in default)
    withcap = [s for s in run_tests.plan(capture=True)
               if "capture_fixtures" in " ".join(s.argv)]
    assert len(withcap) == 1 and withcap[0].gpu


def test_sync_precedes_anything_remote():
    """Otherwise the live checks test whatever happened to be on the host already."""
    names = [s.name for s in run_tests.plan(remote=True)]
    assert names.index("sync") < names.index("live: preflight"), names


def test_every_stage_says_why():
    """A stage without a reason cannot be judged when it fails at 2am."""
    for s in run_tests.plan(remote=True, capture=True):
        assert len(s.why) > 30, f"{s.name} has no useful why: {s.why!r}"


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
