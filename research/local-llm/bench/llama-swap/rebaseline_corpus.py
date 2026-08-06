#!/usr/bin/env python3
"""Re-record the prompt-corpus baseline. A deliberate act, never an automatic one.

    python3 rebaseline_corpus.py --i-understand-this-invalidates-results

test_bench.py asserts the corpus hashes to the value in testdata/v0.lines200.sha. That
test used to WRITE the file when it was missing, which meant it certified itself and
could not fail on a fresh checkout. Regenerating now lives here, behind a flag nobody
types by accident.

Why it matters: `prompt_n` is the only thing tying a row in results.md to the prompt that
produced it. Change the generator and every historical row silently describes a different
workload — the medians stay plausible and the comparison becomes meaningless.

After running this, every row in results.md is stale. Re-measure or mark them.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import bench
import prompts

HERE = Path(__file__).resolve().parent
REF = HERE / "testdata" / "v0.lines200.sha"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i-understand-this-invalidates-results", action="store_true",
                    dest="confirmed")
    a = ap.parse_args()

    prompt, _ = prompts.build_prompt(0, 200, False)
    new = hashlib.sha256(prompt.encode()).hexdigest()
    old = REF.read_text().strip() if REF.exists() else None

    if old == new:
        print(f"unchanged: {new}\nNothing to do — the corpus still matches the baseline.")
        return 0

    print(f"old: {old or '(none recorded)'}\nnew: {new}")
    # The default --lines 1200 anchor, printed so the run_matrix.plan() value can be
    # updated in the same sitting rather than discovered wrong on the host later.
    print(f"\nEvery anchor in bench.EXPECTED_PROMPT_N must be re-measured on the host:")
    for (model, lines), n in sorted(bench.EXPECTED_PROMPT_N.items()):
        chars = len(prompts.build_prompt(0, lines, False)[0])
        print(f"  ({model}, --lines {lines}) = {n}   [prompt is now {chars} chars]")

    if not a.confirmed:
        print("\nRefusing to write without "
              "--i-understand-this-invalidates-results", file=sys.stderr)
        return 1

    REF.parent.mkdir(exist_ok=True)
    REF.write_text(new + "\n")
    print(f"\nwrote {REF}\nEVERY ROW IN results.md IS NOW STALE — re-measure or mark them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
