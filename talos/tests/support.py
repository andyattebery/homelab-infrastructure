"""Helpers shared by the talos/ script tests; conftest.py explains the setup."""

import json
import os
import shutil
import subprocess
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
TALOS_DIR = TESTS_DIR.parent
STUBS = TESTS_DIR / "stubs"
FIXTURES = TESTS_DIR / "fixtures"
DISKS = FIXTURES / "talos-disks.json"

# The talosctl that mise.toml pins: the one the scripts run in real use.
REAL_TALOSCTL = subprocess.run(
    ["mise", "which", "talosctl"], cwd=TALOS_DIR, check=True, capture_output=True, text=True
).stdout.strip()
TALOS_VERSION = next(
    line.split()[1]
    for line in subprocess.run(
        [REAL_TALOSCTL, "version", "--client", "--short"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    if line.startswith("Talos ")
)

# Content-addressed IDs are 64 hex digits; this one is made up.
SCHEMATIC = "5e6f0bd2a1c4d3e8f7a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1"


def make_talos_copy(root):
    """talos/ copied into a fresh git repo that ignores talos/generated/ and talos/images/, as
    the real repo does. The scripts ask git whether generated/ is ignored before writing a
    secret, so the copy has to be inside a repo to run at all."""
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("/talos/generated/\n/talos/images/\n")
    talos = root / "talos"
    shutil.copytree(
        TALOS_DIR,
        talos,
        ignore=shutil.ignore_patterns(
            "generated", "images", "tests", "schematic.id", "mise.toml",
            "__pycache__", ".pytest_cache",
        ),
    )
    return talos


def make_env(tmp, **extra):
    """The environment for a script run: the stubs first on PATH, each appending its argv to
    tmp/calls.jsonl. `extra` sets the stubs' inputs (STUB_* variables)."""
    bindir = tmp / "bin"
    bindir.mkdir()
    for stub in STUBS.glob("*.py"):
        shutil.copy(stub, bindir / stub.stem)
        (bindir / stub.stem).chmod(0o755)
    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
        STUB_LOG=str(tmp / "calls.jsonl"),
        STUB_REAL_TALOSCTL=REAL_TALOSCTL,
    )
    env.update({key: str(value) for key, value in extra.items()})
    return env


def calls(env, name=None):
    """Every logged argv, oldest first -- or only those of the command `name`."""
    log = Path(env["STUB_LOG"])
    if not log.exists():
        return []
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    return [entry for entry in entries if name is None or entry[0] == name]


def run(talos, script, *args, env):
    return subprocess.run(
        [str(talos / "scripts" / script), *args], env=env, capture_output=True, text=True
    )


def gen_secrets(path):
    """A throwaway secrets bundle, from the real talosctl."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([REAL_TALOSCTL, "gen", "secrets", "-o", str(path)], check=True, capture_output=True)
    return path


def captured_disks():
    """fixtures/talos-disks.json as a list of resources: talosctl prints one JSON object after
    another."""
    text, decoder, resources, at = DISKS.read_text(), json.JSONDecoder(), [], 0
    while True:
        while at < len(text) and text[at].isspace():
            at += 1
        if at == len(text):
            return resources
        resource, at = decoder.raw_decode(text, at)
        resources.append(resource)


def only(resources, transport):
    (disk,) = [r for r in resources if r["spec"].get("transport") == transport]
    return disk


def leaves(node, path=()):
    """(path, value) for every scalar in a parsed YAML/JSON tree, in document order."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, path + (key,))
    else:
        yield path, node
