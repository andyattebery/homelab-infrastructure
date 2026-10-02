#!/usr/bin/env python3
"""Sample where a Chromium renderer's memory is going, once per interval, as CSV.

Answers one question: when RSS grows, WHICH pool grows with it?

  JS heap climbs with RSS      -> a JavaScript leak. `--js-flags=--max-old-space-size=N` can
                                  bound it: the page OOMs instead of the container wedging.
  nodes/listeners climb        -> detached DOM retained by listeners. A heap snapshot in DevTools
                                  will name the retainer; no flag helps.
  neither climbs with RSS      -> canvas backing stores, decoded images or GPU transfer buffers.
                                  Not reachable from the JS heap and not capped by V8 flags.

WHY A WEBSOCKET CLIENT IS INLINE HERE. CDP's only transport for commands is a WebSocket, and this
container has neither `websocket-client` nor `websockets`. Installing a dependency on the host to
run a diagnostic is worse than 40 lines of framing: the handshake is a plain HTTP upgrade and the
only frames needed are single text frames. No dependency, nothing to install, nothing to remove.

WHY CDP AND NOT `performance.memory`. `Runtime.getHeapUsage` returns usedSize/totalSize directly
and precisely. `performance.memory` is bucketed unless Chromium is launched with
`--enable-precise-memory-info`, so reading it would have meant a second launch flag AND a
page-side `Runtime.evaluate`, to get a coarser number.

Usage, on the container:
    chromium-memory-watch.py sample  --out FILE [--port 9222] [--interval 30] [--match birbplay]
    chromium-memory-watch.py report  --out FILE
"""

import argparse
import base64
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.request


# ---------------------------------------------------------------------------------------------
# Minimal CDP client. Text frames only, no continuation, no compression -- which is all Chromium
# sends for these commands.
# ---------------------------------------------------------------------------------------------
class CDP:
    def __init__(self, ws_url, timeout=15):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)$", ws_url)
        if not m:
            raise ValueError("unparseable websocket url: %s" % ws_url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
             % (path, host, port, key)).encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise IOError("connection closed during handshake")
            head += chunk
        if b"101" not in head.split(b"\r\n")[0]:
            raise IOError("upgrade refused: %s" % head.split(b"\r\n")[0].decode(errors="replace"))
        self._id = 0
        self._buf = b""

    def _send(self, payload):
        data = payload.encode()
        n = len(data)
        # Client frames MUST be masked (RFC 6455 5.1); an unmasked one is closed on sight.
        mask = os.urandom(4)
        if n < 126:
            hdr = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv_frame(self):
        def need(k):
            while len(self._buf) < k:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise IOError("connection closed")
                self._buf += chunk
        need(2)
        b1, b2 = self._buf[0], self._buf[1]
        ln = b2 & 0x7F
        off = 2
        if ln == 126:
            need(4); ln = struct.unpack("!H", self._buf[2:4])[0]; off = 4
        elif ln == 127:
            need(10); ln = struct.unpack("!Q", self._buf[2:10])[0]; off = 10
        need(off + ln)
        payload = self._buf[off:off + ln]
        self._buf = self._buf[off + ln:]
        return b1 & 0x0F, payload

    def call(self, method, params=None):
        self._id += 1
        want = self._id
        self._send(json.dumps({"id": want, "method": method, "params": params or {}}))
        deadline = time.time() + 20
        while time.time() < deadline:
            opcode, payload = self._recv_frame()
            if opcode == 0x8:
                raise IOError("server closed the websocket")
            if opcode != 0x1:
                continue
            msg = json.loads(payload.decode("utf-8", "replace"))
            # Events carry no "id"; skip them rather than mistaking one for a reply.
            if msg.get("id") != want:
                continue
            if "error" in msg:
                raise IOError("%s failed: %s" % (method, msg["error"]))
            return msg.get("result", {})
        raise IOError("no reply to %s within 20s" % method)

    def call_streaming(self, method, params, event, sink):
        """Call `method`, writing every `event`'s .chunk to `sink` until the reply arrives.

        A heap snapshot is delivered as a long run of HeapProfiler.addHeapSnapshotChunk events
        and only THEN the reply to takeHeapSnapshot. call() drops events, so it would block
        forever here and discard the entire snapshot on the way.
        """
        self._id += 1
        want = self._id
        self._send(json.dumps({"id": want, "method": method, "params": params or {}}))
        chunks = 0
        # No wall-clock deadline: a snapshot of a large heap legitimately takes minutes, and
        # timing out mid-stream would leave a truncated file that parses as valid-looking JSON.
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x8:
                raise IOError("server closed the websocket after %d chunks" % chunks)
            if opcode != 0x1:
                continue
            msg = json.loads(payload.decode("utf-8", "replace"))
            if msg.get("method") == event:
                sink.write(msg["params"]["chunk"])
                chunks += 1
                continue
            if msg.get("id") == want:
                if "error" in msg:
                    raise IOError("%s failed: %s" % (method, msg["error"]))
                return chunks

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def find_target(port, match):
    with urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=10) as r:
        targets = json.load(r)
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if match:
        hit = [t for t in pages if match.lower() in (t.get("url", "") + t.get("title", "")).lower()]
        if hit:
            return hit[0]
    # No match: the biggest real page is the best guess, but say so rather than pretend.
    real = [t for t in pages if not t.get("url", "").startswith(("chrome://", "devtools://"))]
    return (real or pages or [None])[0]


def biggest_renderer():
    """RSS of the largest renderer, in kB, with its pid.

    The largest renderer is the game: on this host every other Chromium process was measured
    under 65 MB while the leaking one reached 6.86 GB. Mapping a CDP target to its pid exactly
    would need Target.getTargets plus SystemInfo.getProcessInfo, and buys nothing over picking
    the biggest.
    """
    best = (0, None)
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
            if "--type=renderer" not in cmd:
                continue
            with open("/proc/%s/statm" % pid) as f:
                rss_pages = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue
        rss_kb = rss_pages * (os.sysconf("SC_PAGE_SIZE") // 1024)
        if rss_kb > best[0]:
            best = (rss_kb, pid)
    return best


def container_memory():
    for path in ("/sys/fs/cgroup/memory.current",):
        try:
            with open(path) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            pass
    return 0


FIELDS = ["iso", "unix", "renderer_pid", "renderer_rss_kb", "js_used", "js_total",
          "dom_documents", "dom_nodes", "dom_listeners", "container_bytes"]


def sample_once(port, match):
    t = find_target(port, match)
    if not t:
        raise IOError("no debuggable page on port %d -- is the browser running with "
                      "--remote-debugging-port?" % port)
    c = CDP(t["webSocketDebuggerUrl"])
    try:
        heap = c.call("Runtime.getHeapUsage")
        dom = c.call("Memory.getDOMCounters")
    finally:
        c.close()
    rss_kb, pid = biggest_renderer()
    now = time.time()
    return {
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "unix": "%d" % now,
        "renderer_pid": pid or "",
        "renderer_rss_kb": rss_kb,
        "js_used": int(heap.get("usedSize", 0)),
        "js_total": int(heap.get("totalSize", 0)),
        "dom_documents": dom.get("documents", 0),
        "dom_nodes": dom.get("nodes", 0),
        "dom_listeners": dom.get("jsEventListeners", 0),
        "container_bytes": container_memory(),
    }, t.get("url", "")


def cmd_sample(args):
    fresh = not os.path.exists(args.out) or os.path.getsize(args.out) == 0
    with open(args.out, "a", buffering=1) as fh:
        if fresh:
            fh.write(",".join(FIELDS) + "\n")
        first = True
        while True:
            try:
                row, url = sample_once(args.port, args.match)
                fh.write(",".join(str(row[k]) for k in FIELDS) + "\n")
                if first:
                    print("watching %s -> %s" % (url or "<unknown page>", args.out), flush=True)
                    first = False
            except Exception as exc:
                # Never die: the renderer being killed, or the page reloading, is exactly the
                # event worth surviving to record what came after.
                fh.write(",".join(["%s" % time.strftime("%Y-%m-%dT%H:%M:%S"), "%d" % time.time()]
                                  + [""] * (len(FIELDS) - 2)) + "\n")
                print("sample failed (recorded as a gap): %s" % exc, file=sys.stderr, flush=True)
            if args.once:
                return 0
            time.sleep(args.interval)


def cmd_report(args):
    rows = []
    with open(args.out) as fh:
        header = fh.readline().strip().split(",")
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) != len(header) or not parts[3]:
                continue
            rows.append(dict(zip(header, parts)))
    if len(rows) < 2:
        print("need at least 2 good samples, have %d" % len(rows))
        return 1

    def g(r, k):
        try:
            return int(r[k])
        except (ValueError, KeyError):
            return 0

    a, b = rows[0], rows[-1]
    span = (g(b, "unix") - g(a, "unix")) / 60.0
    print("samples %d over %.1f min  (%s -> %s)" % (len(rows), span, a["iso"], b["iso"]))
    print()
    print("  %-16s %14s %14s %14s" % ("pool", "first", "last", "growth"))
    for label, key, scale, unit in (
        ("renderer RSS", "renderer_rss_kb", 1024.0, "MB"),
        ("JS heap used", "js_used", 1048576.0, "MB"),
        ("JS heap total", "js_total", 1048576.0, "MB"),
        ("container", "container_bytes", 1048576.0, "MB"),
        ("DOM nodes", "dom_nodes", 1.0, ""),
        ("DOM listeners", "dom_listeners", 1.0, ""),
        ("documents", "dom_documents", 1.0, ""),
    ):
        f, l = g(a, key) / scale, g(b, key) / scale
        print("  %-16s %14.1f %14.1f %+14.1f %s" % (label, f, l, l - f, unit))
    print()

    rss_growth_mb = (g(b, "renderer_rss_kb") - g(a, "renderer_rss_kb")) / 1024.0
    js_growth_mb = (g(b, "js_used") - g(a, "js_used")) / 1048576.0
    if rss_growth_mb < 50:
        print("VERDICT: RSS grew %.0f MB -- too little to attribute. Play longer." % rss_growth_mb)
        return 0
    share = (js_growth_mb / rss_growth_mb * 100.0) if rss_growth_mb else 0.0
    print("RSS grew %.0f MB; the JS heap accounts for %.0f MB of it (%.0f%%)."
          % (rss_growth_mb, js_growth_mb, share))
    if share >= 60:
        print("VERDICT: JS-HEAP LEAK. `--js-flags=--max-old-space-size=N` can bound it -- the page")
        print("         hits an OOM at N instead of the container wedging. A DevTools heap")
        print("         snapshot will name what retains it.")
    elif g(b, "dom_nodes") - g(a, "dom_nodes") > 10000:
        print("VERDICT: DETACHED DOM. Nodes grew %d with the JS heap flat, so nodes are retained"
              % (g(b, "dom_nodes") - g(a, "dom_nodes")))
        print("         outside the measured heap. No launch flag bounds this.")
    else:
        print("VERDICT: NOT THE JS HEAP. Most growth is outside V8 -- canvas backing stores,")
        print("         decoded images or GPU transfer buffers. `--max-old-space-size` would do")
        print("         NOTHING here; bound the process with the unit's MemoryMax instead.")
    return 0


def cmd_snapshot(args):
    """Write a .heapsnapshot for the attached page.

    STREAMED TO DISK, never held in memory. The container this runs on is the one with the memory
    problem -- buffering a snapshot of a multi-GB heap in RAM would be competing with the thing
    being measured, and this repo has already taken that host down once by reading a large file
    whole.

    Taking a snapshot forces a full GC and stops the renderer for seconds. On a live game that is
    a visible hitch. It is also what makes the result meaningful: anything still referenced after
    a forced collection is genuinely retained, not merely uncollected yet.
    """
    t = find_target(args.port, args.match)
    if not t:
        raise IOError("no debuggable page on port %d" % args.port)
    c = CDP(t["webSocketDebuggerUrl"], timeout=600)
    try:
        rss_kb, pid = biggest_renderer()
        print("page: %s" % (t.get("url") or "<unknown>"), flush=True)
        print("renderer pid %s, RSS %.0f MB -- forcing GC and writing the snapshot"
              % (pid, rss_kb / 1024.0), flush=True)
        c.call("HeapProfiler.enable")
        with open(args.out, "w") as sink:
            chunks = c.call_streaming(
                "HeapProfiler.takeHeapSnapshot",
                {"reportProgress": False, "treatGlobalObjectsAsRoots": True,
                 "captureNumericValue": False},
                "HeapProfiler.addHeapSnapshotChunk", sink)
        size = os.path.getsize(args.out)
        print("wrote %s (%.1f MB, %d chunks)" % (args.out, size / 1048576.0, chunks))
        if size < 1024:
            print("WARNING: that is too small to be a real snapshot", file=sys.stderr)
            return 1
    finally:
        c.close()
    return 0


def main(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--out", required=True)
    s.add_argument("--port", type=int, default=9222)
    s.add_argument("--interval", type=int, default=30)
    s.add_argument("--match", default="")
    s.add_argument("--once", action="store_true")
    s.set_defaults(func=cmd_sample)
    n = sub.add_parser("snapshot")
    n.add_argument("--out", required=True)
    n.add_argument("--port", type=int, default=9222)
    n.add_argument("--match", default="")
    n.set_defaults(func=cmd_snapshot)
    r = sub.add_parser("report")
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_report)
    args = p.parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
