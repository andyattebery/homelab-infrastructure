# llama-swap benchmark results

Append rows rather than re-deriving them next session. Produced by
[bench.py](bench.py) — see [README.md](README.md) for the traps that invalidate a row.

A row is only comparable to another row with the same `build`, the same `baseline free`,
and a near-zero `EVICTED`. Rows measured while ComfyUI held VRAM are not comparable to
rows measured without it.

**All rows below are on build `b10156-91f8c9c5f` (llama.cpp 2026-07-27), which already
carries the open RDNA4 flash-attention prefill regression** (issue #26220, introduced by
`fa72aeccb` on 2026-07-24). Prefill numbers here are on the degraded kernel; see the
tuning doc's build-provenance section before comparing against anything from a different
build.

> ## ⚠ Everything dated before 2026-08-01 is a **ROCm** measurement read via **`amd-smi`**
>
> Two things changed on 2026-08-01, and both break comparability with anything measured
> after them if you are not careful:
>
> 1. **Backend.** A Vulkan-vs-ROCm A/B added rows from a second backend. Backends allocate
>    compute buffers differently, so **VRAM figures and the ~17 / ~33 / ~88 MB-per-1k
>    slopes are ROCm properties, not card properties.** Every row now carries a `backend`
>    column; older rows are backfilled `rocm`.
> 2. **VRAM measurement method.** `bench.py` reads free VRAM from host sysfs
>    (`/sys/class/drm/card[0-9]/device/mem_info_vram_*`, converted to MB) rather than
>    `amd-smi` inside the container, because **the Vulkan image has no `amd-smi`** and a
>    per-backend fallback would give the two arms different methods. A paired
>    `amd-smi`/sysfs reading is recorded on the ROCm arm to tie the two scales together —
>    without it, these older rows would be orphaned rather than merely offset.
>
> `EVICTED` is an `amd-smi` field with no sysfs equivalent, so it reads **`n/a` on Vulkan
> rows** — that means *not measured*, not *zero*. There the guards are `BENCH_FLOOR_MB`,
> wall-time sanity, and cross-arm comparison: a row 20× slower than its ROCm twin is
> thrashing whatever the counter would have said. **Not** the 1.5 GB figure — see the
> correction below.

## Backend A/B — RESULT (2026-08-01) — **Vulkan wins on every axis**

18 rows, both arms, `v245-{rocm,vulkan}-b10200` (`b10200-5f55650a7` on both sides),
15,656 MB baseline, `gpu-mode llm`, 67 minutes. **0 problems, no discarded variants, no
refused configs.**

**The session is valid: the A-B-A drift control reproduces to −0.26%** — the first ROCm
gemma row measured 38.7 tok/s (38.7–38.7) and its repeat at the end of the session
measured 38.6 (38.6–38.6).

### The decision

Pre-registered criterion: **tg ≥ +10% with non-overlapping ranges**.

| model | `-c` | ROCm gen | Vulkan gen | Δ | ranges overlap? |
|---|---|---|---|---|---|
| gemma-4-12b-it | 65536 | 38.7 (38.7–38.7) | **42.7** (42.7–42.8) | **+10.3%** | no |
| qwen3.5-9b | 65536 | 48.0 (48.0–48.3) | **51.1** (51.0–51.4) | +6.5% | no |
| gemma-4-26B-A4B | 65536 | 67.4 (67.4–67.5) | **91.1** (90.5–91.1) | **+35.2%** | no |
| gemma-4-26B-A4B | 49152 | 67.4 (67.3–67.5) | **91.2** (91.0–91.4) | **+35.3%** | no |

**Nothing regresses, on any model, on either metric.** gemma clears the ≥10% bar (10.3%);
qwen3.5 favours Vulkan but at +6.5% does not. They do not *disagree* — both point the same
way with non-overlapping ranges — so the "two dense models disagree" branch does not apply.
The MoE, which step 3 may well adopt, is +35%.

Dispersion is tiny: most rows have a gen range of 0.0–0.4%, against a 10% decision
threshold. The instrument was never the limiting factor.

### The reason ROCm was chosen is now inverted

ROCm was selected for **prompt processing**. Vulkan beats it at prefill on every single
config:

| model | ROCm prefill | Vulkan prefill | Δ |
|---|---|---|---|
| gemma `-c 65536` | 1,134.9 | **1,734.6** | **+52.8%** |
| qwen3.5 `-c 65536` | 2,627.2 | **3,095.0** | +17.8% |
| gemma-4-26B-A4B `-c 65536` | 2,357.7 | **2,855.5** | +21.1% |

This is consistent with [#26220](https://github.com/ggml-org/llama.cpp/issues/26220) — the
rocWMMA FlashAttention kernel was removed in `fa72aeccb` (2026-07-24) and our build
postdates it. **The original rationale for ROCm no longer holds on this build.**

### `-ub` on the MoE — real, ~10–14%, and it is NOT the dense null result

The dense 12B sweep was noise (1151/1164/1137). The MoE is not, on either backend:

| `-ub` | ROCm prefill | Vulkan prefill |
|---|---|---|
| 512 | 2,362.1 | 2,858.1 |
| 1024 | 2,597.5 (+10.0%) | 3,140.7 (+9.9%) |
| 2048 | 2,616.8 (+10.8%) | 3,261.9 (**+14.1%**) |

The routing argument holds: 128 experts at top-8 means each expert's FFN GEMM sees only
`U/16` rows, so a dense model's FFN is already saturated where the MoE's is starved. Not
the +29% of #21043, but a real effect in the predicted direction.

**Generation pays slightly for it on ROCm** (67.4 → 65.1, −3.4%) and not at all on Vulkan
(91.2 → 90.8). Since generation dominates wall time, `-ub 512` remains the right default;
`-ub 1024` is defensible on Vulkan where generation is flat.

### `-c` costs nothing

MoE at 65536 vs 49152, `-ub 512`: 2,357.7/67.4 vs 2,362.1/67.4 on ROCm, 2,855.5/91.1 vs
2,858.1/91.2 on Vulkan. **Identical within noise on both backends.** The larger context is
free, so the MoE should be deployed at `-c 65536` alongside the others.

### `-fa 1` holds on both backends, and is larger on Vulkan

| backend | `-fa 0` prefill | `-fa 1` prefill | ratio |
|---|---|---|---|
| ROCm | 169.0 | 1,280.9 | **7.6×** |
| Vulkan | 148.6 | 1,828.6 | **12.3×** |

`-fa 1` also wins generation on both (ROCm 31.4 → 39.4; Vulkan 41.0 → 43.6). No axis on
which `-fa 0` wins anywhere. The global `llama_swap_flash_attn` stays on.

### `GGML_VK_ALLOW_GRAPHICS_QUEUE=1` — small but positive

gemma `-c 65536` on Vulkan: 43.6 tok/s gen and 1,781.1 prefill, against 42.7 / 1,734.6
without. **+2.1% generation, +2.7% prefill.** Worth taking if Vulkan is adopted; not worth
a separate decision.

### `EVICTED` is confirmed not to be a function of headroom

The row with the *least* free VRAM in the entire matrix — MoE `-ub 2048` at 1,060 MB —
recorded **0 ms** of eviction. gemma at 3,640 MB free recorded **304 ms**. This is the
third independent confirmation that the "1.5 GB floor" does not describe a thrashing
threshold; see the correction below.

### Rows

| model | backend | build | -c | -ub | -fa | KV | prompt_n | prefill med | prefill min-max | gen med | gen min-max | free | baseline free | EVICTED | n | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma | rocm | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 21828 | 1134.9 | 1127.1-1151.3 | 38.7 | 38.7-38.7 | 3640 MB | 15656 MB | 304 | 5 | backend A/B |
| qwen3.5 | rocm | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 23492 | 2627.2 | 2622.7-2637.5 | 48.0 | 48.0-48.3 | 4962 MB | 15656 MB | 245 | 5 | backend A/B |
| gemma-moe | rocm | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 21828 | 2357.7 | 2325.0-2367.0 | 67.4 | 67.4-67.5 | 1468 MB | 15656 MB | 216 | 5 | MoE grid -c 65536 -ub 512 |
| gemma-moe | rocm | b10200-5f55650a7 | 49152 | 512 | 1 | f16 | 21828 | 2362.1 | 2334.8-2368.9 | 67.4 | 67.3-67.5 | 1804 MB | 15656 MB | 271 | 5 | MoE grid -c 49152 -ub 512 |
| gemma-moe | rocm | b10200-5f55650a7 | 49152 | 1024 | 1 | f16 | 21828 | 2597.5 | 2549.3-2598.0 | 66.7 | 66.7-66.8 | 1556 MB | 15656 MB | 0 | 5 | MoE grid -c 49152 -ub 1024 |
| gemma-moe | rocm | b10200-5f55650a7 | 49152 | 2048 | 1 | f16 | 21828 | 2616.8 | 2572.5-2617.4 | 65.1 | 65.1-65.2 | 1060 MB | 15656 MB | 0 | 5 | MoE grid -c 49152 -ub 2048 |
| gemma | rocm | b10200-5f55650a7 | 16384 | 512 | 0 | f16 | 9836 | 169.0 | 168.5-174.8 | 31.4 | 31.4-31.4 | 3600 MB | 15656 MB | 147 | 5 | fa sweep |
| gemma | rocm | b10200-5f55650a7 | 16384 | 512 | 1 | f16 | 9836 | 1280.9 | 1279.1-1295.7 | 39.4 | 39.3-39.4 | 4456 MB | 15656 MB | 4 | 5 | fa sweep |
| gemma | vulkan | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 21828 | 1734.6 | 1711.1-1745.5 | 42.7 | 42.7-42.8 | 3776 MB | 15656 MB | n/a | 5 | backend A/B |
| qwen3.5 | vulkan | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 23492 | 3095.0 | 3072.8-3100.5 | 51.1 | 51.0-51.4 | 5092 MB | 15656 MB | n/a | 5 | backend A/B |
| gemma-moe | vulkan | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 21828 | 2855.5 | 2564.0-2866.7 | 91.1 | 90.5-91.1 | 1605 MB | 15656 MB | n/a | 5 | MoE grid -c 65536 -ub 512 |
| gemma-moe | vulkan | b10200-5f55650a7 | 49152 | 512 | 1 | f16 | 21828 | 2858.1 | 2852.8-2868.4 | 91.2 | 91.0-91.4 | 1942 MB | 15656 MB | n/a | 5 | MoE grid -c 49152 -ub 512 |
| gemma-moe | vulkan | b10200-5f55650a7 | 49152 | 1024 | 1 | f16 | 21828 | 3140.7 | 3134.8-3146.7 | 91.1 | 91.0-91.2 | 1695 MB | 15656 MB | n/a | 5 | MoE grid -c 49152 -ub 1024 |
| gemma-moe | vulkan | b10200-5f55650a7 | 49152 | 2048 | 1 | f16 | 21828 | 3261.9 | 3248.4-3269.1 | 90.8 | 90.7-90.9 | 1199 MB | 15656 MB | n/a | 5 | MoE grid -c 49152 -ub 2048 |
| gemma | vulkan | b10200-5f55650a7 | 16384 | 512 | 0 | f16 | 9836 | 148.6 | 147.5-148.9 | 41.0 | 41.0-41.0 | 3734 MB | 15656 MB | n/a | 5 | fa sweep |
| gemma | vulkan | b10200-5f55650a7 | 16384 | 512 | 1 | f16 | 9836 | 1828.6 | 1396.8-1857.7 | 43.6 | 43.6-43.7 | 4592 MB | 15656 MB | n/a | 5 | fa sweep |
| gemma | vulkan | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 21828 | 1781.1 | 1746.7-1784.0 | 43.6 | 43.6-43.7 | 3776 MB | 15656 MB | n/a | 5 | GGML_VK_ALLOW_GRAPHICS_QUEUE=1 |
| gemma | rocm | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 21828 | 1132.5 | 1130.7-1143.0 | 38.6 | 38.6-38.6 | 3641 MB | 15657 MB | 177 | 5 | A-B-A repeat of the first row |

### What this does NOT settle

- **Quality.** Throughput only. The MoE is `UD-Q3_K_XL` against gemma's `UD-Q6_K_XL`, and
  low-bit quantisation degrades exactly the metric this project optimises.
- **Turn wall-clock.** Every row is a single synthetic call. `docs/README.md:339` —
  *"query-level or it didn't happen"* — so the end-to-end LDR check per arm is still owed.
  The ratio should carry (shared overhead cancels), but that is an argument, not a
  measurement.
- **Prompt-size dependence.** All rows at ~21.8k tokens. Generation is flat with prompt
  size (measured 39.6/39.0/40.1 across 8k–22k), so the decision metric is safe; prefill is
  not, and E1 found W bimodal at ~2.2k and 7k–20k.

### Prompt-size anchors this run established

`--lines 1200`: gemma **21,828**, gemma-4-26B-A4B **21,828** (same Gemma tokenizer),
qwen3.5-9b **23,492**. All three are now in `bench.EXPECTED_PROMPT_N`, so every future row
carries an absolute contamination check rather than only the relative gate.

---

### Backend A/B pre-flight, part 2 (2026-08-01) — fit envelope, `-fa` re-run, and a correction

Everything here was measured on `v245-{rocm,vulkan}-b10200` at a **15,656 MB baseline**,
with `llama-swap.service` stopped and ComfyUI down. The matrix itself has not run yet.

**Correction: the "1.5 GB floor" is not a thrashing threshold, and two of this repo's own
measurements say so.** Its origin is `llm-tuning.md:774` — *"the same 8k prompt took >900 s
**with ComfyUI resident** vs 45 s without, `EVICTED_TIME` 772,000 ms → 52 ms"*. That is
**GPU contention between two processes**, not a single model leaving little headroom.
Measured against it:

| free VRAM | what happened |
|---|---|
| **264 MB** (qwen3 f16 KV, needle test — `llm-tuning.md:588`) | prefill 1,191 / 1,174 / 956 tok/s, gen 31.9 — **normal** |
| **1,468 MB** (MoE `-c 65536`, below) | 420 ms eviction, throughput **unaffected**: 67.2 vs 67.4 |

So headroom alone did not reproduce it at either point. The guard that actually matters is
**GPU exclusivity** (`gpu-mode llm`), which `preflight.py` now checks before every run. The
harness therefore separates two numbers that were previously one: `VRAM_FLOOR_MB` (1500)
as *deployment* margin, and `BENCH_FLOOR_MB` (500) as the point below which a throughput
number stops being a measurement. A config between them runs and is flagged.

**Fit envelope — every config the matrix will run, both backends.** `--load-only`, so these
are load-time figures, not throughput.

| model | `-c` | `-ub` | `-fa` | ROCm free | Vulkan free |
|---|---|---|---|---|---|
| gemma | 65536 | 512 | 1 | 3,639 MB | 3,776 MB |
| gemma | 16384 | 512 | 0 | 3,600 MB | 3,734 MB |
| gemma | 16384 | 512 | 1 | 4,456 MB | 4,592 MB |
| qwen3.5 | 65536 | 512 | 1 | 4,962 MB | 5,092 MB |
| gemma-moe | **65536** | 512 | 1 | **1,468 MB** | 1,605 MB |
| gemma-moe | 65536 | 1024 | 1 | 1,204 MB | 1,343 MB |
| gemma-moe | 65536 | 2048 | 1 | **676 MB** | **815 MB** |
| gemma-moe | 49152 | 512 | 1 | 1,804 MB | 1,942 MB |
| gemma-moe | 49152 | 1024 | 1 | 1,556 MB | 1,695 MB |
| gemma-moe | 49152 | 2048 | 1 | 1,060 MB | 1,199 MB |
| gemma-moe | 32768 | 512 | 1 | 2,140 MB | 2,278 MB |
| gemma-moe | 32768 | 2048 | 1 | 1,444 MB | 1,583 MB |

**The MoE loads at `-c 65536` on both backends — it never OOMed.** ROCm's 1,468 MB
reproduces the earlier fit search *exactly*, on a different build, which cross-validates
both. 65536 was originally passed over for sitting below the 1.5 GB margin, not for
failing. The only OOM records in this repo are qwen3-14b: `-c 32768 -fa 0` (2,668 MiB
compute buffer) and `Q6_K`.

**Consequence for the matrix.** The MoE now runs its throughput row at **65536**, matched
to gemma and qwen3.5 and to `ldr-tuning-methodology.md:41`'s held-constant value — without
it the model comparison is confounded by context. The `-ub` sweep stays at **49152**,
because `-ub` depends on expert routing and ubatch, not on `-c`, and at 65536 the 2048 cell
falls to 676/815 MB. That is the tightest cell anywhere in the matrix and the least
supported by evidence — the lowest headroom ever measured to run normally here is 264 MB,
but that is one data point, and on Vulkan there is no `EVICTED` signal to check it against.
Taking the same measurement at 49152 costs nothing and needs no such argument.

**Vulkan consistently leaves ~130–140 MB more free than ROCm** at identical configs — the
allocators differ, and it is the same sign at every point.

`-ub` cost is **linear**, and the dense sweep predicts the MoE to within 1 MB: gemma's
512→1024→2048 cost 316 then 634 MB (exactly 1:2), and the MoE's 512→2048 cost 743 MB, so
512→1024 was predicted at 1,694 and **measured 1,695**.

**`-fa` re-run on the current build — the 8.3× holds, at 7.6×.** ROCm, `-c 16384`,
540 lines (9,836 tokens), `--variants 5`. Both sides f16 KV, so this is the deconfounded
comparison, and both are far above any floor:

| model | backend | build | -c | -ub | -fa | KV | prompt_n | prefill med | prefill min-max | gen med | gen min-max | free | baseline free | EVICTED | n | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma | rocm | b10200-5f55650a7 | 16384 | 512 | 0 | f16 | 9836 | 169.0 | 168.6-174.3 | 31.4 | 31.3-31.5 | 3600 MB | 15656 MB | 333 | 5 | fa sweep |
| gemma | rocm | b10200-5f55650a7 | 16384 | 512 | 1 | f16 | 9836 | 1277.0 | 1274.3-1294.3 | 39.3 | 39.3-39.3 | 4456 MB | 15656 MB | 0 | 5 | fa sweep |

**7.6× prefill and +25% generation.** Note generation is *not* unaffected by `-fa` here —
the earlier tables showed +4–12%, this shows +25% — and `-fa 0` also shows 333 ms of
eviction against `-fa 1`'s 0 despite 3.6 GB free, which is a reminder that `EVICTED` is not
a pure function of headroom.

**Dispersion, which is what makes the backend decision callable at all:** generation spread
was **0.6%** across 5 variants (31.3–31.5) and **0.0%** on the `-fa 1` row. The decision
threshold is a ≥10% gap with non-overlapping ranges, so the instrument resolves it with
~16× margin. This was the open question of whether the harness could decide anything.

**KV structure, read from the startup logs rather than computed** — this is why arithmetic
from `config.json` kept missing:

| model | grows with `-c` | pinned | at the deployed `-c` |
|---|---|---|---|
| gemma-4-12b-it | 8 full-attention layers | 40 sliding-window @ 1,536 cells, 480 MiB | 1,024 MiB @ 65536 |
| gemma-4-26B-A4B | **5** full-attention layers | 25 sliding-window @ 1,536 cells, 300 MiB | 960 MiB @ 49152 |

The MoE has **5** full-attention layers, not the 4 its `config.json` layer indices imply.

**Prompt-size anchors** (`bench.EXPECTED_PROMPT_N`, both measured on gemma):
`--lines 1200` → **21,828** tokens; `--lines 540` → **9,836**. The 540-line size exists
because 1200 lines does not fit `-c 16384` — the fa sweep would have died on HTTP 400.

### Backend A/B pre-flight, part 1 (2026-08-01) — images, drivers, and the container translation

Checks run before the Vulkan-vs-ROCm matrix, against
`ghcr.io/mostlygeek/llama-swap:v245-{rocm,vulkan}-b10200`:

| question | answer |
|---|---|
| **Same llama.cpp build on both sides?** | **Yes — both report `version: 10200 (5f55650a7)`.** Asked of the binary, not inferred from the tag string. This is the precondition the whole comparison rests on |
| Does the Vulkan image have what the harness needs? | **Yes** — `curl`, `pkill`, `mkdir`, `grep`, `cat`, `sh` all present, despite being a 906 MB image against ROCm's 22.8 GB |
| `amd-smi`? | **ROCm yes, Vulkan no** — as predicted. Hence host-sysfs VRAM on both arms, and `EVICTED` = `n/a` on Vulkan |
| Which driver does Vulkan actually load? | **RADV** — `llama-server --list-devices` reports `Vulkan0: AMD Radeon RX 9070 XT (RADV GFX1201)`. **This is a much cheaper RADV check than the `GGML_LOG_DEBUG` device banner**, and it works at normal verbosity |
| Verbosity flag | `-v` / `--verbose` / `--log-verbose`; also `-lv N` / `--log-verbosity N` (`LLAMA_ARG_LOG_VERBOSITY`) |
| Quadlet → `podman run` translation | Works on both arms: container starts, `podman exec` succeeds, `/models` mounts, `/dev/kfd` + `/dev/dri/{card1,renderD128}` visible |

**The sysfs↔amd-smi calibration is a non-issue.** Same instant, nothing loaded:
**sysfs 15,656 MB free vs amd-smi 15,657 MB** — 1 MB apart, 0.006%. Switching the
measurement method therefore does **not** orphan the historical rows: the MB-per-1k
slopes, the 1.5 GB floor and the deployed-footprint table all remain directly comparable.
(`llama-server --list-devices` on the *ROCm* backend separately reports ~16,206 MB free —
a different quantity, roughly 550 MB more optimistic. Do not mix it in.)

**Forcing the RADV ICD matters more than the AMDVLK argument suggested.** The Vulkan image
ships **eight** ICDs — `radeon`, `lvp` (lavapipe, a *software* rasterizer), `intel`,
`intel_hasvk`, `nouveau`, `virtio`, `gfxstream`, `asahi` — and **no AMDVLK at all**. So the
documented risk (AMDVLK ~4× slower on dense prefill) is absent here, and the real hazard is
auto-selection landing on **lavapipe and quietly running on the CPU**, which would be a
spectacular false negative. `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json`
stays mandatory.

**The two images differ well beyond the GPU backend** — 22.8 GB vs 906 MB, built with GCC
13.3.0 vs 15.2.0. The A/B therefore measures *the shipped ROCm image vs the shipped Vulkan
image*, which is exactly the choice being made, but it is **not** evidence about HIP-vs-
Vulkan kernels in the abstract.

Also: the deployed floating `:rocm` tag is a **different digest** from `v245-rocm-b10200`,
so the matrix does move ROCm forward from what is running today; and htpc-01 **cannot** ssh
to docker-01 (host key verification fails), so the end-to-end phase is operator-driven.

**MoE fit search — `-c 49152`, decided on measurement.** Free VRAM after load at a
15,656 MB baseline, plus `EVICTED_TIME` from a real 22.5k-token prompt:

| `-c` | free after load | EVICTED (real prompt) | prefill | gen |
|---|---|---|---|---|
| 65536 | 1,468 MB | **420 ms** | 2,337.9 | 67.2 |
| 49152 | 1,804 MB | **58 ms** | 2,348.9 | 67.4 |
| 32768 | 2,140 MB | — | — | — |

Dead linear at **20.5 MB per 1k**. The two real runs differ only in `-c`, so the 7×
eviction difference is attributable: less headroom, more VRAM↔GTT churn. **Throughput was
unaffected** (67.2 vs 67.4 tok/s), so 65536 would likely have worked — 49152 simply buys
7× less churn for nothing. **Correction to an earlier version of this note:** it described
1.5 GB as a margin over "a measured thrashing event at 264 MB free". There was no such
event — the needle test *at* 264 MB free measured normal throughput, and the 772,000 ms
collapse had ComfyUI resident. See the floor correction above and
[llm-tuning.md](../docs/llm-tuning.md#the-15-gb-floor-is-a-margin-not-a-cliff).

*Do not read `EVICTED` as a pure function of headroom.* A gemma-12b row at 4,184 MB free
showed 163 ms in the same session — some of it is just paging a 10–13 GB model in at load.
It is only comparable **within** one model at one prompt size.

**KV shape from the load log, which is why arithmetic from `config.json` kept missing.**
Gemma-family models split the cache: only the full-attention layers grow with `-c`, while
the sliding-window layers stay pinned at 1,536 cells forever.

| model | grows with `-c` | fixed | measured |
|---|---|---|---|
| gemma-4-12b-it | 8 layers, 64 MiB @ 4096 | 40 layers, 480 MiB | **~16 MB/1k** (matches the 16.6 measured) |
| gemma-4-26B-A4B | **5** layers, 1,280 MiB @ 65536 | 25 layers, 300 MiB | **~19.5 MB/1k** |

Predicting ~64 MB/1k for the 12B — the 4× miss on record — came from assuming all 48
layers cache. They do not. Note the MoE has **5** full-attention layers, not the 4 implied
by `config.json`'s `6/12/18/24`; another reason to read the log rather than the config.

**Unplanned result: the MoE is much faster than the dense 12B on both axes.**
2,348.9 vs ~1,151 tok/s prefill and 67.4 vs ~40 tok/s generation — roughly **2× prefill and
+68% generation**, on ROCm, the backend #21043 says should favour the *dense* model. That is
step 3's question answering itself early. **Quality is entirely unmeasured**, and this is
`UD-Q3_K_XL` against Gemma's `UD-Q6_K_XL`, so low-bit degradation of exactly the metric that
matters is the open question.

**Harness mechanics settled while testing the teardown** (see [README.md](README.md)):
bash defers a trap until the foreground command returns, so a killed session left the GPU
held for the rest of a multi-minute row. Backgrounding each row and blocking on `wait` —
which is interruptible — restores the machine ~20 s after a kill instead.

## Throughput

| model | backend | build | -c | -ub | -fa | KV | prompt_n | prefill med | gen med | free | baseline free | EVICTED | n | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3 | rocm | b10156-91f8c9c5f | 32768 | 512 | 1 | q8_0 | 27753 | 1101.3 | 27.0 | 2475 MB | 15095 MB | 6 ms | 3 | deployed config, harness first run |
| gemma | rocm | b10156-91f8c9c5f | 32768 | 512 | 1 | f16 | 21828 | 1151.2 | 40.1 | 3622 MB | 15095 MB | 6 ms | 3 | ub sweep |
| gemma | rocm | b10156-91f8c9c5f | 32768 | 1024 | 1 | f16 | 21828 | 1163.9 | 39.9 | 3306 MB | 15095 MB | 6 ms | 3 | ub sweep |
| gemma | rocm | b10156-91f8c9c5f | 32768 | 2048 | 1 | f16 | 21828 | 1136.8 | 39.0 | 2672 MB | 15095 MB | 6 ms | 3 | ub sweep |
| gemma | rocm | b10156-91f8c9c5f | 32768 | 512 | 1 | f16 | 21828 | 1148.4 | 40.0 | 3473 MB | 14945 MB | 6 ms | 3 | thinking tail, max_tokens 6000 |

*(Rows written after 2026-08-01 additionally carry `prefill min-max` and `gen min-max`
columns: a backend decision rests on a ≥10% generation gap, and a gap between two medians
whose ranges overlap is not a result.)*

### `-ub` sweep — closed, null result

Both review docs ranked this the highest-value untested lever. It does nothing here:
prefill 1151.2 / 1163.9 / 1136.8 tok/s across `-ub` 512 / 1024 / 2048 is a ~2%
non-monotonic spread at a 21,828-token prompt — noise. Free VRAM falls 3,622 → 3,306 →
2,672 MB, so raising it spends ~950 MB for nothing. **Keep the default 512.**

### Prompt-size sweep — the "16k anomaly" does not reproduce

A 16k-token prompt once failed with an HTTPError while 8k and 24k succeeded either side
of it. That was recorded under `-fa 0`. Retried under the current flags:

| model | backend | build | -c | -ub | -fa | KV | prompt_n | prefill med | gen med | free | baseline free | EVICTED | n | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma | rocm | b10156-91f8c9c5f | 32768 | 512 | 1 | f16 | 7842 | 1314.5 | 39.6 | 3464 MB | 14937 MB | 0 ms | 3 | 8k |
| gemma | rocm | b10156-91f8c9c5f | 32768 | 512 | 1 | f16 | 15764 | 1195.8 | 39.0 | 3464 MB | 14937 MB | 0 ms | 3 | 16k — 3/3 clean |

Three clean runs at 15,764 tokens, plus the 21,828-token rows above. **Closed as not
reproducing.** Note prefill falls with depth (1314 → 1196 → 1151 tok/s from 8k → 16k →
22k), which is expected and is also the shape the RDNA4 regression amplifies.

### Harness fix: `EVICTED_TIME` attribution

Early rows recorded `EVICTED_TIME: 9650`, which was **not** the inference process.
`amd-smi process` lists every GPU client, and the first block is the desktop compositor —
whose counter was ~9.6 s purely because it lived through a suspend/resume. The harness now
reports the `EVICTED_TIME` of the block holding the most VRAM, i.e. llama-server, which
reads **0 ms**. Rows above marked `9650` predate the fix; treat their EVICTED column as
unreliable, not as evidence of thrashing.

### Context size vs VRAM (2026-07-31)

`gpu-mode llm`, ComfyUI stopped, `-fa 1 -np 1`, baseline free 15,510 MB.

| config | used | free | Δ vs row above | slope |
|---|---|---|---|---|
| gemma `-c 32768` | 12,267 MB | 4,037 MB | — | — |
| gemma `-c 40960` | 12,403 MB | 3,901 MB | +136 MB / 8.2k | 16.6 MB/1k |
| gemma `-c 49152` | 12,539 MB | 3,765 MB | +136 MB / 8.2k | 16.6 MB/1k |
| gemma `-c 65536` | 12,811 MB | 3,493 MB | +272 MB / 16.4k | 16.6 MB/1k |
| qwen3 `-c 40960` q8_0 KV | 14,135 MB | 2,169 MB | — | — |
| qwen3 `-c 49152` q8_0 KV | 14,855 MB | 1,449 MB (under the 1.5 GB *deployment* margin) | +720 MB / 8.2k | 87.9 MB/1k |

**Gemma ~17 MB/1k (4 points, linear); Qwen3 ~88 MB/1k (2 points).** Gemma is projected to
reach ~131k on this card (~13.9 GB); Qwen3 caps near 48k. Sliding-window attention vs
dense — an architecture difference, not a hardware one.

**Slopes are only valid within one baseline.** There is no qwen3 `-c 32768` row in this
session; the 13,746 MB in the deployed-footprint table below was taken at a 15,244 MB
baseline, 266 MB under this one. Differencing across the two published **~24 MB/1k** for
Qwen3, wrong by 3.6× and not derivable from any pair of numbers here.

### Qwen3.5-9B added (2026-07-31)

`unsloth/Qwen3.5-9B-GGUF`, `UD-Q6_K_XL` (8.16 GiB) — deliberately the **same quant tier as
Gemma** so a model comparison is not confounded by quantisation. Sampler is its own model
card's thinking-mode-general recommendation, which differs from Qwen3's:
`--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 1.5`.

| model | `-c` | used | free | baseline free |
|---|---|---|---|---|
| gemma-4-12b-it | 65536 | 12,815 MB | 3,489 MB | 15,510 MB |
| **qwen3.5-9b** | **65536** | **10,371 MB** | **5,933 MB** | 15,657 MB |

**2.4 GB more headroom than Gemma at the same context**, and it answered a trivial prompt
8 s after a cold load. That headroom is a lever, not slack: it is what would pay for an MTP
draft model (`unsloth/Qwen3.5-9B-MTP-GGUF`) or a larger context, neither of which fits
alongside Gemma.

Chosen over the already-downloaded Qwen3-14B because BFCL — which ranked Qwen3-14B above
Gemma — measures whether a model *decides* to call a tool, and the local-deep-research
harness makes that decision for it. What matters there is query generation, relevance
judgement and cited synthesis, and Qwen3.5-9B is the only candidate with a published
number in that harness (91.2% SimpleQA, upstream's own figure).

### Real Onyx traffic (2026-07-31) — the failure that started the E2E plan

From `/logs/stream/upstream`, one call in a real research query:

```
task 1815 | prompt eval time = 9845.82 ms / 11173 tokens (1134.80 tok/s)
task 1815 | total time      = 472537.60 ms / 28776 tokens
task 1815 | release: stop processing: n_tokens = 32767, truncated = 1
```

17,534+ tokens of reasoning at ~38 tok/s for 472 s, terminated at the `-c 32768`
ceiling, no content and no tool call emitted. Cause: `--reasoning-budget -1`.
Also visible in the same log: the chat auto-naming call (295-token prompt, 123 decoded,
3.5 s), which fires once per new session against the default model.

**Prefill at real depth: 1,134 tok/s @ 11,173 tokens. Generation: ~38 tok/s, flat.**

### E1 — real Onyx traffic, the seven-query set (2026-07-31)

Gemma `-c 65536`, `max_input_tokens` 55,296, `--reasoning-budget 4096`, `gpu-mode llm`.
Raw capture archived at [../onyx/runs/2026-07-31-e1-upstream.log](../onyx/runs/2026-07-31-e1-upstream.log);
query set at [../queries.md](../queries.md). 21 agent calls + 8 auto-naming
calls. **`truncated = 0` on every call** — nothing hit a ceiling, so these numbers are
the workload rather than the limit.

| query | n | peak prompt | peak total | A | wall | W per search |
|---|---|---|---|---|---|---|
| 1 Home Assistant | 2 | 11,681 | 12,409 | 728 | 58 s | 2,252 · 7,392 |
| 2 Caddy vs Traefik | **0** | 1,468 | 3,406 | 1,938 | 58 s | — |
| 3 ROCm maintainer | **5** | 14,008 | 15,785 | 1,777 | 145 s | 1,783 · 2,156 · 2,229 · 2,379 · 1,736 |
| 4 unanswerable p99 | 4 | 23,180 | 23,859 | 679 | 120 s | 2,122 · 2,177 · 1,839 · **13,651** |
| 5 flash attention | **0** | 1,461 | 3,370 | 1,909 | 64 s | — |
| 6 ZFS vs btrfs | **0** | 1,480 | 3,828 | 2,348 | 68 s | — |
| 7 Battlemage (regression) | 2 | **25,316** | **30,349** | **5,033** | 221 s | 1,973 · **20,110** |
| 8th interaction, unnamed | 1 | 6,745 | 8,265 | 1,520 | 60 s | 2,645 |

Sessions were separated by the auto-naming call, not by time: the operator pasted
queries, so inter-query gaps run as short as 10 s and a gap threshold mis-splits turns
(it produced negative `W`, which is the tell). One naming call per new session,
~660–1,940-token prompt, ~180–250 decoded, on the default model.

**Derived terms:**

| term | value |
|---|---|
| **S** (system + tool schemas) | **~1,430 tokens** — the cached prefix length on every agent call |
| **Q** | 26–50 tokens |
| **n** | 0, 0, 0, 1, 2, 2, 4, 5 → **median 2, max 5** |
| **W** | 14 values. **Median 2,203.** 11 of 14 in a tight **1,736–2,645** band; 3 outliers: **7,392 · 13,651 · 20,110** |
| **A** (final decode, reasoning + answer) | 679–5,033 |
| peak prompt / peak total | **25,316 / 30,349** |

**W is bimodal, and that is the headline.** A plain search-result set costs ~2,200
tokens and is remarkably consistent. Something else — a full page crawl — costs 7k–20k,
and it is what sets the peak. Averaging the two modes together would model neither.

**Two calls exceeded the old 22,528 `max_input_tokens`** (23,180 and 25,316), which is
failure #2 reproduced and then cleared: both completed under 55,296.

**`-c 32768` could not have run this set.** Peak total was 30,349 — inside 32,768 by only
2,419 tokens, and the input budget that context allows (22,528) is exceeded twice above.

### Thinking-token tail

Gemma, 21,828-token RAG prompt, `max_tokens: 6000`, all `finish_reason: stop`:
**1,921 / 1,868 / 1,764 completion tokens.**

This corrects the "128–220 thinking tokens" figure recorded earlier, which was measured
on a trivial `Reply with exactly: OK` prompt and does not generalize — it is ~9× low.

**The tail is wider than that range.** A later run at 15,764 tokens with
`max_tokens: 3000` had one variant hit `finish_reason: length`, i.e. thinking alone
exceeded 3000 tokens. So budget against a tail of >3k, not against the ~1.9k median. The
8192-token output reserve still holds, but with less margin than the median suggests.

Not yet measured: the p99 on genuinely hard multi-source synthesis, which is what
followup item 4 wants and needs real traffic.

## Pre-harness measurements

Taken by hand before this harness existed. Single-shot, not medians, and the prompt was
~4.1–4.5k tokens rather than RAG-sized — kept for the `-fa` comparison, which is the
decision they supported. Do not compare their absolute prefill values against rows above.

| config | free VRAM | prefill | gen |
|---|---|---|---|
| gemma `-c 32768 -fa 0` | 1,038 MB | 151.7 | 31.9 |
| gemma `-c 32768 -fa 1` | 2,807 MB | 1,264.9 | 33.4 |
| qwen3 `-c 16384 -fa 0` | 1,634 MB | 360.2 | 35.4 |
| qwen3 `-c 16384 -fa 1` | 2,840 MB | 1,881.0 | 44.3 |
| qwen3 `-c 32768 -fa 0` | — | **does not load** (2,668 MiB compute buffer OOMs) | — |

FA deconfound at `-c 16384`, f16 KV both sides, run because the `-fa 0` baseline above
sat at 1,038 MB free, which was then believed low enough for the 8.3× to be a thrashing
artifact. (On the evidence in the floor correction above that belief was probably wrong —
headroom alone has never been shown to thrash here — but the re-run settles it either way:)

| config | free VRAM | EVICTED | prefill | gen |
|---|---|---|---|---|
| gemma `-c 16384 -fa 0` | 2,222 MB | 0–6 ms | 152.8 | 32.0 |
| gemma `-c 16384 -fa 1` | 3,079 MB | 0–6 ms | 1,268.9 | 39.6 |

Confound eliminated; the 8.3× holds.

## Needle recall

Qwen3 at ~25k tokens, depths 10/50/90%. Ceiling effect — both perfect, so this rules out
gross degradation from KV quantization but does **not** establish equivalence.

| model | KV | recall | prefill | gen |
|---|---|---|---|---|
| qwen3 | f16 | 3/3 | 1191 / 1174 / 956 | 31.9 |
| qwen3 | q8_0 | 3/3 | 1176 / 1173 / 940 | 28.0 |

## Deployed footprint

| state | used | free |
|---|---|---|
| nothing loaded | 1,060 MB | 15,244 MB |
| gemma resident | 12,534 MB | 3,770 MB |
| qwen3 resident | 13,746 MB | 2,558 MB |
