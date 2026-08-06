#!/usr/bin/env python3
"""llama.cpp / llama-swap benchmark harness for htpc-01.

Measures ONE configuration across N distinct prompt variants and emits a result row for
[results.md](results.md). Sweeps are a loop in the caller — see run_matrix.py.

Runs ON the host (needs podman). It drives `/app/llama-server` directly inside a
container on port 5900, **bypassing llama-swap**, so flags can be varied — llama-swap
only ever runs the command in its own config.

    python3 bench.py --model gemma --ctx 32768 --fa 1
    python3 bench.py --container llama-bench --backend vulkan --model gemma-moe --ctx 49152
    python3 bench.py --dry-run --variants 5          # no container, no GPU, seconds

WHY THIS IS PYTHON AND NOT A SHELL SCRIPT
-----------------------------------------
It used to be 480 lines of bash with four Python fragments embedded in it — 28% of the
file. Of eight defects found in one session, six came from the shell layer or the
shell/Python boundary, including a report block that silently produced nothing because
bash was expanding `$` inside the Python source before python ever saw it.

The decisive one: the cache-contamination gate is twelve lines of logic that decide
whether a measurement is valid at all. Embedded in a shell string, nothing could test
it. It shipped *inverted* — comparing against the median, which fails the moment cache
hits become the majority, i.e. exactly the case it exists for — and survived every run
until contaminated data happened to land in front of a human.

Everything below the "pure logic" line is importable and unit-tested by test_bench.py.

THE TRAPS THIS HARNESS EXISTS TO PREVENT
----------------------------------------
1. The prefix cache silently zeroes repeat runs. Variants are seeded differently from
   their first line (see prompts.py) so no two share a prefix, and the gate discards any
   run whose prompt_n falls far below the largest observed.
2. Prompt sizes are MEASURED, never estimated. The row reports the real prompt_n.
3. `finish_reason == "length"` is normal here (thinking is on) and does NOT invalidate a
   throughput row — it makes generation more comparable by fixing the token count. It
   matters only when judging an answer.
4. Some flag combinations are impossible, not merely bad: a quantised V cache without
   flash attention is rejected by llama.cpp in ~2s.
5. VRAM is read from the HOST, in MB. amd-smi exists in the ROCm image but not the
   Vulkan one, and a per-backend fallback would measure the two arms differently.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import prompts

PORT = 5900          # not 5800/5801 — those are llama-swap's own upstream ports

# TWO different floors, conflated for most of this harness's life and the cause of a real
# mistake: a benchmark row was refused for "thrashing" at 1,199 MB free.
#
# DEPLOYMENT guidance. A conservative margin for a config we intend to ship, and the
# figure llm-tuning.md's tables and slopes are written against. Keep it.
VRAM_FLOOR_MB = 1500
#
# BENCHMARK gate — the point below which a throughput number stops being a measurement.
# Grounded in what was actually observed, not in the round number:
#   264 MB free   -> the ONE measured thrashing event (results.md:87)
#   1,468 MB free -> 420 ms eviction and throughput UNAFFECTED: 67.2 vs 67.4 tok/s
#                    against the 1,804 MB run (results.md:79-85)
# So refusing at 1,500 excludes configs demonstrably capable of producing valid numbers.
# 500 MB is ~2x the measured failure point. Between the two, a row runs and is flagged:
# the number is real, the config is just not one to deploy as-is.
BENCH_FLOOR_MB = 500
HEALTH_TRIES = 180
HEALTH_SLEEP = 2

# Per-variant ceiling on the completion request. This was 1800 s, which with 5 variants
# put a SINGLE row's worst case at 2.5 hours and the 13-row matrix at ~32 hours — an
# unattended job with no upper bound at all.
#
# 300 s is ~7x the measured 45 s per variant (1,024 tokens at ~40 tok/s plus ~19 s of
# prefill), so it cannot trip on a slow-but-working run; it only fires when generation
# has actually stalled. A variant that hits it is recorded as an error and the cache gate
# drops it, which is the correct outcome: a stalled variant is not a measurement.
VARIANT_TIMEOUT_S = 300
DEFAULT_LINES = 1200        # ~22.5k tokens; the size every EXPECTED_PROMPT_N anchor uses

# Mirrors llama_swap_models in ansible/playbook-htpc-01.yaml. Samplers are each
# publisher's own recommendation and are NOT interchangeable — Qwen3.5 wants temp 1.0
# with a presence penalty where Qwen3 wants 0.6 and none.
MODELS = {
    "gemma":     ("/models/gemma-4-12b-it-UD-Q6_K_XL.gguf",
                  "--temp 1.0 --top-p 0.95 --top-k 64"),
    "qwen3":     ("/models/Qwen3-14B-UD-Q5_K_XL.gguf",
                  "--temp 0.6 --top-p 0.95 --top-k 20 --min-p 0"),
    # From the MTP repo, but --spec-type is deliberately NOT passed: the MTP head is
    # inert until it is, so this measures the plain Q8_0 baseline.
    "qwen3.5":   ("/models/Qwen3.5-9B-Q8_0.gguf",
                  "--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 1.5"),
    # 3.8B active of 25.2B. Same sampler as the 12B per its model card.
    "gemma-moe": ("/models/gemma-4-26B-A4B-it-UD-Q3_K_XL.gguf",
                  "--temp 1.0 --top-p 0.95 --top-k 64"),
}

# (model, --lines) -> the prompt_n that configuration MUST measure. Absolute anchors,
# and the single source of truth for 21,828 — repeating it as a literal is how the
# 13-vs-19 contradiction between two test files happened.
#
# MEASURED, never computed. Only gemma is known; the other models tokenize the same
# corpus differently and their anchors have to be measured before they can be asserted.
# A missing entry means no absolute anchor for that config — the relative cache gate
# still applies, but uniform contamination would go undetected. Do not guess a value in
# to fill the gap.
EXPECTED_PROMPT_N = {
    ("gemma", 1200): 21828,
    # The -fa sweep runs at 540 lines because 1200 does not fit -c 16384. Measured on
    # htpc-01 2026-08-01 from the -fa 0 row, so those rows are anchored too.
    ("gemma", 540): 9836,
    # From the backend A/B, 2026-08-01: 8 rows each, both backends, all identical.
    # gemma-4-26B-A4B tokenizes the corpus to exactly the same count as the 12B — same
    # Gemma tokenizer — while Qwen3.5 differs, which is why these are measured per model
    # rather than assumed to transfer.
    ("qwen3.5", 1200): 23492,
    ("gemma-moe", 1200): 21828,
}

# ---------------------------------------------------------------------------
# PURE LOGIC — no I/O, no subprocesses. This is the part that decides whether a
# measurement is real, and the part test_bench.py covers.
# ---------------------------------------------------------------------------


@dataclass
class Run:
    """One variant's result."""
    v: int
    prompt_n: int = 0
    prefill: float = 0.0
    gen: float = 0.0
    finish: str = ""
    completion_tokens: int = 0
    build: str = "?"
    hit: bool | None = None            # needle mode only
    hit_content_only: bool | None = None
    error: str | None = None


def filter_cache_hits(runs: list[Run], threshold: float = 0.9
                      ) -> tuple[list[Run], list[Run]]:
    """Split runs into (valid, discarded-as-prefix-cache-hits).

    Gate on the MAXIMUM prompt_n, not the median. A prefix-cache hit always reports
    FEWER tokens processed than a real run, never more, so the largest value in the set
    is the only trustworthy reference.

    The previous implementation compared against the median, which inverts as soon as
    cache hits are the majority: with 5 of 8 rows at prompt_n=5 the median IS 5, the
    threshold becomes 4.5, every contaminated row passes, and the report prints
    "prefill 7.2 tok/s" as a result. Observed on real data. Covered by a regression test.
    """
    ok = [r for r in runs if r.error is None]
    if not ok:
        return [], []
    max_n = max(r.prompt_n for r in ok)
    valid = [r for r in ok if r.prompt_n >= threshold * max_n]
    discarded = [r for r in ok if r.prompt_n < threshold * max_n]
    return valid, discarded


def parse_load_only(output: str) -> dict | None:
    """The VRAM figures from a --load-only probe, or None if it did not report them.

    Parsed rather than eyeballed because run_matrix uses this to gate the timed rows
    against BENCH_FLOOR_MB, and to flag rows that measure validly but with less headroom
    than we would deploy. See the two floors at the top of this file — conflating them
    caused a perfectly measurable config to be refused.
    """
    import re
    m = re.search(r"LOAD-ONLY: baseline_free=(\d+) MB loaded_free=(\d+) MB", output)
    if not m:
        return None
    return {"baseline_free": int(m.group(1)), "loaded_free": int(m.group(2))}


def check_expected_prompt_n(measured: int, expected: int, tol: float = 0.02) -> str | None:
    """The ABSOLUTE anchor. Returns an error message, or None when the row is sound.

    filter_cache_hits is relative — it compares each run to the largest in the same set —
    so it is blind to contamination that affects every variant equally, and blind to the
    corpus generator changing. Both produce a self-consistent set of wrong numbers.

    2% because prompt_n is deterministic for a given (corpus, model): the tolerance
    covers tokenizer differences between models, not run-to-run variation.
    """
    if not expected:
        return None
    if abs(measured - expected) > tol * expected:
        return (f"prompt_n {measured} deviates from the expected {expected} by "
                f"{abs(measured - expected) / expected * 100:.1f}% (tolerance "
                f"{tol * 100:.0f}%). Either the prompt corpus changed — in which case "
                "every historical row in results.md is invalidated and must be "
                "re-baselined — or this run was served from a warm prefix cache.")
    return None


def summarise(valid: list[Run]) -> dict:
    """Medians plus dispersion.

    Dispersion is not decoration: the backend decision rests on a >=10% generation gap,
    and a gap between two medians whose ranges overlap is not a result. Reporting only
    the median made that impossible to check.
    """
    pres = sorted(r.prefill for r in valid)
    gens = sorted(r.gen for r in valid)
    prompt_ns = sorted(r.prompt_n for r in valid)
    med_n = statistics.median(prompt_ns)
    gen_med = statistics.median(gens)
    return {
        "n": len(valid),
        "prompt_n": int(med_n),
        "prompt_n_spread": (prompt_ns[-1] - prompt_ns[0]) / med_n if med_n else 0.0,
        "prefill_med": statistics.median(pres),
        "prefill_min": pres[0], "prefill_max": pres[-1],
        "gen_med": gen_med, "gen_min": gens[0], "gen_max": gens[-1],
        "gen_spread_pct": (gens[-1] - gens[0]) / gen_med * 100 if gen_med else 0.0,
        "build": valid[0].build,
    }


ROW_COLUMNS = ["model", "backend", "build", "-c", "-ub", "-fa", "KV", "prompt_n",
               "prefill med", "prefill min-max", "gen med", "gen min-max", "free",
               "baseline free", "EVICTED", "n", "notes"]


def format_row(s: dict, *, model: str, backend: str, ctx: int, ub: str, fa: str,
               kv: str, loaded_free, baseline_free, evicted, notes: str) -> str:
    """One markdown row, ready to paste into results.md. Column count is asserted by a
    test against ROW_COLUMNS — a row that does not line up corrupts the table silently."""
    return ("| %s | %s | %s | %s | %s | %s | %s | %d | %.1f | %.1f-%.1f | %.1f | "
            "%.1f-%.1f | %s MB | %s MB | %s | %d | %s |" % (
                model, backend, s["build"], ctx, ub, fa, kv, s["prompt_n"],
                s["prefill_med"], s["prefill_min"], s["prefill_max"],
                s["gen_med"], s["gen_min"], s["gen_max"],
                loaded_free, baseline_free, evicted, s["n"], notes or "-"))


def parse_completion(payload: str, v: int, expect: str) -> Run:
    """Turn one /v1/chat/completions response into a Run."""
    try:
        d = json.loads(payload)
    except Exception:
        return Run(v=v, error="unparseable response")
    if "choices" not in d:
        return Run(v=v, error=json.dumps(d)[:200])
    c, t, u = d["choices"][0], d["timings"], d["usage"]
    r = Run(v=v,
            prompt_n=t["prompt_n"],
            prefill=round(t["prompt_per_second"], 1),
            gen=round(t["predicted_per_second"], 1),
            finish=c["finish_reason"],
            completion_tokens=u["completion_tokens"],
            build=d.get("system_fingerprint", "?"))
    if expect:
        # Score BOTH fields: with thinking on, a correct answer can land in
        # reasoning_content while content is empty, and scoring only content reports a
        # false miss.
        content = (c["message"].get("content") or "").strip()
        reason = (c["message"].get("reasoning_content") or "").strip()
        r.hit = expect in content or expect in reason
        r.hit_content_only = expect in content
    return r


def parse_evicted(amd_smi_process_output: str) -> str:
    """EVICTED_TIME for the process holding the most VRAM — i.e. llama-server.

    `amd-smi process` lists every GPU client, and the first block is NOT llama-server:
    after a suspend/resume the desktop compositor shows seconds of eviction that have
    nothing to do with this benchmark. Attribute the counter to its owner.
    """
    import re
    best_mem, best_ev, mem = -1.0, "?", None
    for line in amd_smi_process_output.splitlines():
        m = re.search(r"MEM_USAGE:\s*([\d.]+)\s*(\w+)", line)
        if m:
            val = float(m.group(1))
            mem = val * 1024 if m.group(2).upper().startswith("G") else val
        m = re.search(r"EVICTED_TIME:\s*(\d+)", line)
        if m and mem is not None and mem > best_mem:
            best_mem, best_ev = mem, m.group(1)
            mem = None
    return best_ev


# Substrings matched against the LOWERCASED line, verified against captured startup logs
# in testdata/ — NOT against a guess at the format. Two rounds of guessing got this wrong:
# first "kv cache" when the real line is `llama_kv_cache:` (underscore), then a broad
# "kv_cache" match which kept 424 of 2,326 lines because llama.cpp emits one
# `llama_kv_cache: layer N: ...` line PER LAYER at debug verbosity — 408 lines of noise
# burying the one line that matters.
#
# The line that matters, exactly as llama-server writes it:
#   llama_kv_cache: size =   64.00 MiB (  4096 cells,   8 layers, ...), K (f16) ...
#   llama_kv_cache: size =  480.00 MiB (  1536 cells,  40 layers, ...), K (f16) ...
# Two of them, and that pair IS the answer to the KV arithmetic gap: only the 8
# full-attention layers scale with -c; the 40 sliding-window layers are pinned at 1,536
# cells no matter how large the context.
STARTUP_KEYS = (
    "llama_kv_cache: size =",        # the KV totals — the whole reason this exists
    "kv buffer size =",              # per-device KV allocation
    "model buffer size =",           # weights, per device
    "output buffer size =",
    "compute buffer size =",
    "memory breakdown",              # llama.cpp's own summary table
    "using device",                  # which GPU was selected, with free VRAM
    "ggml_vulkan:",                  # Vulkan device banner (GGML_LOG_DEBUG only)
    "flash_attn",
    "llama_context: n_ctx",
    "model params",
    "draft",                         # proof that no draft model loaded
)

# Per-layer debug chatter that matches the keys above but carries no information: one
# line per layer, ~450 of them, and they are what swamped the log before.
STARTUP_REJECT = (": layer ", "attn_rot", "reusing layers")


def select_startup_lines(log: str) -> list[str]:
    """The lines worth keeping from llama-server's startup log.

    Evidence for three separate claims: which device was selected (RADV vs lavapipe, a
    failed ICD pin means benchmarking the CPU), what the KV cache actually costs (the
    arithmetic from config.json is a 4x miss, so it must be read and not computed), and
    that no draft model loaded.

    Returns a list and does NOT truncate. The caller used to slice the joined string to
    600 characters, which discarded the KV lines whenever the log was noisy — i.e.
    always, since --verbose is exactly when these lines exist.
    """
    out = []
    for line in log.splitlines():
        low = line.lower()
        if any(k in low for k in STARTUP_KEYS) and not any(r in low for r in STARTUP_REJECT):
            out.append(line)
    return out


def select_device_lines(list_devices_output: str) -> list[str]:
    """`llama-server --list-devices`, minus the Vulkan conformance disclaimer.

    Names the driver at NORMAL verbosity — e.g. "Vulkan0: AMD Radeon RX 9070 XT (RADV
    GFX1201)" — so it is a far cheaper RADV-vs-lavapipe check than the debug banner.
    """
    return [l for l in list_devices_output.splitlines() if "conformant" not in l.lower()]


def parse_free_vram(amd_smi_metric_output: str) -> str:
    """FREE_VRAM in MB from `amd-smi metric -g 0 --mem`.

    Positional: the line is `FREE_VRAM: 3000 MB`, so the value is the second-to-last
    field. Guarded because a format change would otherwise raise IndexError mid-run and
    lose the row. Used only for the one paired reading that ties sysfs to every
    historical amd-smi number.
    """
    for line in amd_smi_metric_output.splitlines():
        if "FREE_VRAM" in line:
            parts = line.split()
            if len(parts) >= 2 and parts[-2].isdigit():
                return parts[-2]
    return "?"


# ---------------------------------------------------------------------------
# I/O — host and container
# ---------------------------------------------------------------------------


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


class Box:
    """The container under test."""

    def __init__(self, name: str):
        self.name = name

    def exec(self, *args: str, **kw) -> subprocess.CompletedProcess:
        return sh(["sudo", "podman", "exec", self.name, *args], **kw)

    def exec_detached(self, shell_cmd: str) -> subprocess.CompletedProcess:
        return sh(["sudo", "podman", "exec", "-d", self.name, "sh", "-c", shell_cmd])

    def cp(self, src: Path, dest: str) -> None:
        sh(["sudo", "podman", "cp", str(src), f"{self.name}:{dest}"])

    def has(self, binary: str) -> bool:
        # `command` is a shell builtin: `podman exec <c> command -v x` tries to exec a
        # binary named "command" and always fails, which silently reported EVICTED as
        # n/a on ROCm where amd-smi is in fact present.
        return self.exec("sh", "-c", f"command -v {shlex.quote(binary)}").returncode == 0


SERVICE = "llama-swap"

# Read by /etc/sleep-inhibitor.d/llama-bench.sh. Holds one line: the PID of the process
# that took it. /run is tmpfs, so a reboot clears it; the PID is what makes a lock left by
# a SIGKILLed run harmless rather than a machine that never sleeps again.
SLEEP_LOCK = "/run/llama-bench.lock"


@contextlib.contextmanager
def sleep_lock(path: str = SLEEP_LOCK):
    """Declare to the host's sleep-inhibitor that a benchmark is holding the GPU.

    htpc-01 suspends on its own schedule. During a matrix every stock inhibitor check
    reports idle — llama-swap.service is stopped, ComfyUI is stopped by `gpu-mode llm`,
    and no playbook is running — so without this nothing blocks sleep for ~92 minutes
    while a process holds ~10 GiB across a GPU context.

    Written through sudo because /run is root-owned; the harness already requires
    passwordless sudo for podman and systemctl, and preflight checks it.

    Released in a finally. Combined with bench.service_stopped's signal handlers, that
    covers every exit except SIGKILL — and the plugin's PID check makes even that safe.
    """
    pid = os.getpid()
    rc = subprocess.run(["sudo", "-n", "tee", path], input=f"{pid}\n", text=True,
                        stdout=subprocess.DEVNULL).returncode
    if rc != 0:
        print(f"!! could not take {path} — the host may SUSPEND mid-run", flush=True)
    else:
        print(f"[sleep lock held: {path} pid={pid}]", flush=True)
    try:
        yield
    finally:
        subprocess.run(["sudo", "-n", "rm", "-f", path], capture_output=True)
        print(f"[sleep lock released: {path}]", flush=True)


@contextlib.contextmanager
def service_stopped(name: str = SERVICE):
    """Stop the deployed unit for the duration, restore it on any exit.

    Lives here rather than in whichever script needs it, so the stop and the restore are
    in the SAME process that holds the card. That is the difference between a guaranteed
    restore and a hoped-for one: signals become SystemExit, so if the ssh connection
    carrying this process drops, the SIGHUP still runs the finally. A trap on the calling
    machine could not — it would exit having left the service down on a host nobody is
    watching.

    Restart=always does not fire after an explicit stop, so the restore has to be ours.
    """
    def on_signal(signum, _frame):
        print(f"\n!! signal {signal.Signals(signum).name} — restoring {name}", flush=True)
        raise SystemExit(128 + signum)
    previous = [(s, signal.signal(s, on_signal))
                for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)]
    print(f"[stopping {name} for the duration]", flush=True)
    sh(["sudo", "systemctl", "stop", name])
    try:
        yield
    finally:
        rc = sh(["sudo", "systemctl", "start", name]).returncode
        state = sh(["systemctl", "is-active", name]).stdout.strip()
        print(f"[restored {name}: {state}]", flush=True)
        if rc != 0 or state != "active":
            print(f"!! {name} did NOT restart — check by hand", flush=True)
        for s, handler in previous:
            signal.signal(s, handler)


def run_paths(now: float | None = None, pid: int | None = None) -> tuple[str, str]:
    """Per-invocation container paths for the corpus directory and the startup log.

    Fixed paths caused a real, catastrophic defect: an aborted run left its corpus
    behind, the next run read the stale files, and the row reported prefill at 7.6 tok/s
    over n=7 from --variants 3. Nothing flagged it.

    Keyed on time AND pid. Time alone is second-resolution, so two invocations starting
    in the same second — which --smoke rows and --load-only probes can — would collide
    again.
    """
    now = time.time() if now is None else now
    pid = os.getpid() if pid is None else pid
    tag = f"{int(now)}.{pid}"
    return f"/tmp/bench.{tag}", f"/tmp/llama-startup.{tag}.log"


def free_vram_mb() -> str:
    """Free VRAM from HOST sysfs, in MB.

    Read on the host rather than via amd-smi in the container so both backends are
    measured identically — amd-smi is absent from the Vulkan image. card[0-9]/ rather
    than card*/ because the latter also matches connector directories (card1-DP-1),
    which have no device/mem_info_*. Units matter: sysfs is bytes, every historical row
    and the 1.5 GB floor are MB.
    """
    base = sorted(Path("/sys/class/drm").glob("card[0-9]/device"))
    for d in base:
        try:
            used = int((d / "mem_info_vram_used").read_text())
            total = int((d / "mem_info_vram_total").read_text())
            return str((total - used) // 1048576)
        except (OSError, ValueError):
            continue
    return "?"


def server_argv(gguf: str, sampler: str, args) -> list[str]:
    """The llama-server command line. Pure — every measurement depends on it being right,
    so it is built where a test can assert it rather than inline in the launcher.

    The sampler arrives as a string from MODELS and is split into separate argv elements:
    passed whole it would reach llama-server as one unparseable argument.
    """
    cmd = ["/app/llama-server", "--port", str(PORT), "-m", gguf, "--jinja",
           "-ngl", "999", "-c", str(args.ctx), "-fa", str(args.fa),
           "--no-context-shift", "-np", "1", "--reasoning-budget", "-1",
           *sampler.split()]
    if args.ub:
        cmd += ["-ub", str(args.ub)]
    if args.kv:
        cmd += ["--cache-type-k", args.kv, "--cache-type-v", args.kv]
    if args.verbose:
        # The Vulkan device banner (which names RADV vs AMDVLK) is GGML_LOG_DEBUG, so it
        # does not appear at default verbosity. Flag name confirmed against --help.
        cmd += ["-v"]
    return cmd


def start_server(box: Box, gguf: str, sampler: str, args, startlog: str) -> list[str]:
    cmd = server_argv(gguf, sampler, args)
    # Redirect INSIDE the container: `podman exec -d` discards the exec session's
    # output, so llama-server's stderr — device banner, `KV self size`, any draft model
    # — was previously thrown away entirely.
    box.exec("sh", "-c", f": > {startlog}")
    box.exec_detached(f"exec {shlex.join(cmd)} > {startlog} 2>&1")
    return cmd


def wait_healthy(box: Box) -> bool:
    for _ in range(HEALTH_TRIES):
        if box.exec("curl", "-sf", f"localhost:{PORT}/health").returncode == 0:
            return True
        time.sleep(HEALTH_SLEEP)
    return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--model", default="gemma", choices=sorted(MODELS))
    p.add_argument("--ctx", type=int, default=32768)
    p.add_argument("--fa", default="1", choices=["0", "1"])
    p.add_argument("--ub", default="", help="physical batch (default: llama.cpp's 512)")
    p.add_argument("--kv", default="", help="quantise K and V cache, e.g. q8_0")
    p.add_argument("--variants", type=int, default=3, help="distinct prompts")
    p.add_argument("--lines", type=int, default=DEFAULT_LINES,
                   help=f"~22.5k tokens at {DEFAULT_LINES}")
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--needle", action="store_true", help="recall instead of throughput")
    p.add_argument("--label", default="")
    p.add_argument("--container", default="llama-swap")
    p.add_argument("--backend", default="", help="rocm|vulkan — recorded in the row")
    p.add_argument("--verbose", action="store_true", help="verbose llama-server")
    p.add_argument("--load-only", action="store_true",
                   help="load, health-check, report VRAM and KV size, stop")
    p.add_argument("--expect-prompt-n", type=int, default=0,
                   help="fail if the median prompt_n deviates >2%% from this. The "
                        "cache gate is RELATIVE (0.9 x max within the run), so it "
                        "cannot see contamination that hits every variant equally; "
                        "this is the absolute anchor")
    p.add_argument("--dry-run", action="store_true",
                   help="no container, no GPU: exercise the script and the row format")
    args = p.parse_args()

    # Invalid-combination guard. llama.cpp rejects a quantised V cache without flash
    # attention and exits in ~2s, which a naive sweep would record as a failed data
    # point rather than an impossible config.
    if args.kv and args.fa == "0":
        print(f"REFUSED: --kv {args.kv} requires --fa 1 "
              "(llama.cpp: 'V cache quantization requires flash_attn').\n"
              "         To compare -fa 0 vs -fa 1, use f16 KV on BOTH sides at a --ctx "
              "small enough that -fa 0 fits, or you are changing two variables.",
              file=sys.stderr)
        return 2

    gguf, sampler = MODELS[args.model]
    box = Box(args.container)
    print(f"### config: model={args.model} ctx={args.ctx} fa={args.fa} "
          f"ub={args.ub or 'default'} kv={args.kv or 'f16'} variants={args.variants} "
          f"needle={int(args.needle)} backend={args.backend or 'unset'} "
          f"container={args.container}{' DRY-RUN' if args.dry_run else ''}")

    with tempfile.TemporaryDirectory(prefix="bench.") as tmp:
        hostdir = Path(tmp)
        prompts.write_corpus(hostdir, args.variants, args.lines, args.needle,
                             args.max_tokens)
        print(f"generated {args.variants} variant(s)")

        if args.dry_run:
            # Synthetic but jittered — a report that only works on identical inputs
            # would hide the dispersion bug this mode exists to catch.
            import random
            runs = []
            for v in range(args.variants):
                rng = random.Random(v)
                runs.append(Run(v=v, prompt_n=21828 + rng.randint(-20, 20),
                                prefill=round(1150 + rng.uniform(-40, 40), 1),
                                gen=round(40 + rng.uniform(-3, 3), 1),
                                finish="length", completion_tokens=args.max_tokens,
                                build="dry-run-nobuild"))
            baseline_free, loaded_free, evicted = "15000", "3000", "n/a"
        else:
            cdir, startlog = run_paths()
            box.exec("mkdir", "-p", cdir)
            for v in range(args.variants):
                box.cp(hostdir / f"v{v}.json", f"{cdir}/")

            # Release the GPU first, or baseline and run both measure whatever was
            # already resident. The unload call is a no-op on a throwaway container with
            # no llama-swap process — harmless.
            box.exec("curl", "-s", "-X", "POST", "localhost:8080/api/models/unload")
            box.exec("pkill", "-f", f"llama-server --port {PORT}")
            time.sleep(6)
            baseline_free = free_vram_mb()

            cmd = start_server(box, gguf, sampler, args, startlog)
            if not wait_healthy(box):
                print("FAILED: server did not become healthy. Its stderr:")
                print(box.exec("cat", startlog).stdout[-3000:])
                print("  reproduce:  sudo podman exec " + args.container + " " +
                      shlex.join(cmd))
                return 3

            loaded_free = free_vram_mb()

            # Which driver actually loaded. Reports e.g. "Vulkan0: AMD Radeon RX 9070 XT
            # (RADV GFX1201)" at NORMAL verbosity, so it is a far cheaper RADV-vs-
            # lavapipe check than the debug banner. The Vulkan image ships eight ICDs
            # including lavapipe, a software rasterizer — a failed ICD pin means
            # silently benchmarking the CPU.
            print("--- device selected ---")
            for line in select_device_lines(
                    box.exec("/app/llama-server", "--list-devices").stdout):
                print(line)

            print("--- startup log (device banner / KV size / any draft model) ---")
            for line in select_startup_lines(box.exec("cat", startlog).stdout):
                print(line)
            print("---")

            # One paired reading so the sysfs numbers stay tied to every historical
            # amd-smi row. Only possible on ROCm; measured at 1 MB apart.
            if box.has("amd-smi"):
                free = parse_free_vram(
                    box.exec("amd-smi", "metric", "-g", "0", "--mem").stdout)
                print(f"VRAM calibration: sysfs_free={loaded_free} MB  "
                      f"amd-smi_free={free} MB")

            if args.load_only:
                print(f"LOAD-ONLY: baseline_free={baseline_free} MB "
                      f"loaded_free={loaded_free} MB (floor is {VRAM_FLOOR_MB} MB)")
                box.exec("pkill", "-f", f"llama-server --port {PORT}")
                return 0

            runs = []
            for v in range(args.variants):
                expect = (hostdir / f"v{v}.expect").read_text()
                r = box.exec("curl", "-s", "--max-time", str(VARIANT_TIMEOUT_S),
                             f"localhost:{PORT}/v1/chat/completions",
                             "-H", "Content-Type: application/json",
                             "-d", f"@{cdir}/v{v}.json")
                if r.returncode == 28:      # curl's timeout exit code
                    runs.append(Run(v=v, error=f"timed out after {VARIANT_TIMEOUT_S}s "
                                               "— generation stalled, not a measurement"))
                    continue
                runs.append(parse_completion(r.stdout, v, expect))

            evicted = (parse_evicted(box.exec("amd-smi", "process", "-g", "0").stdout)
                       if box.has("amd-smi") else "n/a")
            box.exec("pkill", "-f", f"llama-server --port {PORT}")

    # ----------------------------------------------------------------- report
    for r in (r for r in runs if r.error):
        print(f"  RUN v{r.v} ERROR: {r.error}")
    valid, discarded = filter_cache_hits(runs)
    if not valid:
        print("NO VALID RUNS")
        return 1
    for r in discarded:
        print(f"  DISCARDED v{r.v}: prompt_n={r.prompt_n} vs max "
              f"{max(x.prompt_n for x in valid)} — prefix-cache hit, not a run")

    s = summarise(valid)

    # Before anything else is printed as a result: an anchor failure means the row is not
    # a measurement, so it must not land in results.md looking like one.
    anchor_error = check_expected_prompt_n(s["prompt_n"], args.expect_prompt_n)
    if anchor_error:
        print(f"\nFAILED ANCHOR: {anchor_error}", file=sys.stderr)
        return 4

    trunc = [r for r in valid if r.finish == "length"]
    if trunc:
        # NOT a defect for a throughput row: with thinking on, typical reasoning exceeds
        # the default budget, and stopping every row at the same token count makes
        # generation MORE comparable. It matters only when judging an answer.
        print(f"  NOTE: {len(trunc)}/{len(valid)} runs hit finish_reason=length at "
              f"{trunc[0].completion_tokens} tokens — expected with thinking on; fine "
              "for throughput, not for judging an answer")
    if s["prompt_n_spread"] > 0.02:
        print(f"  NOTE: prompt_n spread {s['prompt_n_spread']*100:.1f}% across variants "
              "— sizes not comparable")

    print()
    print(f"  gen  range {s['gen_min']:.1f}-{s['gen_max']:.1f} tok/s "
          f"(spread {s['gen_spread_pct']:.1f}% of median) over n={s['n']}")
    print(f"  pre  range {s['prefill_min']:.1f}-{s['prefill_max']:.1f} tok/s")
    if s["gen_spread_pct"] > 10:
        print("  WARNING: generation spread exceeds the 10% decision threshold — a "
              "backend comparison against this row cannot be called on the median alone")

    hits = [r for r in valid if r.hit is not None]
    recall = ("  recall=%d/%d (content-only %d/%d)" % (
        sum(r.hit for r in hits), len(hits),
        sum(r.hit_content_only for r in hits), len(hits))) if hits else ""

    print()
    print("| " + " | ".join(ROW_COLUMNS) + " |")
    print("|" + "---|" * len(ROW_COLUMNS))
    print(format_row(s, model=args.model, backend=args.backend or "?", ctx=args.ctx,
                     ub=args.ub or "512", fa=args.fa, kv=args.kv or "f16",
                     loaded_free=loaded_free, baseline_free=baseline_free,
                     evicted=evicted, notes=(args.label + recall).strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
