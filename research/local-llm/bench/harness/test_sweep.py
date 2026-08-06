#!/usr/bin/env python3
"""Tests for the launcher's step ordering and command shapes.

    python3 test_sweep.py       # Mac, no ssh, nothing launched

The launcher's mistakes are all silent-until-expensive: a capture started after the first
query, a sweep run against a stale copy, a remote command fish mangles. The plan is data, so
each of those is a one-line assertion instead of a live run.
"""

import sys

import sweep


def names() -> list[str]:
    return [s.name for s in sweep.steps(20, "/data/bench/out.jsonl",
                                        "/data/bench/questions.json")]


def idx(prefix: str) -> int:
    """Index of the first step whose name starts with `prefix`. Prefix-matched so the
    sync's two stages ("sync (stage)", "sync (install)") do not break ordering assertions."""
    for i, n in enumerate(names()):
        if n.startswith(prefix):
            return i
    raise AssertionError(f"no step starting with {prefix!r} in {names()}")


def test_preflight_gates_the_gpu_but_runs_after_the_sync():
    """A guard that errors must stop the run — "the run" being everything that costs GPU
    time or leaves state behind, i.e. the capture and the launch.

    It deliberately runs AFTER the sync: copying files is reversible prep, and preflight
    asserts the harness is present, so preflight-first can never pass on a fresh host.
    Running it second also means it validates the code that will actually execute rather
    than whatever a previous session left there.
    """
    assert idx("preflight") < idx("start capture"), names()
    assert idx("preflight") < idx("launch"), names()
    assert idx("sync") < idx("preflight"), names()


def test_capture_starts_before_the_sweep_is_launched():
    """THE ordering that matters. README.md:57-62 requires the capture before the first
    query; by the time the runner is up, trial one is already in flight.

    Getting this wrong does not crash: every trial records unknown cost and the sweep
    completes looking healthy.
    """
    assert idx("start capture") < idx("launch"), names()
    assert idx("verify capture") < idx("launch"), (
        "the capture must be verified alive BEFORE the GPU is committed", names())


def test_sync_precedes_the_launch():
    assert idx("sync") < idx("launch"), names()


def test_privileged_writes_are_handled_because_the_bench_dir_is_root_owned():
    """`HOST_BENCH` is drwxr-xr-x root:root and ssh lands as an unprivileged user, so BOTH
    the file sync and the capture write need elevation. Discovered the hard way: a direct
    scp fails with permission denied *half way through a launch*, after preflight has
    already passed and the operator thinks the run is starting.

    The container cannot own the capture instead — `docker exec` runs as root and can write
    /data, but the image has **no curl**, so the capture has to stay host-side.
    """
    st = {s.name: s for s in sweep.steps(20, "o", "q")}
    assert "sudo install" in st["sync (install)"].command, st["sync (install)"].command
    assert "sudo" in st["start capture"].command, st["start capture"].command
    # Staging must land somewhere the unprivileged user can actually write.
    assert sweep.STAGE_DIR in st["sync (stage)"].command
    assert sweep.STAGE_DIR.startswith("/tmp"), sweep.STAGE_DIR
    # And the staging dir must be created before scp targets it.
    assert idx("stage dir") < idx("sync (stage)"), names()


def test_capture_url_is_derived_not_hardcoded():
    """`$DOMAIN` in the docs is prose, not an env var — expanding it gives an empty string
    and a URL that silently 404s into an empty capture. The real domain is vault-backed, so
    it must not appear here. Deriving from the container's own configured endpoint is both
    secret-free and guarantees we capture the endpoint actually serving the trials."""
    cap = [s for s in sweep.steps(20, "o", "q") if s.name == "start capture"][0]
    assert "$DOMAIN" not in cap.command, "placeholder would expand to empty"
    # No literal URL of any kind, rather than "not this one domain". Stronger, and it keeps
    # the domain out of this file — which is committed to a public repo, so naming the
    # secret here to assert it is absent would publish it.
    assert "://" not in cap.command, (
        f"the URL must be derived at runtime, not hardcoded: {cap.command}")
    assert "LDR_LLM_OPENAI_ENDPOINT_URL" in cap.command, cap.command
    assert "NO_ENDPOINT" in cap.command, (
        "an unresolvable endpoint must fail loudly rather than start a curl against a "
        "malformed URL and leave an empty capture behind")


def test_capture_liveness_is_checked_by_pid_not_by_pattern_match():
    """`pgrep -f 'logs/stream/upstream'` appears IN the command that runs it, so pgrep
    matches its own shell and reports alive unconditionally — a guard that cannot fail.

    Observed live: after the capture had genuinely exited, that check still said alive.
    """
    st = {s.name: s for s in sweep.steps(20, "o", "q")}
    verify = st["verify capture"].command
    assert "pgrep" not in verify, "pattern matching self-matches; check the PID"
    assert sweep.CAP_PID in verify and "kill -0" in verify, verify
    # and the PID has to be recorded when the capture starts, or there is nothing to check
    assert sweep.CAP_PID in st["start capture"].command


def test_capture_is_written_to_the_bind_mount_not_the_mac():
    """The runner reads it inside the container at /data/bench/upstream.log. Writing it
    anywhere else means the runner sees nothing while the file fills up elsewhere."""
    cap = [s for s in sweep.steps(20, "o", "q") if s.name == "start capture"][0]
    assert sweep.HOST_BENCH in cap.command, cap.command
    assert cap.host == sweep.LDR_HOST, "the capture must run on docker-01's host"
    launch = [s for s in sweep.steps(20, "o", "q") if s.name == "launch"][0]
    assert f"{sweep.CONT_BENCH}/upstream.log" in launch.command, (
        "the runner must be pointed at the container-side path of that same file")


def test_the_sweep_is_launched_detached():
    """A multi-hour run must survive a dropped ssh and a closed laptop."""
    launch = [s for s in sweep.steps(20, "o", "q") if s.name == "launch"][0]
    assert "tmux new -d" in launch.command, launch.command


def test_the_log_redirect_happens_inside_the_container():
    """`CONT_BENCH` is a container path. If the pipe and `tee` run host-side they write to a
    directory that does not exist there — which is exactly what the first smoke run did: the
    sweep completed correctly and its entire log was silently lost, so any monitor watching
    that file stayed dark."""
    launch = [s for s in sweep.steps(20, "o", "q") if s.name == "launch"][0]
    c = launch.command
    assert "sh -c" in c, "the pipeline must run inside the container"
    # tee must appear AFTER the container shell is entered, not before it.
    assert c.index("sh -c") < c.index("tee"), c


def test_remote_commands_are_wrapped_for_fish():
    import inspect
    src = inspect.getsource(sweep.ssh)
    assert "bash -c" in src and "shlex.quote" in src


def test_the_runner_gets_the_same_questions_file_that_was_synced():
    """A sweep against a different question set than the one committed is not reproducible,
    and BENCHMARKING.md:93-101 makes the sample part of the experimental condition."""
    st = sweep.steps(20, "/data/bench/out.jsonl", "/data/bench/questions.json")
    synced = " ".join(s.command for s in st if s.name.startswith("sync"))
    launch = [s for s in st if s.name == "launch"][0]
    assert "questions.json" in synced
    assert "questions.json" in launch.command


def test_sync_list_covers_the_runner_and_everything_it_imports():
    """`shootout.py` imports ldr_trial, records and upstream; a missing one fails at import
    time mid-sweep, after the GPU is already committed."""
    for mod in ("shootout.py", "ldr_trial.py", "records.py", "upstream.py"):
        assert mod in sweep.SYNC, f"{mod} missing from sweep.SYNC"


def test_status_and_stop_do_not_unpack_the_ssh_result():
    """`ssh()` returns a CompletedProcess, not a tuple. `--status` and `--stop` both tried
    to unpack it and raised TypeError — the underlying command had already run, so --stop
    DID stop the sweep and then crashed while reporting it. Caught during round 1's launch.

    Asserted on the source because both paths need a live host to exercise otherwise, which
    is precisely why the bug survived to a real run.
    """
    import inspect, re
    src = inspect.getsource(sweep.main)
    for bad in (r"_,\s*out\s*=\s*ssh\(", r"ok,\s*out\s*=\s*ssh\("):
        assert not re.search(bad, src), f"tuple-unpacking ssh() again: {bad}"


def test_every_step_says_why():
    for s in sweep.steps(20, "o", "q"):
        assert len(s.why) > 30, f"{s.name}: {s.why!r}"


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
