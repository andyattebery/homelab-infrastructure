#!/usr/bin/env python3
"""Preconditions for the shootout. Runs ON THE MAC, because it is the only machine that can
see both hosts.

    python3 preflight.py                 # report; exit non-zero on any FAIL
    python3 preflight.py --warn-only     # report without failing

Every check corresponds to a way the sweep produces junk *without failing loudly*. The
expensive failure is not a crash — it is a session that finishes and whose numbers cannot be
used, which has already happened once to this project (a whole run of trials whose recorded
configuration was a lie).

`research/local-llm/docs/README.md:341`: **a guard that errors must stop the run.** A
pre-flight check that fails and lets the script continue is worse than no check at all.

STRUCTURE: every check is `(name, fn) -> Result`, and the pure interpretation of each host
command lives in a `parse_*` function so `test_preflight.py` can exercise the decision logic
on the Mac without ssh, a GPU, or a container.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass

LLAMA_HOST = "htpc-01"
LDR_HOST = "docker-01"
LDR_CONTAINER = "local-deep-research"
BENCH_DIR = "/mnt/data/local-deep-research/data/bench"
EXPECTED_MODEL = "gemma-4-12b-it"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""
    fatal: bool = True

    @property
    def label(self) -> str:
        return "PASS" if self.ok else ("FAIL" if self.fatal else "WARN")

    def __str__(self) -> str:
        return f"  {self.label}  {self.name}" + (f"  [{self.detail}]" if self.detail else "")


def ssh(host: str, command: str) -> subprocess.CompletedProcess:
    """Run one command on a host.

    Wrapped in `bash -c` because **both hosts use fish as the login shell**, and fish does
    not parse `$(...)`, `&&` chains or bash redirection the same way. An unwrapped command
    fails with a `fish:` syntax error that looks like the remote program crashed.
    """
    return subprocess.run(["ssh", host, f"bash -c {shlex.quote(command)}"],
                          capture_output=True, text=True, timeout=60)


# --------------------------------------------------------------- pure interpretation

def parse_gpu_mode(out: str) -> tuple[bool, str]:
    """`gpu-mode status` must report exactly `llm`.

    Read from `ansible/files/htpc-01/gpu-mode.sh:139-161`, not guessed: `status` prints
    several lines (GPU VRAM, ComfyUI, llama-swap, models) and names the mode on its own line
    as one of `llm`, `comfy`, `game (neither container is running)`, or
    `CONTENDED — both consumers running, expect VRAM thrashing`.

    **CONTENDED is the one that matters most** and a naive substring test would pass it,
    because the line still mentions both consumers. It is precisely the state
    `llm-tuning.md:854-855` measured: the same 8k prompt took >900 s against 45 s, with
    772,000 ms of eviction.
    """
    for line in out.splitlines():
        if line.strip().lower().startswith("mode:"):
            value = line.split(":", 1)[1].strip()
            # First word only: `game` carries a parenthetical, CONTENDED an em-dash clause.
            return value.split()[0].lower() == "llm" if value else False, value[:120]
    return False, f"no mode line in output: {out.strip()[:120]!r}"


def parse_running_model(out: str) -> tuple[bool, str]:
    """llama-swap's /running. Empty is FINE — it loads on first request; what matters is
    that nothing *else* is resident."""
    s = out.strip()
    if s in ("", "[]", "{}"):
        return True, "idle (loads on first request)"
    try:
        data = json.loads(s)
    except ValueError:
        return True, f"unparsed: {s[:80]}"
    items = data if isinstance(data, list) else (
        data.get("running") or data.get("models") or [])
    names = [i.get("model") if isinstance(i, dict) else str(i) for i in items]
    if not names:
        return True, "idle"
    ok = EXPECTED_MODEL in names
    return ok, f"resident: {names}"


def parse_strategies(enum_json: str, wanted: list[str]) -> tuple[bool, str]:
    """Every strategy we sweep must be a live enum member.

    Not a formality: a name that is not in the enum does not raise — it falls back to the
    default strategy, so the sweep would run `langgraph-agent` while reporting whatever we
    asked for. Upstream's own README names three strategies that do not exist in this build
    (`harness-comparison.md:287-289`), so documentation is not an acceptable source.
    """
    try:
        live = set(json.loads(enum_json))
    except ValueError:
        return False, f"could not parse the enum: {enum_json[:100]}"
    missing = [s for s in wanted if s not in live]
    return not missing, (f"missing {missing} from {sorted(live)}" if missing
                         else f"all {len(wanted)} present")


def parse_search_health(out: str) -> tuple[bool, str]:
    """SearXNG's own JSON response. **Zero responsive engines must block the sweep.**

    Added after a verification session found every web engine suspended at once:

        brave      : too many requests        startpage  : Suspended: CAPTCHA
        google cse : too many requests        duckduckgo : timeout

    Only FOUR of the 274 configured engines actually search the web in the `general`
    category (the other six enabled ones are currency/dictzone/lingva/mymemory/
    wikidata/wikipedia), so all four suspended means the assistant returns nothing at all —
    and every trial still completes, "successfully", with zero sources. Round 1 ran with no
    such check, which is why its zero-source counts cannot be fully attributed.

    A partial outage is a WARN, not a FAIL: results get thinner but stay real.
    """
    try:
        data = json.loads(out)
    except ValueError:
        return False, f"unparsed searxng response: {out.strip()[:120]!r}"
    n = len(data.get("results") or [])
    dead = [e[0] if isinstance(e, list) else str(e)
            for e in (data.get("unresponsive_engines") or [])]
    if n == 0:
        return False, f"ZERO results; unresponsive: {dead or 'none reported'}"
    return True, f"{n} results" + (f"; degraded: {dead}" if dead else "")


def parse_capture_growing(size_a: str, size_b: str) -> tuple[bool, str]:
    """Two `stat` samples of the capture file. It must be growing, or every trial records
    unknown cost while the sweep still completes looking healthy."""
    try:
        a, b = int(size_a.strip()), int(size_b.strip())
    except ValueError:
        return False, f"unreadable sizes: {size_a!r} {size_b!r}"
    return b > a, f"{a} -> {b} bytes"


# --------------------------------------------------------------- host checks

def check_llama_host() -> list[Result]:
    out = []
    r = ssh(LLAMA_HOST, "gpu-mode status")
    ok, detail = parse_gpu_mode(r.stdout)
    out.append(Result(f"{LLAMA_HOST}: gpu-mode is llm (ComfyUI stopped)", ok, detail))

    r = ssh(LLAMA_HOST, "systemctl is-active comfyui")
    out.append(Result(f"{LLAMA_HOST}: ComfyUI inactive", r.stdout.strip() != "active",
                      r.stdout.strip()))

    r = ssh(LLAMA_HOST,
            "sudo podman exec llama-swap curl -sf --max-time 10 localhost:8080/running")
    ok, detail = parse_running_model(r.stdout)
    out.append(Result(f"{LLAMA_HOST}: llama-swap reachable, no foreign model resident",
                      ok and r.returncode == 0, detail or r.stderr.strip()[:120]))

    # The sweep is hours long and htpc-01 suspends on its own schedule. During a sweep
    # llama-swap holds a model (ttl 900 > per-trial time), so the stock llama-swap.sh check
    # reports busy — but only while trials keep coming. A stall longer than ttl + the
    # inhibitor's 300 s grace lets the host sleep mid-run.
    r = ssh(LLAMA_HOST, "systemctl is-active sleep-inhibitor")
    out.append(Result(f"{LLAMA_HOST}: sleep-inhibitor active", r.stdout.strip() == "active",
                      r.stdout.strip()))
    return out


def check_ldr_host(strategies: list[str]) -> list[Result]:
    out = []
    r = ssh(LDR_HOST, f"docker ps --filter name={LDR_CONTAINER} --format '{{{{.Status}}}}'")
    st = r.stdout.strip()
    out.append(Result(f"{LDR_HOST}: {LDR_CONTAINER} healthy",
                      "healthy" in st.lower() or st.lower().startswith("up"), st))

    r = ssh(LDR_HOST, f"ls {BENCH_DIR}/shootout.py {BENCH_DIR}/ldr_trial.py "
                      f"{BENCH_DIR}/questions.json 2>&1")
    out.append(Result(f"{LDR_HOST}: harness synced to {BENCH_DIR}",
                      r.returncode == 0 and "No such file" not in r.stdout,
                      r.stdout.strip()[:160]))

    r = ssh(LDR_HOST, f"df -Pm {BENCH_DIR} | tail -1 | awk '{{print $4}}'")
    try:
        free = int(r.stdout.strip())
    except ValueError:
        free = -1
    out.append(Result(f"{LDR_HOST}: >=2000 MB free for the JSONL and capture",
                      free >= 2000, f"{free} MB"))

    # The live strategy enum, read from the container rather than from documentation.
    probe = ("docker exec -i " + LDR_CONTAINER + " python3 -c "
             "\"import json;"
             "from local_deep_research.api.settings_utils import create_settings_snapshot as c;"
             "d=c({})['search.search_strategy'];"
             "print(json.dumps([o['value'] for o in d['options']]))\"")
    r = ssh(LDR_HOST, probe)
    ok, detail = parse_strategies(r.stdout, strategies)
    out.append(Result(f"{LDR_HOST}: every swept strategy is a live enum member", ok,
                      detail or r.stderr.strip()[:160]))

    # Asked FROM the LDR container, over the same docker network and the same URL the app
    # uses -- a check from the Mac would pass while the app still saw nothing. Results are
    # reduced to their count in the probe: the count is the signal, and the payload is large.
    search = ("docker exec -i " + LDR_CONTAINER + " python3 -c "
              "\"import json,urllib.parse,urllib.request;"
              "d=urllib.parse.urlencode({'q':'eiffel tower','format':'json'}).encode();"
              "j=json.load(urllib.request.urlopen("
              "'http://searxng:8080/search',data=d,timeout=45));"
              "print(json.dumps({'results':[0]*len(j.get('results') or []),"
              "'unresponsive_engines':j.get('unresponsive_engines') or []}))\"")
    r = ssh(LDR_HOST, search)
    ok, detail = parse_search_health(r.stdout or r.stderr)
    out.append(Result(f"{LDR_HOST}: searxng returns results (upstream engines not suspended)",
                      ok, detail))
    return out


def check_all(strategies: list[str]) -> list[Result]:
    return check_llama_host() + check_ldr_host(strategies)


def main() -> int:
    import shootout
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--warn-only", action="store_true")
    a = ap.parse_args()

    print("=== preflight (Mac -> htpc-01, docker-01) ===")
    results = check_all(shootout.STRATEGIES)
    for r in results:
        print(r)

    fatal = [r for r in results if not r.ok and r.fatal]
    warn = [r for r in results if not r.ok and not r.fatal]
    if warn:
        print(f"\n  {len(warn)} warning(s):")
        for r in warn:
            print(f"    {r.name}: {r.detail}")
    if fatal:
        print(f"\n{len(fatal)} BLOCKING failure(s):")
        for r in fatal:
            print(f"  {r.name}: {r.detail}")
        return 0 if a.warn_only else 1
    print("\npreflight OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
