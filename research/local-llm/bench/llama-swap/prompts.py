"""Seeded prompt corpus for the llama-swap benchmark.

**The output of this module is a frozen artifact.** The default `--lines 1200` measures
**21,828 tokens** on Gemma. If that number moves, this generator changed and **every
historical row in results.md is invalidated** — treat a change here as breaking and
re-baseline, exactly as README.md says.

Two separate checks enforce that, and neither is automatic unless asked for:

- `bench.py --expect-prompt-n 21828` is the **absolute** anchor. `run_matrix.plan()`
  passes it on every gemma row. Without the flag nothing compares against 21,828.
- `bench.py`'s cache gate (`filter_cache_hits`) is **relative** — 0.9 x the largest
  prompt_n *within one run* — so it catches a variant served from cache but is blind to
  contamination affecting all variants equally, and blind to this file changing.

The logic below was lifted from the `PYGEN` heredoc inside the old bench.sh. That script
no longer exists and was never committed, so the equivalence cannot be re-derived; what
is enforced now is stability against the hash recorded in testdata/.

Why the variants exist: llama.cpp serves a repeated prompt from its prefix cache and
reports `prompt_n` of ~5 instead of ~21,828, which looks like a spectacularly fast run
rather than a non-run. Each variant is therefore seeded differently **from its first
line**, so no two share a prefix.
"""

import json
import random
from pathlib import Path

WORDS = """quarterly logistics variance shipment corridor throughput inventory ledger
auditor turbine calibration humidity sediment aquifer pipeline substrate compliance
dispatch manifest freight tolerance bearing lubricant gasket flange turbulence
viscosity annealing tensile fatigue corrosion coupling actuator relay telemetry
redundancy latency firmware diagnostic threshold anomaly baseline sampling drift
filtration reagent centrifuge titration spectrometer""".split()

TITLES = ["Field Report", "Maintenance Log", "Inspection Note", "Site Survey",
          "Calibration Record", "Incident Summary", "Audit Extract", "Sensor Digest"]

NEEDLES = [("PLUM-4471", "Meridian"), ("TANGO-9082", "Harbourline"),
           ("CEDAR-3316", "Northfield")]

SEED_BASE = 1000


def build_prompt(variant: int, lines: int, needle: bool) -> tuple[str, str]:
    """One variant's prompt and its expected answer ('' when not in needle mode)."""
    rng = random.Random(SEED_BASE + variant)      # different seed -> no shared prefix
    body: list[str] = []
    chunk = 0
    n = 0
    # RAG-shaped: source-headed chunks, as Onyx assembles retrieved context
    while n < lines:
        chunk += 1
        body.append("[Source %d: %s %04d | https://example.invalid/doc/%d]"
                    % (chunk, rng.choice(TITLES), rng.randrange(9999), chunk))
        for _ in range(min(12, lines - n)):
            body.append("Record %04d: %s." % (n, " ".join(rng.choice(WORDS) for _ in range(7))))
            n += 1
        body.append("")

    expect = ""
    if needle:
        code, proj = NEEDLES[variant % len(NEEDLES)]
        depth = [0.1, 0.5, 0.9][variant % 3]
        body.insert(int(len(body) * depth),
                    "Record NOTE: The access code for %s is %s." % (proj, code))
        question = ("Using only the sources above, what is the access code for %s? "
                    "Answer with the code only." % proj)
        expect = code
    else:
        question = "Using only the sources above, name one Source header that appears."

    prompt = ("You are a research assistant. Answer only from the provided sources.\n\n"
              "<sources>\n" + "\n".join(body) + "\n</sources>\n\n" + question)
    return prompt, expect


def write_corpus(outdir: Path, variants: int, lines: int, needle: bool,
                 max_tokens: int) -> None:
    """Write v<N>.json request bodies and v<N>.expect answers into outdir."""
    outdir.mkdir(parents=True, exist_ok=True)
    for v in range(variants):
        prompt, expect = build_prompt(v, lines, needle)
        (outdir / f"v{v}.json").write_text(json.dumps(
            {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}))
        (outdir / f"v{v}.expect").write_text(expect)
