#!/usr/bin/env python3
"""Tests for the upstream-log parser, against a REAL captured log.

Run:  python3 research/local-llm/bench/harness/test_upstream.py     (no container, no GPU, no LDR)

`testdata/upstream-Q1-i1-q2.log` is a genuine capture — gemma-4-12b-it, Q1 at
iterations=1, questions_per_iteration=2, on Vulkan, 2026-08-01. A parser written against
an *imagined* format is the failure this guards: the llama-swap harness matched
`"kv cache"` where llama.cpp writes `llama_kv_cache:`, captured nothing, and reported the
silence as a valid empty result for days.
"""

import sys
from pathlib import Path

import upstream

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "testdata" / "upstream-Q1-i1-q2.log"


def load() -> str:
    assert FIXTURE.exists(), (
        f"missing {FIXTURE} — capture one with:\n"
        '  sudo podman exec llama-swap curl -Ns "localhost:8080/logs/stream/upstream?no-history"\n'
        "A missing fixture is a failure, not a reason to write the parser from memory.")
    return FIXTURE.read_text()


# --------------------------------------------------------------- shape

def test_finds_every_completed_call():
    """i=1, q=2 produced five completed calls in the recorded run."""
    tasks = upstream.parse_tasks(load())
    assert len(tasks) == 5, [t["task"] for t in tasks]
    assert [t["task"] for t in tasks] == ["0", "397", "2638", "3850", "7425"]


def test_every_task_has_all_fields():
    for t in upstream.parse_tasks(load()):
        for f in ("n_tokens", "n_decoded", "tg", "prompt_tokens", "truncated"):
            assert t[f] is not None, f"task {t['task']} missing {f}"


def test_last_n_decoded_wins():
    """`n_decoded` and `tg` are printed repeatedly as generation proceeds. Taking the
    first would report a call as ~130 tokens when it decoded thousands."""
    tasks = {t["task"]: t for t in upstream.parse_tasks(load())}
    assert tasks["3850"]["n_decoded"] == 3444, "took an intermediate progress line"


# ------------------------------------------- THE trap this parser exists for

def test_peak_prompt_is_not_the_prompt_eval_count():
    """`README.md:132`: use `n_tokens − n_decoded`, **not** the `prompt eval time` token
    count, which excludes a cached prefix and therefore UNDER-reports the prompt.

    Visible in the fixture: task 0 has n_tokens 497 − n_decoded 276 = 221 prompt tokens,
    while `prompt eval time` reports only 104 processed. Sizing `-c` from 104 would be
    wrong by half.
    """
    tasks = {t["task"]: t for t in upstream.parse_tasks(load())}
    t0 = tasks["0"]
    assert t0["n_tokens"] == 497 and t0["n_decoded"] == 276
    assert t0["prompt_tokens"] == 221
    assert t0["prompt_processed"] == 104
    assert t0["prompt_tokens"] != t0["prompt_processed"], \
        "the cached-prefix gap vanished — the fixture or the parser changed"
    # And it is not a one-off: every call in this run had some prefix cached.
    under = [t for t in tasks.values() if t["prompt_processed"] < t["prompt_tokens"]]
    assert len(under) == 5, "expected every call to show a cached prefix"


# --------------------------------------------------------------- summary

def test_summary_matches_the_recorded_run():
    s = upstream.summarise(load())
    assert s["calls"] == 5
    assert s["truncated"] == 0
    assert s["peak_prompt"] == 3131        # task 397
    assert s["peak_total"] == 5912         # task 3850
    assert 40 < s["gen_tok_s"] < 50, s["gen_tok_s"]


def test_peak_prompt_and_peak_total_come_from_different_calls():
    """Not interchangeable, and the fixture proves it: task 3850 has the largest TOTAL
    (5,912) because it decoded 3,444 tokens, while task 397 has the largest PROMPT
    (3,131). Sizing `-c` needs the total; sizing `max_input_tokens` needs the prompt.
    Taking the prompt from whichever call had the biggest total would understate it."""
    tasks = {t["task"]: t for t in upstream.parse_tasks(load())}
    biggest_prompt = max(tasks.values(), key=lambda t: t["prompt_tokens"])
    biggest_total = max(tasks.values(), key=lambda t: t["n_tokens"])
    assert biggest_prompt["task"] == "397"
    assert biggest_total["task"] == "3850"
    assert biggest_prompt["task"] != biggest_total["task"]


def test_peak_is_max_not_sum_or_mean():
    """Peak sizes `-c`. A sum would wildly overstate it; a mean would hide the worst call
    — and `llm-tuning.md` shows the peak is set by whether a turn crawls a big page."""
    s = upstream.summarise(load())
    tasks = upstream.parse_tasks(load())
    assert s["peak_prompt"] == max(t["prompt_tokens"] for t in tasks)
    assert s["peak_prompt"] < sum(t["prompt_tokens"] for t in tasks)


def test_truncated_is_detected():
    """`ldr-tuning-methodology.md:56-57` makes a truncated call a failure, not a point on
    the frontier. It must never be silently absent."""
    doctored = load().replace("n_tokens = 5254, truncated = 0",
                              "n_tokens = 5254, truncated = 1")
    assert upstream.summarise(doctored)["truncated"] == 1


# ------------------------------------------- absence is not evidence

def test_dead_capture_returns_none_not_zero():
    """`README.md:61`: the capture has died mid-run before (curl exit 56), and a dead
    capture means "no capacity data", NEVER "no traffic". Returning 0 calls would look
    like a trial that never reached the GPU."""
    assert upstream.summarise("") is None
    assert upstream.summarise("some unrelated log line\n") is None


def test_incomplete_call_is_dropped_not_half_counted():
    """A call still running when the capture stopped has no `release` line. Counting it
    with a missing total would silently lower the peak."""
    log = load()
    cut = log.rsplit("stop processing", 1)[0]     # drop the final release line
    assert upstream.summarise(cut)["calls"] == 4


def test_parser_tolerates_interleaved_noise():
    """The stream carries model-load banners and slot bookkeeping between calls."""
    noisy = "\n".join(["srv  llama_server: model loaded", load(),
                       "load: control-looking token: 106 '<eos>'"])
    assert upstream.summarise(noisy)["calls"] == 5


# ------------------------------------------- attribution across a multi-cell sweep

def _trial(task: str, prompt_tokens: int, decoded: int) -> str:
    """One synthetic completed call, in the real format."""
    total = prompt_tokens + decoded
    return "\n".join([
        f"slot print_timing: id  0 | task {task} | prompt eval time = 100.0 ms / "
        f"{prompt_tokens} tokens (0.10 ms per token)",
        f"slot print_timing: id  0 | task {task} | n_decoded = {decoded}, tg = 44.0 t/s",
        f"slot      release: id  0 | task {task} | stop processing: n_tokens = {total}, "
        f"truncated = 0",
    ])


def test_byte_offset_slicing_is_exact():
    """The runner records file size before and after a trial; everything between is its."""
    a = _trial("0", 100, 50) + "\n"
    b = _trial("1", 900, 80) + "\n"
    raw = (a + b).encode()

    first = upstream.summarise(upstream.slice_range(raw, 0, len(a.encode())))
    second = upstream.summarise(upstream.slice_range(raw, len(a.encode())))
    assert first["calls"] == 1 and first["peak_prompt"] == 100, first
    assert second["calls"] == 1 and second["peak_prompt"] == 900, second


def test_byte_offsets_survive_non_ascii_in_the_log():
    """Offsets come from os.path.getsize/seek, which count BYTES. A character-based slice
    would drift the moment a query or page title carries a multibyte character."""
    header = "srv  log: query='café naïve — \U0001f600'\n"   # 4 multibyte chars
    a = header + _trial("0", 100, 50) + "\n"
    b = _trial("1", 900, 80) + "\n"
    raw = (a + b).encode()
    assert len(raw) != len(a + b), "test is not exercising multibyte handling"

    second = upstream.summarise(upstream.slice_range(raw, len(a.encode())))
    assert second["calls"] == 1 and second["peak_prompt"] == 900, second


def test_slice_range_tolerates_a_boundary_mid_codepoint():
    """A capture is appended to while we read, so a region edge can split a codepoint.
    That must degrade to one replacement character, not raise."""
    raw = "é".encode() + _trial("7", 10, 5).encode()
    out = upstream.slice_range(raw, 1)          # start inside the 2-byte 'é'
    assert upstream.summarise(out)["calls"] == 1


def test_task_id_slicing_misattributes_when_ids_reset():
    """WHY byte offsets are used. A model or strategy change restarts llama-server and task
    ids restart at 0, so one capture holds several id sequences.

    `slice_log(log, "0")` matches the FIRST sequence and hands back everything after it —
    including the earlier trial's traffic. Byte offsets are immune.
    """
    first_cell = _trial("0", 100, 50) + "\n" + _trial("1", 120, 60) + "\n"
    # llama-server restarted here: ids go back to 0.
    second_cell = _trial("0", 900, 80) + "\n"
    raw = (first_cell + second_cell).encode()

    # The wrong way, and the damage is worse than leakage. `parse_tasks` keys by task id, so
    # the second cell's task 0 OVERWRITES the first cell's task 0: three real calls collapse
    # to two, and the 100-token call is gone without trace. A silently-lost call lowers the
    # peak and inflates the per-call average — both in the flattering direction.
    by_task = upstream.summarise(upstream.slice_log(raw.decode(), "0"))
    assert by_task["calls"] == 2, f"expected an id collision to eat a call: {by_task}"
    assert by_task["peak_prompt"] == 900, "the later cell overwrote the earlier one"
    # Proof the first call vanished rather than merely being mis-scoped: its 100-token
    # prompt appears nowhere in the totals.
    assert by_task["prompt_tokens"] == 900 + 120, by_task

    # The right way: the second cell alone.
    by_offset = upstream.summarise(
        upstream.slice_range(raw, len(first_cell.encode())))
    assert by_offset["calls"] == 1, by_offset
    assert by_offset["peak_prompt"] == 900


def test_slice_range_rejects_impossible_offsets():
    """A negative or inverted range means the runner lost track of its own bookkeeping.
    Failing loudly beats returning an empty string that reads as 'no traffic'."""
    raw = _trial("0", 10, 5).encode()
    for start, end in ((-1, None), (10, 4)):
        try:
            upstream.slice_range(raw, start, end)
        except ValueError:
            continue
        raise AssertionError(f"slice_range({start}, {end}) should have raised")


def test_an_empty_region_is_none_not_zero():
    """A trial that produced no capture bytes at all — a dead capture, or a request that
    never reached the GPU. Must read as unknown, never as a real zero."""
    assert upstream.summarise(upstream.slice_range(b"", 0)) is None


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
