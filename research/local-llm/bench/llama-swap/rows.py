"""Parse and validate the result rows bench.py emits.

Pure — no I/O, no subprocesses. This is the "did it produce the CORRECT output" half of
the harness, and it is separate from the code that runs the benchmark so it can be tested
without a GPU.

The rule it enforces: **a row that reaches results.md must be a measurement.** Every
failure mode below has actually occurred — an empty `backend` column making two arms
indistinguishable, a mismatched build silently comparing two llama.cpp versions, variants
discarded by the cache gate leaving n=3 reported as if it were n=5.
"""

from __future__ import annotations

import bench


def extract_row(output: str) -> str | None:
    """The one result row from a bench.py run's output.

    Identified by its first cell being a known model name, which distinguishes it from
    the markdown header and the `|---|---|` separator printed just above it.
    """
    for line in output.splitlines():
        if line.startswith("| ") and line.split("|")[1].strip() in bench.MODELS:
            return line.rstrip()
    return None


def parse_row(line: str) -> dict[str, str]:
    """A markdown row into {column: value}, keyed by bench.ROW_COLUMNS.

    Raises on a column-count mismatch rather than returning a partial dict: a row that
    does not line up with the header corrupts results.md silently, and silently is the
    problem.
    """
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) != len(bench.ROW_COLUMNS):
        raise ValueError(f"row has {len(cells)} cells, expected "
                         f"{len(bench.ROW_COLUMNS)}: {line}")
    return dict(zip(bench.ROW_COLUMNS, cells))


def _is_int(s: str) -> bool:
    return s.isdigit()


def check_row(row: dict[str, str], *, expect_backend: str,
              expect_variants: int) -> list[str]:
    """Problems with one row. Empty list means the row is sound."""
    problems = []
    backend = row["backend"]
    if backend in ("", "?", "-"):
        problems.append("backend is unset — the two arms are indistinguishable in "
                        "results.md, which is the entire point of the experiment")
    elif backend != expect_backend:
        problems.append(f"backend is {backend!r} but this row ran on {expect_backend!r}")

    if not row["build"].startswith("b"):
        problems.append(f"build {row['build']!r} did not come from system_fingerprint")

    if not _is_int(row["prompt_n"]) or int(row["prompt_n"]) <= 0:
        problems.append(f"prompt_n {row['prompt_n']!r} is not a positive integer")

    if not _is_int(row["n"]):
        problems.append(f"n {row['n']!r} is not an integer")
    elif int(row["n"]) != expect_variants:
        # The cache gate discards contaminated variants. Fewer than requested means some
        # were thrown away, and README.md calls that the one condition invalidating a row.
        problems.append(f"n={row['n']} but --variants {expect_variants} was requested — "
                        "the cache gate discarded runs, so this row is not valid")

    for col in ("free", "baseline free"):
        value = row[col].replace(" MB", "").strip()
        if not _is_int(value) or int(value) <= 0:
            problems.append(f"{col} {row[col]!r} is not a positive MB integer")

    # EVICTED is amd-smi-only. On Vulkan it MUST read n/a — meaning not measured, never
    # zero. On ROCm a '?' means the amd-smi parse failed, which is a defect, not a value.
    evicted = row["EVICTED"]
    if expect_backend == "vulkan":
        if evicted != "n/a":
            problems.append(f"EVICTED is {evicted!r} on vulkan, expected 'n/a' — "
                            "amd-smi is absent from that image")
    elif not _is_int(evicted):
        problems.append(f"EVICTED is {evicted!r} on rocm — amd-smi parse failed; "
                        "'?' is a broken parser, not a measurement")

    return problems


def gen_spread_pct(row: dict[str, str]) -> float | None:
    """(max - min) / median as a percentage, from a recorded row. None if unparseable.

    This is the number the whole decision rests on. The criterion is a >=10% generation
    gap with NON-OVERLAPPING ranges between arms, so a row whose own spread exceeds 10%
    cannot contribute to that comparison however many times it is repeated.
    """
    try:
        lo, hi = (float(x) for x in row["gen min-max"].split("-"))
        med = float(row["gen med"])
    except (ValueError, KeyError):
        return None
    return (hi - lo) / med * 100 if med else None


def config_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    """What makes two rows the same configuration, ignoring the backend."""
    return (row["model"], row["-c"], row["-fa"], row["-ub"])


def check_arms_comparable(rows: list[dict[str, str]],
                          single_arm_ok: set | None = None) -> list[str]:
    """Cross-arm invariants. These are the checks that no single row can make.

    An A/B is only an A/B if both arms ran the same configurations on the same build.

    `single_arm_ok` is the set of config keys the DESIGN deliberately runs on one arm —
    the Vulkan-only `-ub 2048` MoE row, whose ROCm counterpart was a measured no-op and
    would be a wasted five minutes. Derived by the caller from plan(), never listed here:
    a hand-maintained exemption list is how an accidental asymmetry gets excused as
    intentional. Without this the checker flags the deliberate row and cries wolf on
    every run — observed on the first smoke run.
    """
    problems = []
    exempt = single_arm_ok or set()
    by_backend: dict[str, set] = {}
    for r in rows:
        by_backend.setdefault(r["backend"], set()).add(config_key(r))

    builds = {r["build"] for r in rows}
    if len(builds) > 1:
        problems.append(f"rows span multiple llama.cpp builds {sorted(builds)} — the "
                        "comparison measures backend AND version while reporting backend")

    arms = sorted(by_backend)
    if len(arms) == 2:
        a, b = arms
        only_a = by_backend[a] - by_backend[b] - exempt
        only_b = by_backend[b] - by_backend[a] - exempt
        if only_a:
            problems.append(f"configs run on {a} but not {b}: {sorted(only_a)}")
        if only_b:
            problems.append(f"configs run on {b} but not {a}: {sorted(only_b)}")

    # prompt_n is a property of (model, prompt size) and the tokenizer — never of the
    # backend. A difference between arms means the two ran different prompts, so the
    # throughput numbers are not comparable. This is the corpus check during a smoke run,
    # where the absolute --expect-prompt-n anchors do not apply.
    by_config: dict[tuple, set] = {}
    for r in rows:
        by_config.setdefault(config_key(r), set()).add(r["prompt_n"])
    for cfg, ns in sorted(by_config.items()):
        if len(ns) > 1:
            problems.append(f"config {cfg} measured different prompt_n across arms "
                            f"{sorted(ns)} — the arms did not run the same prompt")
    return problems
