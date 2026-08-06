#!/usr/bin/env python3
"""Tests for the test orchestrator.

An orchestrator is a script, and the last three defects in this directory all came from
scripts written once, run once, and never verified: a trap that never fired, a tilde that
would have been quoted out of existence, a `command -v` that could not work under
`podman exec`. This file exists so the thing that runs the tests is not itself the
untested part.

Run:  python3 test_run_tests.py
"""

import ast
import subprocess
import sys
from pathlib import Path

import run_tests as rt

HERE = Path(__file__).resolve().parent


def _remote_stages(gpu=True):
    return [s for s in rt.plan("testhost", gpu=gpu) if s.remote]


def _names(gpu=True):
    return [s.name for s in rt.plan("testhost", gpu=gpu)]


# ------------------------------------------------------- the fish/ssh boundary

def test_every_remote_command_is_shell_safe():
    """ssh hands the string to the LOGIN shell, which on htpc-01 is fish. Anything fish
    parses differently from bash breaks silently or, worse, partially."""
    for s in _remote_stages():
        assert rt.SHELL_SAFE.match(s.remote), f"unsafe remote command: {s.remote!r}"


def test_shell_safe_actually_rejects_the_things_it_claims_to():
    """A regex nobody tested is decoration. These are the five forms that have actually
    bitten: tilde (shlex.quote would quote it, so it never expands), command
    substitution, pipe, redirection, and a statement separator."""
    for bad in ("python3 ~/test_integration.py",
                "python3 x.py $(date +%F)",
                "python3 x.py | tee log",
                "python3 x.py > log 2>&1",
                "python3 x.py; echo done",
                "python3 x.py `hostname`"):
        assert not rt.SHELL_SAFE.match(bad), f"SHELL_SAFE wrongly accepted {bad!r}"


def test_every_remote_stage_forces_a_tty_so_a_disconnect_signals_the_job():
    """Without -tt, killing the ssh client leaves the remote process running: it holds
    the GPU with llama-swap.service stopped and nothing tears it down. Verified with a
    probe — plain ssh delivered no signal and the process survived; -tt delivered SIGHUP
    and the finally block ran.

    Every remote stage here either holds the card or stops the service, and their
    teardown is a signal handler, so this flag is what makes the teardown reachable.
    """
    for s in _remote_stages():
        assert s.argv[:2] == ["ssh", "-tt"], f"{s.name} can orphan on disconnect: {s.argv}"


def test_remote_commands_use_relative_paths_not_tilde_or_home():
    """Files are scp'd to the remote home, which is also the login shell's cwd, so a bare
    filename resolves. That is what lets the command stay free of shell syntax."""
    for s in _remote_stages():
        assert "~" not in s.remote and "$HOME" not in s.remote, s.remote
        assert "/" not in s.remote.split()[1], f"remote path is not bare: {s.remote}"


# ------------------------------------------------------- the sync list

def _local_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return {m for m in mods if (HERE / f"{m}.py").exists()}


def test_sync_list_is_closed_under_the_remote_entry_points_imports():
    """The defect this prevents: add an import to test_integration.py, forget to add the
    file to SYNC, and the remote run fails on the host — or worse, succeeds against a
    stale copy left there by an earlier session."""
    entry = {s.remote.split()[1] for s in _remote_stages()}
    seen, queue = set(), list(entry)
    while queue:
        f = queue.pop()
        if f in seen:
            continue
        seen.add(f)
        queue += [f"{m}.py" for m in _local_imports(HERE / f)]
    # The entry points themselves must be synced too, not just their dependencies.
    missing = seen - set(rt.SYNC)
    assert not missing, f"needed on the host but not in SYNC: {sorted(missing)}"


def test_every_synced_file_exists():
    for f in rt.SYNC:
        assert (HERE / f).exists(), f"SYNC names a file that does not exist: {f}"


def test_sync_stage_copies_exactly_the_sync_list():
    sync = [s for s in rt.plan("testhost") if s.name == "sync"]
    assert len(sync) == 1
    argv = sync[0].argv
    assert argv[0] == "scp"
    copied = {Path(a).name for a in argv if a.endswith(".py")}
    assert copied == set(rt.SYNC), f"{copied} != {set(rt.SYNC)}"
    assert argv[-1] == "testhost:", "destination must be the remote HOME (bare colon)"


# ------------------------------------------------------- service safety

def test_only_the_gpu_stage_stops_the_service():
    """The non-GPU integration stage must be safe to run against a live deployment: it
    uses its own container name and loads no model. If it stopped llama-swap, running the
    cheap checks would take Onyx and LDR down for no reason."""
    for s in _remote_stages():
        assert ("--stop-service" in s.remote) == s.gpu, s.remote


def test_the_gpu_stage_stops_the_service():
    """Without it the deployed container holds the card and every GPU test fails on a
    model load — after burning the health-poll timeout on each."""
    gpu = [s for s in _remote_stages() if s.gpu]
    assert len(gpu) == 1
    assert "--stop-service" in gpu[0].remote and "--gpu" in gpu[0].remote


def test_the_stop_is_delegated_to_the_host_never_issued_from_here():
    """A stop issued from the Mac cannot guarantee its own restore: if this process or
    the ssh connection dies, nothing on the host runs the restore. Delegating it means
    the remote process gets SIGHUP and restores in its own finally."""
    for s in rt.plan("testhost", gpu=True):
        joined = " ".join(s.argv)
        assert "systemctl" not in joined, f"orchestrator issues systemctl itself: {joined}"


def test_gpu_stages_are_absent_without_the_flag():
    assert not [s for s in rt.plan("testhost", gpu=False) if s.gpu]
    assert [s for s in rt.plan("testhost", gpu=True) if s.gpu]


def test_each_expensive_stage_is_behind_its_own_flag():
    """--gpu, --smoke and --capture cost 4, 12 and 3 minutes of exclusive GPU. Bundling
    them would mean the cheap run stops being cheap and gets skipped."""
    base = {s.name for s in rt.plan("testhost")}
    for flag, expect in (("gpu", "remote: integration --gpu"),
                         ("smoke", "remote: matrix --smoke"),
                         ("capture", "remote: capture fixtures")):
        added = {s.name for s in rt.plan("testhost", **{flag: True})} - base
        assert expect in added, f"--{flag} did not add {expect}"
        assert len(added) <= 2, f"--{flag} added more than its own work: {added}"


def test_smoke_stage_runs_the_matrix_driver_not_a_test_file():
    """The whole point of --smoke is that it exercises run_matrix.py's OWN commands. If
    it invoked a test file instead, the 2h driver would still be untried."""
    smoke = [s for s in rt.plan("testhost", smoke=True) if "smoke" in s.name]
    assert len(smoke) == 1
    assert "run_matrix.py --smoke" in smoke[0].remote


def test_capture_fetches_the_fixtures_back():
    """Capturing on the host is useless if testdata/ never returns — the unit tests run
    on the Mac."""
    stages = rt.plan("testhost", capture=True)
    names = [s.name for s in stages]
    assert names.index("remote: capture fixtures") < names.index("fetch fixtures")
    fetch = [s for s in stages if s.name == "fetch fixtures"][0]
    assert fetch.argv[0] == "scp" and "-r" in fetch.argv
    assert any(a.startswith("testhost:") for a in fetch.argv)


# ------------------------------------------------------- shape and ordering

def test_local_suites_run_before_anything_touches_the_host():
    """A syntax error should cost a second, not an ssh round trip and a model load."""
    names = _names()
    sync = names.index("sync")
    assert all(names.index(n) < sync for n in names if n.startswith(("unit:", "dry:")))
    assert all(names.index(s.name) > sync for s in _remote_stages())


def test_the_orchestrator_tests_itself():
    """If this file is not in the plan, it rots — which is how the previous round ended
    up with test_integration.py asserting 13 matrix rows while test_run_matrix.py
    asserted 19."""
    assert any("test_run_tests.py" in s.argv for s in rt.plan("testhost"))


def test_run_remote_sh_is_exercised_and_costs_no_gpu():
    """It was the one script in this directory that had never been executed at all."""
    st = [s for s in rt.plan("testhost") if s.name == "local: run-remote.sh"]
    assert len(st) == 1
    assert "--dry-run" in st[0].argv, "would load a model just to test arg passing"
    assert "two words" in st[0].argv, "must test the %q re-quoting the script claims"
    assert st[0].env.get("BENCH_HOST") == "testhost", \
        "without BENCH_HOST the wrapper ignores --host and hits its own default"


def test_every_stage_names_a_file_that_exists():
    for s in rt.plan("testhost", gpu=True):
        if s.argv[0] in ("ssh", "scp"):
            continue
        target = s.argv[1] if s.argv[0] == sys.executable else s.argv[0]
        assert (HERE / target).exists(), f"{s.name} runs a missing file: {target}"


def test_every_stage_states_why_it_exists():
    for s in rt.plan("testhost", gpu=True):
        assert len(s.why) > 20, f"{s.name} has no rationale"


# ------------------------------------------------------- the dry run is really dry

def test_dry_run_executes_nothing():
    """Proven, not asserted: point it at a host that cannot resolve. If any stage ran,
    scp or ssh would fail and the exit code would be non-zero."""
    r = subprocess.run([sys.executable, str(HERE / "run_tests.py"), "--dry-run", "--gpu",
                        "--host", "no-such-host.invalid"],
                       capture_output=True, text=True, cwd=HERE, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing executed" in r.stdout
    for name in _names(gpu=True):
        assert name in r.stdout, f"dry run omitted stage {name}"


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
