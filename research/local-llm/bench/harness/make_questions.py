#!/usr/bin/env python3
"""Build the shootout's question set from SimpleQA. Emits JSON on stdout.

Runs INSIDE the LDR container, because the dataset loader ships with the package:

    ssh docker-01 'bash -c "docker exec -i local-deep-research python3 - --n 20"' \
        < research/local-llm/bench/harness/make_questions.py > research/local-llm/bench/harness/testdata/questions.json

WHY SIMPLEQA AND NOT OUR SEVEN QUERIES
--------------------------------------
The metric is **correctness**, and correctness needs ground truth. Our seven queries
(research/local-llm/bench/queries.md) were designed to measure Onyx's *search rate* and mostly have no
verifiable answer, which makes them a poor tuning set and an expensive one to grade. SimpleQA
questions ship with a short known answer, so grading is cheap and repeatable, and the numbers
are comparable to upstream's published figures.

The seven queries keep their job as the **confirmation** set for the winning config, where
multi-source synthesis is what is being judged.

WHY UPSTREAM'S LOADER RATHER THAN FETCHING THE CSV
--------------------------------------------------
`BenchmarkDataset.load()` owns the download, the CSV parsing, the field normalisation
(`problem`/`answer` -> `correct_answer`), and — critically — the **seeded sampling**. Drawing
our own sample would silently produce a different question set from any upstream comparison,
and `docs/BENCHMARKING.md:93-101` makes the seed part of the experimental condition: change
it and rows stop being comparable.

No auth: the dataset is a public CSV
(`datasets/simpleqa.py:get_default_dataset_path` -> openaipublic.blob.core.windows.net).
"""

from __future__ import annotations

import argparse
import json
import sys

# BENCHMARKING.md:98 — "always use --seed 42 (or any fixed seed) consistently across
# compared runs". Fixed here rather than defaulted at the call site so it cannot drift.
SEED = 42


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=20,
                    help="examples to sample. BENCHMARKING.md:71: n=20 gives a +/-17-21%% "
                         "Wilson margin — enough to eliminate, not to rank")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--dataset", default="simpleqa")
    a = ap.parse_args()

    from local_deep_research.benchmarks.datasets import DatasetRegistry

    ds = DatasetRegistry.create_dataset(dataset_id=a.dataset, num_examples=a.n,
                                        seed=a.seed)
    examples = ds.load()
    print(f"loaded {len(examples)} {a.dataset} examples (seed={a.seed})", file=sys.stderr)

    out = []
    for i, ex in enumerate(examples):
        q = ds.get_question(ex)
        ans = ds.get_answer(ex)
        if not q or not ans:
            # A question with no ground truth cannot be graded, and silently keeping it
            # would inflate the denominator with an unscorable row.
            print(f"  skipping example {i}: missing question or answer", file=sys.stderr)
            continue
        out.append({
            # Stable, seed-derived id so the same question keeps the same id across runs —
            # which is what makes the JSONL resumable and two runs comparable.
            "id": f"{a.dataset}-s{a.seed}-{i:04d}",
            "question": q,
            "correct_answer": ans,
        })

    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    print(f"wrote {len(out)} questions", file=sys.stderr)
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
