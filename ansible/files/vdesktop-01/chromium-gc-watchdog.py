#!/usr/bin/env python3
"""Force a Chromium major GC when the game's renderer grows past a threshold.

WHY THIS EXISTS, in numbers measured on this host 2026-10-02:

  the game churns            12.5 MB/min of canvas garbage while being played
  V8 collects it             never, on its own
  a forced major GC frees    776 MB in 0.3 s (98.9% of what had accumulated)
  the floor it leaves        rises 9 MB/h -- ~32 days to the container ceiling
  without this              ~18 h to the ceiling, then the container WEDGES

The wedge is the part worth preventing. PVE sets `memory.high` just under `memory.max`, so the
cgroup is throttled into reclaim rather than OOM-killed: 34,494 high events and `oom_kill 0` were
recorded. Nothing inside the container recovers from that -- it needs `pct` from the node.

WHY V8 NEVER COLLECTS. Major GCs are scheduled on JS-HEAP growth. This page's heap sits at ~50 MB
while several hundred MB of canvas backing store rides along as external memory that does not
weigh on that decision. By V8's own accounting there is never a reason to collect, so it doesn't.
Measured: `[anon:v8]` 484 MB with the JS heap at 64 MB; a forced GC took `[anon:v8]` to 116 MB.

WHAT THIS IS NOT. Not a fix for a leak -- there is no leak. The retained set is STABLE: two heap
snapshots an hour apart, with an hour of play between them, showed 984 -> 994 canvas contexts and
122.3 -> 122.4 MB of backing stores. Everything else is ordinary garbage that simply never gets
collected.

Ordinary behaviour is to do nothing: below the threshold it connects, measures, and exits.
"""

import base64
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.request

PORT = int(os.environ.get("GC_WATCHDOG_PORT", "9222"))
# Default 2 GB. From a ~460 MB floor at 12.5 MB/min this is about two hours of active play
# between collections, i.e. one sub-second hitch every couple of hours. Low enough to leave the
# container's other ~6 GB untouched, high enough not to interrupt constantly.
THRESHOLD_MB = int(os.environ.get("GC_WATCHDOG_THRESHOLD_MB", "2048"))
MATCH = os.environ.get("GC_WATCHDOG_MATCH", "")


def log(msg):
    # stdout is the journal: this runs as a systemd unit. Flushed because a oneshot that exits
    # immediately can otherwise lose buffered output.
    print(msg, flush=True)


class CDP:
    """Minimal CDP client. Vendored rather than shared with the diagnostic tooling in
    scripts/vdesktop-01/: that is an operator tool run from a workstation, this is deployed host
    state with a different lifecycle. Sixty lines of duplication beats deploying a library for one
    consumer."""

    def __init__(self, ws_url, timeout=30):
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
             % (path, host, port, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            ch = self.sock.recv(1)
            if not ch:
                raise IOError("closed during handshake")
            head += ch
        if b"101" not in head.split(b"\r\n")[0]:
            raise IOError("upgrade refused: %s" % head.split(b"\r\n")[0].decode("replace"))
        self._id = 0
        self._buf = b""

    def _send(self, payload):
        data = payload.encode()
        n = len(data)
        mask = os.urandom(4)  # client frames must be masked (RFC 6455 5.1)
        if n < 126:
            hdr = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _frame(self):
        def need(k):
            while len(self._buf) < k:
                ch = self.sock.recv(65536)
                if not ch:
                    raise IOError("closed")
                self._buf += ch
        need(2)
        b1, b2 = self._buf[0], self._buf[1]
        ln = b2 & 0x7F
        off = 2
        if ln == 126:
            need(4); ln = struct.unpack("!H", self._buf[2:4])[0]; off = 4
        elif ln == 127:
            need(10); ln = struct.unpack("!Q", self._buf[2:10])[0]; off = 10
        need(off + ln)
        p = self._buf[off:off + ln]
        self._buf = self._buf[off + ln:]
        return b1 & 0x0F, p

    def call(self, method, params=None):
        self._id += 1
        want = self._id
        self._send(json.dumps({"id": want, "method": method, "params": params or {}}))
        deadline = time.time() + 60
        while time.time() < deadline:
            op, payload = self._frame()
            if op == 0x8:
                raise IOError("server closed the websocket")
            if op != 0x1:
                continue
            msg = json.loads(payload.decode("utf-8", "replace"))
            if msg.get("id") != want:
                continue  # an event; not our reply
            if "error" in msg:
                raise IOError("%s: %s" % (method, msg["error"]))
            return msg.get("result", {})
        raise IOError("no reply to %s in 60s" % method)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def biggest_renderer():
    """(rss_kb, pid) of the largest renderer. The game's tab is always the largest by a wide
    margin -- every other Chromium process was measured under 85 MB while this one reached
    6.86 GB."""
    best = (0, None)
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                if b"--type=renderer" not in f.read():
                    continue
            with open("/proc/%s/statm" % pid) as f:
                pages = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kb = pages * (os.sysconf("SC_PAGE_SIZE") // 1024)
        if kb > best[0]:
            best = (kb, pid)
    return best


def find_page():
    # localhost, not 127.0.0.1 -- and NOT curl, which is not installed on this host and whose
    # absence reads as a connection failure.
    with urllib.request.urlopen("http://localhost:%d/json" % PORT, timeout=10) as r:
        targets = json.load(r)
    pages = [t for t in targets
             if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
             and not (t.get("url") or "").startswith(("chrome://", "devtools://"))]
    if MATCH:
        hit = [t for t in pages if MATCH.lower() in (t.get("url", "") + t.get("title", "")).lower()]
        if hit:
            return hit[0]
    return pages[0] if pages else None


def main():
    rss_kb, pid = biggest_renderer()
    rss_mb = rss_kb / 1024.0
    if pid is None:
        log("no renderer running; nothing to do")
        return 0
    if rss_mb < THRESHOLD_MB:
        log("renderer %s at %.0f MB, under the %d MB threshold; no action" % (pid, rss_mb, THRESHOLD_MB))
        return 0

    try:
        t = find_page()
    except Exception as exc:
        # The browser being down, or the debug port being absent, is not this unit's emergency.
        # Exit 0 so a timer-driven oneshot does not accumulate failed states; the journal carries
        # the reason.
        log("renderer %s at %.0f MB but CDP is unreachable (%s): %s"
            % (pid, rss_mb, type(exc).__name__, exc))
        log("  if this persists, check that the browser still has --remote-debugging-port=%d" % PORT)
        return 0
    if not t:
        log("renderer %s at %.0f MB but no debuggable page found" % (pid, rss_mb))
        return 0

    try:
        c = CDP(t["webSocketDebuggerUrl"])
    except Exception as exc:
        log("could not attach to %s: %s" % (t.get("url"), exc))
        return 0

    try:
        # TWICE, with a pause. One pass can leave objects that only become unreachable once the
        # first pass drops their holders, so a single collection understates the reclaim.
        t0 = time.time()
        c.call("HeapProfiler.collectGarbage")
        time.sleep(2)
        c.call("HeapProfiler.collectGarbage")
        elapsed = time.time() - t0
    except Exception as exc:
        log("GC call failed on %s: %s" % (t.get("url"), exc))
        return 0
    finally:
        c.close()

    time.sleep(5)  # the kernel reports RSS back after V8 returns pages to the OS
    after_kb, _ = biggest_renderer()
    after_mb = after_kb / 1024.0
    log("renderer %s %.0f -> %.0f MB (freed %.0f MB) in %.1fs on %s"
        % (pid, rss_mb, after_mb, rss_mb - after_mb, elapsed, t.get("url") or "?"))
    if after_mb > THRESHOLD_MB:
        # Expected only if the RETAINED set has genuinely grown, which measurement says it does
        # not (984 -> 994 contexts over an hour). Worth a loud line if it ever happens.
        log("  WARNING: still above the threshold after collecting. The retained set may be")
        log("  growing, which this watchdog cannot fix -- re-measure the floor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
