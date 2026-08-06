#!/usr/bin/env python3
"""Verify the whole harness — every suite, both machines — in one command.

    python3 run_tests.py --dry-run    # print the plan, touch nothing
    python3 run_tests.py              # local suites + host checks that are safe live
    python3 run_tests.py --gpu        # + loads models; stops llama-swap for the duration

Run from the Mac. Exits non-zero on the first failure.

WHY THIS EXISTS
---------------
The three things this runs used to be typed by hand into an ssh command line each time:
a `bash -s` heredoc carrying a trap, a `systemctl stop`, an interpreter invocation and a
restore. That is a script — and writing it fresh at each invocation meant it was never
reviewed, never version-controlled, and never tested. One draft of it stopped
llama-swap.service inside a heredoc whose trap would not have fired if ssh dropped,
leaving the deployment down with nobody watching.

So the plan is data (`plan()`), like run_matrix.plan(), and test_run_tests.py asserts its
shape: that nothing remote carries syntax fish will mangle, that every module the remote
entry points import is in the sync list, and that the GPU stage is the one that stops the
service while the live-safe stage is not.

WHAT IT DOES NOT DO
-------------------
It does not stop llama-swap from here. `--stop-service` is passed to
test_integration.py so the stop and the restore live in the process on the host that
holds the card — a `finally` plus SIGINT/SIGTERM/SIGHUP handlers. If this program dies,
or the ssh connection drops, the remote side gets SIGHUP and restores the service itself.
A trap on this end could not do that.

FAIL-FAST, DELIBERATELY
-----------------------
Every stage presumes the ones before it. A failing unit test makes the integration
result meaningless, and an unsynced file makes the remote result a test of a stale copy.
There is no --keep-going: continuing past a failure would produce output that looks like
evidence and is not.
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
DEFAULT_HOST = os.environ.get("BENCH_HOST", "htpc-01")

# Copied to the host's home directory, which is also the remote cwd, so the remote
# commands can use bare relative filenames — see SHELL_SAFE below. This list must be
# closed under the local imports of every remote entry point; test_sync_list_is_closed
# derives that from the AST rather than trusting this comment.
SYNC = ["bench.py", "prompts.py", "rows.py", "run_matrix.py", "test_integration.py",
        "capture_fixtures.py", "preflight.py"]

# What a remote command string may contain. ssh hands the string to the LOGIN shell,
# which on htpc-01 is fish, and fish does not parse $(...), backticks, or bash's
# redirection the way bash does. Note `~` is excluded on purpose: shlex.quote() does not
# consider it safe, so any attempt to build these with shlex.join would emit
# '~/test_integration.py' — quoted, therefore never tilde-expanded, therefore a file-not-
# found from a program that looked correct. Relative paths avoid the whole question.
SHELL_SAFE = re.compile(r"^[A-Za-z0-9_./= -]+$")


@dataclass
class Stage:
    name: str
    argv: list[str]
    why: str = ""
    gpu: bool = False                 # only runs with --gpu
    remote: str = ""                  # the remote command string, if this is an ssh call
    env: dict[str, str] = field(default_factory=dict)


def ssh_stage(name: str, host: str, command: str, why: str, gpu: bool = False) -> Stage:
    """An ssh call whose remote command is a plain string with no shell syntax at all.

    `-tt` is load-bearing, not cosmetic. Without a tty, killing the ssh client does NOT
    signal the remote process: it keeps running, orphaned, holding the GPU with
    llama-swap.service still stopped, until somebody notices. Measured directly — a probe
    that logs the signals it receives recorded nothing under plain ssh and survived the
    disconnect; under `-tt` it recorded SIGHUP, ran its teardown and exited.

    That matters because every remote stage here either holds the card or stops the
    deployed service, and their teardown is a signal handler. A teardown that is never
    signalled is not a teardown.
    """
    return Stage(name=name, argv=["ssh", "-tt", host, command], why=why, gpu=gpu,
                 remote=command)


def plan(host: str = DEFAULT_HOST, gpu: bool = False, smoke: bool = False,
         capture: bool = False) -> list[Stage]:
    """Every check, cheapest first.

    Ordering is load-bearing: a syntax error must cost a second, not an ssh round trip
    and a model load. Local suites, then the local dry runs that exercise the real code
    paths with no GPU, then the sync, then anything remote.
    """
    stages = [
        Stage("unit: bench", [sys.executable, "test_bench.py"],
              "the cache-contamination gate and the row format"),
        Stage("unit: matrix", [sys.executable, "test_run_matrix.py"],
              "the matrix IS the experiment; asserts its shape without burning 2h of GPU"),
        Stage("unit: rows", [sys.executable, "test_rows.py"],
              "row parsing and validation — the 'is the output correct' half, which "
              "decides whether a measured row is allowed to reach results.md"),
        Stage("unit: preflight", [sys.executable, "test_preflight.py"],
              "the preconditions that gate the 2h run — what it needs on disk, which "
              "failures are blocking, and whether the runtime estimate is credible"),
        Stage("unit: fixtures", [sys.executable, "test_fixtures.py"],
              "every parser against REAL captured tool output in testdata/. A "
              "hand-written fixture cannot catch a wrong assumption about a format, "
              "because the same assumption produces the parser and the fixture"),
        Stage("unit: self", [sys.executable, "test_run_tests.py"],
              "this orchestrator's own tests — it is a script like any other"),
        Stage("dry: bench.py", [sys.executable, "bench.py", "--dry-run", "--variants", "5"],
              "arg parsing, corpus generation, dispersion and the report, no container"),
        Stage("dry: run_matrix.py", [sys.executable, "run_matrix.py", "--dry-run"],
              "prints all 19 invocations and touches nothing"),
        Stage("sync", ["scp", "-q", *[str(HERE / f) for f in SYNC], f"{host}:"],
              "everything remote below tests THESE files, not a stale copy"),
        ssh_stage("remote: preflight", host, "python3 preflight.py",
                  "the matrix's own go/no-go, run against the live host: images pulled, "
                  "models on disk, card idle, no stray container. Cheap, and it is what "
                  "stops a 2h run starting against a busy GPU"),
        ssh_stage("remote: integration", host, "python3 test_integration.py",
                  "every podman/curl/llama-server invocation, against real podman. "
                  "Safe while the deployment is live: own container name, no model load"),
        Stage("local: run-remote.sh", [str(HERE / "run-remote.sh"), "--model", "gemma",
                                       "--dry-run", "--variants", "3",
                                       "--label", "two words"],
              "the wrapper's own %q re-quoting claim: --label must arrive as ONE argument",
              env={"BENCH_HOST": host}),
    ]
    if gpu:
        stages.append(ssh_stage(
            "remote: integration --gpu", host,
            "python3 test_integration.py --gpu --stop-service",
            "loads models and runs a real completion, incl. the prompt_n determinism "
            "anchor. --stop-service frees the card and restores it in the remote "
            "process's finally, so a dropped connection still restores the deployment",
            gpu=True))
    if capture:
        stages += [
            ssh_stage("remote: capture fixtures", host, "python3 capture_fixtures.py",
                      "record REAL tool output — startup logs, amd-smi, --list-devices, "
                      "a completion — so the parsers are tested against the format they "
                      "actually meet. Loads a model, so it stops the service (~3 min)",
                      gpu=True),
            Stage("fetch fixtures", ["scp", "-q", "-r", f"{host}:testdata/",
                                     str(HERE)],
                  "bring the captured output back so the unit tests can run offline",
                  gpu=True),
        ]
    if smoke:
        stages.append(ssh_stage(
            "remote: matrix --smoke", host, "python3 run_matrix.py --smoke",
            "the only run that executes run_matrix's OWN commands — arm(), cleanup(), "
            "both images, the graphics-queue container, systemctl stop/start — and "
            "checks every row it produces. ~12 min, versus ~2h for the real matrix",
            gpu=True))
    return stages


# --------------------------------------------------------------------------- runtime

def run(stages: list[Stage], dry: bool) -> int:
    width = max(len(s.name) for s in stages)
    failed = None
    for i, s in enumerate(stages, 1):
        print(f"\n=== [{i}/{len(stages)}] {s.name.ljust(width)} ===")
        print(f"    why: {s.why}")
        print(f"    $ {' '.join(s.argv)}", flush=True)
        if dry:
            continue
        env = {**os.environ, **s.env}
        t0 = time.time()
        rc = subprocess.run(s.argv, cwd=HERE, env=env).returncode
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
    ap.add_argument("--gpu", action="store_true",
                    help="also run the host tests that load a model (~4 min, stops "
                         "llama-swap.service on the host for the duration)")
    ap.add_argument("--smoke", action="store_true",
                    help="also run run_matrix.py --smoke on the host (~12 min): the only "
                         "check that exercises the 2h driver's own commands")
    ap.add_argument("--capture", action="store_true",
                    help="re-record testdata/ from real tool output on the host (~3 min). "
                         "Needed when the images change")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    a = ap.parse_args()
    return run(plan(a.host, a.gpu, a.smoke, a.capture), a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
