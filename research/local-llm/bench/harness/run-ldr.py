#!/usr/bin/env python3
"""
Run the fixed query set through local-deep-research and emit a result row.

Runs INSIDE the LDR container -- the package is installed there and
programmatic_mode bypasses auth entirely, so no credentials are involved:

    ssh docker-01 'docker exec -i local-deep-research python3 - --strategy source-based' \
        < research/local-llm/bench/harness/run-ldr.py

Companion to ../docs/harness-comparison.md (the methodology) and
../queries.md (the input). Append output rows to results.md.

Why this file exists: the LDR calls were hand-written three times during the first
session before anyone wrote them down. research/local-llm/bench/llama-swap/ exists for the same reason.
"""

import argparse
import json
import sys
import time

# The seven questions from ../queries.md, in order. Kept here verbatim so a run is
# reproducible from this file alone; if queries.md changes, change this and re-baseline.
QUERIES = [
    ("Q1-home-assistant", "What is the most recent stable release of Home Assistant, and what was its headline feature?"),
    ("Q2-caddy-traefik", "Compare Caddy and Traefik for reverse-proxying a homelab: config format, ACME certificate handling, and Docker service discovery."),
    ("Q3-rocm-maintainer", "Who maintains llama.cpp's HIP/ROCm backend, and what have they merged in the last month?"),
    ("Q4-unanswerable", "What is the measured p99 query latency of Onyx's OpenSearch backend on an RTX A4000 with a 50,000-document index?"),
    ("Q5-flash-attention", "Explain the difference between flash attention and standard scaled dot-product attention, and why flash attention uses less memory."),
    ("Q6-zfs-btrfs", "Summarize the tradeoffs between ZFS and btrfs for a home NAS: data integrity guarantees, RAID/parity options, memory requirements, and the snapshot and send/receive workflow. Cite your sources."),
    ("Q7-battlemage", "Research to make a table comparing the intel arc battlemage gpu models including the pro ones"),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default="source-based",
                   help="source-based | focused-iteration | focused-iteration-standard "
                        "| topic-organization | langgraph-agent (langgraph-agent is the "
                        "AGENTIC default and reproduces Onyx's defect -- see the docs)")
    p.add_argument("--model", default="gemma-4-12b-it")
    p.add_argument("--search-tool", default="searxng")
    p.add_argument("--iterations", type=int, default=1)
    p.add_argument("--questions", type=int, default=2, help="questions per iteration")
    p.add_argument("--temperature", type=float, default=1.0)
    p.add_argument("--only", default=None,
                   help="run a single query by id prefix, e.g. Q6")
    args = p.parse_args()

    from local_deep_research.api import quick_summary
    from local_deep_research.api.settings_utils import create_settings_snapshot

    # llm.model MUST be in the snapshot: LDR_LLM_MODEL is deliberately unset in the
    # compose so the web UI keeps its model selector. Without it you get
    # "OpenAI-Compatible Endpoint model not configured".
    settings = create_settings_snapshot({
        "search.tool": args.search_tool,
        "llm.provider": "openai_endpoint",
        "llm.model": args.model,
    })

    selected = [q for q in QUERIES if not args.only or q[0].startswith(args.only)]
    rows, raw = [], []

    for qid, query in selected:
        t0 = time.time()
        rec = {"id": qid, "strategy": args.strategy, "model": args.model}
        try:
            r = quick_summary(
                query=query,
                settings_snapshot=settings,
                search_strategy=args.strategy,
                iterations=args.iterations,
                questions_per_iteration=args.questions,
                temperature=args.temperature,
                programmatic_mode=True,
            )
            summary = r.get("summary") or ""
            questions = r.get("questions") or {}
            rec.update(
                ok=True,
                wall_s=round(time.time() - t0, 1),
                # THE METRIC: a harness that never searches reports 0 here.
                sources=len(r.get("sources") or []),
                # `questions` comes back EMPTY for source-based (measured), so it is not
                # a usable search signal -- `sources` is. Kept for the strategies where
                # it is populated.
                searches=sum(len(v) for v in questions.values()) if isinstance(questions, dict) else None,
                iterations_ran=r.get("iterations"),
                findings=len(r.get("findings") or []),
                summary_chars=len(summary),
                research_id=r.get("research_id"),
            )
            raw.append({"id": qid, "result": r})
        except Exception as e:  # a failed query is a data point, not a reason to stop
            rec.update(ok=False, wall_s=round(time.time() - t0, 1),
                       error=f"{type(e).__name__}: {e}"[:200])
        rows.append(rec)
        print(json.dumps(rec), flush=True)  # flush: docker exec buffers otherwise

    ok = [r for r in rows if r.get("ok")]
    searched = [r for r in ok if r.get("sources", 0) > 0]
    print("\n=== SUMMARY ===", flush=True)
    print(f"strategy={args.strategy} model={args.model} "
          f"iterations={args.iterations} questions={args.questions} temp={args.temperature}")
    print(f"completed {len(ok)}/{len(rows)}   SEARCHED {len(searched)}/{len(ok)}   "
          f"total_wall_s={round(sum(r['wall_s'] for r in rows), 1)}")
    print("\n--- paste into results.md ---")
    print(f"| local-deep-research | {args.model} | {args.strategy} | "
          f"{len(searched)}/{len(ok)} | "
          f"{round(sum(r['wall_s'] for r in ok) / max(len(ok), 1))} s | "
          f"it={args.iterations} q={args.questions} temp={args.temperature} |")
    print("\n--- RAW (save under runs/) ---")
    print(json.dumps(raw, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
