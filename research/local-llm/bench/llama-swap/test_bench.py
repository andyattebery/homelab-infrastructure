#!/usr/bin/env python3
"""Unit tests for the parts of bench.py that decide whether a measurement is real.

Run:  python3 -m pytest test_bench.py -q      (or: python3 test_bench.py)

These exist because the validity logic used to live inside a shell string, where nothing
could test it. It shipped inverted — see test_gate_survives_cache_hit_majority, which is
a regression test against data actually observed on htpc-01 on 2026-08-01.
"""

import json
import subprocess
import sys
from pathlib import Path

import bench
import prompts

HERE = Path(__file__).parent


# --------------------------------------------------------------- cache gate

def mk(v, prompt_n, prefill=1000.0, gen=40.0):
    return bench.Run(v=v, prompt_n=prompt_n, prefill=prefill, gen=gen,
                     finish="stop", completion_tokens=100, build="b")


def test_gate_keeps_clean_runs():
    runs = [mk(0, 21828), mk(1, 21830), mk(2, 21826)]
    valid, discarded = bench.filter_cache_hits(runs)
    assert len(valid) == 3 and not discarded


def test_gate_discards_a_single_cache_hit():
    runs = [mk(0, 21828), mk(1, 5), mk(2, 21826)]
    valid, discarded = bench.filter_cache_hits(runs)
    assert [r.v for r in valid] == [0, 2]
    assert [r.v for r in discarded] == [1]


def test_gate_survives_cache_hit_MAJORITY():
    """THE regression test. Real data from htpc-01, 2026-08-01.

    Three genuine runs at ~21,828 tokens and five prefix-cache hits at prompt_n=5.
    The original implementation gated on `>= 0.9 * median`; with the hits in the
    majority the median IS 5, the threshold becomes 4.5, every contaminated row passes,
    and the harness reported a prefill median of 7.2 tok/s as a result.

    Gating on the maximum is what makes this hold: a cache hit always reports FEWER
    tokens than a real run, never more.
    """
    runs = ([mk(i, 21828, prefill=1123.5) for i in range(3)] +
            [mk(i, 5, prefill=7.2) for i in range(5)])
    valid, discarded = bench.filter_cache_hits(runs)
    assert len(valid) == 3, "cache hits in the majority defeated the gate"
    assert len(discarded) == 5
    s = bench.summarise(valid)
    assert s["prefill_med"] == 1123.5, "reported a cache hit as a measurement"

    # And prove the old rule really did fail, so this test cannot rot into a tautology.
    import statistics
    ok = runs
    med = statistics.median(r.prompt_n for r in ok)
    old_valid = [r for r in ok if r.prompt_n >= 0.9 * med]
    assert len(old_valid) == 8, "the old median rule was expected to admit everything"


def test_gate_ignores_errored_runs():
    runs = [mk(0, 21828), bench.Run(v=1, error="unparseable response")]
    valid, discarded = bench.filter_cache_hits(runs)
    assert len(valid) == 1 and not discarded


def test_gate_on_all_errors_returns_empty():
    runs = [bench.Run(v=0, error="x"), bench.Run(v=1, error="y")]
    assert bench.filter_cache_hits(runs) == ([], [])


# --------------------------------------------------- absolute anchor (--expect-prompt-n)

def test_anchor_passes_within_tolerance():
    assert bench.check_expected_prompt_n(21828, 21828) is None
    assert bench.check_expected_prompt_n(21900, 21828) is None      # +0.3%


def test_anchor_fails_outside_tolerance():
    msg = bench.check_expected_prompt_n(19000, 21828)
    assert msg and "re-baselined" in msg


def test_anchor_catches_uniform_contamination_the_relative_gate_cannot():
    """THE reason this exists. If every variant is served from cache, filter_cache_hits
    sees a self-consistent set and passes all of them — max is 5, the threshold 4.5.
    Only an absolute anchor can tell that the whole run is worthless."""
    runs = [mk(v, 5, prefill=7.2) for v in range(5)]
    valid, discarded = bench.filter_cache_hits(runs)
    assert len(valid) == 5 and not discarded, "relative gate is expected to be blind here"
    assert bench.check_expected_prompt_n(bench.summarise(valid)["prompt_n"], 21828)


def test_anchor_is_inert_when_not_requested():
    """Default 0 means no anchor: bench.py must stay usable for configs whose prompt_n
    has never been measured."""
    assert bench.check_expected_prompt_n(1, 0) is None


def test_expected_prompt_n_has_no_guessed_entries():
    """Only MEASURED anchors belong here. Other models tokenize the same corpus
    differently, so a guessed value would make the check assert a fiction — and an anchor
    asserting a fiction fails every row it is attached to.

    Both entries were read off a real row on htpc-01: 21,828 at 1,200 lines (the ub
    sweep) and 9,836 at 540 lines (the -fa 0 row). qwen3.5 and gemma-moe are deliberately
    absent: their 1,200-line values have not been measured yet, and the relative cache
    gate still covers them.
    """
    assert bench.EXPECTED_PROMPT_N == {
        ("gemma", bench.DEFAULT_LINES): 21828,
        ("gemma", 540): 9836,
        ("qwen3.5", bench.DEFAULT_LINES): 23492,
        ("gemma-moe", bench.DEFAULT_LINES): 21828,
    }
    anchored = {m for (m, _) in bench.EXPECTED_PROMPT_N}
    assert anchored <= set(bench.MODELS), "an anchor names a model that does not exist"
    # qwen3-14b is deliberately absent — it is out of the model comparison and has never
    # been run through this corpus, so there is no measured value to anchor it to.
    assert "qwen3" not in anchored


# ------------------------------------------------- llama-server command construction

class Args:
    """argparse.Namespace stand-in — server_argv only reads attributes."""
    def __init__(self, **kw):
        self.ctx, self.fa, self.ub, self.kv = 32768, "1", "", ""
        self.verbose = False
        self.__dict__.update(kw)


def test_server_argv_always_carries_the_invariants():
    """These five are what make two rows comparable at all. -np 1 because concurrent
    slots split the KV cache; --no-context-shift so an overrun fails loudly instead of
    silently truncating; --reasoning-budget -1 so thinking is not capped mid-measurement."""
    argv = bench.server_argv("/models/x.gguf", "--temp 1.0", Args())
    for flag in ("--no-context-shift", "--jinja"):
        assert flag in argv, f"missing {flag}"
    assert argv[argv.index("-np") + 1] == "1"
    assert argv[argv.index("--reasoning-budget") + 1] == "-1"
    assert argv[argv.index("-ngl") + 1] == "999"
    assert argv[argv.index("-c") + 1] == "32768"
    assert argv[argv.index("--port") + 1] == str(bench.PORT)


def test_server_argv_splits_the_sampler_into_separate_elements():
    """Passed whole, '--temp 1.0 --top-k 64' reaches llama-server as ONE argument and is
    rejected. There is no shell here to split it."""
    argv = bench.server_argv("/m.gguf", "--temp 1.0 --top-k 64", Args())
    assert "--temp" in argv and argv[argv.index("--temp") + 1] == "1.0"
    assert argv[argv.index("--top-k") + 1] == "64"
    assert not any(" " in a for a in argv), f"unsplit argument: {argv}"


def test_server_argv_omits_optional_flags_unless_asked():
    """An unconditional -ub would silently change every row: llama.cpp's default is 512
    and passing it explicitly is not the same as leaving it unset for future builds."""
    argv = bench.server_argv("/m.gguf", "", Args())
    for flag in ("-ub", "--cache-type-k", "--cache-type-v", "-v"):
        assert flag not in argv, f"{flag} present without being requested"


def test_server_argv_includes_optional_flags_when_asked():
    argv = bench.server_argv("/m.gguf", "", Args(ub=2048, kv="q8_0", verbose=True))
    assert argv[argv.index("-ub") + 1] == "2048"
    assert argv[argv.index("--cache-type-k") + 1] == "q8_0"
    assert argv[argv.index("--cache-type-v") + 1] == "q8_0", "V cache must match K"
    assert "-v" in argv


def test_server_argv_model_path_comes_from_MODELS():
    for name, (gguf, _) in bench.MODELS.items():
        argv = bench.server_argv(gguf, "", Args())
        assert argv[argv.index("-m") + 1] == gguf
        assert gguf.startswith("/models/"), f"{name} path is not the container mount"


# --------------------------------------------------------------- dispersion

def test_summarise_reports_range_not_just_median():
    runs = [mk(0, 21828, gen=38.0), mk(1, 21828, gen=40.0), mk(2, 21828, gen=42.0)]
    s = bench.summarise(runs)
    assert s["gen_med"] == 40.0
    assert (s["gen_min"], s["gen_max"]) == (38.0, 42.0)
    assert abs(s["gen_spread_pct"] - 10.0) < 1e-9


def test_zero_spread_when_identical():
    runs = [mk(v, 21828, gen=40.0) for v in range(3)]
    assert bench.summarise(runs)["gen_spread_pct"] == 0.0


# --------------------------------------------------------------- row format

def test_row_column_count_matches_header():
    """A row that does not line up with the header corrupts results.md silently."""
    s = bench.summarise([mk(0, 21828)])
    row = bench.format_row(s, model="gemma", backend="rocm", ctx=32768, ub="512",
                           fa="1", kv="f16", loaded_free="3000", baseline_free="15000",
                           evicted="0", notes="x")
    assert row.startswith("| ") and row.endswith(" |")
    assert len(row.strip("|").split("|")) == len(bench.ROW_COLUMNS)


def test_row_notes_defaults_to_dash():
    s = bench.summarise([mk(0, 21828)])
    row = bench.format_row(s, model="g", backend="rocm", ctx=1, ub="512", fa="1",
                           kv="f16", loaded_free="1", baseline_free="2", evicted="0",
                           notes="")
    assert row.rstrip().endswith("| - |")


# --------------------------------------------------------------- response parsing

GOOD = json.dumps({
    "choices": [{"message": {"content": "OK", "reasoning_content": ""},
                 "finish_reason": "stop"}],
    "timings": {"prompt_n": 21828, "prompt_per_second": 1151.2,
                "predicted_per_second": 40.1},
    "usage": {"completion_tokens": 120},
    "system_fingerprint": "b10200-5f55650a7",
})


def test_parse_completion_extracts_the_metrics():
    r = bench.parse_completion(GOOD, 0, "")
    assert (r.prompt_n, r.prefill, r.gen, r.build) == (21828, 1151.2, 40.1,
                                                       "b10200-5f55650a7")
    assert r.error is None


def test_parse_completion_handles_garbage():
    assert bench.parse_completion("not json", 0, "").error == "unparseable response"
    assert bench.parse_completion('{"error":"boom"}', 0, "").error is not None


def test_needle_scores_reasoning_content_too():
    """With thinking on, the answer can land in reasoning_content while content is
    empty; scoring only content reports a false miss."""
    payload = json.loads(GOOD)
    payload["choices"][0]["message"] = {"content": "", "reasoning_content": "PLUM-4471"}
    r = bench.parse_completion(json.dumps(payload), 0, "PLUM-4471")
    assert r.hit is True and r.hit_content_only is False


# --------------------------------------------------------------- EVICTED attribution

def test_evicted_attributed_to_the_biggest_vram_consumer():
    """`amd-smi process` lists every GPU client and the first block is NOT llama-server;
    taking the first match reports the compositor's counter."""
    out = """
    PROCESS: gnome-shell
        MEM_USAGE: 281 MB
        EVICTED_TIME: 9600
    PROCESS: llama-server
        MEM_USAGE: 11.2 GB
        EVICTED_TIME: 420
    """
    assert bench.parse_evicted(out) == "420"


def test_evicted_unknown_when_no_processes():
    assert bench.parse_evicted("") == "?"


# --------------------------------------------------------------- prompt corpus

def test_corpus_is_deterministic():
    """The corpus is a frozen artifact: `--expect-prompt-n 21828` anchors every gemma row
    against it, and a change here invalidates every historical row in results.md."""
    a, _ = prompts.build_prompt(0, 1200, False)
    b, _ = prompts.build_prompt(0, 1200, False)
    assert a == b


def test_variants_share_no_prefix():
    """The whole point: a shared prefix makes llama.cpp serve the run from cache and
    report prompt_n far below the real size."""
    p0, _ = prompts.build_prompt(0, 200, False)
    p1, _ = prompts.build_prompt(1, 200, False)
    body0 = p0.split("<sources>\n", 1)[1]
    body1 = p1.split("<sources>\n", 1)[1]
    assert body0[:200] != body1[:200], "variants share a prefix — cache will zero them"


def test_corpus_matches_the_recorded_hash():
    """The corpus has not drifted since the hash in testdata/ was recorded.

    A MISSING baseline is a FAILURE, not something to regenerate. The previous version
    wrote the hash it was about to assert against when the file was absent, so on any
    fresh checkout it certified itself and could not fail on first run.

    Scope, stated honestly: this proves stability against a recorded value. It does NOT
    prove equivalence to the PYGEN block in the old bench.sh — that script was deleted
    and never committed, so no such comparison can be re-derived. To re-baseline
    deliberately, run `python3 rebaseline_corpus.py --i-understand-this-invalidates-results`,
    which is a separate explicit act.
    """
    import hashlib
    ref = HERE / "testdata" / "v0.lines200.sha"
    assert ref.exists(), (f"missing baseline {ref} — this is a failure, not a prompt to "
                          "regenerate it; a re-baseline invalidates results.md")
    p, _ = prompts.build_prompt(0, 200, False)
    got = hashlib.sha256(p.encode()).hexdigest()
    assert got == ref.read_text().strip(), "prompt corpus changed — re-baseline required"


# --------------------------------------------------------------- load-only probe

def test_parse_load_only_extracts_both_figures():
    out = ("--- device selected ---\n"
           "LOAD-ONLY: baseline_free=15656 MB loaded_free=1199 MB (floor is 1500 MB)\n")
    assert bench.parse_load_only(out) == {"baseline_free": 15656, "loaded_free": 1199}


def test_parse_load_only_returns_none_when_the_probe_failed():
    """A probe that never reported must not be read as 'fits'. run_matrix gates timed
    rows on this, and a silent None-means-OK would let a thrashing config through."""
    assert bench.parse_load_only("FAILED: server did not become healthy.") is None
    assert bench.parse_load_only("") is None


def test_parse_load_only_ignores_the_floor_value_in_the_same_line():
    """The line also contains '(floor is 1500 MB)'. A looser regex would capture it."""
    out = "LOAD-ONLY: baseline_free=15656 MB loaded_free=1199 MB (floor is 1500 MB)"
    assert bench.parse_load_only(out)["loaded_free"] == 1199


# --------------------------------------------------------------- files written

def test_run_paths_differ_between_processes_in_the_same_second():
    """A fixed path let an aborted run's corpus be read by the next one: prefill 7.6
    tok/s over n=7 from --variants 3, and nothing flagged it. Time alone is
    second-resolution, and --load-only probes finish inside one second of each other."""
    a = bench.run_paths(now=1000.0, pid=111)
    b = bench.run_paths(now=1000.0, pid=222)
    assert a != b, "same second, different process — paths collided"
    assert a[0] != a[1], "corpus dir and startup log must not be the same path"


def test_run_paths_are_absolute_and_under_tmp():
    for p in bench.run_paths():
        assert p.startswith("/tmp/"), p


def test_write_corpus_emits_valid_request_bodies():
    """These files are handed to `curl -d @file` inside the container. Malformed JSON
    surfaces as an HTTP 400 five minutes into a row, not as a parse error here."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        prompts.write_corpus(out, variants=3, lines=40, needle=False, max_tokens=256)
        for v in range(3):
            body = json.loads((out / f"v{v}.json").read_text())
            assert body["max_tokens"] == 256
            assert body["messages"][0]["role"] == "user"
            assert "<sources>" in body["messages"][0]["content"]
            assert (out / f"v{v}.expect").exists(), "missing .expect for a variant"


def test_write_corpus_needle_answer_is_present_and_recorded():
    """In needle mode the .expect file is the scoring key. If it did not match the text
    actually planted in the prompt, recall would read 0/N and look like a model failure."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        prompts.write_corpus(out, variants=3, lines=40, needle=True, max_tokens=64)
        for v in range(3):
            expect = (out / f"v{v}.expect").read_text().strip()
            content = json.loads((out / f"v{v}.json").read_text())["messages"][0]["content"]
            assert expect, f"v{v} has no expected answer"
            assert expect in content, f"v{v} expects {expect} but it is not in the prompt"


def test_write_corpus_creates_a_missing_directory():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "does" / "not" / "exist"
        prompts.write_corpus(out, variants=1, lines=10, needle=False, max_tokens=8)
        assert (out / "v0.json").exists()


# --------------------------------------------------------------- end to end

def test_dry_run_emits_a_wellformed_row():
    r = subprocess.run([sys.executable, str(HERE / "bench.py"), "--dry-run",
                        "--variants", "3", "--backend", "rocm"],
                       capture_output=True, text=True, cwd=HERE)
    assert r.returncode == 0, r.stderr
    rows = [l for l in r.stdout.splitlines() if l.startswith("| gemma ")]
    assert len(rows) == 1
    assert len(rows[0].strip("|").split("|")) == len(bench.ROW_COLUMNS)


def test_refuses_quantised_kv_without_flash_attention():
    """Rejected by llama.cpp in ~2s; a naive sweep would record it as a failed data
    point rather than an impossible config."""
    r = subprocess.run([sys.executable, str(HERE / "bench.py"), "--kv", "q8_0",
                        "--fa", "0"], capture_output=True, text=True, cwd=HERE)
    assert r.returncode == 2 and "REFUSED" in r.stderr


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
