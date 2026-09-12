"""Guards for the meta script behind github_release_install.

    cd ansible && .venv/bin/pytest roles/github_release_install/tests/ -q

Hermetic: the worker is injected with --updater, so every case points it at a stub that prints a
chosen status line. What is under test here is the walking, the aggregation and the exit status --
not the worker, which has its own suite beside this one.

The property that matters most is that one install's failure does not stop the others. A host with
five managed binaries should update the four that are fine and tell you about the fifth.
"""

import importlib.util
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "github_release_update_all.py"


def _load():
    spec = importlib.util.spec_from_file_location("github_release_update_all", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grua = _load()


def make_updater(tmp_path, body):
    """A stand-in for github-release-update. Receives --env-file and prints one status line."""
    stub = tmp_path / "fake-updater.py"
    stub.write_text(
        "import sys, os\n"
        "env = sys.argv[sys.argv.index('--env-file') + 1]\n"
        "name = os.path.splitext(os.path.basename(env))[0]\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return stub


def env_dir(tmp_path, names):
    directory = tmp_path / "conf"
    directory.mkdir(exist_ok=True)
    for name in names:
        (directory / f"{name}.env").write_text("REPO='a/b'\n", encoding="utf-8")
    return directory


def run(argv, capsys):
    code = grua.main(argv)
    return code, capsys.readouterr().out


# ---------------------------------------------------------------------------------------------


def test_walks_every_env_file_in_sorted_order(tmp_path, capsys):
    directory = env_dir(tmp_path, ["topgrade", "beszel-agent", "zfs_exporter"])
    updater = make_updater(tmp_path, "print(f'OK      {name}  1.0.0')")

    code, out = run(["--config-dir", str(directory), "--updater", str(updater)], capsys)
    assert code == 0
    names = [line.split()[1] for line in out.splitlines() if line.startswith("OK")]
    assert names == ["beszel-agent", "topgrade", "zfs_exporter"]
    assert "3 install(s): 0 changed" in out


def test_one_failure_does_not_stop_the_others(tmp_path, capsys):
    """The reason each install runs in its own process."""
    directory = env_dir(tmp_path, ["aaa", "bbb", "ccc"])
    updater = make_updater(
        tmp_path,
        "print(f'FAILED  {name}  boom') if name == 'bbb' else print(f'CHANGED {name}  1 -> 2')\n"
        "sys.exit(1 if name == 'bbb' else 0)",
    )

    code, out = run(["--config-dir", str(directory), "--updater", str(updater)], capsys)
    assert code == 1
    assert "CHANGED aaa" in out and "CHANGED ccc" in out
    assert "FAILED  bbb" in out
    assert "2 changed" in out and "1 failed" in out


def test_skip_is_not_a_failure(tmp_path, capsys):
    """An env file whose binary is gone is how a retired install stops being updated. It must not
    make the whole run report failure, or every host with an orphan alerts forever."""
    directory = env_dir(tmp_path, ["gone"])
    updater = make_updater(tmp_path, "print(f'SKIP    {name}  binary absent at /nope')")

    code, out = run(["--config-dir", str(directory), "--updater", str(updater)], capsys)
    assert code == 0
    assert "1 skipped" in out


def test_unrecognised_status_counts_as_failure(tmp_path, capsys):
    """An unknown word in column one means the worker changed and this script did not. Counting it
    as success would make a broken pair look healthy."""
    directory = env_dir(tmp_path, ["odd"])
    updater = make_updater(tmp_path, "print('MAYBE   odd  who knows')")

    code, out = run(["--config-dir", str(directory), "--updater", str(updater)], capsys)
    assert code == 1
    assert "1 failed" in out


def test_silent_updater_counts_as_failure(tmp_path, capsys):
    directory = env_dir(tmp_path, ["quiet"])
    updater = make_updater(tmp_path, "sys.exit(3)")

    code, out = run(["--config-dir", str(directory), "--updater", str(updater)], capsys)
    assert code == 1
    assert "produced no output" in out


def test_flags_are_passed_through(tmp_path, capsys):
    directory = env_dir(tmp_path, ["one"])
    updater = make_updater(
        tmp_path,
        "print('WOULD-UPDATE one  ' + ('dry' if '--dry-run' in sys.argv else 'nodry')\n"
        "      + ' ' + ('force' if '--force' in sys.argv else 'noforce'))",
    )

    code, out = run(["--config-dir", str(directory), "--updater", str(updater),
                     "--dry-run", "--force"], capsys)
    assert code == 0
    assert "dry force" in out
    assert "1 would update" in out


def test_missing_config_directory_is_not_an_error(tmp_path, capsys):
    """A host that has never run the role has nothing to update; that is not a failure."""
    updater = make_updater(tmp_path, "print('OK x 1')")
    code, out = run(["--config-dir", str(tmp_path / "absent"), "--updater", str(updater)], capsys)
    assert code == 0
    assert "nothing to update" in out


def test_empty_config_directory_is_not_an_error(tmp_path, capsys):
    directory = env_dir(tmp_path, [])
    updater = make_updater(tmp_path, "print('OK x 1')")
    code, out = run(["--config-dir", str(directory), "--updater", str(updater)], capsys)
    assert code == 0
    assert "no env files" in out


def test_missing_updater_is_an_error(tmp_path, capsys):
    directory = env_dir(tmp_path, ["one"])
    code, _ = run(["--config-dir", str(directory), "--updater", str(tmp_path / "nope")], capsys)
    assert code == 2


def test_non_env_files_are_ignored(tmp_path, capsys):
    directory = env_dir(tmp_path, ["real"])
    (directory / "README").write_text("not an install\n", encoding="utf-8")
    (directory / "backup.env.bak").write_text("REPO='a/b'\n", encoding="utf-8")
    updater = make_updater(tmp_path, "print(f'OK      {name}  1.0.0')")

    code, out = run(["--config-dir", str(directory), "--updater", str(updater)], capsys)
    assert code == 0
    assert "1 install(s)" in out


def test_default_updater_resolves_beside_this_script():
    """In a checkout the pair still carry their .py names; deployed they do not."""
    resolved = grua.default_updater()
    assert os.path.basename(resolved) == "github_release_update.py"
    assert os.path.exists(resolved)
