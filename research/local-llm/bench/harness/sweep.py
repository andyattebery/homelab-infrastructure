#!/usr/bin/env python3
"""Launch a shootout on docker-01, detached. Runs FROM THE MAC.

    python3 sweep.py --n 20              # preflight, sync, start capture, launch in tmux
    python3 sweep.py --dry-run           # print every command, run none
    python3 sweep.py --status            # progress of the running sweep
    python3 sweep.py --stop              # stop the capture and the tmux session

WHY A LAUNCHER RATHER THAN A DOCUMENTED PROCEDURE
-------------------------------------------------
Three things have to happen in one order, on two hosts, and getting them wrong is silent:

1. **preflight before anything** — `research/local-llm/docs/README.md:341`: a guard that
   errors must stop the run.
2. **the capture must start BEFORE the first query** (`README.md:57-62`). It cannot be the
   runner's job: by the time the runner is up, trial one is already in flight. If it never
   starts, `upstream.summarise` correctly returns None, every trial records unknown cost,
   and **the sweep still completes looking perfectly healthy** — Phase 0's cost model half
   missing, discovered days later.
3. **tmux, not a foreground ssh** — a multi-hour sweep must survive a dropped connection and
   a closed laptop (`current-work.md:328-332`).

Teardown of the capture belongs to the *runner*, in a `finally`, not here: the process
holding a resource is the one that can reliably release it. A launcher that has already
exited cannot.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent

LDR_HOST = "docker-01"
LLAMA_HOST = "htpc-01"
CONTAINER = "local-deep-research"

# `/data` inside the container is this path on docker-01 (current-work.md:334). Writing the
# capture here is what makes it readable by the runner as /data/bench/upstream.log without
# any second copy.
HOST_BENCH = "/mnt/data/local-deep-research/data/bench"
# Writable landing zone: HOST_BENCH is root-owned, ssh lands unprivileged.
STAGE_DIR = "/tmp/ldr-bench-sync"
# PID of the capture curl, so it can be checked and killed precisely.
CAP_PID = "/tmp/ldr-capture.pid"
CONT_BENCH = "/data/bench"

SESSION = "ldr-shootout"
SYNC = ["shootout.py", "ldr_trial.py", "records.py", "upstream.py"]


@dataclass
class Step:
    name: str
    host: str | None          # None = local
    command: str
    why: str


# The capture URL is DERIVED on the host, not written down here.
#
# The docs give it as `https://llama-swap.htpc-01.$DOMAIN/...`, but `$DOMAIN` is a
# placeholder in prose, not a real environment variable — expanding it yields an empty
# string and a URL that silently 404s. The real domain comes from `vault_domain_name`
# (ansible/group_vars/*/vars.yaml:2), i.e. it is a secret and does not belong in this file.
#
# The LDR container already holds the answer: `LDR_LLM_OPENAI_ENDPOINT_URL` is the llama-swap
# base URL it actually talks to. Deriving from that is both secret-free and *self-consistent*
# — we capture the endpoint serving the trials, not one we hoped was the same.
CAPTURE_URL_CMD = (
    "docker exec " + CONTAINER + " printenv LDR_LLM_OPENAI_ENDPOINT_URL "
    "| sed 's#/v1$##'")


def steps(n: int, out: str, questions: str) -> list[Step]:
    """Every command, in order. Pure, so `--dry-run` and the tests share it."""
    cap = f"{HOST_BENCH}/upstream.log"
    return [
        Step("stage dir", LDR_HOST, f"mkdir -p {STAGE_DIR} && echo ok",
             "scp cannot create its own destination directory"),
        # Sync BEFORE preflight, deliberately. Copying files is reversible prep, not "the
        # run" the guard exists to stop — and preflight checks that the harness is present,
        # so running it first can never pass on a fresh host. More importantly this way the
        # guard validates the code that will ACTUALLY execute rather than whatever happened
        # to be on the host from a previous session.
        #
        # Two stages because `HOST_BENCH` is **root-owned** (drwxr-xr-x root root) while ssh
        # lands as an unprivileged user: a direct scp fails with permission denied, and it
        # fails half way through a launch rather than up front. Staging through /tmp keeps
        # the privileged step to a single `install`.
        Step("sync (stage)", None,
             "scp -q " + " ".join(str(HERE / f) for f in SYNC)
             + f" {HERE / 'testdata' / 'questions.json'} {LDR_HOST}:{STAGE_DIR}/",
             "copy into a writable staging dir; HOST_BENCH is root-owned"),
        Step("sync (install)", LDR_HOST,
             f"sudo install -d -m 0755 {HOST_BENCH} && "
             f"sudo install -m 0644 {STAGE_DIR}/*.py {STAGE_DIR}/questions.json "
             f"{HOST_BENCH}/ && ls {HOST_BENCH}",
             "the sweep runs THESE files, not whatever was left on the host"),
        Step("preflight", None, f"{sys.executable} {HERE / 'preflight.py'}",
             "both hosts: gpu-mode llm, ComfyUI stopped, llama-swap serving, "
             "sleep-inhibitor active, container healthy, disk, strategy enum, and the "
             "harness just synced above"),
        Step("start capture", LDR_HOST,
             f"BASE=$({CAPTURE_URL_CMD}); test -n \"$BASE\" || {{ echo NO_ENDPOINT; exit 1; }}; "
             f"sudo sh -c \"nohup curl -Ns '$BASE/logs/stream/upstream?no-history' "
             f"> {cap} 2>/dev/null & echo \\$! > {CAP_PID}\"; "
             f"echo started pid=$(cat {CAP_PID})",
             "BEFORE the first query. On docker-01's host, not in the container and not on "
             "the Mac, so the runner reads the same file at /data/bench/upstream.log. The "
             "URL is derived from the container's own endpoint, so it cannot drift from "
             "what LDR actually calls"),
        Step("verify capture", LDR_HOST,
             f"sleep 3; test -f {cap} && sudo kill -0 $(cat {CAP_PID}) 2>/dev/null "
             f"&& echo alive || echo EMPTY",
             "check the curl process BY PID, recorded when it was started. Not `pgrep -f "
             "logs/stream/upstream`: that pattern appears in this very command line, so "
             "pgrep matches its own shell and the check can never fail — a guard that always "
             "passes. Not the file's size either: `?no-history` streams live only, so the "
             "file is legitimately empty until the first query"),
        Step("launch", LDR_HOST,
             f"tmux new -d -s {SESSION} "
             + shlex.quote(
                 f"docker exec {CONTAINER} sh -c " + shlex.quote(
                     f"python3 {CONT_BENCH}/shootout.py "
                     f"--n {n} --out {out} --capture {CONT_BENCH}/upstream.log "
                     f"--questions-file {CONT_BENCH}/questions.json "
                     f"2>&1 | tee -a {CONT_BENCH}/shootout.log")),
             "detached, so a dropped ssh or a closed laptop costs nothing. The `sh -c` is "
             "load-bearing: without it the pipe and `tee` run on the HOST, where "
             f"{CONT_BENCH} does not exist — the first smoke run lost its whole log that "
             "way while the sweep itself ran fine, so the failure is invisible"),
    ]


def ssh(host: str, command: str) -> subprocess.CompletedProcess:
    """Wrapped in bash -c: both hosts use fish as the login shell, which parses $(...),
    redirection and `&&` differently. An unwrapped command fails with a `fish:` error that
    reads like the remote program crashed."""
    return subprocess.run(["ssh", host, f"bash -c {shlex.quote(command)}"],
                          capture_output=True, text=True)


def run_step(s: Step) -> tuple[bool, str]:
    if s.host is None:
        p = subprocess.run(s.command, shell=True, capture_output=True, text=True, cwd=HERE)
    else:
        p = ssh(s.host, s.command)
    return p.returncode == 0, (p.stdout or p.stderr).strip()[:400]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default=f"{CONT_BENCH}/shootout.jsonl")
    ap.add_argument("--questions", default=f"{CONT_BENCH}/questions.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    a = ap.parse_args()

    if a.status:
        p = ssh(LDR_HOST, f"tmux has-session -t {SESSION} >/dev/null 2>&1 "
                          f"&& echo 'sweep: RUNNING' || echo 'sweep: not running'; "
                          f"docker exec {CONTAINER} python3 {CONT_BENCH}/shootout.py "
                          f"--status --out {a.out} --questions-file {a.questions} "
                          f"--n {a.n}")
        print((p.stdout or p.stderr).rstrip())
        return 0

    if a.stop:
        # The capture is a bare curl; the runner stops its own in a finally, so this is the
        # belt-and-braces path for an abandoned run.
        # Kill by recorded PID, for the same reason the verify step does: a `pkill -f`
        # on this pattern can match the very shell running it.
        p = ssh(LDR_HOST, f"tmux kill-session -t {SESSION} 2>&1 || true; "
                          f"test -f {CAP_PID} && sudo kill $(cat {CAP_PID}) 2>/dev/null; "
                          f"sudo rm -f {CAP_PID}; echo stopped")
        print((p.stdout or p.stderr).rstrip())
        return 0

    plan = steps(a.n, a.out, a.questions)
    for i, s in enumerate(plan, 1):
        where = s.host or "local"
        print(f"\n=== [{i}/{len(plan)}] {s.name}  ({where}) ===")
        print(f"    why: {s.why}")
        print(f"    $ {s.command}")
        if a.dry_run:
            continue
        ok, out = run_step(s)
        if out:
            print(f"    {out}")
        if not ok or (s.name == "verify capture" and "EMPTY" in out):
            print(f"\n!! FAILED at {s.name} — nothing after it ran.", file=sys.stderr)
            if s.name != "preflight":
                print("   Run `sweep.py --stop` before retrying so no capture is orphaned.",
                      file=sys.stderr)
            return 1

    if a.dry_run:
        print(f"\nDRY RUN — {len(plan)} step(s) listed, nothing executed")
        return 0

    print(f"\nlaunched. watch:   ssh {LDR_HOST} -t 'tmux attach -t {SESSION}'")
    print(f"          progress: python3 sweep.py --status")
    print(f"          stop:     python3 sweep.py --stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
