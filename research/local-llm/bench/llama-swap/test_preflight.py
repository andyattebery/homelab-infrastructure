#!/usr/bin/env python3
"""Tests for the preconditions that gate the unattended matrix.

These check the pure logic — what the matrix needs and how the runtime is estimated. The
host-facing checks (sudo, VRAM, disk) are exercised for real by test_integration.py and
by run_matrix itself, which calls check_all() before it stops the service.

Run:  python3 test_preflight.py
"""

import sys

import bench
import preflight as p
import run_matrix as rm


def test_models_needed_is_derived_from_the_plan():
    """Listing the models by hand is how a model gets added to the matrix and not to the
    check, so the run dies at the row that needs it."""
    needed = p.models_needed()
    planned = {row[row.index("--model") + 1]
               for b in ("rocm", "vulkan") for row in rm.plan(b) + rm.probes(b)}
    assert needed == {bench.MODELS[m][0] for m in planned}
    assert all(path.startswith("/models/") for path in needed)


def test_models_needed_covers_probes_as_well_as_rows():
    """The probes load every model before the timed rows do, so a missing GGUF surfaces
    there first — the check has to include them or it reports a false pass."""
    assert "gemma-moe" in {row[row.index("--model") + 1] for row in rm.probes("rocm")}
    assert bench.MODELS["gemma-moe"][0] in p.models_needed()


def test_missing_images_detects_an_unpulled_tag():
    """A mid-run `podman run` that fetches ~5 GB turns a transient network failure into a
    dead unattended session, and it happens between arms where nobody is watching."""
    assert p.missing_images("") == list(rm.IMAGE.values())
    assert p.missing_images(" ".join(rm.IMAGE.values())) == []
    only_rocm = p.missing_images(rm.IMAGE["rocm"])
    assert only_rocm == [rm.IMAGE["vulkan"]]


def test_missing_images_is_exact_not_substring():
    """`llama-swap:rocm` (the deployed floating tag) must NOT satisfy the requirement for
    `llama-swap:v245-rocm-b10200`, or preflight would pass while the pinned image is
    absent and the matrix would silently compare against a different build."""
    assert p.missing_images("ghcr.io/mostlygeek/llama-swap:rocm") == list(rm.IMAGE.values())


def test_runtime_estimate_is_in_the_right_ballpark():
    """'About two hours' needs to be a number: too low and the session outruns its
    window, too high and a hang looks normal."""
    est = p.estimate_runtime_s(rows=13, probes=6, variants=5, gen_tok=1024,
                               gen_rate=40.0, prefill_tok=21828, prefill_rate=1150.0)
    assert 30 * 60 < est < 3 * 3600, f"{est / 60:.0f} min is not a credible estimate"


def test_runtime_estimate_scales_with_variants():
    args = dict(rows=13, probes=6, gen_tok=1024, gen_rate=40.0,
                prefill_tok=21828, prefill_rate=1150.0)
    assert p.estimate_runtime_s(variants=5, **args) > \
           p.estimate_runtime_s(variants=3, **args)


def test_result_labels_distinguish_fatal_from_advisory():
    """A WARN that prints as FAIL gets the run cancelled for nothing; a FAIL that prints
    as WARN gets ignored."""
    assert p.Result("x", False, fatal=True).label == "FAIL"
    assert p.Result("x", False, fatal=False).label == "WARN"
    assert p.Result("x", True).label == "PASS"


def test_the_blocking_checks_are_the_ones_that_waste_the_session():
    """Advisory checks must not be able to cancel the run, and the ones that make every
    row invalid must not be advisory."""
    fatal = {c.__name__ for c in (p.check_sudo, p.check_images, p.check_models,
                                  p.check_baseline_vram, p.check_no_stray_containers,
                                  p.check_disk, p.check_sleep_guard)}
    advisory = {p.check_service_is_ours_to_stop.__name__}
    assert not (fatal & advisory)
    # The sleep guard is blocking on purpose: a suspend mid-run does not slow the session
    # down, it voids it, and the host has demonstrably suspended before.
    assert p.check_sleep_guard.__name__ in fatal


def test_every_check_is_in_check_all():
    """A check that exists but is never called is worse than no check — it reads as
    coverage. check_sleep_guard was added and nearly left unwired."""
    import inspect
    defined = {n for n, _ in inspect.getmembers(p, inspect.isfunction)
               if n.startswith("check_") and n != "check_all"}
    src = inspect.getsource(p.check_all)
    missing = {n for n in defined if f"{n}()" not in src}
    assert not missing, f"defined but never run by check_all: {sorted(missing)}"


def test_baseline_floor_leaves_room_for_the_largest_planned_context():
    """MIN_BASELINE_FREE_MB has to exceed the largest model plus its KV, or the check
    passes on a card that cannot actually hold the first row."""
    largest_ctx = max(int(row[row.index("--ctx") + 1])
                      for b in ("rocm", "vulkan") for row in rm.plan(b))
    assert largest_ctx == 65536
    # ~10.2 GB weights + ~1.1 GB KV at 65536 + the 1.5 GB floor.
    assert p.MIN_BASELINE_FREE_MB >= 12800


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {name}: {e}")
    print(f"\n{fails} failure(s)")
    sys.exit(1 if fails else 0)
