#!/usr/bin/env python3
"""Backend A/B driver: llama.cpp Vulkan vs ROCm on htpc-01. Runs ON the host, detached.

    scp bench.py prompts.py run_matrix.py htpc-01:~/
    ssh htpc-01 'tmux new -d -s bench python3 run_matrix.py'
    ssh htpc-01 -t 'tmux attach -t bench'

The tmux command line deliberately contains NO shell syntax — no $(...), no pipe, no
redirection. tmux runs it through the login shell, which on this host is fish, and fish
does not parse those the way bash does. This program opens its own log.

WHY A THROWAWAY CONTAINER RATHER THAN ANSIBLE
---------------------------------------------
The backend swap is a container built from the image under test, not a change to the
deployed quadlet. bench.py never touches llama-swap's config or its process — it runs
/app/llama-server directly by `podman exec` — so all it needs is a container with the
models mounted. Nothing persistent is modified, so there is nothing to roll back and the
matrix can run unattended.

WHY THIS IS PYTHON
------------------
It was 199 lines of bash. Only 9 of its 86 code lines were actually podman/systemctl;
30 were the row list and control flow — the definition of *what the experiment is*,
sitting where nothing could test it. The signal handling took three attempts to get
right (a missing HUP, a trap deferred until a multi-minute row finished, then
background+wait). `plan()` below is data, and test_run_matrix.py asserts the matrix has
the shape we think it has without running anything.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import bench
import preflight
import rows

DEFAULT_LINES = bench.DEFAULT_LINES

# Both tags MUST be the same llama.cpp build (bNNNNN). The floating :rocm and :vulkan
# tags drift independently, so an unpinned comparison measures backend AND version while
# reporting backend. Verified by asking the binary, not by reading the tag: both report
# `version: 10200 (5f55650a7)`.
IMAGE = {
    "rocm":   "ghcr.io/mostlygeek/llama-swap:v245-rocm-b10200",
    "vulkan": "ghcr.io/mostlygeek/llama-swap:v245-vulkan-b10200",
}

CONTAINER = "llama-bench"     # never "llama-swap": that name belongs to the systemd unit
SERVICE = "llama-swap"
MODELS_DIR = "/run/media/system/data/llamacpp/models"
CONFIG_DIR = "/run/media/system/data/llamacpp/config"

# The MoE runs at TWO contexts, for two different questions.
#
# MOE_MATCHED_CTX matches gemma and qwen3.5 and ldr-tuning-methodology.md:41's
# held-constant `-c 65536`. Without it the model comparison — which is what step 3 of
# current-work.md actually asks — is confounded by context, since the other two models
# only ever run at 65536.
#
# MOE_UB_CTX is where the -ub sweep runs. -ub is a property of expert routing and ubatch,
# not of -c, so the sweep is valid at any context and there is no reason to pay for it in
# headroom. MEASURED free VRAM at -c 65536 (rocm/vulkan): 1,468/1,605 at -ub 512, but only
# 676/815 at -ub 2048 — the tightest cell anywhere in the matrix, below the ~1 GB the docs
# cite, and on Vulkan EVICTED reads n/a so there would be no eviction signal to defend it.
# At 49152 the same sweep sits at 1,804/1,942 -> 1,060/1,199. Same question, real headroom.
#
# The pair (MOE_MATCHED_CTX, 512) vs (MOE_UB_CTX, 512) also gives the -c effect for free.
MOE_MATCHED_CTX = 65536
MOE_UB_CTX = 49152
# 1200 lines (~21,828 tokens) is bench.py's default and both MoE contexts have room for
# it, so prompt size stays IDENTICAL across all three models and both MoE contexts. That
# removes a difference rather than adding one, and keeps every prefill number on the same
# part of the throughput curve — which matters, because prefill falls with depth
# (results.md:150: 1,314 -> 1,196 -> 1,151 tok/s from 8k -> 16k -> 22k).
MOE_LINES = 1200

# The MoE grid answers two separate questions, and each pair below differs in ONE variable:
#
#   (65536, 512) vs gemma/qwen3.5 at 65536   which model is faster, context matched
#   (49152, 512) vs (49152, 1024) vs (…2048) what -ub buys on a MoE
#   (65536, 512) vs (49152, 512)             what -c costs, at fixed -ub
#
# Run on BOTH arms, so a -ub effect is attributable to the backend — which is exactly what
# discussion #21043 claims — and so no config is single-arm.
#
# WHY -ub is the MoE's lever and was a null result on the dense 12B — from config.json:
# 128 experts, top_k 8, moe_intermediate_size 704, hidden_size 2816. Routing splits the
# ubatch across 128 experts at top-8, so each expert's FFN GEMM
# ([rows x 2816] @ [2816 x 704]) sees only U*8/128 = U/16 rows:
#     -ub 512 -> 32 rows,  1024 -> 64,  2048 -> 128
# The dense model's FFN already gets all U rows, which is why raising -ub bought it
# nothing (results.md: 1151/1164/1137 tok/s, ~2% non-monotonic noise). The MoE starts 16x
# starved, so this is where #21043's +29% would come from. Even 2048 reaches only 128
# rows/expert; -b defaults to 2048 and caps -ub, so going further needs -b raised too — a
# second variable, deliberately out of scope.
#
# Two superseded designs, recorded so they are not re-proposed:
#   -ub 2048 at -c 32768, to keep free VRAM over 1,500 MB. Wrong twice: -ub does not
#   depend on -c, so the smaller context measured nothing extra; and 1,500 is a deployment
#   margin, not a thrashing threshold (see BENCH_FLOOR_MB in bench.py).
#   The whole grid at 49152. Left the MoE's throughput row un-matched to the other two
#   models, confounding the model comparison with context.
MOE_GRID = [(MOE_MATCHED_CTX, ""),
            (MOE_UB_CTX, ""), (MOE_UB_CTX, "1024"), (MOE_UB_CTX, "2048")]

# The -fa sweep runs at -c 16384, where the default 1200 lines does NOT fit: the corpus
# measures 18.19 tokens/line (21,828 / 1,200), so 1200 lines is ~21,828 tokens against a
# 16,384-token context. Every fa-sweep row would have died with HTTP 400 "request (21835
# tokens) exceeds the available context size", losing the entire -fa question 40 minutes
# into an unattended run. Caught by test_every_planned_row_fits_its_context after the
# same bug appeared in --smoke.
#
# 540 lines is ~9,823 tokens — 60% of the context, leaving room for the 1,024-token
# generation and the KV overhead. Both fa rows use it, so the -fa 0 vs -fa 1 comparison
# is still like-for-like; it is only incomparable to the -c 65536 rows, which is fine
# because -fa is not being compared across contexts.
FA_CTX = 16384
FA_LINES = 540

# The RADV ICD, forced explicitly. The Vulkan image ships EIGHT ICDs including lavapipe
# (a software rasterizer) and no AMDVLK at all, so auto-selection could silently run the
# whole benchmark on the CPU — a spectacular false negative. Verified at run time from
# `llama-server --list-devices`, which names the driver at normal verbosity.
RADV_ICD = "/usr/share/vulkan/icd.d/radeon_icd.json"

# The pre-registered decision threshold. A backend switch needs a >=10% generation gap
# with non-overlapping ranges, so a single row whose OWN spread exceeds this cannot
# contribute to the comparison — the arms would be separated by less than the noise
# inside one arm.
RESOLVABILITY_PCT = 10.0


# A --smoke row: same code path, ~1 minute instead of ~5. The point is to execute every
# command the real run issues — arm(), cleanup(), both images, the graphics-queue
# container, systemctl stop/start — before committing two unattended hours to them.
SMOKE = {"ctx": "4096", "lines": "50", "variants": "1", "max_tokens": "32"}


def smoke(row: list[str]) -> list[str]:
    """Shrink a real row into a smoke row, preserving everything that is not size.

    Rewrites values in place rather than building a separate row list, so a smoke run
    cannot drift into exercising a different set of flags than the real matrix. Whatever
    plan() gains later is carried automatically.
    """
    out = list(row)
    # --lines MUST be set even when the real row omits it. Its default is 1200 (~21,835
    # tokens), so shrinking --ctx to 4096 while leaving --lines alone makes every prompt
    # overflow its context and the row dies with HTTP 400 "request (21835 tokens) exceeds
    # the available context size (4096 tokens)". Found by the first smoke run, which is
    # what the first smoke run is for.
    for flag, value in (("--ctx", SMOKE["ctx"]), ("--lines", SMOKE["lines"]),
                        ("--variants", SMOKE["variants"]),
                        ("--max-tokens", SMOKE["max_tokens"])):
        if flag in out:
            out[out.index(flag) + 1] = value
        else:
            out += [flag, value]
    # The anchors are measured at --lines 1200; at --lines 50 they would fire on every
    # row. Cross-arm prompt_n equality is what checks the corpus during a smoke run.
    if "--expect-prompt-n" in out:
        i = out.index("--expect-prompt-n")
        del out[i:i + 2]
    return out


def status_report(log: str, rows_md: str, holder_pid: str, expected_rows: int) -> str:
    """A progress summary for a run in flight. Pure, so it is tested without a GPU.

    Answers the five questions worth asking of a 92-minute unattended job: is it alive,
    how far in, what is it doing now, what has it recorded, and has anything gone wrong.
    """
    data = [l for l in rows_md.splitlines()
            if l.startswith("| ") and l.split("|")[1].strip() in bench.MODELS]
    lines = log.splitlines()
    current = next((l for l in reversed(lines) if l.startswith("=== ROW:")), "")
    terminal = next((l for l in reversed(lines) if any(
        k in l for k in ("DONE —", "PARTIAL RUN COMPLETE", "SESSION STOPPED",
                         "ABORTED", "TEARDOWN"))), "")
    problems = [l.strip() for l in lines if l.lstrip().startswith("!!")]
    refused = [l for l in lines if "REFUSED (does not fit)" in l]

    alive = holder_pid.strip().isdigit()
    out = [f"state      : {'RUNNING (pid ' + holder_pid.strip() + ')' if alive else 'not running'}",
           f"rows       : {len(data)}/{expected_rows} recorded"]
    if current:
        out.append(f"current    : {current.replace('=== ROW:', '').replace('===', '').strip()}")
    if refused:
        out.append(f"refused    : {len(refused)} config(s) did not fit (a result, not a failure)")
    out.append(f"problems   : {len(problems)}")
    out += [f"             {p}" for p in problems[:5]]
    if terminal and not alive:
        out.append(f"finished   : {terminal.strip().strip('=').strip()}")
    return "\n".join(out)


def config_key_of(argv: list[str]) -> tuple[str, str, str, str]:
    """The rows.config_key a given bench.py argv will produce.

    Defaults mirror bench.py's argparse and format_row: -fa defaults to 1, and an unset
    -ub is reported as llama.cpp's own default of 512. Getting these wrong would make
    every derived key miss.
    """
    def val(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv else default
    return (val("--model", "?"), val("--ctx", "?"), val("--fa", "1"), val("--ub", "512"))


def single_arm_configs(shrink=lambda r: r) -> set:
    """Config keys the design deliberately runs on ONE arm only.

    Derived from plan() rather than listed, so a deliberate asymmetry and an accidental
    one cannot be confused: if a row is dropped from an arm by mistake, this set changes
    with it and the check still passes — which is why the check ALSO compares against
    what actually ran. What this prevents is the opposite error, flagging the intended
    Vulkan-only -ub row as a defect on every single run.
    """
    seen: dict[tuple, set] = {}
    for backend in ("rocm", "vulkan"):
        for row in plan(backend):
            seen.setdefault(config_key_of(shrink(row)), set()).add(backend)
    return {k for k, arms in seen.items() if len(arms) == 1}


def with_anchor(row: list[str]) -> list[str]:
    """Attach --expect-prompt-n when an anchor exists for this (model, --lines).

    Derived from bench.EXPECTED_PROMPT_N rather than written into each row: the anchor
    is one fact, and a fact written down twice is how the 13-vs-19 contradiction between
    two test files happened. A config with no recorded anchor gets none — the relative
    cache gate still applies, and inventing a value would defeat the check entirely.
    """
    # A --load-only probe never runs a completion, so it has no prompt_n to anchor. It
    # also carries no --lines, so the lookup would fall back to the default and attach an
    # anchor for a size the probe is not using — misleading in the log.
    if "--load-only" in row:
        return row
    model = row[row.index("--model") + 1]
    lines = int(row[row.index("--lines") + 1]) if "--lines" in row else DEFAULT_LINES
    n = bench.EXPECTED_PROMPT_N.get((model, lines))
    return [*row, "--expect-prompt-n", str(n)] if n else row


def plan(backend: str) -> list[list[str]]:
    """The rows for one arm, as bench.py argument lists.

    Identical between arms by construction — the only difference is the image the
    container was built from, plus two Vulkan-only probes that have no ROCm meaning.
    """
    common = ["--container", CONTAINER, "--backend", backend]
    matrix = [
        # Throughput. --variants 5, not the default 3: Vulkan prefill variance is
        # reported at 5,600-7,500 where ROCm holds under 1%, and each variant is a
        # DIFFERENT seeded prompt, so five variants are five independent measurements
        # rather than five prefix-cache hits.
        [*common, "--model", "gemma", "--ctx", "65536", "--variants", "5",
         "--label", "backend A/B"],
        [*common, "--model", "qwen3.5", "--ctx", "65536", "--variants", "5",
         "--label", "backend A/B"],
        *[[*common, "--model", "gemma-moe", "--ctx", str(ctx),
           "--lines", str(MOE_LINES), *(["--ub", ub] if ub else []),
           "--variants", "5",
           "--label", f"MoE grid -c {ctx} -ub {ub or '512'}"]
          for ctx, ub in MOE_GRID],
        # -fa is a ROCm measurement (8.3x prefill) and the RDNA4 FA regression is
        # HIP-specific, so the decision may not transfer. -c 16384 gives both sides
        # headroom and removes the thrashing confound. Gemma only: llama_swap_flash_attn
        # is global, so a per-model answer could not be acted on anyway.
        [*common, "--model", "gemma", "--ctx", str(FA_CTX), "--fa", "0",
         "--lines", str(FA_LINES), "--variants", "5", "--label", "fa sweep"],
        [*common, "--model", "gemma", "--ctx", str(FA_CTX), "--fa", "1",
         "--lines", str(FA_LINES), "--variants", "5", "--label", "fa sweep"],
    ]
    # No arm-specific rows any more. The MoE grid runs on both arms precisely because
    # #21043's claim is that -ub interacts with the backend; measuring it on one arm
    # could not distinguish a -ub effect from a backend effect.
    return matrix


def probes(backend: str) -> list[list[str]]:
    """Untimed --load-only --verbose probes, run before the timed rows.

    DERIVED from plan(): one probe per distinct (model, -c, -ub, -fa) the arm will
    actually run. Hand-listing them left the Vulkan `MoE -ub 2048` row unprobed, and that
    is the row most likely to fail — -ub 2048 cost ~950 MB on the dense 12B, and the MoE
    has only ~1,942 MB free at -ub 512, which puts it under the 1.5 GB floor where
    thrashing was measured at >900 s against 45 s.

    -fa is in the key because -fa 0 allocates a much larger compute buffer, and -ub
    because it is a direct VRAM cost. Both change whether a config fits.

    Running them all first means every fit failure surfaces in the first ~10 minutes
    instead of scattered across two unattended hours. They are separate from the timed
    rows because --verbose logs during generation, which is overhead on the number being
    measured. ~50s each.
    """
    common = ["--container", CONTAINER, "--backend", backend, "--load-only", "--verbose"]
    seen, out = set(), []
    for row in plan(backend):
        model = row[row.index("--model") + 1]
        ctx = row[row.index("--ctx") + 1]
        ub = row[row.index("--ub") + 1] if "--ub" in row else ""
        fa = row[row.index("--fa") + 1] if "--fa" in row else "1"
        key = (model, ctx, ub, fa)
        if key in seen:
            continue
        seen.add(key)
        probe = [*common, "--model", model, "--ctx", ctx, "--fa", fa]
        if ub:
            probe += ["--ub", ub]
        out.append(probe)
    return out


def container_argv(backend: str, extra_env: dict[str, str] | None = None) -> list[str]:
    """A faithful translation of ansible/files/htpc-01/llama-swap.container.j2, with
    three deliberate deviations:

    --network none      the quadlet joins caddy.network. Detaching the bench container
                        means Onyx and LDR CANNOT reach it, so neither can trigger a
                        model load that steals ~10 GiB mid-row. That turns a procedural
                        "remember to stop the harnesses" into a structural guarantee.
                        bench.py only ever curls localhost inside the container.
    --entrypoint sleep  we want the image's llama-server binary, not its llama-swap
                        supervisor. Nothing listens; nothing loads unprompted.
    a distinct name     so it can never collide with the systemd unit's container.
    """
    env = dict(extra_env or {})
    if backend == "vulkan":
        env.setdefault("VK_ICD_FILENAMES", RADV_ICD)
    argv = ["sudo", "podman", "run", "-d", "--name", CONTAINER,
            "--network", "none",
            "--device", "/dev/kfd", "--device", "/dev/dri",
            "--group-add", "keep-groups", "--security-opt", "label=disable",
            "-v", f"{MODELS_DIR}:/models:ro",
            "-v", f"{CONFIG_DIR}:/config:ro"]
    for k, v in env.items():
        argv += ["-e", f"{k}={v}"]
    argv += ["--entrypoint", "sleep", IMAGE[backend], "infinity"]
    return argv


# --------------------------------------------------------------------------- runtime

class Driver:
    def __init__(self, dry: bool = False, smoke_mode: bool = False,
                 rows_path: Path | None = None, only: str = "",
                 probes_only: bool = False):
        self.dry = dry
        self.smoke_mode = smoke_mode
        self.rows_path = rows_path
        self.only = only
        self.probes_only = probes_only
        self.child: subprocess.Popen | None = None
        self.rows: list[dict[str, str]] = []
        self.row_problems: list[str] = []
        self.skipped = 0
        self.abort = ""       # set by the resolvability gate; ends the session early
        # config key -> why it was refused. A measured non-fit, which is a result rather
        # than a failure, and a legitimate reason for the arms not to match on that cell.
        self.refused: dict[tuple, str] = {}
        # Ran and measured, but with less headroom than we would deploy. A caveat on the
        # row, not a reason to discard it.
        self.tight_rows: dict[tuple, str] = {}
        # (backend, model, ctx, ub, fa) -> free VRAM after load, from the probes. Used to
        # refuse a timed row whose config does not fit; see fits().
        self.fit: dict[tuple, int] = {}

    def fit_key(self, argv: list[str]) -> tuple:
        return (argv[argv.index("--backend") + 1], *config_key_of(argv))

    def fits(self, argv: list[str]) -> str:
        """'' if the config can produce a valid measurement, else why it cannot.

        Gated on BENCH_FLOOR_MB, not the 1.5 GB deployment guidance. The only thrashing
        event ever measured here was at 264 MB free; at 1,468 MB, eviction was 420 ms and
        throughput was unchanged (67.2 vs 67.4 tok/s). Refusing at 1,500 would throw away
        configs that measure perfectly well — it did, until this was corrected.
        """
        free = self.fit.get(self.fit_key(argv))
        if free is None or free >= bench.BENCH_FLOOR_MB:
            return ""
        return (f"probe measured {free} MB free, below the {bench.BENCH_FLOOR_MB} MB "
                "benchmark floor (~2x the 264 MB where thrashing was actually observed) "
                "— a throughput number from it would not be a measurement")

    def tight(self, argv: list[str]) -> str:
        """Runs, but with less headroom than we would deploy. Reported, never refused."""
        free = self.fit.get(self.fit_key(argv))
        if free is None or free >= bench.VRAM_FLOOR_MB:
            return ""
        return (f"{free} MB free — a valid measurement, but below the "
                f"{bench.VRAM_FLOOR_MB} MB margin we would ship")

    def shrink(self, argv: list[str]) -> list[str]:
        return smoke(argv) if self.smoke_mode else argv

    def wanted(self, argv: list[str]) -> bool:
        """--only filters by label substring. Probes carry no --label and are always run:
        they are what prove the model still loads at the context the rows assume."""
        if not self.only or "--load-only" in argv:
            return True
        label = argv[argv.index("--label") + 1] if "--label" in argv else ""
        return self.only in label

    def sh(self, argv: list[str], **kw) -> int:
        if self.dry:
            print("  [dry] " + " ".join(argv))
            return 0
        return subprocess.run(argv, **kw).returncode

    def say(self, msg: str) -> None:
        print(f"\n=== {msg} ===\n", flush=True)

    def cleanup(self) -> None:
        """Runs on ANY exit — success, failure, a signal, or the tmux session being
        killed. This is what makes walking away safe: the worst case leaves the machine
        as it started.

        BOTH container names are removed. llama-bench is ours; llama-swap is what the
        end-to-end phase creates, and if one were left behind `systemctl start
        llama-swap` would fail on a name conflict and the machine would NOT be back to
        its starting state.
        """
        self.say("TEARDOWN")
        if self.child and self.child.poll() is None:
            # Stop the in-flight row first, or `podman rm` races a live llama-server.
            self.child.terminate()
            try:
                self.child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.child.kill()
        for name in (CONTAINER, SERVICE):
            self.sh(["sudo", "podman", "rm", "-f", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.sh(["sudo", "systemctl", "start", SERVICE]) != 0:
            print(f"!! {SERVICE} did NOT restart — check by hand", flush=True)

    def row(self, argv: list[str]) -> None:
        """One row. A failure is recorded and the matrix continues: a config that will
        not load is itself a data point (it is one of the decision-criteria outcomes),
        and losing the remaining rows to it would waste the session.

        Output is streamed rather than buffered so the log stays live for `tail -f`, and
        so a crash keeps everything printed up to that point. The result row is also
        appended to rows_path as it completes: a matrix that dies at 90 minutes must not
        lose the 90 minutes of rows it already produced.
        """
        # Anchor and shrink here rather than in plan(): these apply to EVERY row,
        # including the two ad-hoc ones below, and a new row must not be able to
        # opt out by being written somewhere plan() does not reach.
        argv = self.shrink(with_anchor(argv))
        if not self.wanted(argv):
            self.skipped += 1
            return
        # A config the probes measured as not fitting is refused rather than run: the
        # number it would produce looks like a backend result and is thrashing.
        why = self.fits(argv) if "--load-only" not in argv else ""
        if why:
            # A measured non-fit is a FINDING, not a defect: current-work.md's decision
            # criteria say outright that "MoE will not fit at a usable -c" is itself an
            # answer. So it is recorded and exempted from the matched-arms check rather
            # than failing the session — but it is never silent.
            self.say("REFUSED (does not fit): " + " ".join(argv))
            print(f"  !! {why}", flush=True)
            self.refused[self.fit_key(argv)] = why
            self.skipped += 1
            return
        tight = self.tight(argv) if "--load-only" not in argv else ""
        self.say("ROW: " + " ".join(argv))
        if tight:
            print(f"  note: {tight}", flush=True)
            self.tight_rows[self.fit_key(argv)] = tight
        if self.dry:
            print("  [dry] python3 bench.py " + " ".join(argv))
            return
        self.child = subprocess.Popen(
            [sys.executable, str(Path(__file__).parent / "bench.py"), *argv],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        captured = []
        for line in self.child.stdout:
            print(line, end="", flush=True)
            captured.append(line)
        rc = self.child.wait()
        self.child = None
        if rc != 0:
            print(f"!! ROW FAILED (continuing), rc={rc}", flush=True)
            return
        if "--load-only" in argv:
            # Record what the probe measured so the timed rows can be gated on it.
            fit = bench.parse_load_only("".join(captured))
            if fit:
                self.fit[self.fit_key(argv)] = fit["loaded_free"]
                free = fit["loaded_free"]
                if free < bench.BENCH_FLOOR_MB:
                    mark = f"  <-- under the {bench.BENCH_FLOOR_MB} MB benchmark floor"
                elif free < bench.VRAM_FLOOR_MB:
                    mark = (f"  <-- measurable, but under the {bench.VRAM_FLOOR_MB} MB "
                            "margin we would deploy")
                else:
                    mark = ""
                print(f"  fit: {fit['loaded_free']} MB free{mark}", flush=True)
            else:
                self.row_problems.append(
                    f"probe reported no VRAM figure: {' '.join(argv)}")
        else:
            self.record("".join(captured), argv)

    def record(self, output: str, argv: list[str]) -> None:
        """Capture the result row and check it immediately.

        Checked here, not at the end: a systematically broken row — an empty backend
        column, a discarded variant — repeats for every remaining row, and finding out
        two hours later wastes the session that this whole exercise exists to protect.
        """
        line = rows.extract_row(output)
        if not line:
            self.row_problems.append(f"no result row emitted by: {' '.join(argv)}")
            return
        if self.rows_path:
            with self.rows_path.open("a") as fh:
                fh.write(line + "\n")
                fh.flush()
        try:
            parsed = rows.parse_row(line)
        except ValueError as e:
            self.row_problems.append(str(e))
            return
        self.rows.append(parsed)

        # Resolvability gate, on the FIRST timed row only. That row is the primary dense
        # comparison, and the decision criterion is a >=10% generation gap with
        # non-overlapping ranges. If its own 5-variant spread already exceeds 10%, the
        # headline question is unanswerable and the remaining ~60 minutes cannot fix it —
        # so stop and say so rather than spending them.
        if len(self.rows) == 1 and not self.smoke_mode:
            spread = rows.gen_spread_pct(parsed)
            if spread is not None:
                print(f"  resolvability: first row gen spread {spread:.1f}% "
                      f"(threshold {RESOLVABILITY_PCT}%)", flush=True)
                if spread > RESOLVABILITY_PCT:
                    self.abort = (
                        f"first row's generation spread is {spread:.1f}%, above the "
                        f"{RESOLVABILITY_PCT}% decision threshold. Arms cannot be "
                        "separated by a gap smaller than the noise within one arm, so "
                        "the remaining rows cannot produce a decision. Investigate "
                        "variance before spending the rest of the session.")

        problems = rows.check_row(
            parsed,
            expect_backend=argv[argv.index("--backend") + 1],
            expect_variants=int(argv[argv.index("--variants") + 1]))
        for p in problems:
            print(f"  !! ROW PROBLEM: {p}", flush=True)
        self.row_problems += problems

    def arm(self, backend: str) -> bool:
        self.say(f"ARM: {backend}  ({IMAGE[backend]})")
        self.sh(["sudo", "podman", "rm", "-f", CONTAINER],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.sh(container_argv(backend), stdout=subprocess.DEVNULL) != 0:
            print(f"!! container would not start for {backend} — ABORTING this arm.\n"
                  "   Every row after it would be meaningless.", flush=True)
            return False
        self.say(f"probes: device banner + KV size, {backend} (untimed)")
        for argv in probes(backend):
            self.row(argv)
        if self.probes_only:
            # The fit question is answered; the timed rows are the expensive part.
            self.sh(["sudo", "podman", "rm", "-f", CONTAINER],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        for argv in plan(backend):
            if self.abort:
                break
            self.row(argv)

        if backend == "vulkan":
            # llama.cpp deliberately avoids the graphics queue; its source says
            # overriding that "can increase performance on RADV". Presence of the
            # variable is the switch, so this needs its own container.
            self.say("Vulkan extra: GGML_VK_ALLOW_GRAPHICS_QUEUE=1")
            self.sh(["sudo", "podman", "rm", "-f", CONTAINER],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if self.sh(container_argv("vulkan",
                                      {"GGML_VK_ALLOW_GRAPHICS_QUEUE": "1"}),
                       stdout=subprocess.DEVNULL) == 0:
                self.row(["--container", CONTAINER, "--backend", "vulkan",
                          "--model", "gemma", "--ctx", "65536", "--variants", "5",
                          "--label", "GGML_VK_ALLOW_GRAPHICS_QUEUE=1"])

        self.sh(["sudo", "podman", "rm", "-f", CONTAINER],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the whole matrix without touching the GPU")
    ap.add_argument("--smoke", action="store_true",
                    help="same code path, tiny rows (~12 min): executes every command "
                         "the real run issues, so the 2h run is not their first outing")
    ap.add_argument("--arm", default="", choices=["", "rocm", "vulkan"],
                    help="run one arm only. Recovery after a mid-run failure: rows "
                         "already measured are in the .rows.md file, so re-running "
                         "everything wastes the arm that succeeded")
    ap.add_argument("--only", default="",
                    help="run only rows whose --label contains this substring")
    ap.add_argument("--status", action="store_true",
                    help="report on the newest run and exit. Safe to call at any time, "
                         "including while a matrix is in flight — reads files only")
    ap.add_argument("--probes-only", action="store_true",
                    help="load each model at its REAL context on each backend and stop "
                         "(~8 min). Answers the one question --smoke cannot: does every "
                         "model fit at the -c the timed rows assume, on BOTH backends")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="not recommended: preflight is what stops a 2h run starting "
                         "against a busy card or a missing model")
    ap.add_argument("--log", default="", help="log file (default: ~/bench-backend-ab-*.log)")
    ap.add_argument("--rows", default="",
                    help="append result rows here as they complete (default alongside "
                         "the log). A crash keeps the rows already measured")
    a = ap.parse_args()

    if a.status:
        newest = lambda pat: max(Path.home().glob(pat), key=lambda p: p.stat().st_mtime,
                                 default=None)
        log, rowsf = newest("bench-*.log"), newest("bench-*.rows.md")
        if not log:
            print("no run found under ~/bench-*.log")
            return 1
        lock = Path(bench.SLEEP_LOCK)
        expected = sum(len(plan(b)) for b in ("rocm", "vulkan")) + 2
        print(f"log        : {log}")
        print(f"rows       : {rowsf}")
        print(status_report(log.read_text(),
                            rowsf.read_text() if rowsf else "",
                            lock.read_text() if lock.exists() else "",
                            expected))
        print("\n--- last 8 log lines ---")
        print("\n".join(log.read_text().splitlines()[-8:]))
        return 0

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    kind = "smoke" if a.smoke else ("probes" if a.probes_only else "backend-ab")
    rows_path = None
    if not a.dry_run:
        log = Path(a.log or Path.home() / f"bench-{kind}-{stamp}.log")
        # Line-buffered: a crash or a kill must not lose what has already been printed,
        # and `tail -f` on the log is the only view into an unattended run.
        sys.stdout = sys.stderr = log.open("a", buffering=1)
        rows_path = Path(a.rows or Path.home() / f"bench-{kind}-{stamp}.rows.md")
        rows_path.write_text("| " + " | ".join(bench.ROW_COLUMNS) + " |\n" +
                             "|" + "---|" * len(bench.ROW_COLUMNS) + "\n")
        print(f"log: {log}\nrows: {rows_path}", flush=True)

    d = Driver(dry=a.dry_run, smoke_mode=a.smoke, rows_path=rows_path, only=a.only,
               probes_only=a.probes_only)

    # BEFORE the service is stopped and before anything is torn down, so a failed
    # precondition costs seconds and leaves the machine untouched. Structural: there is
    # no step to remember.
    if not a.dry_run and not a.skip_preflight:
        results = preflight.check_all()
        for r in results:
            print(r, flush=True)
        blocking = [r for r in results if not r.ok and r.fatal]
        if blocking:
            print(f"\nABORTED — {len(blocking)} blocking precondition(s). Nothing was "
                  "changed on this host.", flush=True)
            for r in blocking:
                print(f"  {r.name}: {r.detail}", flush=True)
            return 2

    # SIGKILL remains untrappable — same as the shell version — but everything else
    # lands in the finally block. Unlike bash, a signal interrupts child.wait()
    # immediately rather than being deferred until the multi-minute row returns.
    def on_signal(signum, _frame):
        print(f"\n!! signal {signal.Signals(signum).name} — tearing down", flush=True)
        raise SystemExit(128 + signum)
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, on_signal)

    # Taken BEFORE the service stops — that stop is what makes the host's own inhibitor
    # checks go idle, so the unprotected window must never open. Released in its own
    # finally, which nests outside the teardown below.
    with contextlib.ExitStack() as stack:
        if not a.dry_run:
            stack.enter_context(bench.sleep_lock())
        return _run(d, a)


def _run(d: "Driver", a) -> int:
    try:
        d.say(f"START  rocm={IMAGE['rocm']}  vulkan={IMAGE['vulkan']}")
        # Stop the deployed service: otherwise its container holds the card. Same
        # mechanism gpu-mode uses, so nothing is left inconsistent. Restart=always does
        # not fire after an explicit stop, and gpu-mode's [Install] drop-in is untouched.
        # DO NOT run gpu-mode during the benchmark — it would start this back up.
        d.sh(["sudo", "systemctl", "stop", SERVICE])

        arms = [a.arm] if a.arm else ["rocm", "vulkan"]
        for backend in arms:
            if d.abort:
                break
            d.arm(backend)

        if d.abort:
            d.say("SESSION STOPPED — the comparison cannot be resolved")
            print(f"  {d.abort}", flush=True)
            print(f"  {len(d.rows)} row(s) were measured and kept in the rows file.",
                  flush=True)
            return 3

        # A-B-A drift control. The arms are separated by a container swap, so thermal
        # state and page cache differ; a slow first arm and a fast second could be drift
        # rather than backend. If this row does not reproduce its earlier self within
        # the reported gen spread, the session is void.
        #
        # Only meaningful when both arms ran: it compares against the FIRST ROCm row, so
        # in a single-arm recovery run there is nothing for it to drift against.
        partial = bool(a.arm or a.only or a.probes_only)
        if not partial:
            d.say("A-B-A: repeat one ROCm config")
            d.sh(["sudo", "podman", "rm", "-f", CONTAINER],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if d.sh(container_argv("rocm"), stdout=subprocess.DEVNULL) == 0:
                d.row(["--container", CONTAINER, "--backend", "rocm", "--model", "gemma",
                       "--ctx", "65536", "--variants", "5",
                       "--label", "A-B-A repeat of the first row"])
        else:
            d.say(f"PARTIAL RUN (arm={a.arm or 'both'} only={a.only or '-'}) — skipping "
                  "the A-B-A drift control, which needs both arms in one session")

        if d.refused:
            d.say(f"{len(d.refused)} CONFIG(S) DID NOT FIT — a result, not a failure")
            for key, why in d.refused.items():
                print(f"  {key}: {why}", flush=True)

        # A cell refused for not fitting is exempt from the matched-arms check: the arms
        # genuinely differ there, and the difference is the measurement.
        exempt = single_arm_configs(d.shrink) | {k[1:] for k in d.refused}
        problems = d.row_problems + rows.check_arms_comparable(
            d.rows, single_arm_ok=exempt)
        if problems:
            d.say(f"{len(problems)} PROBLEM(S) — these rows are not a valid comparison")
            for pr in problems:
                print(f"  !! {pr}", flush=True)
            return 1
        if partial:
            # Never report a partial run as a completed comparison. The rows are valid
            # individually; the A/B is not finished.
            d.say(f"PARTIAL RUN COMPLETE — {len(d.rows)} row(s) measured, "
                  f"{d.skipped} skipped, no A-B-A. This is NOT a finished comparison; "
                  "merge these rows with the rest before deciding anything")
            return 0
        d.say(f"DONE — {len(d.rows)} row(s), all checks passed. Compare against the "
              "decision criteria before touching the deployment")
        return 0
    finally:
        if not a.dry_run:
            d.cleanup()


if __name__ == "__main__":
    sys.exit(main())
