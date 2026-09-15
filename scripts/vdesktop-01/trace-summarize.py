#!/usr/bin/env python3
"""Summarise a Chrome JSON trace WITHOUT loading it into memory.

Why this exists: on 2026-09-13 a 120-second Chromium capture came out at 667 MB, and
json.load() of it pinned CT 120 at its 4 GB limit with swap full and oom_kill 0 -- the kernel
never reaped it, sshd stopped answering, and the hypervisor's load reached 99. The parse had to
be killed by PID from the host. Nothing may read a trace whole again.

This reads ONE EVENT AT A TIME. Chrome writes its JSON trace as {"traceEvents":[ followed by
one object per line, so a line iterator is a valid event iterator. Accumulators are keyed by
thread and event name, so memory is bounded by the number of distinct names (hundreds), not by
the file.

Durations reported are INCLUSIVE: a Chrome "X" event's dur covers its children, so the names
overlap and do not sum to wall time. Per-thread busy uses the outermost task event only, which
does not overlap. Both are labelled below; do not add them together.
"""

import collections
import json
import os
import sys

# The outermost event on a Chromium sequence. Summing these gives real busy time because they
# do not nest inside each other.
TOPLEVEL = ("ThreadControllerImpl::RunTask", "RunTask", "MessageLoop::RunTask",
            "SequenceManager::RunTask", "ThreadPool_RunTask")

# Frame markers get their OWN measured window, and this is not a refinement -- without it the
# frame rate is simply wrong on any long capture.
#
# browser-profile.sh traces with record_mode=record-continuously and a per-process ring buffer
# (trace_buffer_size_in_kb). A busy renderer fills its ring and drops its OLDEST events; a quiet
# browser process never fills its own and keeps events from the very first millisecond. The
# file's overall span is therefore the QUIET process's span, which on a long run is far wider
# than the window the frame events actually cover. count/span then understates the rate, badly
# and silently.
#
# MEASURED 2026-09-14: a 240 s window produced a 943 MB file with 5632 MainFrame.Draw. Divided
# by the file span that reads as ~23 fps; divided by the window those draws actually occupy it
# is nothing of the sort. A 60 s capture does not overflow the ring, which is why the earlier
# runs were not affected and why this went unnoticed.
FRAME_MARKERS = (
    "MainFrame.Draw",
    "ProxyMain::BeginMainFrame",
    "FrameRequestCallbackCollection::ExecuteFrameCallbacks",
    "PageAnimator::serviceScriptedAnimations",
)


def events(path):
    with open(path, "r", errors="replace") as fh:
        fh.readline()  # '{"traceEvents":['
        for line in fh:
            line = line.strip().rstrip(",")
            if not line or line[0] != "{":
                continue
            try:
                yield json.loads(line)
            except ValueError:
                yield None


def main(argv):
    if len(argv) < 2:
        print("usage: trace-summarize.py <trace.json> [top_n] [name_substring]",
              file=sys.stderr)
        return 2
    path = argv[1]
    top_n = int(argv[2]) if len(argv) > 2 else 14
    needle = argv[3] if len(argv) > 3 else None
    size = os.path.getsize(path)

    threads = {}
    dur = collections.defaultdict(float)     # (pid, tid, name) -> us, inclusive
    cnt = collections.Counter()              # (pid, tid, name) -> occurrences
    cat = collections.defaultdict(float)     # category -> us, inclusive
    busy = collections.defaultdict(float)    # (pid, tid) -> us, outermost tasks only
    tlo, thi = {}, {}                        # (pid, tid) -> first/last ts seen on that thread
    mlo, mhi = {}, {}                        # frame marker name -> first/last ts
    mcnt = collections.Counter()             # frame marker name -> occurrences
    mdur = collections.defaultdict(float)    # frame marker name -> inclusive us
    lo = hi = None
    total = bad = 0

    for e in events(path):
        if e is None:
            bad += 1
            continue
        total += 1
        key = (e.get("pid"), e.get("tid"))
        if e.get("ph") == "M" and e.get("name") == "thread_name":
            threads[key] = e.get("args", {}).get("name", "?")
            continue
        ts = e.get("ts")
        ts_ok = isinstance(ts, (int, float)) and ts > 0
        if ts_ok:
            lo = ts if lo is None or ts < lo else lo
            hi = ts if hi is None or ts > hi else hi
            # Per-thread window, so busy% can be expressed against the span this thread was
            # actually captured over rather than the file's.
            if key not in tlo or ts < tlo[key]:
                tlo[key] = ts
            if key not in thi or ts > thi[key]:
                thi[key] = ts
        if e.get("ph") != "X":
            continue
        d = e.get("dur")
        if not isinstance(d, (int, float)) or d <= 0:
            continue
        name = e.get("name", "?")
        dur[key + (name,)] += d
        cnt[key + (name,)] += 1
        cat[e.get("cat", "?")] += d
        if name in TOPLEVEL:
            # These nest inside EACH OTHER (RunTask wraps ThreadControllerImpl::RunTask), so
            # summing them all double-counts -- the first version of this printed 193% of
            # span. Keep the largest single outermost name per thread.
            k = key + (name,)
            if dur[k] > busy[key]:
                busy[key] = dur[k]
        # Counted on exactly the events the rate is computed from -- X events with a real
        # duration -- so the count and the window can never come from different populations.
        if name in FRAME_MARKERS and ts_ok:
            mcnt[name] += 1
            mdur[name] += d
            if name not in mlo or ts < mlo[name]:
                mlo[name] = ts
            if name not in mhi or ts > mhi[name]:
                mhi[name] = ts

    span = (hi - lo) / 1e6 if lo is not None and hi is not None else 0.0
    print("file      : %s (%.1f MB)" % (path, size / 1048576.0))
    print("events    : %d parsed, %d unparseable" % (total, bad))
    print("span      : %.1f s" % span)
    print()

    print("BUSY TIME PER THREAD (outermost tasks only -- these do not overlap)")
    print("  %_of_span uses the FILE's span; %_of_own uses the window that thread was actually")
    print("  captured over. They differ when the ring buffer dropped that thread's early events,")
    print("  and %_of_own is the honest one -- see FRAME_MARKERS in this file.")
    print("  %-28s %-8s %10s %10s  %s"
          % ("thread", "pid/tid", "busy_s", "own_span_s", "%_of_span / %_of_own"))
    ranked = sorted(busy.items(), key=lambda kv: -kv[1])[:12]
    for (pid, tid), us in ranked:
        pct = (us / 1e6 / span * 100) if span else 0
        own = (thi.get((pid, tid), 0) - tlo.get((pid, tid), 0)) / 1e6
        opct = (us / 1e6 / own * 100) if own else 0
        print("  %-28s %-8s %10.2f %10.1f  %6.1f%% / %6.1f%%"
              % (threads.get((pid, tid), "?")[:28], "%s/%s" % (pid, tid),
                 us / 1e6, own, pct, opct))
    print()

    if mcnt:
        print("FRAME RATE, each marker over the window IT actually spans")
        print("  Dividing by the file span (%.1f s) is wrong when the ring dropped early events."
              % span)
        print("  %10s %9s %11s %9s  %s"
              % ("window_s", "count", "per_second", "mean_ms", "marker"))
        for n in FRAME_MARKERS:
            if n not in mcnt:
                continue
            w = (mhi[n] - mlo[n]) / 1e6
            rate = (mcnt[n] / w) if w else 0
            print("  %10.1f %9d %11.2f %9.2f  %s"
                  % (w, mcnt[n], rate, (mdur[n] / mcnt[n]) / 1000.0, n))
        print()

    for (pid, tid), _ in ranked[:3]:
        tname = threads.get((pid, tid), "?")
        print("TOP EVENTS ON %s (%s/%s) -- INCLUSIVE, they nest and overlap"
              % (tname, pid, tid))
        rows = [(n, v) for (p, t, n), v in dur.items() if (p, t) == (pid, tid)]
        print("  %10s %9s %11s  %s" % ("total_s", "count", "mean_ms", "event"))
        for n, v in sorted(rows, key=lambda r: -r[1])[:top_n]:
            c = cnt[(pid, tid, n)]
            print("  %10.2f %9d %11.2f  %s" % (v / 1e6, c, (v / c) / 1000.0, n))
        print()

    if needle:
        print("EVENTS MATCHING %r, ANY THREAD (inclusive)" % needle)
        print("  %10s %9s %11s  %s" % ("total_s", "count", "mean_ms", "thread / event"))
        hits = [(threads.get((p_, t_), "?"), n, v, cnt[(p_, t_, n)])
                for (p_, t_, n), v in dur.items() if needle.lower() in n.lower()]
        if not hits:
            print("  (none)")
        for th, n, v, c in sorted(hits, key=lambda r: -r[2])[:25]:
            print("  %10.2f %9d %11.2f  %s / %s" % (v / 1e6, c, (v / c) / 1000.0, th, n))
        print()

    print("INCLUSIVE DURATION BY CATEGORY (overlapping; for orientation only)")
    for c, v in sorted(cat.items(), key=lambda r: -r[1])[:14]:
        print("  %10.2f s  %s" % (v / 1e6, c))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
