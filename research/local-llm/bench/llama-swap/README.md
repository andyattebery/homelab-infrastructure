# llama-swap benchmark harness (htpc-01)

Measures one llama.cpp configuration across N prompt variants and emits a result row for
[results.md](results.md).

Companion to [llm-tuning.md](../../docs/llm-tuning.md), which holds the
config values and the reasoning; this holds the tooling. Ordering and status of the work
these numbers feed live in [current-work.md](../../docs/current-work.md).

**It exists because the same measurements kept being re-derived, and re-derived wrongly.**
The needle and throughput harnesses were written as scratch twice and thrown away twice.
Every guard in [Validity](#validity-what-makes-a-row-a-measurement) below corresponds to a
specific wrong number that was once believed.

---

## Quick start

```bash
python3 run_tests.py                 # 164 unit tests + 52 host checks (~35 s)
python3 run_tests.py --dry-run       # print the plan, run nothing
python3 run_tests.py --gpu           # + load models on the host (~4 min)
python3 run_tests.py --smoke         # + rehearse run_matrix's own commands (~12 min)
python3 run_tests.py --capture       # + re-record testdata/ from real output (~3 min)

python3 bench.py --dry-run --variants 5              # no container, no GPU, seconds
./run-remote.sh --model gemma --needle --variants 3  # one row from the Mac
```

**Run `run_tests.py`, not the suites by hand.** Stages are ordered so a syntax error costs a
second rather than an ssh round trip and a model load, and the file list synced to htpc-01
is derived from the AST — an import added without a matching `scp` would otherwise test a
stale copy on the host and pass.

## Files

| file | job |
|---|---|
| [bench.py](bench.py) | **one row.** Load a model, run N variants, emit a markdown row |
| [prompts.py](prompts.py) | the seeded prompt corpus — a frozen artifact |
| [rows.py](rows.py) | parses and **validates** a row. Decides whether it may reach results.md |
| [run_matrix.py](run_matrix.py) | **the backend A/B.** 18 rows + 16 probes across two arms, unattended |
| [run_tests.py](run_tests.py) | **the one entry point.** Every suite, both machines, cheapest first |
| [preflight.py](preflight.py) | go/no-go. `run_matrix` calls it *before* stopping the service |
| [capture_fixtures.py](capture_fixtures.py) | records real tool output into `testdata/` |
| [rebaseline_corpus.py](rebaseline_corpus.py) | re-records the corpus hash, behind a deliberate flag |
| [run-remote.sh](run-remote.sh) | one row from the Mac. Ties the job to the ssh connection — single rows only |
| `test_*.py` | **164 unit tests + 52 host integration checks** |

`bench.py` runs *on* htpc-01 and drives `llama-server` directly on port 5900, **bypassing
llama-swap**, so flags can be varied — llama-swap only ever runs the command in its own
config. All it needs is a container with the models mounted, which is what lets the backend
A/B use a throwaway container instead of editing the deployed quadlet.

---

## Validity: what makes a row a measurement

This is the part worth reading. Each item cost a wrong number to learn.

**1. The prefix cache silently zeroes repeat runs.** The same prompt against a live server
returns `prompt_n≈5` and single-digit tok/s — a total cache hit that reads as a spectacular
result. Each variant is seeded differently *from its first line*, so no two share a prefix.

> **Gate on the maximum, never the median.** A cache hit always reports *fewer* tokens than
> a real run, so the largest value is the only trustworthy reference. The median version
> inverts as soon as hits are the majority: with 5 of 8 rows at `prompt_n=5` the median *is*
> 5, the threshold becomes 4.5, everything passes, and the harness prints 7.2 tok/s as a
> result. That shipped, and survived every run until contaminated data landed in front of a
> human. `test_gate_survives_cache_hit_MAJORITY` is built from the exact bad data.

**2. The cache gate is relative, so it cannot see uniform contamination.** It compares each
variant to the largest in the same run. If every variant were served from cache the set
would be self-consistent and wrong. `--expect-prompt-n N` is the absolute anchor;
`run_matrix` attaches it automatically wherever `bench.EXPECTED_PROMPT_N` has a *measured*
value. Guessing a value for an unmeasured model would make the check assert a fiction.

**3. Sizes are measured, never estimated.** A "24k" prompt built from a tokens-per-line
guess was really 38k and returned HTTP 400. `--lines` sets the body size; the row reports
the measured `prompt_n` and warns if variants differ by >2%.

**4. Report min–max, not just the median.** The backend decision rests on a ≥10% generation
gap, and a gap between two medians whose ranges overlap is not a result. `bench.py` warns
above 10% spread, and `run_matrix` **stops the session** if the first row exceeds it — if
the primary comparison cannot resolve 10%, no later row can either.

**5. `finish_reason=length` is expected, not a failure.** With thinking on, typical
reasoning (1,764–1,921 tokens on Gemma) exceeds the default 1024 budget. For a throughput
row that is fine — better, even: every row is measured over the same token count. It matters
only when judging an answer's content.

**6. Score both `content` and `reasoning_content`.** In needle mode a correct answer can
land in either; scoring only `content` reports false misses.

**7. Some flag combinations are impossible, not merely bad.** `--kv q8_0` with `--fa 0` is
rejected by llama.cpp (`V cache quantization requires flash_attn`) in ~2 s. The harness
refuses it up front rather than recording a failed data point.

**8. `-fa 0` vs `-fa 1` on Qwen3 changes two variables.** Its deployed config carries
`--cache-type-k/v q8_0`, which cannot exist at `-fa 0`. A valid comparison uses f16 KV on
both sides, at a `--ctx` small enough that `-fa 0` fits.

**9. `podman exec -d` discards the exec session's output.** llama-server's stderr — device
banner, KV sizes, any draft-model line — was thrown away entirely until the command was made
to redirect *inside* the container.

**10. Read KV size from the startup log; do not compute it.** Arithmetic from `config.json`
missed by 4× because Gemma-family models split the cache — only full-attention layers grow
with `-c`, while sliding-window layers stay pinned at 1,536 cells. `select_startup_lines()`
extracts the real figures, and is tested against captured logs rather than invented strings.

### `--verbose` is not free

It logs during generation, i.e. overhead on the number being measured. No timed row uses it.
The device banner and KV lines come from separate untimed `--load-only --verbose` probes.
For the RADV-vs-lavapipe check, `--list-devices` names the driver at *normal* verbosity and
is much cheaper.

---

## VRAM, and the floor that is not a cliff

**VRAM is read from the host, not `amd-smi`** — `free_vram_mb()` reads
`/sys/class/drm/card[0-9]/device/mem_info_vram_*` and converts bytes to MB. `amd-smi` ships
in the ROCm image but **not** the Vulkan one, and a per-backend fallback would measure the
two arms by different methods. One paired reading on the ROCm arm keeps the scales tied —
**measured 1 MB apart**.

`EVICTED` is `amd-smi`-only and reads `n/a` on Vulkan. That means *not measured*, never
*zero*. On Vulkan the remaining guards are `BENCH_FLOOR_MB`, wall-time sanity, and cross-arm
comparison: a row 20× slower than its ROCm twin is thrashing whatever the counter would have
said.

### The two floors are different numbers

| constant | value | meaning |
|---|---|---|
| `VRAM_FLOOR_MB` | 1500 | **deployment margin.** Conservative headroom for a config we intend to ship, and what `llm-tuning.md`'s tables are written against |
| `BENCH_FLOOR_MB` | 500 | **benchmark gate.** Below this a throughput number stops being a measurement |

Conflating them caused a real mistake: a config measuring 1,199 MB free was refused as
"thrashing" and a whole matrix row was redesigned around it.

**Headroom alone has never been measured to cause thrashing on this card.** The one
collapse on record — `EVICTED_TIME` 772,000 ms, an 8k prompt taking >900 s instead of 45 s —
had **ComfyUI resident** (`llm-tuning.md:774`). That is contention between two GPU
consumers, not a model leaving little free VRAM. Measured against the headroom reading:

| free VRAM | result |
|---|---|
| **264 MB** — qwen3 f16 KV, needle test (`llm-tuning.md:588`) | prefill 1,191 / 1,174 / 956 tok/s, gen 31.9 — **normal** |
| **1,468 MB** — MoE at `-c 65536` (`results.md`) | 420 ms eviction, throughput **unaffected**: 67.2 vs 67.4 |

The guard that actually matters is **GPU exclusivity** — `gpu-mode llm`, which
`preflight.py` checks before every run. A row between the two floors runs and is flagged:
the number is real, the config just isn't one to ship as-is.

---

## The backend A/B — `run_matrix.py`

The one long job: ROCm vs Vulkan, 18 timed rows + 16 probes across two arms, ~92 minutes
unattended.

```bash
python3 run_matrix.py --dry-run     # print all 34 invocations, touch nothing
python3 run_tests.py --smoke        # rehearse every command it issues, ~12 min
python3 run_tests.py                # sync happens here — do not scp by hand
ssh htpc-01 'tmux new -d -s bench python3 run_matrix.py'
```

That launch line contains **no shell syntax on purpose** — no `$(...)`, no pipe, no
redirection. tmux runs it through the login shell, which on htpc-01 is fish, and fish does
not parse those as bash does. `run_matrix.py` opens its own log instead.

### Watching it

```bash
ssh htpc-01 'python3 run_matrix.py --status'   # is it alive, how far in, anything wrong
ssh htpc-01 -t 'tmux attach -t bench'          # live, if you want to sit with it
```

`--status` reads files only and is safe to call at any time. It finds the newest run
itself and reports: whether the process is alive (from the sleep lock's PID), rows recorded
against rows expected, the row in flight, refusals separately from problems — a refusal is
a measured non-fit, which is a result — and the last few log lines.

The log is line-buffered (`open("a", buffering=1)`), so it reflects progress as it happens
rather than appearing at the end. That is what makes tailing it useful mid-run.

### What stops it wasting itself

| risk | bound |
|---|---|
| starts against a busy card or a missing model | `preflight.check_all()` runs **before** the service is stopped; a blocking failure exits 2 having changed nothing |
| a config that will not fit | `--load-only` probes run first and **gate** the timed rows against `BENCH_FLOOR_MB`. Every planned config was measured to load on both arms before the run |
| runs unbounded | `VARIANT_TIMEOUT_S = 300`. It was 1800, which put one row's worst case at 2.5 h and the matrix's at ~32 h |
| **the host suspends mid-run** | `bench.sleep_lock()` writes `/run/llama-bench.lock`, read by the `llama-bench.sh` sleep-inhibitor plugin. Without it every stock inhibitor check reports idle for the whole run — see below |
| a first row that cannot resolve the decision | the session stops — see Validity #4 |
| dies midway | rows append to `*.rows.md` as they complete; `--arm` and `--only` re-run just what was lost, and a partial run says so and skips the A-B-A |
| results stranded on the host | **not bounded.** See [Getting the results back](#getting-the-results-back) |

### `--smoke` before the real run

`run_matrix.py --smoke` runs the **same code path** — `arm()`, `cleanup()`, both images, the
graphics-queue container, `systemctl stop`/`start` — with `--ctx 4096 --lines 50
--variants 1`. ~12 minutes instead of ~92.

It exists because those commands had never been executed: of `run_matrix.py`'s 9 command
sites only one had ever run, and the bash teardown it replaced was tested once and found
**broken**. `--smoke` shrinks only the row size, so it cannot drift into rehearsing a
different program; a test asserts that.

### Why the MoE runs at two contexts

`-ub` is a property of expert routing and ubatch, **not of `-c`**. From `config.json`: 128
experts at `top_k` 8, `moe_intermediate_size` 704, `hidden_size` 2816. Routing splits the
ubatch, so each expert's FFN GEMM (`[rows × 2816] @ [2816 × 704]`) sees only `U × 8 / 128 =
U/16` rows — 32 at `-ub 512`, 128 at 2048. A dense model's FFN already gets all `U` rows,
which is exactly why the `-ub` sweep on gemma-12b was a **null result** (1151/1164/1137
tok/s, ~2% non-monotonic noise) while discussion #21043 reports +29% on Vulkan + MoE.

| rows | `-c` | why |
|---|---|---|
| throughput / model comparison | **65536** | matched to gemma, qwen3.5 and `ldr-tuning-methodology.md:41`'s held-constant value. Measured 1,468/1,605 MB free — loads fine on both backends, never OOMed |
| the `-ub` sweep | **49152** | valid at any `-c`, and at 65536 the `-ub 2048` cell falls to 676/815 MB — the tightest anywhere, with no `EVICTED` signal on Vulkan to defend it |

`(65536, 512)` vs `(49152, 512)` gives the `-c` effect for free.

### Keeping the host awake

htpc-01 suspends on its own schedule, and its `sleep-inhibitor.service` holds a block-mode
lock only while one of `/etc/sleep-inhibitor.d/`'s checks reports busy. **During a matrix
every stock check reports idle:**

| check | why it goes idle |
|---|---|
| `llama-swap.sh` | we stop `llama-swap.service` for the whole run, and it treats an unreachable container as nothing-on-the-GPU |
| `comfyui.sh` | ComfyUI is stopped by `gpu-mode llm`, a precondition |
| `ansible.sh` | no playbook is running |

So ~92 minutes would run unprotected while a process holds ~10 GiB across a GPU context —
which `llama-swap.sh`'s own comment says "does not reliably survive resume".

`llama-bench.sh` closes it, reading a lock file the bench declares rather than guessing
from container names:

```
bench.sleep_lock()  ->  /run/llama-bench.lock   (one line: the holder's PID)
```

`preflight.py` **blocks the run** if the plugin is missing, non-executable, or the service
is down. Deploy it with `ansible-playbook playbook-htpc-01.yaml --tags sleep-inhibitor`.

**The PID is what makes a crash safe.** `/run` is tmpfs so a reboot clears the lock, but a
SIGKILLed run leaves it behind — and a lock nothing can clear would pin the host awake
indefinitely. The plugin ignores a lock whose process is gone, and treats malformed or
empty content as idle for the same reason. All four cases are tested against the real
plugin in `test_integration.py`.

### Teardown

Stops `llama-swap.service` for the duration and restores it in a `finally`, removing **both**
container names (`llama-bench`, and `llama-swap` which the end-to-end phase creates — a
leftover would make `systemctl start llama-swap` fail on a name conflict).

`SIGINT`, `SIGTERM` and `SIGHUP` raise `SystemExit` so the `finally` runs. Unlike bash —
which defers a trap until the current foreground command returns, holding the GPU for the
rest of a multi-minute row — a signal interrupts `Popen.wait()` immediately. Remote stages
use `ssh -tt` because **without a tty a dropped connection signals nothing** and the job
orphans, holding the card with the service still stopped.

`SIGKILL` remains untrappable, so know the recovery:

```bash
sudo podman rm -f llama-bench && sudo systemctl start llama-swap
```

---

## Getting the results back

`run_matrix.py` writes `~/bench-<kind>-<stamp>.{log,rows.md}` **on htpc-01**, and nothing
pulls them back. **A run is not finished when the process exits — it is finished when the
rows are in [results.md](results.md) with their build commit.**

```bash
ssh htpc-01 'ls -t ~/bench-*.rows.md | head -1'
ssh htpc-01 'cat ~/bench-backend-ab-<stamp>.rows.md'   # paste into results.md
```

This is the failure the harness exists to prevent, and it recurred anyway: a session on
2026-08-01 produced a full fit envelope, a re-run `-fa` pair and the dispersion figure, and
left all of it in 16 unread files on the host while `results.md` still said "no rows yet".
Measurements in a log nobody reads get re-derived.

---

## Design notes

### The prompt corpus is a frozen artifact

`prompts.py` commits a deterministic seeded generator rather than ~1.5 MB of filler. Same
seeds, same prompts, so `prompt_n` is a regression test on the generator itself: `--lines
1200` measures **21,828 tokens** on Gemma, `--lines 540` measures **9,836**.

If those move, the generator changed and **every historical row is invalidated**.
`test_corpus_matches_the_recorded_hash` asserts stability against the hash in `testdata/`; a
missing baseline is a failure, not something to regenerate. Re-baselining is a deliberate act
behind `rebaseline_corpus.py --i-understand-this-invalidates-results`.

It does **not** prove equality with the pre-rewrite shell generator — that script was deleted
and never committed, so no such comparison can be re-derived.

### Parsers are tested against captured output

`testdata/` holds real `llama-server` startup logs (both backends), `amd-smi` output,
`--list-devices`, a completion response and sysfs values, recorded by `capture_fixtures.py`.
A hand-written fixture cannot catch a wrong assumption about a format, because the same
assumption produces both the parser and the fixture. Two defects prove it: the startup filter
once matched `"kv cache"` when llama.cpp writes `llama_kv_cache:`, capturing nothing; fixing
that to `"kv_cache"` then kept 424 of 2,326 lines, burying the signal under per-layer debug
noise.

### No sweep mode in `bench.py`

A sweep is a loop, and keeping it out keeps each row a single explicit configuration:

```bash
for ub in 512 1024 2048; do
  ./run-remote.sh --model gemma --ctx 32768 --fa 1 --ub "$ub" --label "ub sweep"
done
```

Anything that takes hours belongs in `run_matrix.py` under tmux, not in `run-remote.sh`.

### Why Python and not shell

It was 480 lines of bash with four Python fragments embedded in it, plus a 199-line bash
driver. Of eight defects found in one session, **six came from the shell layer or the
shell/Python boundary** — env assignments placed after a command, `command -v` failing under
`podman exec` because it is a builtin, a trap deferred until a multi-minute row returned,
fixed `/tmp` paths letting an aborted run contaminate the next, and a report block that
silently produced nothing because bash expanded `$` inside the Python source.

The decisive one was the cache gate: the logic that decides whether a measurement is real at
all, sitting in a shell string where nothing could test it. The driver was the same story —
only 9 of its 86 code lines were podman/systemctl; 30 were the row list, i.e. the definition
of what the experiment *is*, sitting where nothing could verify it. `run_matrix.plan()` is
now data, and the tests assert the matrix has the shape it claims without burning two hours
of GPU to find out.

### Row columns

`build` is the llama.cpp commit, not just the build number — it is what ties a number to the
open RDNA4 flash-attention regression. `baseline free` is device-wide free VRAM *before* the
model loaded; a row without it is not comparable to any other, because the figure includes
ComfyUI and the desktop.

| flag | effect |
|---|---|
| `--container NAME` | which container to exec into (default `llama-swap`) |
| `--backend rocm\|vulkan` | recorded in the row. Two rows are not comparable across backends, and without this column they look identical |
| `--expect-prompt-n N` | absolute anchor; fails the row if the median deviates >2% |
| `--load-only` | load, health-check, report VRAM and KV sizes, stop |
| `--verbose` | verbose llama-server. Untimed probes only — see above |
| `--dry-run` | synthetic timings, no container, no GPU |
