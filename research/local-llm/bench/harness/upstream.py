"""Parse llama-swap's `/logs/stream/upstream` capture into per-call facts.

This is the only source for the numbers Phase 0 must produce — `calls = f(i,q)`,
tokens/call and peak prompt (`ldr-tuning-methodology.md:117`). None of them appear in
`quick_summary`'s return value, so the runner records a trial's *cost* only if a capture
was running.

Pure: no I/O, no network. Tested against a real captured log in `testdata/`, never against
an invented one — the llama-swap harness lost days to a parser written from a guess at the
format, which matched nothing and reported silence as zero.

CAPTURE IT LIKE THIS (README.md:59), before the first query:

    sudo podman exec llama-swap curl -Ns "localhost:8080/logs/stream/upstream?no-history"

THE FORMAT, verbatim from a real run (2026-08-01, gemma-4-12b-it, Q1 at i=1 q=2):

    slot print_timing: id  0 | task 397 | prompt eval time = 1870.77 ms / 3012 tokens (...)
    slot print_timing: id  0 | task 397 | n_decoded = 2123, tg = 44.06 t/s, tg_3s = 43.91 t/s
    slot      release: id  0 | task 397 | stop processing: n_tokens = 5254, truncated = 0

`n_decoded` and `tg` are printed REPEATEDLY as generation proceeds, so the last occurrence
for a task is the final one. A task is only complete when its `release` line arrives.
"""

from __future__ import annotations

import re
import statistics

# `prompt eval time = <ms> ms / <n> tokens` — tokens actually PROCESSED this call.
_PROMPT_EVAL = re.compile(r"task\s+(\d+)\s*\|\s*prompt eval time =\s*[\d.]+ ms /\s*(\d+) tokens")
# `n_decoded = <n>, tg = <rate> t/s` — emitted repeatedly; the last wins.
_DECODED = re.compile(r"task\s+(\d+)\s*\|\s*n_decoded =\s*(\d+), tg =\s*([\d.]+) t/s")
# The completion marker. `n_tokens` is prompt + decoded for the whole call.
_RELEASE = re.compile(r"task\s+(\d+)\s*\|\s*stop processing: n_tokens =\s*(\d+), truncated =\s*(\d+)")


def parse_tasks(log: str) -> list[dict]:
    """One dict per COMPLETED call, in the order they finished.

    A call without a `release` line was still running when the capture stopped; it is
    dropped rather than reported with a missing total, because a half-call silently
    lowers the peak.

    **Task ids must be unique within `log`.** Entries are keyed by id, so if the region
    spans a llama-server restart -- any model swap -- the reused id OVERWRITES the earlier
    call rather than adding to it. Three real calls become two, the lost one vanishing
    without trace, which lowers the peak and raises the per-call average: both in the
    flattering direction. Slice with `slice_range` (byte offsets) so a region never spans a
    restart. `test_upstream.py:test_task_id_slicing_misattributes_when_ids_reset` pins it.
    """
    seen: dict[str, dict] = {}
    order: list[str] = []

    def slot(tid: str) -> dict:
        if tid not in seen:
            seen[tid] = {"task": tid, "prompt_processed": None, "n_decoded": None,
                         "tg": None, "n_tokens": None, "truncated": None}
            order.append(tid)
        return seen[tid]

    for line in log.splitlines():
        if (m := _PROMPT_EVAL.search(line)):
            slot(m.group(1))["prompt_processed"] = int(m.group(2))
        elif (m := _DECODED.search(line)):
            s = slot(m.group(1))          # repeated during generation: last wins
            s["n_decoded"] = int(m.group(2))
            s["tg"] = float(m.group(3))
        elif (m := _RELEASE.search(line)):
            s = slot(m.group(1))
            s["n_tokens"] = int(m.group(2))
            s["truncated"] = int(m.group(3))

    out = []
    for tid in order:
        t = seen[tid]
        if t["n_tokens"] is None or t["n_decoded"] is None:
            continue                       # incomplete: never report a partial call
        # THE PROMPT SIZE. `prompt eval time`'s token count is what was PROCESSED and
        # EXCLUDES a cached prefix, so it under-reports — README.md:132, and visible in
        # testdata: n_tokens 497 - n_decoded 276 = 221 prompt tokens against 104 processed.
        t["prompt_tokens"] = t["n_tokens"] - t["n_decoded"]
        out.append(t)
    return out


def summarise(log: str) -> dict | None:
    """Per-trial cost facts, or **None if the capture is unusable**.

    None, never zeros. `README.md:61` records the capture dying mid-run (curl exit 56),
    and a dead capture must read as "no capacity data" — reporting 0 calls would look
    like a trial that never touched the GPU.
    """
    tasks = parse_tasks(log)
    if not tasks:
        return None
    return {
        "calls": len(tasks),
        "prompt_tokens": sum(t["prompt_tokens"] for t in tasks),
        "decoded_tokens": sum(t["n_decoded"] for t in tasks),
        # Peak is what sizes -c, so it is the max over calls, not the sum or the mean.
        "peak_prompt": max(t["prompt_tokens"] for t in tasks),
        "peak_total": max(t["n_tokens"] for t in tasks),
        # Median across calls: one short call at a different rate should not move it.
        "gen_tok_s": round(statistics.median(t["tg"] for t in tasks if t["tg"]), 2),
        # A single truncated call invalidates the trial — ldr-tuning-methodology.md:56-57
        # calls it "a failure, not a point on the frontier".
        "truncated": sum(t["truncated"] or 0 for t in tasks),
    }


def slice_range(raw: bytes, start: int, end: int | None = None) -> str:
    """The capture region belonging to one trial, taken by **byte offset**.

    THIS IS THE CORRECT ATTRIBUTION METHOD, and `slice_log` below is not. The runner records
    the capture file's size immediately before a trial and again after it; everything written
    between is that trial's traffic, whatever the task ids happen to be.

    Bytes, not characters: `os.path.getsize` and `seek` are byte-denominated, and a log line
    can carry non-ASCII (a query echoed into a prompt, a page title in a search result). A
    character offset would drift against the file position the moment one appears.

    `errors="replace"` because a region boundary can land mid-codepoint -- the capture is
    still being appended to while we read. A replacement character costs nothing here: the
    parser matches ASCII-only patterns.
    """
    if start < 0:
        raise ValueError(f"negative start offset {start}")
    if end is not None and end < start:
        raise ValueError(f"end {end} precedes start {start}")
    return raw[start:end].decode("utf-8", errors="replace")


def slice_log(log: str, start_task: str | None = None) -> str:
    """Split on the first occurrence of a task id. **Unsafe across a sweep — prefer
    `slice_range`.**

    Kept because a single-trial capture (`?no-history`, one model, one process) still slices
    correctly this way, and the Phase B fixture was taken that way.

    Why it is unsafe: it assumes task ids increase monotonically for the life of the capture.
    They are monotonic only **per llama-server process**. Any model swap restarts the process
    and resets ids to 0, so a sweep's capture can contain several id sequences and
    `start_task="0"` matches the *earliest* one -- silently attributing a later trial's
    traffic to an earlier one. `test_upstream.py` demonstrates this on a reset log.
    """
    if start_task is None:
        return log
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if re.search(rf"task\s+{re.escape(start_task)}\s*\|", line):
            return "\n".join(lines[i:])
    return ""
