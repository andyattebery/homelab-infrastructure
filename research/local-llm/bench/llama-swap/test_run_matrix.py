#!/usr/bin/env python3
"""Tests for the matrix definition.

The point of these: the row list *is* the experiment. In the shell version it was 30
lines of untestable control flow, so "does the matrix run the right rows with the right
flags" could only be answered by burning two hours of exclusive GPU and reading a log.

Run:  python3 test_run_matrix.py
"""

import subprocess
import sys
from pathlib import Path

import bench
import run_matrix as rm

HERE = Path(__file__).parent


# ------------------------------------------------------- shape of the experiment

def test_both_arms_share_the_same_measurement_rows():
    """The arms must differ ONLY by backend, or the A/B measures two things at once."""
    def strip(rows):
        out = []
        for r in rows:
            r = list(r)
            i = r.index("--backend")
            del r[i:i + 2]
            out.append(r)
        return out
    rocm = strip(rm.plan("rocm"))
    vulkan = strip(rm.plan("vulkan"))
    assert rocm == vulkan[:len(rocm)], "arms diverge on a shared row"


def test_the_arms_are_identical():
    """No arm-specific rows. #21043 claims -ub interacts with the BACKEND, so measuring
    the MoE grid on one arm could not separate a -ub effect from a backend effect."""
    assert rm.plan("rocm") == [r if r[r.index("--backend") + 1] == "rocm" else r
                               for r in rm.plan("rocm")]
    strip = lambda rows_: [[x for x in r if x not in ("rocm", "vulkan")] for r in rows_]
    assert strip(rm.plan("rocm")) == strip(rm.plan("vulkan"))


def _moe_cells(backend="vulkan"):
    return [(r[r.index("--ctx") + 1], r[r.index("--ub") + 1] if "--ub" in r else "512")
            for r in rm.plan(backend) if r[r.index("--model") + 1] == "gemma-moe"]


def test_the_moe_has_a_context_matched_row_for_the_model_comparison():
    """gemma and qwen3.5 only ever run at 65536, and ldr-tuning-methodology.md:41 holds
    -c 65536 constant. A MoE measured only at 49152 would make the model comparison —
    step 3's actual question — a comparison of contexts as much as of models."""
    matched = str(rm.MOE_MATCHED_CTX)
    assert (matched, "512") in _moe_cells()
    dense = {r[r.index("--ctx") + 1] for r in rm.plan("vulkan")
             if r[r.index("--model") + 1] in ("gemma", "qwen3.5")
             and "fa sweep" not in r}
    assert dense == {matched}, f"the dense rows are not all at {matched}: {dense}"


def test_the_ub_sweep_is_single_variable_and_has_headroom():
    """-ub is a property of routing and ubatch, not of -c, so the sweep is valid at any
    context — and there is no reason to pay for it in headroom. MEASURED free VRAM at
    -ub 2048: 676/815 MB at -c 65536 against 1,060/1,199 at -c 49152 (rocm/vulkan)."""
    sweep = [(c, ub) for c, ub in _moe_cells() if c == str(rm.MOE_UB_CTX)]
    assert [ub for _, ub in sweep] == ["512", "1024", "2048"]
    assert len({c for c, _ in sweep}) == 1, "the -ub sweep varies -c as well"


def test_the_c_effect_is_measurable_at_fixed_ub():
    """(65536, 512) vs (49152, 512) differ only in -c, so the context cost is free."""
    cells = _moe_cells()
    assert (str(rm.MOE_MATCHED_CTX), "512") in cells
    assert (str(rm.MOE_UB_CTX), "512") in cells


def test_no_moe_cell_is_below_a_gigabyte():
    """MEASURED 2026-08-01, both backends. -ub 2048 at -c 65536 was 676/815 MB — the
    tightest cell anywhere, below the ~1 GB the docs cite, and on Vulkan EVICTED reads
    n/a so there is no eviction signal to defend it with. It is deliberately not planned."""
    measured = {("65536", "512"): 1468, ("65536", "1024"): 1204, ("65536", "2048"): 676,
                ("49152", "512"): 1804, ("49152", "1024"): 1556, ("49152", "2048"): 1060}
    for cell in _moe_cells():
        assert cell in measured, f"MoE cell {cell} is planned but was never probed"
        assert measured[cell] >= 1000, \
            f"{cell} measured {measured[cell]} MB on rocm — under the ~1 GB figure"


def test_the_two_floors_are_not_conflated():
    """The bug this encodes: a row measuring 1,199 MB free was refused as 'thrashing'
    against a 1,500 MB figure that results.md:86 describes as a round-number deployment
    margin. The only measured thrashing event was at 264 MB."""
    assert bench.BENCH_FLOOR_MB < bench.VRAM_FLOOR_MB
    assert bench.BENCH_FLOOR_MB > 264, "the benchmark floor must clear the measured event"
    assert bench.BENCH_FLOOR_MB < 1468, \
        "1,468 MB was measured throughput-neutral; a floor above it refuses valid rows"


def test_row_counts():
    """Both arms identical: 2 dense throughput + 4 MoE grid + 2 fa sweep."""
    assert len(rm.plan("rocm")) == 2 + len(rm.MOE_GRID) + 2
    assert len(rm.plan("rocm")) == len(rm.plan("vulkan"))


def test_every_row_names_a_known_model():
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            model = row[row.index("--model") + 1]
            assert model in bench.MODELS, f"unknown model {model}"


def test_every_row_carries_the_backend_label():
    """A row without --backend is indistinguishable from the other arm in results.md."""
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            assert row[row.index("--backend") + 1] == backend


def test_throughput_rows_use_five_variants():
    """Vulkan prefill variance is reported at 5,600-7,500 where ROCm holds under 1%;
    three variants cannot resolve a 10% decision."""
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            if "fa sweep" in row:
                continue
            assert row[row.index("--variants") + 1] == "5"


def test_moe_contexts_are_both_measured_values():
    """Two contexts, each for a stated reason, and no third one creeping in. 65536 is the
    matched context (and was measured at 1,468/1,605 MB free, loading fine — it never
    OOMed); 49152 is where the -ub sweep gets its headroom."""
    allowed = {str(ctx) for ctx, _ in rm.MOE_GRID}
    assert allowed == {str(rm.MOE_MATCHED_CTX), str(rm.MOE_UB_CTX)}
    assert rm.MOE_MATCHED_CTX > rm.MOE_UB_CTX
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            if row[row.index("--model") + 1] == "gemma-moe":
                assert row[row.index("--ctx") + 1] in allowed


def test_moe_prompt_size_matches_the_dense_models():
    """Holding prompt size constant across models removes a difference rather than
    adding one, and keeps prefill on the same part of the throughput curve."""
    for row in rm.plan("rocm"):
        if row[row.index("--model") + 1] == "gemma-moe":
            assert row[row.index("--lines") + 1] == "1200"


def test_fa_sweep_is_a_matched_pair_at_the_same_context():
    """Comparing -fa 0 against -fa 1 at different contexts changes two variables."""
    fa = [r for r in rm.plan("rocm") if "fa sweep" in r]
    assert len(fa) == 2
    assert {r[r.index("--fa") + 1] for r in fa} == {"0", "1"}
    assert len({r[r.index("--ctx") + 1] for r in fa}) == 1


def test_no_row_combines_quantised_kv_with_fa_0():
    """llama.cpp rejects that combination outright; bench.py refuses it too."""
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            if "--kv" in row and "--fa" in row:
                assert not (row[row.index("--fa") + 1] == "0")


# ------------------------------------------------------- container wiring

def test_bench_container_is_isolated_from_the_network():
    """--network none is what makes 'Onyx or LDR must be stopped' structural rather
    than procedural: nothing can reach the container to trigger a model load."""
    assert "none" in rm.container_argv("rocm")


def test_only_vulkan_gets_the_radv_icd_pin():
    v = " ".join(rm.container_argv("vulkan"))
    r = " ".join(rm.container_argv("rocm"))
    assert rm.RADV_ICD in v, "RADV not forced — auto-selection could pick lavapipe (CPU)"
    assert "VK_ICD" not in r, "ROCm arm should be byte-identical to the deployed config"


def test_container_never_uses_the_service_name():
    """A container called llama-swap would collide with the systemd unit on restart."""
    assert rm.CONTAINER != rm.SERVICE
    assert rm.CONTAINER in rm.container_argv("rocm")


def test_gpu_devices_and_model_mount_present():
    argv = rm.container_argv("rocm")
    assert "/dev/kfd" in argv and "/dev/dri" in argv
    assert any(a.startswith(rm.MODELS_DIR) for a in argv)


def test_graphics_queue_container_differs_by_exactly_one_env_var():
    """The GGML_VK_ALLOW_GRAPHICS_QUEUE row needs its own container, because presence of
    the variable IS the switch. If that container differed in any other way, the row
    would measure two changes and be uninterpretable."""
    base = rm.container_argv("vulkan")
    gfx = rm.container_argv("vulkan", {"GGML_VK_ALLOW_GRAPHICS_QUEUE": "1"})
    assert "GGML_VK_ALLOW_GRAPHICS_QUEUE=1" in gfx
    # Removing the added `-e VAR=1` pair must give back the base container exactly.
    i = gfx.index("GGML_VK_ALLOW_GRAPHICS_QUEUE=1")
    assert gfx[i - 1] == "-e", "env var not introduced by a -e flag"
    assert gfx[:i - 1] + gfx[i + 1:] == base, \
        "the graphics-queue container differs from the base by more than one -e"


def test_container_argv_is_identical_between_arms_apart_from_the_image_and_icd():
    """The container shape is a controlled variable. Anything differing beyond the image
    tag and the RADV pin would be a second change riding along with the backend."""
    r = [a for a in rm.container_argv("rocm") if a != rm.IMAGE["rocm"]]
    v = [a for a in rm.container_argv("vulkan") if a != rm.IMAGE["vulkan"]]
    v = [a for a in v if not a.startswith("VK_ICD_FILENAMES") and a != "-e"]
    assert r == v, f"container shapes diverge:\n  rocm={r}\n  vulkan={v}"


def test_smoke_shrinks_size_without_changing_anything_else():
    """--smoke must exercise the same FLAGS as the real run, only smaller. If it dropped
    or added a flag it would stop being a rehearsal for the 2h run."""
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            small = rm.smoke(row)
            def flags(a):
                return {x for x in a if x.startswith("--") or
                        (x.startswith("-") and not x[1:].isdigit())}
            added = flags(small) - flags(row)
            assert added <= {"--max-tokens", "--lines", "--variants"}, \
                f"smoke added unexpected flags {added}"
            assert flags(row) - flags(small) <= {"--expect-prompt-n"}, \
                "smoke dropped a flag the real row carries"
            assert small[small.index("--ctx") + 1] == rm.SMOKE["ctx"]
            assert small[small.index("--variants") + 1] == rm.SMOKE["variants"]


# The corpus measures 21,828 tokens at 1,200 lines. Derived, not guessed, and used to
# check that a row's prompt can physically fit the context it asks for.
TOKENS_PER_LINE = bench.EXPECTED_PROMPT_N[("gemma", bench.DEFAULT_LINES)] / bench.DEFAULT_LINES


def test_every_planned_row_fits_its_context():
    """REGRESSION. The -fa sweep ran at -c 16384 with the default 1200 lines — ~21,828
    tokens into a 16,384-token context. All four fa rows would have died with HTTP 400
    roughly 40 minutes into the unattended matrix, losing the entire -fa question, and
    --no-context-shift means it fails rather than silently truncating.

    80% leaves room for the generation and the KV overhead.
    """
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            ctx = int(row[row.index("--ctx") + 1])
            lines = int(row[row.index("--lines") + 1]) if "--lines" in row \
                else bench.DEFAULT_LINES
            tokens = lines * TOKENS_PER_LINE
            assert tokens < ctx * 0.8, (
                f"{backend} {row[row.index('--model') + 1]} at -c {ctx}: {lines} lines is "
                f"~{tokens:.0f} tokens and will not fit")


def test_the_fa_sweep_is_like_for_like():
    """-fa 0 vs -fa 1 is only a comparison if everything else matches. Different prompt
    sizes between the two would make the pair meaningless."""
    fa = [r for r in rm.plan("rocm") if "fa sweep" in r]
    assert len(fa) == 2
    for flag in ("--ctx", "--lines", "--variants", "--model"):
        assert len({r[r.index(flag) + 1] for r in fa}) == 1, f"fa rows differ in {flag}"


def test_every_smoke_row_sets_lines_so_the_prompt_fits_the_shrunken_ctx():
    """REGRESSION. The first smoke run died on every gemma row with HTTP 400: 'request
    (21835 tokens) exceeds the available context size (4096 tokens)'.

    Rows that omit --lines inherit bench.py's default of 1200 (~21,835 tokens). Shrinking
    --ctx to 4096 without also setting --lines guarantees an overflow. --lines is the one
    flag that MUST be added when absent, not the one that may be skipped.
    """
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            small = rm.smoke(row)
            assert "--lines" in small, f"smoke row has no --lines: {small}"
            assert small[small.index("--lines") + 1] == rm.SMOKE["lines"]
            # The real constraint, stated directly rather than trusted: ~18.5 tokens per
            # line must fit inside the shrunken context with room for generation.
            lines = int(small[small.index("--lines") + 1])
            ctx = int(small[small.index("--ctx") + 1])
            assert lines * 19 < ctx * 0.8, \
                f"{lines} lines (~{lines * 19} tokens) will not fit -c {ctx}"


def test_no_config_is_single_arm():
    """Every config now runs on both arms, so check_arms_comparable needs no exemptions.
    A non-empty set here means an accidental asymmetry — which is what the checker is
    for, and it would be excused rather than reported."""
    assert rm.single_arm_configs() == set()
    assert rm.single_arm_configs(rm.smoke) == set()


def test_the_exemption_mechanism_still_works_if_an_asymmetry_is_ever_added():
    """The exemption path is currently unused. Keep it proven, so re-introducing a
    deliberate single-arm row does not require rediscovering how it behaves."""
    seen = {}
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend) + ([["--model", "x", "--ctx", "1"]]
                                       if backend == "vulkan" else []):
            seen.setdefault(rm.config_key_of(row), set()).add(backend)
    single = {k for k, arms in seen.items() if len(arms) == 1}
    assert single == {("x", "1", "1", "512")}


def test_config_key_of_matches_what_the_row_actually_reports():
    """config_key_of has to reproduce bench.py's defaults exactly — -fa 1 and an unset
    -ub reported as 512 — or every derived key misses and the exemption never applies."""
    row = ["--model", "gemma", "--ctx", "65536"]
    assert rm.config_key_of(row) == ("gemma", "65536", "1", "512")
    row = ["--model", "gemma-moe", "--ctx", "49152", "--fa", "0", "--ub", "2048"]
    assert rm.config_key_of(row) == ("gemma-moe", "49152", "0", "2048")


def test_smoke_drops_the_anchor_because_it_is_measured_at_a_different_size():
    """EXPECTED_PROMPT_N is recorded at --lines 1200. At --lines 50 it would fire on
    every row, so a smoke run would fail for a reason that is not a defect."""
    row = rm.with_anchor(rm.plan("rocm")[0])
    assert "--expect-prompt-n" in row
    assert "--expect-prompt-n" not in rm.smoke(row)


def test_anchor_is_attached_only_where_it_has_been_measured():
    """bench.EXPECTED_PROMPT_N holds gemma only. Attaching a guessed value to qwen3.5 or
    the MoE would assert a fiction and fail every row."""
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            model = row[row.index("--model") + 1]
            lines = int(row[row.index("--lines") + 1]) if "--lines" in row \
                else bench.DEFAULT_LINES
            anchored = "--expect-prompt-n" in rm.with_anchor(row)
            assert anchored == ((model, lines) in bench.EXPECTED_PROMPT_N), \
                f"{model} at --lines {lines}: anchored={anchored}"


def test_both_images_are_the_same_llamacpp_build():
    """An unpinned comparison measures backend AND llama.cpp version while reporting
    backend. Both tags must carry the same bNNNNN."""
    build = {k: v.rsplit("-b", 1)[1] for k, v in rm.IMAGE.items()}
    assert build["rocm"] == build["vulkan"], f"build mismatch: {build}"


# ------------------------------------------------------- end to end

def test_no_timed_row_uses_verbose():
    """--verbose logs during generation, i.e. overhead on the number being measured. It
    would cancel between arms but would make the row incomparable to every other row."""
    for backend in ("rocm", "vulkan"):
        for row in rm.plan(backend):
            assert "--verbose" not in row, f"timed row carries --verbose: {row}"


def test_probes_are_load_only_and_verbose():
    """--load-only so a probe costs ~50s instead of ~4.5 min, --verbose because the
    device banner and the KV size lines only exist at debug verbosity. Count is derived
    from plan(), so adding a row adds its probe automatically."""
    for backend in ("rocm", "vulkan"):
        pr = rm.probes(backend)
        assert pr, f"{backend} has no probes"
        assert len(pr) == len({_fit_key(r) for r in rm.plan(backend)})
        for row in pr:
            assert "--load-only" in row and "--verbose" in row


def test_only_filters_by_label_but_never_skips_a_probe():
    """--only is for recovery: re-run the fa sweep without re-running everything. Probes
    are exempt because they are what prove the model still loads at the context the rows
    assume — skipping them would let a row start against a model that will not fit."""
    d = rm.Driver(dry=True, only="fa sweep")
    fa = [r for r in rm.plan("rocm") if "fa sweep" in r]
    other = [r for r in rm.plan("rocm") if "backend A/B" in r]
    assert all(d.wanted(r) for r in fa)
    assert not any(d.wanted(r) for r in other)
    assert all(d.wanted(pr) for pr in rm.probes("rocm")), "a probe was filtered out"


def test_no_filter_runs_everything():
    d = rm.Driver(dry=True)
    assert all(d.wanted(r) for r in rm.plan("rocm") + rm.probes("rocm"))


def _fit_key(argv):
    return (argv[argv.index("--model") + 1],
            argv[argv.index("--ctx") + 1],
            argv[argv.index("--ub") + 1] if "--ub" in argv else "",
            argv[argv.index("--fa") + 1] if "--fa" in argv else "1")


def test_every_timed_row_has_a_matching_fit_probe():
    """REGRESSION. Probes were hand-listed and covered only (model, ctx), which left the
    Vulkan `MoE -ub 2048` row unprobed — the row most likely to fail, since -ub 2048 cost
    ~950 MB on the dense 12B and the MoE has only ~1,942 MB free at -ub 512.

    --probes-only answers what --smoke cannot: does each config fit at the size the timed
    rows assume, on BOTH backends? The smoke ran everything at -c 4096.
    """
    for backend in ("rocm", "vulkan"):
        probed = {_fit_key(pr) for pr in rm.probes(backend)}
        for row in rm.plan(backend):
            assert _fit_key(row) in probed, \
                f"{backend}: {_fit_key(row)} is run by a timed row but never probed"


def test_probes_are_deduplicated():
    """The two fa-sweep rows differ only by -fa, and both gemma rows share a context.
    Probing every row blindly would add minutes for no information."""
    for backend in ("rocm", "vulkan"):
        keys = [_fit_key(pr) for pr in rm.probes(backend)]
        assert len(keys) == len(set(keys)), f"{backend}: duplicate probes {keys}"
        assert len(rm.probes(backend)) < len(rm.plan(backend)) + 1


def test_probes_use_contexts_that_a_timed_row_actually_asks_for():
    """A probe at a context no row uses proves nothing about whether the run will fit.
    (Not 'ctx >= 49152' — the fa sweep legitimately runs at 16384, which is a real
    context, just a smaller one.)"""
    for backend in ("rocm", "vulkan"):
        planned = {row[row.index("--ctx") + 1] for row in rm.plan(backend)}
        for pr in rm.probes(backend):
            ctx = pr[pr.index("--ctx") + 1]
            assert ctx in planned, f"probe at -c {ctx} matches no timed row"
            assert ctx != rm.SMOKE["ctx"], "probe is at the smoke context, not a real one"


def test_a_row_below_the_benchmark_floor_is_refused():
    """Refused only near where thrashing was actually measured (264 MB), not at the
    deployment margin."""
    d = rm.Driver(dry=True)
    row = [r for r in rm.plan("vulkan") if "--ub" in r][0]
    d.fit[d.fit_key(row)] = 300
    assert d.fits(row), "a config near the measured thrashing point was allowed"


def test_a_row_between_the_two_floors_runs_but_is_flagged():
    """THE regression. vulkan gemma-moe -ub 2048 probed at 1,199 MB and was refused as
    'thrashing' — but 1,468 MB was measured throughput-neutral and the only observed
    thrashing was at 264 MB. It must run, and carry a caveat."""
    d = rm.Driver(dry=True)
    row = [r for r in rm.plan("vulkan") if "--ub" in r][0]
    d.fit[d.fit_key(row)] = 1199
    assert d.fits(row) == "", "a valid measurement was refused"
    assert d.tight(row), "a row below the deployment margin was not flagged"


def test_a_row_whose_probe_measured_above_the_floor_runs():
    d = rm.Driver(dry=True)
    row = rm.plan("rocm")[0]
    d.fit[d.fit_key(row)] = 3639
    assert d.fits(row) == ""


def test_an_unprobed_row_is_not_silently_refused():
    """Absence of a measurement is not evidence of a bad fit. An unprobed config runs and
    reports its own free VRAM in the row, where check_row sees it."""
    d = rm.Driver(dry=True)
    assert d.fits(rm.plan("rocm")[0]) == ""


def test_the_fit_gate_keys_on_backend_too():
    """The same config can fit on one backend and not the other — vulkan measured 1,942 MB
    free for the MoE where rocm measured 1,804. A key without the backend would let one
    arm's measurement veto the other's row."""
    d = rm.Driver(dry=True)
    vulkan_row = [r for r in rm.plan("vulkan") if "--ub" in r][0]
    d.fit[d.fit_key(vulkan_row)] = 1199
    rocm_moe = [r for r in rm.plan("rocm") if "gemma-moe" in r][0]
    assert d.fits(rocm_moe) == "", "a vulkan measurement blocked a rocm row"


GOOD_ROW = ("| gemma | rocm | b10200-x | 65536 | 512 | 1 | f16 | 21828 | 1151.2 | "
            "1120.0-1180.0 | 40.0 | 39.0-41.0 | 3000 MB | 15656 MB | 0 | 5 | x |")
FIRST_ROW_ARGV = ["--backend", "rocm", "--model", "gemma", "--ctx", "65536",
                  "--variants", "5"]


def test_an_unresolvable_first_row_stops_the_session():
    """The first row is the primary dense comparison. If its own 5-variant spread already
    exceeds the 10% decision threshold, the arms cannot be separated by a gap smaller
    than the noise inside one arm — so the remaining ~60 minutes cannot produce a
    decision and should not be spent."""
    d = rm.Driver()
    d.record(GOOD_ROW.replace("39.0-41.0", "34.0-44.0"), FIRST_ROW_ARGV)
    assert d.abort and "cannot produce a decision" in d.abort


def test_a_resolvable_first_row_lets_the_session_continue():
    d = rm.Driver()
    d.record(GOOD_ROW, FIRST_ROW_ARGV)
    assert not d.abort


def test_the_resolvability_gate_only_judges_the_first_row():
    """Later rows have their own spreads and some are expected to be noisier; the gate
    exists to stop early, not to police every row."""
    d = rm.Driver()
    d.record(GOOD_ROW, FIRST_ROW_ARGV)
    d.record(GOOD_ROW.replace("39.0-41.0", "20.0-60.0"), FIRST_ROW_ARGV)
    assert not d.abort


def test_the_gate_is_inert_in_smoke_mode():
    """--smoke runs --variants 1, so min == max == median and the spread is meaningless.
    Judging it would either always pass or always fire."""
    d = rm.Driver(smoke_mode=True)
    d.record(GOOD_ROW.replace("39.0-41.0", "34.0-44.0"), FIRST_ROW_ARGV)
    assert not d.abort


def test_variant_timeout_bounds_the_session():
    """The old 1800 s per variant put ONE row's worst case at 2.5 h and the matrix at
    ~32 h — an unattended job with no upper bound at all.

    The ceiling is set against the SLOWEST variant actually measured, not the typical
    one: gemma -fa 0 at -c 16384 / 540 lines ran ~90 s per variant (prefill 9,823 tokens
    at ~171 tok/s, then 1,024 tokens at 31.4 tok/s). Everything else is ~45 s.
    """
    slowest_measured_s = 9823 / 171.0 + 1024 / 31.4        # ~90 s, the -fa 0 row
    assert bench.VARIANT_TIMEOUT_S > 2.5 * slowest_measured_s, \
        "too tight — would fire on the -fa 0 row, which is slow but working"
    assert bench.VARIANT_TIMEOUT_S < 5 * slowest_measured_s, "too loose to bound anything"
    # Worst case assumes EVERY variant times out, which is pathological; the point is
    # only that a finite bound exists and is not measured in days.
    worst_case_h = (sum(len(rm.plan(b)) for b in ("rocm", "vulkan")) + 2) * \
        5 * bench.VARIANT_TIMEOUT_S / 3600
    assert worst_case_h < 8, f"worst case is still {worst_case_h:.1f} h"


def test_probes_carry_no_prompt_anchor():
    """A --load-only probe runs no completion, and carries no --lines, so an anchor would
    be attached for a size it is not using — it appeared in the log as
    `--load-only ... --expect-prompt-n 21828` on a row that never generates."""
    for backend in ("rocm", "vulkan"):
        for pr in rm.probes(backend):
            assert "--expect-prompt-n" not in rm.with_anchor(pr)


def test_a_refused_row_is_a_finding_not_a_session_failure():
    """current-work.md's decision criteria say outright that a config not fitting is an
    answer ('MoE will not fit at a usable -c ... record the non-fit'), so a genuine
    non-fit must be reported without failing the run."""
    d = rm.Driver(dry=True)
    row = [r for r in rm.plan("rocm")
           if r[r.index("--model") + 1] == "gemma-moe" and "--ub" in r][0]
    d.fit[d.fit_key(row)] = 300        # near the 264 MB measured thrashing point
    d.row(row)
    assert d.refused, "a non-fitting row was not recorded"
    assert not d.row_problems, "a measured non-fit must not fail the session"


ROWS_MD = ("| " + " | ".join(bench.ROW_COLUMNS) + " |\n"
           "|" + "---|" * len(bench.ROW_COLUMNS) + "\n"
           "| gemma | rocm | b10200-x | 65536 | 512 | 1 | f16 | 21828 | 1151.2 | "
           "1120.0-1180.0 | 40.0 | 39.0-41.0 | 3000 MB | 15656 MB | 0 | 5 | x |\n")


def test_status_reports_progress_of_a_live_run():
    """The five things worth asking of a 92-minute unattended job."""
    log = ("=== ROW: --backend rocm --model gemma ===\n"
           "=== ROW: --backend rocm --model qwen3.5 ===\n")
    out = status_lines(log, ROWS_MD, "12345", 18)
    assert "RUNNING (pid 12345)" in out
    assert "1/18 recorded" in out
    assert "qwen3.5" in out, "should name the row in flight, not an earlier one"


def test_status_counts_only_data_rows_not_the_header():
    """The header starts with '| model |' and would otherwise inflate the count."""
    out = status_lines("", ROWS_MD, "1", 18)
    assert "1/18 recorded" in out


def test_status_surfaces_problems_and_refusals_separately():
    """A refusal is a measured non-fit — a result. A problem is not. Conflating them
    would either hide a defect or cry wolf."""
    log = ("!! ROW FAILED (continuing), rc=3\n"
           "=== REFUSED (does not fit): --model gemma-moe ===\n")
    out = status_lines(log, ROWS_MD, "1", 18)
    assert "refused    : 1" in out
    assert "problems   : 1" in out
    assert "ROW FAILED" in out


def test_status_reports_a_finished_run_as_not_running():
    out = status_lines("=== DONE — 18 row(s), all checks passed ===\n", ROWS_MD, "", 18)
    assert "not running" in out
    assert "finished" in out


def status_lines(log, rows_md, pid, expected):
    return rm.status_report(log, rows_md, pid, expected)


def test_dry_run_prints_the_whole_matrix_and_touches_nothing():
    r = subprocess.run([sys.executable, str(HERE / "run_matrix.py"), "--dry-run"],
                       capture_output=True, text=True, cwd=HERE)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "podman run" in out and "systemctl stop" in out
    # DERIVED from plan()/probes(), never written down. The two ad-hoc rows main() adds —
    # the graphics-queue probe and the A-B-A repeat — are the only literal. A hardcoded
    # total here is exactly what let this file assert 19 while test_integration.py
    # asserted 13, both "passing", contradicting each other.
    expected = sum(len(rm.plan(b)) + len(rm.probes(b)) for b in ("rocm", "vulkan")) + 2
    assert out.count("bench.py") == expected, \
        f"expected {expected} invocations, saw {out.count('bench.py')}"


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
