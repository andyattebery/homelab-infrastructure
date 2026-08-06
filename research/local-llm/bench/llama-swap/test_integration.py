#!/usr/bin/env python3
"""Integration tests: every external command the harness issues, against real podman.

Runs ON htpc-01 (needs podman + the model bind mount). The unit tests cover logic; these
cover the thing logic tests cannot — that each `podman` / `curl` / `llama-server`
invocation is actually well-formed and does what the code assumes.

Do not invoke it by hand — `python3 run_tests.py [--gpu]` from the Mac syncs the files
and runs this with the right flags. Hand-typed ssh/scp lines are how the sync list and
the service teardown drifted out of version control in the first place.

Deliberately uses its own container name and does NOT stop llama-swap.service, so it is
safe to run while the deployment is live. Only the two tests marked GPU load a model.

    --gpu             also load a model and run one real completion (~90s)
    --stop-service    stop llama-swap.service first and restore it on ANY exit

--stop-service lives here, in the process that actually needs the card, rather than in
whatever shell invoked it. That is the difference between a guaranteed restore and a
hoped-for one: this process handles SIGINT/SIGTERM/SIGHUP, so if the ssh connection
carrying it drops, the SIGHUP restores the deployment. A trap on the calling machine
could not — it would exit having left the service down on a host nobody is watching.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import bench
import prompts
import rows as rows_mod
import run_matrix as rm

CONTAINER = "bench-selftest"       # never llama-bench or llama-swap

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""),
          flush=True)
    return ok


def sh(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def rm_container(name: str = CONTAINER) -> None:
    sh(["sudo", "podman", "rm", "-f", name])


@contextlib.contextmanager
def service_stopped(name: str = bench.SERVICE):
    """bench.service_stopped, plus removal of THIS file's selftest container.

    The stop/restore itself is shared rather than copied — two implementations of a
    teardown is two things that can be separately wrong, and the teardown is the part
    that has already been broken once.
    """
    with bench.service_stopped(name):
        try:
            yield
        finally:
            rm_container()


# --------------------------------------------------------------------- host

def test_host_vram_reader():
    """free_vram_mb() must return a plausible MB integer, not '?' and not bytes."""
    v = bench.free_vram_mb()
    ok = v != "?" and v.isdigit() and 1000 < int(v) < 64000
    check("host: free_vram_mb() returns plausible MB", ok, f"{v} MB")


def test_host_sudo_is_passwordless():
    """A password prompt hangs a detached run forever rather than failing."""
    check("host: sudo -n true", sh(["sudo", "-n", "true"]).returncode == 0)


# ---------------------------------------------------------------- container

def test_container_argv_starts(backend: str):
    rm_container()
    argv = rm.container_argv(backend)
    argv = [a if a != rm.CONTAINER else CONTAINER for a in argv]
    r = sh(argv)
    if not check(f"podman run ({backend}) from container_argv()", r.returncode == 0,
                 r.stderr.strip()[:70]):
        return False
    box = bench.Box(CONTAINER)

    check(f"  podman exec ({backend})", box.exec("true").returncode == 0)
    check(f"  models mounted ({backend})",
          int(box.exec("sh", "-c", "ls /models/*.gguf | wc -l").stdout.strip() or 0) >= 4)
    check(f"  /dev/kfd + /dev/dri present ({backend})",
          box.exec("sh", "-c", "test -e /dev/kfd && test -d /dev/dri").returncode == 0)

    # Box.has() — the bug that silently reported EVICTED as n/a on ROCm was calling
    # `podman exec <c> command -v x`, where `command` is a shell builtin and never an
    # executable. Assert the ROCm/Vulkan split we actually depend on.
    check(f"  Box.has('curl') ({backend})", box.has("curl"))
    check(f"  Box.has('pkill') ({backend})", box.has("pkill"))
    check(f"  Box.has('nonexistent-xyz') is False ({backend})",
          not box.has("nonexistent-xyz"))
    check(f"  Box.has('amd-smi') == {backend == 'rocm'} ({backend})",
          box.has("amd-smi") == (backend == "rocm"))

    # mkdir + cp: the corpus transfer path
    cdir = "/tmp/selftest.d"
    check(f"  podman exec mkdir -p ({backend})",
          box.exec("mkdir", "-p", cdir).returncode == 0)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "v0.json"
        p.write_text('{"hello":"world"}')
        box.cp(p, f"{cdir}/")
        got = box.exec("cat", f"{cdir}/v0.json").stdout
    check(f"  podman cp round-trip ({backend})", got.strip() == '{"hello":"world"}', got[:40])

    # The corpus round-trip, byte-for-byte. `curl -d @file` reads this inside the
    # container, so a truncation or an encoding change here surfaces as an HTTP 400
    # minutes into a row rather than as a visible failure.
    with tempfile.TemporaryDirectory() as td:
        host = Path(td)
        prompts.write_corpus(host, 2, 40, needle=True, max_tokens=16)
        box.exec("mkdir", "-p", cdir)
        for v in range(2):
            box.cp(host / f"v{v}.json", f"{cdir}/")
        local = (host / "v0.json").read_bytes()
        remote = box.exec("cat", f"{cdir}/v0.json").stdout.encode()
        check(f"  corpus survives podman cp byte-identical ({backend})",
              local == remote, f"{len(local)} vs {len(remote)} bytes")
        # And that llama-server's own client accepts the file as a request body. Nothing
        # is listening, so a connection refusal is success: what is being tested is that
        # curl PARSED the @file argument, not that the request succeeded.
        r = box.exec("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                     f"localhost:{bench.PORT}/v1/chat/completions",
                     "-H", "Content-Type: application/json", "-d", f"@{cdir}/v0.json")
        check(f"  curl accepts -d @file (no 'couldn't open' error) ({backend})",
              "could not open" not in r.stderr.lower()
              and "couldn't open" not in r.stderr.lower(), r.stderr.strip()[:60])

    # The redirect-inside-the-container form used to capture llama-server's stderr.
    log = "/tmp/selftest.log"
    box.exec("sh", "-c", f": > {log}")
    check(f"  startlog truncate empties the file ({backend})",
          box.exec("cat", log).stdout == "")
    box.exec_detached(f"exec sh -c 'echo hello-from-detached' > {log} 2>&1")
    time.sleep(1)
    check(f"  exec_detached + redirect captured output ({backend})",
          "hello-from-detached" in box.exec("cat", log).stdout)

    # pkill with a multi-word pattern as ONE argv element (no shell to split it)
    box.exec_detached(f"exec sleep 300 > /dev/null 2>&1")
    time.sleep(1)
    before = box.exec("pgrep", "-f", "sleep 300").returncode
    box.exec("pkill", "-f", "sleep 300")
    time.sleep(1)
    after = box.exec("pgrep", "-f", "sleep 300").returncode
    check(f"  pkill -f 'multi word pattern' ({backend})", before == 0 and after != 0)

    # curl to a port with nothing listening must fail cleanly, not hang: this is the
    # health-poll and the models/unload call, both of which run before any server exists.
    t0 = time.time()
    rc = box.exec("curl", "-sf", f"localhost:{bench.PORT}/health").returncode
    check(f"  curl to dead port fails fast ({backend})",
          rc != 0 and time.time() - t0 < 10, f"{time.time()-t0:.1f}s")

    # --list-devices: the RADV-vs-lavapipe check, and it must name the right backend
    out = box.exec("/app/llama-server", "--list-devices").stdout
    want = "ROCm0" if backend == "rocm" else "Vulkan0"
    check(f"  llama-server --list-devices reports {want} ({backend})", want in out,
          out.strip().splitlines()[-1][:60] if out.strip() else "no output")
    if backend == "vulkan":
        check("  Vulkan device is RADV, not lavapipe/AMDVLK", "RADV" in out,
              "ICD pin failed — would benchmark the CPU" if "RADV" not in out else "")

    if backend == "rocm":
        m = box.exec("amd-smi", "metric", "-g", "0", "--mem")
        check("  amd-smi metric --mem parses (rocm)",
              m.returncode == 0 and "FREE_VRAM" in m.stdout)
        pr = box.exec("amd-smi", "process", "-g", "0")
        check("  amd-smi process + parse_evicted (rocm)",
              pr.returncode == 0 and bench.parse_evicted(pr.stdout) is not None)

    rm_container()
    return True


def test_gpu_full_row():
    """One real bench.py row end to end, and the determinism anchor.

    prompt_n MUST be 21,828 at --lines 1200 on gemma. That number is the only proof the
    Python rewrite drives llama-server identically to the shell version it replaced; if
    it moves, the corpus changed and every historical row is invalidated.

    Note this row does NOT pass --verbose, matching every row run_matrix.plan() emits:
    verbose logging during generation is overhead on the number being measured. The KV
    and device-banner assertions therefore live in test_gpu_probe_captures_kv_lines,
    which exercises the untimed --load-only --verbose probe instead.
    """
    rm_container()
    argv = [a if a != rm.CONTAINER else CONTAINER for a in rm.container_argv("rocm")]
    if not check("gpu: container up", sh(argv).returncode == 0):
        return
    # Anchor derived from bench.EXPECTED_PROMPT_N, never written down here. Passing it as
    # --expect-prompt-n also proves the flag works end to end against a real server.
    anchor = bench.EXPECTED_PROMPT_N[("gemma", bench.DEFAULT_LINES)]
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "bench.py"),
                        "--container", CONTAINER, "--backend", "rocm", "--model", "gemma",
                        "--ctx", "32768", "--variants", "3",
                        "--expect-prompt-n", str(anchor), "--label", "integration"],
                       capture_output=True, text=True)
    line = rows_mod.extract_row(r.stdout)
    if not check("gpu: bench.py emitted a row", r.returncode == 0 and line is not None,
                 (r.stderr or r.stdout)[-200:] if line is None else ""):
        rm_container()
        return
    try:
        parsed = rows_mod.parse_row(line)
    except ValueError as e:
        check("gpu: row column count matches header", False, str(e))
        rm_container()
        return
    check("gpu: row column count matches header", True, f"{len(parsed)} cells")
    check(f"gpu: DETERMINISM ANCHOR prompt_n == {anchor}",
          parsed["prompt_n"] == str(anchor), f"got {parsed['prompt_n']}")
    # The same validation run_matrix applies to every row it records, against a real one.
    problems = rows_mod.check_row(parsed, expect_backend="rocm", expect_variants=3)
    check("gpu: the real row passes rows.check_row", not problems, "; ".join(problems))
    rm_container()


def test_sleep_lock_round_trip():
    """The bench must take the lock, and must give it back.

    A lock never taken lets the host suspend ~92 minutes into a run, holding ~10 GiB
    across a GPU context. A lock never released pins the host awake forever. Both are
    silent, so both are tested against the real file and the real plugin.
    """
    plugin = "/etc/sleep-inhibitor.d/llama-bench.sh"
    if not check("sleep guard: plugin is deployed", Path(plugin).exists(),
                 plugin if Path(plugin).exists()
                 else "MISSING — deploy with --tags sleep-inhibitor"):
        return

    # Idle before we start: nothing else should be holding it.
    check("sleep guard: reports idle with no lock",
          sh([plugin]).returncode != 0 or Path(bench.SLEEP_LOCK).exists())

    with bench.sleep_lock():
        held = Path(bench.SLEEP_LOCK)
        check("sleep guard: lock file created", held.exists(), bench.SLEEP_LOCK)
        content = sh(["cat", bench.SLEEP_LOCK]).stdout.strip()
        check("sleep guard: lock records OUR pid", content == str(os.getpid()),
              f"{content!r} vs {os.getpid()}")
        check("sleep guard: plugin reports BUSY while held",
              sh([plugin]).returncode == 0)

    check("sleep guard: lock removed on exit", not Path(bench.SLEEP_LOCK).exists())
    check("sleep guard: plugin reports idle again", sh([plugin]).returncode != 0)


def test_sleep_lock_stale_pid_is_ignored():
    """A run killed with SIGKILL leaves the lock behind. If the plugin honoured it, the
    host would never sleep again — so a lock whose process is gone must read as idle."""
    plugin = "/etc/sleep-inhibitor.d/llama-bench.sh"
    if not Path(plugin).exists():
        return
    dead = 4194303          # above /proc/sys/kernel/pid_max default: cannot be live
    for label, body in (("stale pid", str(dead)), ("malformed", "not-a-pid"),
                        ("empty", "")):
        sh(["sudo", "-n", "sh", "-c",
            f"printf '%s\\n' {shlex.quote(body)} > {bench.SLEEP_LOCK}"])
        check(f"sleep guard: {label} lock reads as idle", sh([plugin]).returncode != 0,
              f"content={body!r}")
    sh(["sudo", "-n", "rm", "-f", bench.SLEEP_LOCK])
    check("sleep guard: cleaned up after stale test",
          not Path(bench.SLEEP_LOCK).exists())


def test_gpu_load_only():
    rm_container()
    argv = [a if a != rm.CONTAINER else CONTAINER for a in rm.container_argv("rocm")]
    sh(argv)
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "bench.py"),
                        "--container", CONTAINER, "--backend", "rocm", "--model", "gemma",
                        "--ctx", "4096", "--load-only"], capture_output=True, text=True)
    check("gpu: --load-only reports VRAM and exits 0",
          r.returncode == 0 and "LOAD-ONLY:" in r.stdout,
          r.stdout.strip().splitlines()[-1][:70] if r.stdout.strip() else "")
    rm_container()


def test_gpu_probe_captures_kv_lines():
    """The exact form run_matrix.probes() emits: --load-only --verbose, untimed.

    This is where the startup-log capture is proven. The keys in bench.py are matched as
    substrings against the lowercased line, and an earlier version looked for "kv cache"
    when the real line is `llama_kv_cache: size = ...` — underscore, not space — so KV
    size was silently never recorded. Assert the real format, not "something matched".

    It also carries the RADV check: at normal verbosity --list-devices already names the
    driver, and a Vulkan arm that quietly selected lavapipe would benchmark the CPU.
    """
    probe = rm.probes("rocm")[0]
    argv = [a if a != rm.CONTAINER else CONTAINER for a in probe]
    rm_container()
    if not check("gpu: probe container up",
                 sh([a if a != rm.CONTAINER else CONTAINER
                     for a in rm.container_argv("rocm")]).returncode == 0):
        return
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "bench.py"), *argv],
                       capture_output=True, text=True)
    low = r.stdout.lower()
    check("gpu: probe exits 0", r.returncode == 0, (r.stderr or r.stdout)[-150:])
    check("gpu: KV cache line captured from startup log", "llama_kv_cache" in low)
    check("gpu: KV line carries cell/layer detail", "cells" in low and "layers" in low)
    check("gpu: device line captured", "using device" in low)
    check("gpu: --list-devices named the backend device", "rocm0" in low)
    rm_container()


# ---------------------------------------------------------------- dry paths

def test_dry_run_needs_no_container():
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "bench.py"),
                        "--dry-run", "--variants", "3", "--container", "does-not-exist"],
                       capture_output=True, text=True)
    check("bench.py --dry-run works with no container at all",
          r.returncode == 0 and any(l.startswith("| gemma ") for l in r.stdout.splitlines()))


def test_matrix_dry_run_lists_every_invocation():
    """The count is derived from plan()/probes(), not written down twice. An earlier
    version hardcoded 13 here while test_run_matrix.py asserted 19, so the two files
    contradicted each other and whichever ran second was 'the bug'."""
    expected = sum(len(rm.plan(b)) + len(rm.probes(b)) for b in ("rocm", "vulkan")) + 2
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "run_matrix.py"),
                        "--dry-run"], capture_output=True, text=True)
    check(f"run_matrix.py --dry-run lists {expected} invocations and touches nothing",
          r.returncode == 0 and r.stdout.count("bench.py") == expected,
          f"{r.stdout.count('bench.py')} seen")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", action="store_true",
                    help="also load a model and run a real completion (~90s)")
    ap.add_argument("--stop-service", action="store_true",
                    help=f"stop {rm.SERVICE} first; restored on any exit incl. signals")
    a = ap.parse_args()

    with (service_stopped() if a.stop_service else contextlib.nullcontext()):
        print("=== host ===")
        test_host_sudo_is_passwordless()
        test_host_vram_reader()

        print("=== sleep guard ===")
        test_sleep_lock_round_trip()
        test_sleep_lock_stale_pid_is_ignored()

        print("=== dry paths ===")
        test_dry_run_needs_no_container()
        test_matrix_dry_run_lists_every_invocation()

        for backend in ("rocm", "vulkan"):
            print(f"=== container: {backend} ===")
            test_container_argv_starts(backend)

        if a.gpu:
            print("=== gpu (loads a model) ===")
            test_gpu_load_only()
            test_gpu_probe_captures_kv_lines()
            test_gpu_full_row()
        else:
            print("=== gpu tests skipped (pass --gpu) ===")

        rm_container()

    fails = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(fails)}/{len(results)} passed")
    for n in fails:
        print(f"  FAILED: {n}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
