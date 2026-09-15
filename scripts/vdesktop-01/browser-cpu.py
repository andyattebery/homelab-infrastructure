"""Sample per-thread CPU for a browser on a remote host, engine-agnostically.

Fed to `sudo python3 -` over ssh by browser-cpu.sh. Args: <cmdline-match> <seconds>

The point is comparison between engines. Firefox and Chromium name their threads completely
differently -- Renderer/SwComposite/WRWorker versus CrRendererMain/Compositor/
CompositorTileWorker -- so per-thread breakdowns are not comparable across engines. The TOTAL
is: core-seconds burned rendering the same thing is the same measurement either way.

Must run as root. An unprivileged caller can only read its OWN processes' /proc/<pid>/task,
and silently reports nothing at all rather than failing -- which is exactly how an earlier
measurement in this work went wrong.
"""
import collections
import os
import sys
import time

MATCH = sys.argv[1] if len(sys.argv) > 1 else "firefox"
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

# Thread-name fragments that indicate rasterisation/compositing rather than script. Used only
# to summarise; the raw table is printed regardless so the classification can be checked.
PAINTY = ("render", "composit", "swcomposite", "wrworker", "wrrender", "wrscene", "tile", "viz",
          "skia", "raster", "gpu")


def snapshot():
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                cmd = fh.read().decode("utf8", "replace")
        except OSError:
            continue
        if MATCH not in cmd:
            continue
        taskdir = "/proc/%s/task" % pid
        try:
            tids = os.listdir(taskdir)
        except OSError:
            continue
        for tid in tids:
            try:
                with open("%s/%s/comm" % (taskdir, tid)) as fh:
                    name = fh.read().strip()
                with open("%s/%s/stat" % (taskdir, tid)) as fh:
                    stat = fh.read()
                # comm can contain spaces and parens, so parse after the LAST ')'
                fields = stat[stat.rindex(")") + 2:].split()
                out[(pid, tid)] = (name, int(fields[11]) + int(fields[12]))
            except (OSError, ValueError, IndexError):
                pass
    return out


if os.geteuid() != 0:
    sys.stderr.write("must run as root, or this silently measures nothing\n")
    sys.exit(2)

first = snapshot()
if not first:
    sys.stderr.write("no processes matching %r are running\n" % MATCH)
    sys.exit(1)
time.sleep(SECONDS)
second = snapshot()

hz = os.sysconf("SC_CLK_TCK")
per_thread = collections.Counter()
for key, (name, ticks) in second.items():
    if key in first:
        delta = ticks - first[key][1]
        if delta > 0:
            per_thread[name] += delta

total = sum(per_thread.values())
if not total:
    sys.stderr.write("matched %d threads but none used CPU in %.1fs -- is it idle?\n"
                     % (len(second), SECONDS))
    sys.exit(1)

core_seconds = total / hz
print("match=%r  window=%.1fs" % (MATCH, SECONDS))
print("TOTAL: %.2f core-seconds  (%.0f%% of one core)"
      % (core_seconds, 100 * core_seconds / SECONDS))

painty = sum(v for k, v in per_thread.items() if any(p in k.lower() for p in PAINTY))
print("  raster/composite-ish threads: %3.0f%% of that" % (100.0 * painty / total))
print("  everything else:              %3.0f%%" % (100.0 - 100.0 * painty / total))
print()
print("%-24s%8s  %6s" % ("thread", "%CPU", "share"))
for name, delta in per_thread.most_common(15):
    print("%-24s%7.0f%%  %5.0f%%"
          % (name, 100.0 * delta / hz / SECONDS, 100.0 * delta / total))
