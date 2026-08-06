#!/usr/bin/env python3
"""Preconditions for the unattended matrix. Runs ON htpc-01, and run_matrix runs it first.

    python3 preflight.py            # report, exit non-zero on any FAIL
    python3 preflight.py --warn-only

Every check here corresponds to a way the 2-hour run dies or produces junk *without
failing loudly*. The expensive failure is not a crash — it is a session that finishes and
whose numbers cannot be used.

Structural, not procedural: run_matrix calls check_all() before stopping the service, so
a bad precondition aborts in seconds instead of 90 minutes in. There is nothing to
remember.

FAIL kills the run. WARN is recorded and continues — used where the condition degrades
confidence but does not invalidate rows.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import bench
import run_matrix as rm

# A model plus its KV at the largest planned context, with the 1.5 GB floor on top. If
# less than this is free before we start, something else is holding the card.
MIN_BASELINE_FREE_MB = 13000
MIN_DISK_FREE_MB = 2000


class Result:
    def __init__(self, name: str, ok: bool, detail: str = "", fatal: bool = True):
        self.name, self.ok, self.detail, self.fatal = name, ok, detail, fatal

    @property
    def label(self) -> str:
        return "PASS" if self.ok else ("FAIL" if self.fatal else "WARN")

    def __str__(self) -> str:
        return f"  {self.label}  {self.name}" + (f"  [{self.detail}]" if self.detail else "")


def sh(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


# --------------------------------------------------------------- pure logic

def models_needed() -> set[str]:
    """Every GGUF the matrix will ask for, derived from plan() rather than listed."""
    names = set()
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend) + rm.probes(backend):
            names.add(bench.MODELS[row[row.index("--model") + 1]][0])
    return names


def missing_images(available: str) -> list[str]:
    """Image tags the matrix needs that are not already pulled.

    A mid-run `podman run` that has to fetch ~5 GB turns a transient network failure into
    a dead unattended session, and the pull happens between arms where nobody is looking.
    """
    have = set(available.split())
    return [tag for tag in rm.IMAGE.values() if tag not in have]


def estimate_runtime_s(rows: int, probes: int, variants: int, gen_tok: int,
                       gen_rate: float, prefill_tok: int, prefill_rate: float,
                       load_s: float = 45.0) -> float:
    """Predicted wall clock, so 'about two hours' is a number that can be checked.

    Matters for two reasons: an estimate wildly under the real thing means the session
    outlives the window it was given, and an estimate wildly over means something hung.
    """
    per_variant = gen_tok / gen_rate + prefill_tok / prefill_rate
    return rows * (load_s + variants * per_variant) + probes * load_s


# --------------------------------------------------------------- host checks

def check_sudo() -> Result:
    """Detached there is no tty, so a sudo password prompt hangs forever rather than
    failing. Every podman and systemctl call in the matrix needs it."""
    return Result("sudo -n true (no password prompt in a detached run)",
                  sh("sudo", "-n", "true").returncode == 0)


def check_images() -> Result:
    out = sh("sudo", "podman", "images", "--format", "{{.Repository}}:{{.Tag}}").stdout
    missing = missing_images(out)
    return Result("both images pulled (no mid-run network dependency)", not missing,
                  f"missing {missing}" if missing else "both present")


def check_models() -> Result:
    missing = [p for p in sorted(models_needed())
               if not (Path(rm.MODELS_DIR) / Path(p).name).exists()]
    return Result("every model the matrix asks for is on disk", not missing,
                  f"missing {missing}" if missing else f"{len(models_needed())} present")


def check_baseline_vram() -> Result:
    """ComfyUI, a game, or a stray llama-server holding the card makes every baseline
    figure wrong and can OOM the largest context outright."""
    free = bench.free_vram_mb()
    ok = free.isdigit() and int(free) >= MIN_BASELINE_FREE_MB
    if ok:
        return Result(f"card is idle (>={MIN_BASELINE_FREE_MB} MB free before we start)",
                      True, f"{free} MB free")
    # Name the actual holder. "run gpu-mode llm" is wrong advice when what is resident is
    # a model llama-swap loaded, and sending someone to the wrong fix costs a session.
    running = sh("sudo", "podman", "exec", rm.SERVICE, "curl", "-sf",
                 "localhost:8080/running").stdout
    if running.strip() not in ("", "[]", "{}") and "[]" not in running:
        why = (f"llama-swap has a model resident. It unloads itself after ttl 900, or "
               f"force it now:  sudo podman exec {rm.SERVICE} curl -s -X POST "
               "localhost:8080/api/models/unload")
    elif sh("systemctl", "is-active", "comfyui").stdout.strip() == "active":
        why = "ComfyUI is running — `gpu-mode llm` stops it"
    else:
        why = "something else holds the card; check `amd-smi process -g 0`"
    return Result(f"card is idle (>={MIN_BASELINE_FREE_MB} MB free before we start)",
                  False, f"{free} MB free — {why}")


def check_no_stray_containers() -> Result:
    """A leftover llama-bench makes `podman run` fail on a name conflict, and a leftover
    container named llama-swap makes the service refuse to start at teardown."""
    out = sh("sudo", "podman", "ps", "-a", "--format", "{{.Names}}").stdout.split()
    stray = [n for n in out if n == rm.CONTAINER]
    return Result("no stray bench container from a previous run", not stray, str(stray))


def check_disk() -> Result:
    free_mb = shutil.disk_usage(Path.home()).free // 1048576
    return Result(f"disk for logs (>={MIN_DISK_FREE_MB} MB in $HOME)",
                  free_mb >= MIN_DISK_FREE_MB, f"{free_mb} MB free")


SLEEP_CHECK = "/etc/sleep-inhibitor.d/llama-bench.sh"


def check_sleep_guard() -> Result:
    """The matrix must not be suspended part-way through.

    htpc-01 suspends on its own schedule, and its sleep-inhibitor service holds a
    block-mode lock only while one of /etc/sleep-inhibitor.d/'s checks reports busy.
    During a matrix ALL of the stock checks report idle:

      llama-swap.sh  we stop llama-swap.service for the whole run, and the check treats
                     an unreachable container as nothing-on-the-GPU
      comfyui.sh     ComfyUI is stopped by `gpu-mode llm`, a precondition
      ansible.sh     no playbook is running

    llama-bench.sh closes that hole by reporting busy while a bench container exists.
    Without it, ~92 minutes run unprotected while a process holds ~10 GiB across a GPU
    context — and suspending that "does not reliably survive resume".

    BLOCKING: a suspended run is not a slow run, it is a void session.
    """
    if not Path(SLEEP_CHECK).exists():
        return Result("sleep guard installed", False,
                      f"{SLEEP_CHECK} missing — deploy with "
                      "`ansible-playbook playbook-htpc-01.yaml --tags sleep-inhibitor`")
    if not os.access(SLEEP_CHECK, os.X_OK):
        # sleep-inhibitor.sh skips non-executable files silently.
        return Result("sleep guard installed", False,
                      f"{SLEEP_CHECK} is not executable — the inhibitor skips it")
    state = sh("systemctl", "is-active", "sleep-inhibitor").stdout.strip()
    return Result("sleep guard installed and running", state == "active",
                  f"plugin present, sleep-inhibitor is {state}")


def check_service_is_ours_to_stop() -> Result:
    """The matrix stops llama-swap.service and restarts it at teardown. If it is already
    stopped, something else is mid-flight and the restore would 'fix' a state we did not
    create."""
    state = sh("systemctl", "is-active", rm.SERVICE).stdout.strip()
    return Result(f"{rm.SERVICE} is active now (so teardown restores what we found)",
                  state == "active", state, fatal=False)


def check_all() -> list[Result]:
    return [check_sudo(), check_images(), check_models(), check_baseline_vram(),
            check_no_stray_containers(), check_disk(), check_sleep_guard(),
            check_service_is_ours_to_stop()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--warn-only", action="store_true",
                    help="report without failing — for inspecting a host mid-session")
    a = ap.parse_args()

    print("=== preflight ===")
    results = check_all()
    for r in results:
        print(r)

    rows = sum(len(rm.plan(b)) for b in ("rocm", "vulkan")) + 2
    probes = sum(len(rm.probes(b)) for b in ("rocm", "vulkan"))
    est = estimate_runtime_s(rows, probes, variants=5, gen_tok=1024, gen_rate=40.0,
                             prefill_tok=21828, prefill_rate=1150.0)
    print(f"\n  {rows} timed rows + {probes} probes, estimated {est / 60:.0f} min "
          f"({est / 3600:.1f} h) at gemma's measured rates")

    fatal = [r for r in results if not r.ok and r.fatal]
    warn = [r for r in results if not r.ok and not r.fatal]
    if warn:
        print(f"\n  {len(warn)} warning(s) — the run may proceed:")
        for r in warn:
            print(f"    {r.name}: {r.detail}")
    if fatal:
        print(f"\n{len(fatal)} BLOCKING failure(s):")
        for r in fatal:
            print(f"  {r.name}: {r.detail}")
        return 0 if a.warn_only else 1
    print("\npreflight OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
