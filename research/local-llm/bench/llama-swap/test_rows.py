#!/usr/bin/env python3
"""Tests for row parsing and validation — the "is the output CORRECT" half.

Every check here corresponds to a way a row has actually been wrong or could be wrong
without anyone noticing: an unset backend column making two arms indistinguishable, a
build mismatch silently comparing two llama.cpp versions, variants discarded by the cache
gate leaving n=3 reported as though 5 had been requested.

Run:  python3 test_rows.py
"""

import sys

import bench
import rows

# A real row, in the exact shape bench.format_row emits.
OK = ("| gemma | rocm | b10200-5f55650a7 | 65536 | 512 | 1 | f16 | 21828 | 1151.2 | "
      "1120.0-1180.0 | 40.1 | 39.0-41.0 | 3000 MB | 15656 MB | 420 | 5 | backend A/B |")


def row(**over):
    d = rows.parse_row(OK)
    d.update(over)
    return d


# --------------------------------------------------------------- extraction

def test_extract_finds_the_row_among_the_noise():
    """bench.py prints a config line, device lines, a startup log, the header and the
    separator before the row. Only one line is the result."""
    out = ("### config: model=gemma ctx=65536\n"
           "--- device selected ---\n"
           "ROCm0: AMD Radeon RX 9070 XT\n"
           "| " + " | ".join(bench.ROW_COLUMNS) + " |\n"
           "|" + "---|" * len(bench.ROW_COLUMNS) + "\n"
           + OK + "\n")
    assert rows.extract_row(out) == OK


def test_extract_ignores_the_header_row():
    """The header starts with '| model |' — close enough to a data row to be picked up by
    a naive startswith check."""
    out = "| " + " | ".join(bench.ROW_COLUMNS) + " |\n"
    assert rows.extract_row(out) is None


def test_extract_returns_none_when_the_run_produced_nothing():
    assert rows.extract_row("FAILED: server did not become healthy.\n") is None


def test_every_model_name_is_extractable():
    """Extraction keys on the first cell being a known model. A model added to
    bench.MODELS but not recognised here would silently produce 'no result row'."""
    for name in bench.MODELS:
        line = OK.replace("| gemma |", f"| {name} |", 1)
        assert rows.extract_row(line) == line, f"{name} not extractable"


# --------------------------------------------------------------- parsing

def test_parse_maps_every_column():
    d = rows.parse_row(OK)
    assert set(d) == set(bench.ROW_COLUMNS)
    assert d["model"] == "gemma" and d["backend"] == "rocm" and d["n"] == "5"
    assert d["prompt_n"] == "21828"


def test_parse_rejects_a_wrong_column_count():
    """A row that does not line up with the header corrupts results.md silently, so this
    must raise rather than return a shifted dict."""
    try:
        rows.parse_row("| gemma | rocm | b1 |")
    except ValueError as e:
        assert "expected" in str(e)
    else:
        assert False, "accepted a row with the wrong number of columns"


def test_parse_round_trips_what_format_row_emits():
    """Guards against ROW_COLUMNS and format_row drifting apart."""
    s = bench.summarise([bench.Run(v=0, prompt_n=21828, prefill=1.0, gen=2.0,
                                   finish="stop", completion_tokens=1, build="b1")])
    line = bench.format_row(s, model="gemma", backend="rocm", ctx=65536, ub="512",
                            fa="1", kv="f16", loaded_free="3000", baseline_free="15656",
                            evicted="420", notes="x")
    assert set(rows.parse_row(line)) == set(bench.ROW_COLUMNS)


# --------------------------------------------------------------- per-row checks

def test_a_good_row_has_no_problems():
    assert rows.check_row(row(), expect_backend="rocm", expect_variants=5) == []


def test_unset_backend_is_a_problem():
    """Without it the two arms are indistinguishable in results.md — the entire point of
    the experiment. bench.py writes '?' when --backend is omitted."""
    for bad in ("?", "", "-"):
        p = rows.check_row(row(backend=bad), expect_backend="rocm", expect_variants=5)
        assert any("backend is unset" in x for x in p), f"{bad!r} not caught"


def test_backend_mismatch_is_a_problem():
    p = rows.check_row(row(backend="vulkan"), expect_backend="rocm", expect_variants=5)
    assert any("but this row ran on" in x for x in p)


def test_discarded_variants_are_a_problem():
    """n < --variants means the cache gate threw runs away. README.md calls that the one
    condition that invalidates a row, and the median alone would not reveal it."""
    p = rows.check_row(row(n="3"), expect_backend="rocm", expect_variants=5)
    assert any("cache gate discarded" in x for x in p)


def test_missing_build_is_a_problem():
    p = rows.check_row(row(build="?"), expect_backend="rocm", expect_variants=5)
    assert any("system_fingerprint" in x for x in p)


def test_non_numeric_vram_is_a_problem():
    for col in ("free", "baseline free"):
        p = rows.check_row(row(**{col: "? MB"}), expect_backend="rocm", expect_variants=5)
        assert any(col in x for x in p), f"{col} not validated"


def test_vram_with_and_without_the_MB_suffix_both_parse():
    assert rows.check_row(row(free="3000"), expect_backend="rocm",
                          expect_variants=5) == []


def test_evicted_must_be_na_on_vulkan_and_numeric_on_rocm():
    """amd-smi ships in the ROCm image but not the Vulkan one. 'n/a' means NOT MEASURED,
    never zero; '?' on rocm means the parser broke, which is a defect, not a value."""
    assert rows.check_row(row(backend="vulkan", EVICTED="n/a"),
                          expect_backend="vulkan", expect_variants=5) == []
    p = rows.check_row(row(backend="vulkan", EVICTED="420"),
                       expect_backend="vulkan", expect_variants=5)
    assert any("expected 'n/a'" in x for x in p)
    p = rows.check_row(row(EVICTED="?"), expect_backend="rocm", expect_variants=5)
    assert any("amd-smi parse failed" in x for x in p)


def test_zero_prompt_n_is_a_problem():
    p = rows.check_row(row(prompt_n="0"), expect_backend="rocm", expect_variants=5)
    assert any("prompt_n" in x for x in p)


# --------------------------------------------------------------- cross-arm checks

def pair(**over):
    """One config measured on both arms."""
    a = row()
    b = row(backend="vulkan", EVICTED="n/a")
    b.update(over)
    return [a, b]


def test_matched_arms_have_no_problems():
    assert rows.check_arms_comparable(pair()) == []


def test_a_build_mismatch_between_arms_is_caught():
    """The floating :rocm and :vulkan tags drift independently. An unpinned comparison
    measures backend AND llama.cpp version while reporting backend."""
    p = rows.check_arms_comparable(pair(build="b10156-91f8c9c5f"))
    assert any("multiple llama.cpp builds" in x for x in p)


def test_gen_spread_pct_matches_the_decision_criterion():
    """The number the whole backend decision rests on: a >=10% gap between arms is only a
    result if the ranges do not overlap, so a row's own spread has to be smaller than the
    gap being claimed."""
    assert abs(rows.gen_spread_pct(row(**{"gen med": "40.0",
                                          "gen min-max": "38.0-42.0"})) - 10.0) < 1e-9
    assert rows.gen_spread_pct(row(**{"gen med": "40.0",
                                      "gen min-max": "40.0-40.0"})) == 0.0


def test_gen_spread_pct_is_none_when_unparseable():
    """A dry-run or malformed row must not read as spread 0 — that would silently pass
    the resolvability gate."""
    assert rows.gen_spread_pct(row(**{"gen min-max": "n/a"})) is None
    assert rows.gen_spread_pct(row(**{"gen med": "0.0"})) is None


def test_a_deliberate_single_arm_config_is_not_flagged():
    """REGRESSION from the first smoke run: the Vulkan-only `-ub 2048` MoE row is in the
    design, and the checker reported it as a defect on every run. A checker that cries
    wolf every time gets ignored, which is worse than not having one."""
    a = row()
    b = row(backend="vulkan", EVICTED="n/a")
    only_vulkan = row(backend="vulkan", EVICTED="n/a", **{"-ub": "2048"})
    key = rows.config_key(only_vulkan)
    assert rows.check_arms_comparable([a, b, only_vulkan], single_arm_ok={key}) == []
    # ...and without the exemption it IS reported, so the check still has teeth.
    assert rows.check_arms_comparable([a, b, only_vulkan]) != []


def test_a_config_missing_from_one_arm_is_caught():
    a = row()
    b = row(backend="vulkan", EVICTED="n/a")
    extra = row(backend="vulkan", EVICTED="n/a", **{"-c": "16384"})
    p = rows.check_arms_comparable([a, b, extra])
    assert any("but not" in x for x in p)


def test_different_prompt_n_between_arms_is_caught():
    """prompt_n is a property of (model, prompt size, tokenizer) and never of the
    backend. A difference means the arms ran different prompts, so their throughput
    numbers are not comparable. This is the corpus check during a smoke run, where the
    absolute anchors do not apply."""
    p = rows.check_arms_comparable(pair(prompt_n="19000"))
    assert any("did not run the same prompt" in x for x in p)


def test_single_arm_is_not_flagged_as_mismatched():
    """A rocm-only run (--smoke on one arm, or an aborted vulkan arm) is incomplete, not
    self-contradictory. It must not produce spurious problems."""
    assert rows.check_arms_comparable([row()]) == []


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
