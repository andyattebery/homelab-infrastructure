#!/usr/bin/env python3
"""
Resumable parameter sweep for local-deep-research.

Runs INSIDE the LDR container (programmatic_mode bypasses auth entirely):

    ssh docker-01 'docker exec -i local-deep-research python3 - \
        --models gemma-4-12b-it,qwen3.5-9b --iterations 1,2 --questions 2,3' \
        < research/local-llm/bench/harness/run-matrix.py

Methodology: ../docs/ldr-tuning-methodology.md

RESUMABILITY IS THE POINT. A sweep is hours long, the GPU host sleeps, and a dropped ssh
should cost one trial and not a night. So:
  - every completed trial is appended to the JSONL results file IMMEDIATELY and flushed
  - trials are keyed by (model, strategy, iterations, questions, temperature, query_id)
  - on start, completed keys are read back and skipped
Kill it and re-run the identical command to continue where it stopped.
"""

import argparse
import json
import os
import sys
import time

# Results live inside the container's /data (a bind mount), so they survive `docker rm`.
DEFAULT_OUT = "/data/bench/ldr-matrix.jsonl"

# Phase 0 uses a single fixed query so cost is comparable across configs. Deliberately one
# of the set's "must search" cases rather than a throwaway -- cost scales with what the
# pipeline actually does.
COST_MODEL_QUERY = (
    "Q1-home-assistant",
    "What is the most recent stable release of Home Assistant, and what was its "
    "headline feature?",
)

# The full set. Kept in sync with ../queries.md by hand; if that file changes, change this
# and re-baseline rather than silently comparing across different inputs.
QUERIES = [
    COST_MODEL_QUERY,
    ("Q2-caddy-traefik", "Compare Caddy and Traefik for reverse-proxying a homelab: config format, ACME certificate handling, and Docker service discovery."),
    ("Q3-rocm-maintainer", "Who maintains llama.cpp's HIP/ROCm backend, and what have they merged in the last month?"),
    ("Q4-unanswerable", "What is the measured p99 query latency of Onyx's OpenSearch backend on an RTX A4000 with a 50,000-document index?"),
    ("Q5-flash-attention", "Explain the difference between flash attention and standard scaled dot-product attention, and why flash attention uses less memory."),
    ("Q6-zfs-btrfs", "Summarize the tradeoffs between ZFS and btrfs for a home NAS: data integrity guarantees, RAID/parity options, memory requirements, and the snapshot and send/receive workflow. Cite your sources."),
    ("Q7-battlemage", "Research to make a table comparing the intel arc battlemage gpu models including the pro ones"),
]


def key_of(t: dict) -> tuple:
    return (t["model"], t["strategy"], t["iterations"], t["questions"],
            t["temperature"], t["query_id"])


def load_done(path: str) -> set:
    """Completed trial keys. A truncated final line (killed mid-write) is ignored."""
    done = set()
    if not os.path.exists(path):
        return done
    with open(path) as f:
        for line in f:
            try:
                done.add(key_of(json.loads(line)))
            except Exception:
                continue
    return done


def csv(s: str, cast=str) -> list:
    return [cast(x.strip()) for x in s.split(",") if x.strip()]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", default="gemma-4-12b-it")
    p.add_argument("--strategies", default="source-based")
    p.add_argument("--iterations", default="1")
    p.add_argument("--questions", default="2")
    p.add_argument("--temperatures", default="1.0")
    p.add_argument("--search-tool", default="searxng")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--cost-model", action="store_true",
                   help="Phase 0: one fixed query, no grading -- derive calls=f(i,q)")
    p.add_argument("--only", default=None, help="query id prefix, e.g. Q6")
    # NO --timeout. There was one: it was parsed, documented as raising "the 300s library
    # default", and never passed to quick_summary -- so it did nothing. Worse, the 300s
    # figure was LDRClient.quick_research's documented default, and quick_summary is a
    # different function whose timeout behaviour is UNVERIFIED. Removed rather than wired,
    # because a flag that silently does nothing is worse than an absent one. Before a long
    # run, check `inspect.signature(quick_summary)` in the container: if it takes a
    # timeout, add it here; if it does not, the mitigation is external (tmux + resume).
    args = p.parse_args()

    from local_deep_research.api import quick_summary
    from local_deep_research.api.settings_utils import create_settings_snapshot

    queries = [COST_MODEL_QUERY] if args.cost_model else [
        q for q in QUERIES if not args.only or q[0].startswith(args.only)
    ]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    done = load_done(args.out)
    print(f"resuming: {len(done)} trials already complete in {args.out}", flush=True)

    grid = [
        (m, s, i, q, t, qid, text)
        for m in csv(args.models)
        for s in csv(args.strategies)
        for i in csv(args.iterations, int)
        for q in csv(args.questions, int)
        for t in csv(args.temperatures, float)
        for qid, text in queries
    ]
    todo = [g for g in grid
            if (g[0], g[1], g[2], g[3], g[4], g[5]) not in done]
    print(f"grid: {len(grid)} trials, {len(todo)} to run", flush=True)

    for n, (model, strategy, iters, qpi, temp, qid, text) in enumerate(todo, 1):
        # llm.model must be in the snapshot: LDR_LLM_MODEL is intentionally unset in the
        # compose so the web UI keeps its selector.
        settings = create_settings_snapshot({
            "search.tool": args.search_tool,
            "llm.provider": "openai_endpoint",
            "llm.model": model,
        })
        rec = {"model": model, "strategy": strategy, "iterations": iters,
               "questions": qpi, "temperature": temp, "query_id": qid}
        print(f"[{n}/{len(todo)}] {qid} {model} {strategy} i={iters} q={qpi} t={temp}",
              flush=True)
        t0 = time.time()
        try:
            r = quick_summary(
                query=text, settings_snapshot=settings, search_strategy=strategy,
                iterations=iters, questions_per_iteration=qpi, temperature=temp,
                programmatic_mode=True,
            )
            summary = r.get("summary") or ""
            srcs = r.get("sources") or []
            rec.update(
                ok=True, wall_s=round(time.time() - t0, 1),
                # `sources` is the reliable signal; `questions` comes back empty for
                # source-based (measured), so do not depend on it.
                sources=len(srcs),
                findings=len(r.get("findings") or []),
                summary_chars=len(summary),
                research_id=r.get("research_id"),
                # Everything below is required by export-for-grading.py. The QUESTION and
                # the SOURCE URLS must be persisted here -- a grader cannot check whether
                # citations are real from a source *count*, and checking that is the whole
                # point of the `sourced` score.
                question=text,
                source_list=[str(s) for s in srcs][:40],
                summary=summary,
            )
        except Exception as e:
            # A failed trial is a data point. Record and continue -- never abort the sweep.
            rec.update(ok=False, wall_s=round(time.time() - t0, 1),
                       error=f"{type(e).__name__}: {e}"[:300])

        # Append + flush + fsync BEFORE the next trial starts. This is what makes the run
        # resumable; buffering here would lose everything on a kill.
        with open(args.out, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        print(f"    -> ok={rec.get('ok')} sources={rec.get('sources')} "
              f"wall={rec['wall_s']}s", flush=True)

    print("\ndone. summarise with:  python3 - < research/local-llm/bench/harness/summarise.py", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
