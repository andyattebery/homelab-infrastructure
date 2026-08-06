#!/usr/bin/env python3
"""Parser tests against REAL captured tool output, not invented strings.

testdata/ is recorded by capture_fixtures.py on htpc-01. Re-record it with
`python3 run_tests.py --capture` when the images change.

Why this file is separate from test_bench.py: a hand-written fixture cannot catch a wrong
assumption about a format, because the same assumption produces both the parser and the
fixture. Both defects these tests now pin were of exactly that kind —

  1. The filter matched "kv cache" when llama.cpp writes `llama_kv_cache:`. It captured
     nothing, silently, and the fit search that needed KV size came up empty on the host.
  2. Fixing that to match "kv_cache" kept 424 of 2,326 lines, because llama.cpp emits one
     `llama_kv_cache: layer N: ...` line PER LAYER at debug verbosity. The signal was
     present but buried under 408 lines of noise, and the caller truncated to 600 chars.

Run:  python3 test_fixtures.py
"""

import json
import sys
from pathlib import Path

import bench
import rows

T = Path(__file__).resolve().parent / "testdata"


def load(name: str) -> str:
    p = T / name
    assert p.exists(), (f"missing fixture {p} — run `python3 run_tests.py --capture`. "
                        "A missing fixture is a failure, not something to synthesise: "
                        "invented output is what these tests exist to replace.")
    return p.read_text()


BACKENDS = ("rocm", "vulkan")


# ------------------------------------------------- startup log: the KV size line

def test_kv_size_line_is_captured_on_both_backends():
    """THE line. Without it there is no way to know what a given -c costs, and the
    config.json arithmetic is a 4x miss so it cannot be computed."""
    for be in BACKENDS:
        kept = bench.select_startup_lines(load(f"startup.{be}.log"))
        size = [l for l in kept if "llama_kv_cache: size =" in l]
        assert size, f"{be}: KV size line not captured"
        assert any("MiB" in l and "cells" in l and "layers" in l for l in size), \
            f"{be}: KV size line captured but without the size/cells/layers detail"


def test_kv_split_is_visible_and_explains_the_arithmetic_gap():
    """gemma-12b has TWO KV caches: 8 full-attention layers that scale with -c, and 40
    sliding-window layers pinned at 1,536 cells. Only the first grows. That is the whole
    explanation for llm-tuning.md's 4x miss, and it is readable straight off this line."""
    kept = bench.select_startup_lines(load("startup.rocm.log"))
    size = [l.split("llama_kv_cache: ", 1)[1] for l in kept
            if "llama_kv_cache: size =" in l]
    # llama-server builds the context TWICE — once at 0.00s and again at 0.03s for the
    # server slots — so each cache is announced twice. Distinct caches is the fact;
    # emission count is not.
    distinct = sorted(set(size))
    assert len(distinct) == 2, \
        f"expected two distinct KV caches (full + sliding), got {len(distinct)}: {distinct}"
    assert any("4096 cells" in l and "8 layers" in l for l in distinct), \
        "the full-attention cache should hold n_ctx (4096) cells over 8 layers"
    assert any("1536 cells" in l and "40 layers" in l for l in distinct), \
        "the sliding-window cache should be pinned at 1536 cells over 40 layers"


def test_the_two_context_builds_allocate_identically():
    """If the second build differed from the first, the server would be running with a
    KV cache other than the one the log's first announcement describes — and every VRAM
    figure read from that log would be wrong."""
    for be in BACKENDS:
        kept = bench.select_startup_lines(load(f"startup.{be}.log"))
        size = [l.split("llama_kv_cache: ", 1)[1] for l in kept
                if "llama_kv_cache: size =" in l]
        assert len(size) == 4, f"{be}: expected 2 caches x 2 builds, got {len(size)}"
        assert size[:2] == size[2:], f"{be}: the two context builds disagree: {size}"


def test_per_layer_noise_is_rejected():
    """llama.cpp emits one `llama_kv_cache: layer N:` line per layer at debug verbosity.
    Keeping them buried the signal: 424 lines kept, 408 of them noise."""
    for be in BACKENDS:
        kept = bench.select_startup_lines(load(f"startup.{be}.log"))
        noise = [l for l in kept if ": layer " in l.lower()]
        assert not noise, f"{be}: kept {len(noise)} per-layer lines, e.g. {noise[0][:80]}"


def test_the_filter_is_actually_selective():
    """A filter that keeps hundreds of lines is not a filter. If this grows, something is
    matching per-layer chatter again and the KV line is being buried."""
    for be in BACKENDS:
        raw = load(f"startup.{be}.log")
        kept = bench.select_startup_lines(raw)
        assert len(raw.splitlines()) > 2000, "fixture is not the full log"
        assert len(kept) <= 40, (f"{be}: kept {len(kept)} lines from "
                                 f"{len(raw.splitlines())} — the signal is buried again")
        assert len(kept) >= 8, f"{be}: kept only {len(kept)} lines — filter too narrow"


def test_device_selection_is_captured_and_names_the_driver():
    """A failed ICD pin means benchmarking lavapipe, the CPU rasterizer — a spectacular
    false negative for the whole Vulkan arm."""
    rocm = bench.select_startup_lines(load("startup.rocm.log"))
    vulkan = bench.select_startup_lines(load("startup.vulkan.log"))
    assert any("using device ROCm0" in l for l in rocm)
    assert any("using device Vulkan0" in l for l in vulkan)
    assert any("RADV" in l for l in vulkan), \
        "Vulkan startup log does not name RADV — lavapipe or AMDVLK would void the arm"


def test_no_draft_model_in_the_captured_logs():
    """The MTP repo ships a drafter that recent llama.cpp can auto-discover. If one
    loaded, the arm would be measuring speculative decoding as well as the backend."""
    for be in BACKENDS:
        kept = bench.select_startup_lines(load(f"startup.{be}.log"))
        drafts = [l for l in kept if "draft" in l.lower()]
        assert not drafts, f"{be}: a draft model appears to have loaded: {drafts[:2]}"


def test_model_buffer_and_context_size_are_captured():
    """Weights and context are the two halves of the VRAM budget; a row that cannot
    account for its own footprint cannot be compared to another."""
    for be in BACKENDS:
        kept = bench.select_startup_lines(load(f"startup.{be}.log"))
        assert any("model buffer size" in l for l in kept), f"{be}: no model buffer size"
        assert any("llama_context: n_ctx" in l for l in kept), f"{be}: no n_ctx line"


def test_flash_attention_state_is_recorded():
    """-fa is a row-level variable; the log is the only proof it took effect."""
    for be in BACKENDS:
        kept = bench.select_startup_lines(load(f"startup.{be}.log"))
        fa = [l for l in kept if "flash_attn" in l.lower()]
        assert fa and "enabled" in " ".join(fa), f"{be}: flash_attn state not captured"


# ------------------------------------------------- amd-smi

def test_parse_free_vram_against_real_amd_smi():
    got = bench.parse_free_vram(load("amd-smi-metric-mem.rocm.txt"))
    assert got.isdigit(), f"got {got!r} from the real amd-smi output"
    assert 1000 < int(got) < 64000, f"{got} MB is not a plausible free-VRAM figure"


def test_parse_free_vram_agrees_with_host_sysfs():
    """The cross-calibration that keeps every historical amd-smi row interpretable after
    VRAM measurement moved to host sysfs. Measured 1 MB apart when this was decided."""
    smi = int(bench.parse_free_vram(load("amd-smi-metric-mem.rocm.txt")))
    sysfs = load("sysfs-vram.txt")
    used = int([l for l in sysfs.splitlines() if "used=" in l][0].split("=")[1])
    total = int([l for l in sysfs.splitlines() if "total=" in l][0].split("=")[1])
    free_mb = (total - used) // 1048576
    assert abs(smi - free_mb) < 200, \
        f"amd-smi says {smi} MB free, sysfs says {free_mb} MB — the two methods disagree"


def test_sysfs_values_are_bytes_not_megabytes():
    """Units matter: every historical row and the 1.5 GB floor are MB. Without the
    //1048576 conversion the floor check silently never fires."""
    sysfs = load("sysfs-vram.txt")
    total = int([l for l in sysfs.splitlines() if "total=" in l][0].split("=")[1])
    assert total > 10 ** 9, f"total {total} looks like MB, not bytes — conversion assumption"


def test_parse_evicted_against_real_amd_smi_process():
    got = bench.parse_evicted(load("amd-smi-process.rocm.txt"))
    assert got.isdigit(), f"EVICTED came back {got!r} — '?' means the parser broke"


# ------------------------------------------------- completion response

def test_parse_completion_against_a_real_response():
    r = bench.parse_completion(load("completion.json"), 0, "")
    assert r.error is None, r.error
    assert r.prompt_n > 0 and r.prefill > 0 and r.gen > 0
    assert r.build.startswith("b10"), f"build {r.build!r} not read from system_fingerprint"
    assert r.finish in ("stop", "length")


def test_real_response_carries_every_field_the_row_needs():
    """format_row consumes these. A missing timings key would surface as a KeyError five
    minutes into a row rather than here."""
    d = json.loads(load("completion.json"))
    for key in ("prompt_n", "prompt_per_second", "predicted_per_second"):
        assert key in d["timings"], f"timings.{key} missing from the real response"
    assert "completion_tokens" in d["usage"]
    assert "system_fingerprint" in d


def test_a_row_built_from_the_real_response_passes_validation():
    """End to end on captured data: real response -> Run -> summarise -> format_row ->
    parse_row -> check_row, with no GPU and no invented numbers anywhere."""
    r = bench.parse_completion(load("completion.json"), 0, "")
    s = bench.summarise([r])
    line = bench.format_row(s, model="gemma", backend="rocm", ctx=4096, ub="512",
                            fa="1", kv="f16", loaded_free="3000", baseline_free="15656",
                            evicted=bench.parse_evicted(load("amd-smi-process.rocm.txt")),
                            notes="fixture")
    problems = rows.check_row(rows.parse_row(line), expect_backend="rocm",
                              expect_variants=1)
    assert not problems, problems


# ------------------------------------------------- --list-devices

def test_list_devices_names_the_expected_device_per_backend():
    assert any("ROCm0" in l for l in
               bench.select_device_lines(load("list-devices.rocm.txt")))
    assert any("Vulkan0" in l for l in
               bench.select_device_lines(load("list-devices.vulkan.txt")))


def test_list_devices_reports_radv_at_normal_verbosity():
    """This is the cheap RADV check — no --verbose needed, so it costs nothing on a
    timed row."""
    lines = bench.select_device_lines(load("list-devices.vulkan.txt"))
    assert any("RADV" in l for l in lines), lines
    assert not any("llvmpipe" in l.lower() or "lavapipe" in l.lower() for l in lines)


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
