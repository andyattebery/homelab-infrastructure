"""Tests for the talos/ scripts.

    cd ansible && .venv/bin/pytest ../talos/tests -q

Hermetic: each test runs the real scripts on a copy of talos/ in a temp git repo, with the stubs
in stubs/ first on PATH for every command that would touch a disk, 1Password or the network
(diskutil, dd, sudo, curl, op, talosctl). talosctl's stub answers `get disks` from a fixture and
swallows `wipe disk`; every other talosctl call goes to the real binary mise.toml pins, which
needs no node. plutil, jq, yq, xz and git are the real ones.

Fixtures are captured from real output, never written by hand (README.md, "Tests"). Tests that
need one skip until it exists.
"""

import pytest

from support import make_talos_copy


@pytest.fixture
def talos(tmp_path):
    return make_talos_copy(tmp_path / "repo")
