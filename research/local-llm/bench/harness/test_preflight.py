#!/usr/bin/env python3
"""Tests for the preflight decision logic.

    python3 test_preflight.py       # Mac, no ssh, no GPU, no container

Only the *interpretation* is tested here — the `parse_*` functions that turn a host command's
output into pass/fail. That is where the judgement lives, and it is the part that would
otherwise only ever be exercised against a live host, i.e. never against the failure cases.
"""

import json
import sys

import preflight
import shootout


# Real `gpu-mode status` output shapes, transcribed from
# ansible/files/htpc-01/gpu-mode.sh:139-161 rather than imagined. The multi-line preamble is
# load-bearing: an earlier version of parse_gpu_mode matched "llm" anywhere in the blob and
# passed the CONTENDED case, which is the exact state that voids a measurement.
def _status(mode_line: str, llama: str = "active", comfy: str = "inactive") -> str:
    return ("GPU:  12534 MB used / 16304 MB total  (3770 MB free)\n"
            f"ComfyUI:    {comfy:<10} boot=no\n"
            f"llama-swap: {llama:<10} boot=yes\n"
            "models:     [{\"model\": \"gemma-4-12b-it\"}]\n"
            f"mode:       {mode_line}\n")


def test_gpu_mode_must_be_llm():
    ok, detail = preflight.parse_gpu_mode(_status("llm"))
    assert ok, detail

    for bad in ("comfy", "game (neither container is running)"):
        ok, _ = preflight.parse_gpu_mode(_status(bad))
        assert not ok, f"mode {bad!r} should not pass"


def test_contended_is_rejected_even_though_llama_swap_is_up():
    """Both consumers running. llama-swap IS active, so a check that only asked 'is
    llama-swap up' would pass — and this is the state that produced 772,000 ms of eviction
    and a >900 s prompt (llm-tuning.md:854-855)."""
    out = _status("CONTENDED — both consumers running, expect VRAM thrashing",
                  llama="active", comfy="active")
    ok, detail = preflight.parse_gpu_mode(out)
    assert not ok, "CONTENDED must block the run"
    assert "CONTENDED" in detail


def test_missing_or_empty_output_fails_closed():
    for bad in ("", "gpu-mode: command not found\n"):
        ok, detail = preflight.parse_gpu_mode(bad)
        assert not ok, f"{bad!r} should fail closed"
        assert "no mode line" in detail


def test_idle_llama_swap_is_fine_but_a_foreign_model_is_not():
    """llama-swap loads on first request, so idle is the normal pre-run state. A *different*
    model resident means something else is driving it and the run is not exclusive."""
    for idle in ("", "[]", "{}"):
        ok, _ = preflight.parse_running_model(idle)
        assert ok, f"{idle!r} is idle and should pass"

    ok, detail = preflight.parse_running_model(
        '[{"model": "' + preflight.EXPECTED_MODEL + '"}]')
    assert ok, detail

    ok, detail = preflight.parse_running_model('[{"model": "qwen3-14b"}]')
    assert not ok, "a foreign resident model should block the run"
    assert "qwen3-14b" in detail


def test_unknown_strategy_is_blocking():
    """A name absent from the live enum does NOT raise — it silently falls back to the
    default strategy, so the sweep would run langgraph-agent while reporting otherwise."""
    live = '["source-based", "focused-iteration", "langgraph-agent"]'
    ok, _ = preflight.parse_strategies(live, ["source-based"])
    assert ok

    ok, detail = preflight.parse_strategies(live, ["focused_iteration"])
    assert not ok, "the underscore form is not a live member and must be caught"
    assert "focused_iteration" in detail

    ok, detail = preflight.parse_strategies("not json", ["source-based"])
    assert not ok and "parse" in detail


def test_the_strategies_we_actually_sweep_are_checked():
    """Guards against the check drifting away from the grid it is supposed to protect."""
    live = '["source-based", "focused-iteration", "focused-iteration-standard"]'
    ok, detail = preflight.parse_strategies(live, shootout.STRATEGIES)
    assert ok, detail


def test_a_static_capture_file_fails():
    """A capture that exists but is not growing is the dangerous case: every trial records
    unknown cost and the sweep still completes looking healthy."""
    ok, _ = preflight.parse_capture_growing("100", "250")
    assert ok
    for a, b in (("100", "100"), ("250", "100"), ("x", "1")):
        ok, _ = preflight.parse_capture_growing(a, b)
        assert not ok, f"({a}, {b}) should fail"


def test_a_fully_suspended_search_backend_is_blocking():
    """VERBATIM from the outage that motivated this check (2026-08-02): every web engine
    suspended at once. Only four of SearXNG's engines actually search the web in `general`,
    so this state returns nothing — while every trial still completes 'successfully' with
    zero sources, which is indistinguishable from a strategy that retrieves badly."""
    real = json.dumps({"results": [], "unresponsive_engines": [
        ["brave", "too many requests"], ["duckduckgo", "timeout"],
        ["google cse", "Suspended: too many requests"], ["startpage", "Suspended: CAPTCHA"]]})
    ok, detail = preflight.parse_search_health(real)
    assert not ok
    assert "brave" in detail and "startpage" in detail, detail


def test_a_partial_outage_still_passes():
    """Degraded is not dead: fewer engines means thinner results, not fabricated ones. Failing
    here would block every sweep, since one engine is nearly always misbehaving."""
    ok, detail = preflight.parse_search_health(json.dumps(
        {"results": [0] * 12, "unresponsive_engines": [["duckduckgo", "timeout"]]}))
    assert ok and "duckduckgo" in detail, detail


def test_search_health_fails_closed_on_junk():
    """A container that cannot reach searxng at all prints a traceback, not JSON."""
    for junk in ("", "Traceback (most recent call last):", "urlopen error"):
        ok, _ = preflight.parse_search_health(junk)
        assert not ok, f"{junk!r} should fail closed"


def test_search_health_is_asked_from_inside_the_container():
    """From the Mac it would pass while the app still saw nothing — different network, and
    searxng publishes no host port."""
    import inspect
    src = inspect.getsource(preflight.check_ldr_host)
    assert "docker exec" in src and "http://searxng:8080" in src, (
        "the search check must use the same URL, from the same network, as the app")


def test_result_labels_distinguish_blocking_from_advisory():
    assert preflight.Result("n", False, fatal=True).label == "FAIL"
    assert preflight.Result("n", False, fatal=False).label == "WARN"
    assert preflight.Result("n", True).label == "PASS"


def test_remote_commands_are_wrapped_for_fish():
    """Both hosts use fish as the login shell. An unwrapped command fails with a `fish:`
    syntax error that reads like the remote program crashed."""
    import inspect
    src = inspect.getsource(preflight.ssh)
    assert "bash -c" in src, "remote commands must be wrapped in bash -c"
    assert "shlex.quote" in src, "the wrapped command must be quoted as one argument"


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
