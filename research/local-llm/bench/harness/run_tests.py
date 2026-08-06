#!/usr/bin/env python3
"""Verify the whole harness in one command.

    python3 run_tests.py --dry-run     # print the plan, touch nothing
    python3 run_tests.py               # local suites + dry runs (Mac only, seconds)
    python3 run_tests.py --remote      # + sync to docker-01 and run the live preflight
    python3 run_tests.py --capture     # + re-record testdata/ldr-api.json (~1 min of GPU)

Run from the Mac. Exits non-zero on the first failure.

FAIL-FAST, DELIBERATELY
-----------------------
Every stage presumes the ones before it. A failing unit test makes a live result meaningless,
and an unsynced file makes a remote result a test of a stale copy. There is no --keep-going:
continuing past a failure produces output that looks like evidence and is not.

STAGE 1 IS FIRST FOR A REASON
-----------------------------
`test_ldr_api.py` guards the failure that cost this project its configuration labels —
`iterations=` passed as a kwarg is silently discarded. If our call site has drifted back to
the broken channel, every number produced downstream is mislabelled, so nothing else is worth
running.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
LDR_HOST = os.environ.get("LDR_HOST", "docker-01")
BENCH_DIR = "/mnt/data/local-deep-research/data/bench"

# Copied to the container's /data/bench. Must be closed under the local imports of every
# file that runs remotely — test_run_tests.py derives that from the AST rather than trusting
# this comment.
SYNC = ["shootout.py", "ldr_trial.py", "records.py", "upstream.py",
        "capture_fixtures.py", "make_questions.py"]

# What a remote command string may contain. ssh hands it to the LOGIN shell, which on both
# hosts is fish, and fish does not parse $(...), backticks or bash redirection the way bash
# does. Anything richer must go through `bash -c` with the whole command quoted as one word.
SHELL_SAFE = re.compile(r"^[A-Za-z0-9_./:= -]+$")


@dataclass
class Stage:
    name: str
    argv: list[str]
    why: str = ""
    remote: str = ""
    gpu: bool = False
    env: dict = field(default_factory=dict)


def plan(remote: bool = False, capture: bool = False) -> list[Stage]:
    """Every check, cheapest first. Ordering is load-bearing: a syntax error must cost a
    second, not an ssh round trip."""
    stages = [
        Stage("unit: ldr api", [sys.executable, "test_ldr_api.py"],
              "our call sites against the REAL captured API. Guards the silently-ignored "
              "kwargs bug — if this fails, every downstream number is mislabelled"),
        Stage("unit: searxng patch", [sys.executable, "test_patch.py"],
              "the container's sitecustomize wrapper, for the same reason stage 1 is first: "
              "if it stops applying, every downstream number silently returns to snippets "
              "with no other signal — the same shape of failure as the ignored kwarg"),
        Stage("unit: upstream", [sys.executable, "test_upstream.py"],
              "the capture parser, incl. byte-offset attribution and the task-id-reset "
              "case where id collision silently eats a call"),
        Stage("unit: shootout+records", [sys.executable, "test_shootout.py"],
              "grid shape, question-outermost balance, resume keying, and the record "
              "validation that catches a well-formed row whose config is a lie"),
        Stage("unit: summarise", [sys.executable, "test_summarise.py"],
              "the scoring maths, cross-checked against upstream's own published "
              "margin-of-error table rather than against our arithmetic"),
        Stage("unit: export", [sys.executable, "test_export.py"],
              "blinding — asserted mechanically, because once a judge has read an anchored "
              "packet the grades are contaminated and nothing afterwards reveals it"),
        Stage("unit: preflight", [sys.executable, "test_preflight.py"],
              "the go/no-go interpretation, incl. CONTENDED — the state where llama-swap "
              "is up but ComfyUI is too, which voids a measurement"),
        Stage("unit: sweep", [sys.executable, "test_sweep.py"],
              "launcher step ordering: preflight first, capture started AND verified "
              "before the GPU is committed, sweep detached, capture on the bind mount"),
        Stage("unit: self", [sys.executable, "test_run_tests.py"],
              "this orchestrator is a script like any other"),
        Stage("dry: shootout", [sys.executable, "shootout.py", "--dry-run",
                                "--questions-file", "testdata/questions.json", "--n", "2",
                                "--out", "/tmp/ldr-shootout-dryrun.jsonl"],
              "expands the real plan through the real code path; calls no LLM"),
    ]
    if remote:
        stages += [
            Stage("sync", ["scp", "-q", *[str(HERE / f) for f in SYNC],
                           str(HERE / "testdata" / "questions.json"),
                           f"{LDR_HOST}:{BENCH_DIR}/"],
                  "everything below tests THESE files, not a stale copy"),
            Stage("live: preflight", [sys.executable, "preflight.py"],
                  "the sweep's own go/no-go against both live hosts: gpu-mode, ComfyUI, "
                  "llama-swap, sleep-inhibitor, container health, disk, strategy enum"),
        ]
    if capture:
        stages.append(
            Stage("capture: ldr api fixture",
                  ["bash", "-c",
                   f"ssh {LDR_HOST} 'bash -c \"docker exec -i local-deep-research python3 -\"'"
                   f" < {HERE / 'capture_fixtures.py'} > {HERE / 'testdata' / 'ldr-api.json'}"],
                  "re-record the real API surface. Needed when the LDR image updates — "
                  "it is pinned to :latest, so that happens without warning",
                  gpu=True))
    return stages


def run(stages: list[Stage], dry: bool) -> int:
    width = max(len(s.name) for s in stages)
    failed = None
    for i, s in enumerate(stages, 1):
        print(f"\n=== [{i}/{len(stages)}] {s.name.ljust(width)} ===")
        print(f"    why: {s.why}")
        print(f"    $ {' '.join(s.argv)}", flush=True)
        if dry:
            continue
        t0 = time.time()
        rc = subprocess.run(s.argv, cwd=HERE, env={**os.environ, **s.env}).returncode
        dt = time.time() - t0
        if rc != 0:
            print(f"\n!! FAILED after {dt:.0f}s (rc={rc}): {s.name}", flush=True)
            failed = s.name
            break
        print(f"    ok ({dt:.0f}s)", flush=True)

    print()
    if dry:
        print(f"DRY RUN — {len(stages)} stage(s) listed, nothing executed")
        return 0
    if failed:
        print(f"FAILED at: {failed}\nNothing after it ran — later stages presume it.")
        return 1
    print(f"ALL {len(stages)} STAGES PASSED")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--remote", action="store_true",
                    help="also sync to docker-01 and run the live preflight")
    ap.add_argument("--capture", action="store_true",
                    help="also re-record testdata/ldr-api.json (~1 min, uses the GPU)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    a = ap.parse_args()
    return run(plan(a.remote, a.capture), a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
