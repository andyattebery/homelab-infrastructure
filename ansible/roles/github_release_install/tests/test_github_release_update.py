"""Guards for the vendored updater behind github_release_install.

    cd ansible && .venv/bin/pytest roles/github_release_install/tests/ -q

Hermetic. The script takes its GitHub API base and its apt-get as arguments, so every case points
them at a local directory tree and a stub. `--api-base` is a `file://` URL into a tempdir laid out
as `repos/<owner>/<repo>/releases/latest`, which urllib resolves natively -- no HTTP server, and
no branch in the script that exists only for tests.

Fixture discipline follows ansible/tests/fixtures/README.md: real shape, placeholder values,
`example.invalid` download URLs so a case that should never fetch fails loudly if it does. The two
shared release fixtures are reused rather than re-invented.

These cases exist because this script is a SECOND implementation of the role's decision logic.
They pin the behaviours the two must agree on; they cannot stop the two from drifting.
"""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "github_release_update.py"
SHARED_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def _load():
    spec = importlib.util.spec_from_file_location("github_release_update", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gru = _load()


# ---------------------------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------------------------


def api_tree(root, repo, release, ref="latest"):
    """Lay out a release response where the script's own URL construction will find it."""
    owner, name = repo.split("/")
    path = root / "api" / "repos" / owner / name / "releases"
    if ref != "latest":
        path = path / "tags"
        ref = ref.split("/")[-1]
    path.mkdir(parents=True, exist_ok=True)
    (path / ref).write_text(json.dumps(release), encoding="utf-8")
    return f"file://{root / 'api'}"


def make_tarball(root, name, members):
    """members: {path_inside_archive: bytes}"""
    staging = root / f"staging-{name}"
    staging.mkdir(parents=True, exist_ok=True)
    for member, payload in members.items():
        target = staging / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    archive = root / name
    with tarfile.open(archive, "w:gz") as tar:
        for member in members:
            tar.add(staging / member, arcname=member)
    shutil.rmtree(staging)
    return archive


def release_with_asset(tag, asset_name, url, digest="sha256:" + "a" * 64, asset_id=4242):
    asset = {"id": asset_id, "name": asset_name, "browser_download_url": url}
    if digest is not None:
        asset["digest"] = digest
    return {"tag_name": tag, "assets": [asset]}


def write_env(root, **overrides):
    values = {
        "NAME": "tool",
        "REPO": "acme/tool",
        "ASSET_PATTERN": r"linux-amd64\.tar\.gz$",
        "ARCHIVE_TYPE": "tarball",
        "BINARY_PATH": str(root / "bin" / "tool"),
        "BINARY_IN_ARCHIVE": "tool",
        "VERSION_COMMAND": "",
        "VERSION_REGEX": r"([0-9]+\.[0-9]+\.[0-9]+)",
        "RELEASE_TAG": "",
        "USE_TAG_STAMP": "false",
        "TAG_STAMP_PATH": "",
        "SYMLINK": "false",
        "SYMLINK_PATH": "",
        "POST_UPDATE_COMMAND": "",
    }
    values.update(overrides)
    lines = [f"{key}='{value}'" for key, value in values.items()]
    env_file = root / "tool.env"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


def install_fake_binary(root, version, name="tool"):
    """A 'binary' that reports a version, so version-command mode has something real to run."""
    target = root / "bin" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"#!/bin/sh\necho '{name} {version}'\n", encoding="utf-8")
    target.chmod(0o755)
    return target


def run(argv, capsys):
    code = gru.main(argv)
    out = capsys.readouterr().out.strip()
    return code, out


# ---------------------------------------------------------------------------------------------
# C1-C3  the no-bootstrap rule, and that it costs no API call
# ---------------------------------------------------------------------------------------------


def test_absent_binary_skips(tmp_path, capsys):
    env = write_env(tmp_path)
    code, out = run(["--env-file", str(env), "--api-base", f"file://{tmp_path}/nonexistent"], capsys)
    assert code == 0
    assert out.startswith("SKIP")
    assert "binary absent" in out


def test_absent_binary_makes_no_api_call(tmp_path, capsys):
    """The api-base points at a path that does not exist. Reaching the network would fail; SKIP
    proves the existence check runs first, which is what keeps an orphan off the rate limit."""
    env = write_env(tmp_path)
    code, out = run(["--env-file", str(env), "--api-base", f"file://{tmp_path}/definitely-not-here"], capsys)
    assert (code, out.split()[0]) == (0, "SKIP")


def test_force_installs_over_absent_binary(tmp_path, capsys):
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"NEW BYTES"})
    release = release_with_asset("v2.0.0", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path)
    (tmp_path / "bin").mkdir(exist_ok=True)

    code, out = run(["--env-file", str(env), "--api-base", api, "--force"], capsys)
    assert code == 0, out
    assert out.startswith("CHANGED")
    assert (tmp_path / "bin" / "tool").read_bytes() == b"NEW BYTES"


# ---------------------------------------------------------------------------------------------
# C4-C6  version-command mode
# ---------------------------------------------------------------------------------------------


def test_version_command_current_is_ok(tmp_path, capsys):
    binary = install_fake_binary(tmp_path, "1.4.2")
    release = release_with_asset("v1.4.2", "tool-linux-amd64.tar.gz", "https://example.invalid/x")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, VERSION_COMMAND=str(binary))

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert out.startswith("OK")
    assert "1.4.2" in out


def test_version_command_stale_updates(tmp_path, capsys):
    install_fake_binary(tmp_path, "1.4.2")
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"v150"})
    release = release_with_asset("v1.5.0", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, VERSION_COMMAND=str(tmp_path / "bin" / "tool"))

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert out.startswith("CHANGED")
    assert "1.4.2 -> 1.5.0" in out
    assert (tmp_path / "bin" / "tool").read_bytes() == b"v150"


def test_leading_v_stripped_once_and_only_at_the_front():
    """Calls the script's own helper, not re.sub directly -- an earlier version of this case
    asserted on the stdlib and so could not fail however the script was mutated.

    The jellyfin-ffmpeg tag is the one that matters: a plain replace() mangles the 'nvenc' in it.
    """
    assert gru.strip_leading_v("v1.2.3") == "1.2.3"
    assert gru.strip_leading_v("vv1.2.3") == "v1.2.3"
    assert gru.strip_leading_v("1.2.3") == "1.2.3"
    assert gru.strip_leading_v("v8.1.2-3+nvenc-n13.0.19.1") == "8.1.2-3+nvenc-n13.0.19.1"


# ---------------------------------------------------------------------------------------------
# C7-C10  tag-stamp mode, and the digest fallback
# ---------------------------------------------------------------------------------------------


def test_stamp_uses_digest_when_present():
    asset = {"id": 5, "name": "a", "digest": "sha256:abc"}
    assert gru.asset_fingerprint(asset) == "sha256:abc"


def test_stamp_falls_back_to_id_when_digest_key_absent():
    """The shared fixture is a real release from before the API published digests."""
    release = json.loads((SHARED_FIXTURES / "github-release-no-digest.json").read_text())
    asset = release["assets"][0]
    assert "digest" not in asset
    assert gru.asset_fingerprint(asset) == "id:987654"


def test_stamp_falls_back_to_id_when_digest_is_null():
    """An unguarded lookup evaluates to empty here and silently collapses the comparison back to
    tag-only, which is the bug the digest was added to fix."""
    assert gru.asset_fingerprint({"id": 77, "name": "a", "digest": None}) == "id:77"


def test_stamp_matching_is_ok(tmp_path, capsys):
    install_fake_binary(tmp_path, "ignored")
    stamp = tmp_path / "bin" / "tool.release-tag"
    release = release_with_asset("v3.0.0", "tool-linux-amd64.tar.gz", "https://example.invalid/x",
                                 digest="sha256:" + "b" * 64)
    stamp.write_text("v3.0.0 sha256:" + "b" * 64 + "\n", encoding="utf-8")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, USE_TAG_STAMP="true")

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert out.startswith("OK")


def test_replaced_asset_under_unchanged_tag_updates(tmp_path, capsys):
    """The case the digest exists for: same tag, different bytes. A tag-only stamp matches forever
    and the host silently keeps a build the release no longer offers."""
    install_fake_binary(tmp_path, "ignored")
    stamp = tmp_path / "bin" / "tool.release-tag"
    stamp.write_text("v3.0.0 sha256:" + "b" * 64 + "\n", encoding="utf-8")

    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"REBUILT"})
    release = release_with_asset("v3.0.0", "tool-linux-amd64.tar.gz", f"file://{archive}",
                                 digest="sha256:" + "c" * 64)
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, USE_TAG_STAMP="true")

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert out.startswith("CHANGED")
    assert stamp.read_text().strip() == "v3.0.0 sha256:" + "c" * 64


def test_bare_tag_stamp_self_heals(tmp_path, capsys):
    """A stamp written before the digest half existed holds only the tag. It must not compare
    equal, so the first run after the upgrade rewrites it."""
    install_fake_binary(tmp_path, "ignored")
    stamp = tmp_path / "bin" / "tool.release-tag"
    stamp.write_text("v3.0.0\n", encoding="utf-8")

    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"SAME"})
    release = release_with_asset("v3.0.0", "tool-linux-amd64.tar.gz", f"file://{archive}",
                                 digest="sha256:" + "d" * 64)
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, USE_TAG_STAMP="true")

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert stamp.read_text().strip() == "v3.0.0 sha256:" + "d" * 64


def test_stamp_keeps_raw_tag_not_v_stripped(tmp_path, capsys):
    """The stamp compares the raw tag_name; the version-command path strips the 'v'. Two
    identifiers that look interchangeable and are not."""
    install_fake_binary(tmp_path, "ignored")
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"X"})
    release = release_with_asset("v9.9.9", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, USE_TAG_STAMP="true")

    run(["--env-file", str(env), "--api-base", api], capsys)
    assert (tmp_path / "bin" / "tool.release-tag").read_text().startswith("v9.9.9 ")


def test_failed_download_leaves_stamp_untouched(tmp_path, capsys):
    """Written last on purpose: a failed fetch must leave the previous stamp so the next run
    retries rather than believing itself converged."""
    install_fake_binary(tmp_path, "ignored")
    stamp = tmp_path / "bin" / "tool.release-tag"
    stamp.write_text("v1.0.0 sha256:old\n", encoding="utf-8")

    release = release_with_asset("v2.0.0", "tool-linux-amd64.tar.gz",
                                 f"file://{tmp_path}/no-such-archive.tar.gz")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, USE_TAG_STAMP="true")

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 1
    assert out.startswith("FAILED")
    assert stamp.read_text().strip() == "v1.0.0 sha256:old"


# ---------------------------------------------------------------------------------------------
# C11-C13  asset selection
# ---------------------------------------------------------------------------------------------


def test_ambiguous_pattern_takes_the_first_match(tmp_path):
    """The role's `select(...) | first` takes the first match without complaint, and this mirrors
    it exactly rather than improving on it -- an updater that chose differently from the role
    would be a drift between the two implementations, which is the one thing to avoid here.

    The warning on stderr is the only addition; behaviour is identical.
    """
    release = json.loads((SHARED_FIXTURES / "github-release-jellyfin-ffmpeg.json").read_text())
    asset = gru.select_asset(release, "arm64")
    assert asset["name"] == "jellyfin-ffmpeg_8.1.2-3_linuxarm64-gpl.tar.xz"


def test_selects_exactly_one_of_four_real_asset_names():
    """The shared fixture carries winarm64 next to win64, which is why 'contains win64' is not a
    safe pattern and the anchored one is."""
    release = json.loads((SHARED_FIXTURES / "github-release-jellyfin-ffmpeg.json").read_text())
    asset = gru.select_asset(release, r"linux64-gpl\.tar\.xz$")
    assert asset["name"] == "jellyfin-ffmpeg_8.1.2-3_linux64-gpl.tar.xz"
    assert len(release["assets"]) == 4


def test_unanchored_pattern_would_have_matched_two():
    """Proves the previous case is not vacuous: the fixture really does contain a near-miss."""
    release = json.loads((SHARED_FIXTURES / "github-release-jellyfin-ffmpeg.json").read_text())
    matched = [a["name"] for a in release["assets"] if gru.re.search("arm64", a["name"])]
    assert len(matched) == 2


def test_no_matching_asset_names_what_was_published(tmp_path):
    release = json.loads((SHARED_FIXTURES / "github-release-jellyfin-ffmpeg.json").read_text())
    with pytest.raises(gru.Failure) as excinfo:
        gru.select_asset(release, r"freebsd\.tar\.gz$")
    assert "no asset matches" in str(excinfo.value)
    assert "win64-clang-gpl.zip" in str(excinfo.value)


# ---------------------------------------------------------------------------------------------
# C14-C15  ${VERSION} substitution
# ---------------------------------------------------------------------------------------------


def test_version_placeholder_substituted():
    assert gru.resolve_in_archive("tool-${VERSION}.linux-amd64/tool", "v2.3.12") == \
        "tool-2.3.12.linux-amd64/tool"


def test_tag_placeholder_keeps_the_v():
    assert gru.resolve_in_archive("x/${TAG}/y", "v2.3.12") == "x/v2.3.12/y"


def test_nested_versioned_directory_is_found(tmp_path, capsys):
    """The zfs_exporter shape: the directory inside the tarball is named after the release, so a
    literal captured at deploy time is wrong for every later release."""
    install_fake_binary(tmp_path, "2.3.11")
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz",
                           {"tool-2.3.12.linux-amd64/tool": b"NESTED"})
    release = release_with_asset("v2.3.12", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path,
                    BINARY_IN_ARCHIVE="tool-${VERSION}.linux-amd64/tool",
                    VERSION_COMMAND=str(tmp_path / "bin" / "tool"))

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert (tmp_path / "bin" / "tool").read_bytes() == b"NESTED"


# ---------------------------------------------------------------------------------------------
# C16-C18  byte comparison and POST_UPDATE_COMMAND
# ---------------------------------------------------------------------------------------------


def test_identical_bytes_do_not_touch_mtime_or_run_post_update(tmp_path, capsys):
    """A caller keys a service restart off this binary's mtime. Rewriting an unchanged file would
    make the next playbook run report a change that did not happen."""
    binary = tmp_path / "bin" / "tool"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"IDENTICAL")
    binary.chmod(0o755)
    os.utime(binary, (1000000, 1000000))
    before = binary.stat().st_mtime

    marker = tmp_path / "post-update-ran"
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"IDENTICAL"})
    release = release_with_asset("v4.0.0", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, USE_TAG_STAMP="true",
                    POST_UPDATE_COMMAND=f"touch {marker}")

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert "bytes unchanged" in out
    assert binary.stat().st_mtime == before
    assert not marker.exists()


def test_different_bytes_move_mtime_and_run_post_update(tmp_path, capsys):
    binary = tmp_path / "bin" / "tool"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"OLD")
    binary.chmod(0o755)
    os.utime(binary, (1000000, 1000000))
    before = binary.stat().st_mtime

    marker = tmp_path / "post-update-ran"
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"NEW"})
    release = release_with_asset("v4.0.0", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, USE_TAG_STAMP="true",
                    POST_UPDATE_COMMAND=f"touch {marker}")

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert out.startswith("CHANGED")
    assert binary.stat().st_mtime != before
    assert marker.exists()


def test_installed_binary_is_executable(tmp_path, capsys):
    install_fake_binary(tmp_path, "0.0.1")
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"PAYLOAD"})
    release = release_with_asset("v0.0.2", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, VERSION_COMMAND=str(tmp_path / "bin" / "tool"))

    run(["--env-file", str(env), "--api-base", api], capsys)
    assert (tmp_path / "bin" / "tool").stat().st_mode & stat.S_IXUSR


# ---------------------------------------------------------------------------------------------
# C19-C20  the other two archive types
# ---------------------------------------------------------------------------------------------


def test_binary_archive_type_downloads_straight_to_destination(tmp_path, capsys):
    install_fake_binary(tmp_path, "1.0.0")
    payload = tmp_path / "collector-linux-amd64"
    payload.write_bytes(b"RAW BINARY")
    release = release_with_asset("v1.1.0", "collector-linux-amd64", f"file://{payload}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, ARCHIVE_TYPE="binary", BINARY_IN_ARCHIVE="",
                    ASSET_PATTERN="collector-linux-amd64",
                    VERSION_COMMAND=str(tmp_path / "bin" / "tool"))

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert (tmp_path / "bin" / "tool").read_bytes() == b"RAW BINARY"


def test_deb_archive_type_shells_out_to_apt_get(tmp_path, capsys):
    """apt-get is injected, the way pve_pci_mapping_metrics.py injects pvesh. The stub records its
    argv and plays the part of dpkg by writing the binary."""
    binary = install_fake_binary(tmp_path, "1.0.0")
    argv_log = tmp_path / "apt-get.log"
    stub = tmp_path / "apt-get"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {argv_log}\n'
        f'printf "INSTALLED BY DPKG" > {binary}\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    package = tmp_path / "tool_1.1.0_amd64.deb"
    package.write_bytes(b"not really a deb")
    release = release_with_asset("v1.1.0", "tool_1.1.0_amd64.deb", f"file://{package}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, ARCHIVE_TYPE="deb", BINARY_IN_ARCHIVE="",
                    ASSET_PATTERN=r"_amd64\.deb$", VERSION_COMMAND=str(binary))

    code, out = run(["--env-file", str(env), "--api-base", api, "--apt-get", str(stub)], capsys)
    assert code == 0, out
    assert out.startswith("CHANGED")
    assert "install -y" in argv_log.read_text()
    assert binary.read_bytes() == b"INSTALLED BY DPKG"


def test_deb_failure_is_reported_not_swallowed(tmp_path, capsys):
    binary = install_fake_binary(tmp_path, "1.0.0")
    stub = tmp_path / "apt-get"
    stub.write_text("#!/bin/sh\necho 'E: Unable to locate package' >&2\nexit 100\n", encoding="utf-8")
    stub.chmod(0o755)

    package = tmp_path / "tool_1.1.0_amd64.deb"
    package.write_bytes(b"x")
    release = release_with_asset("v1.1.0", "tool_1.1.0_amd64.deb", f"file://{package}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, ARCHIVE_TYPE="deb", BINARY_IN_ARCHIVE="",
                    ASSET_PATTERN=r"_amd64\.deb$", VERSION_COMMAND=str(binary))

    code, out = run(["--env-file", str(env), "--api-base", api, "--apt-get", str(stub)], capsys)
    assert code == 1
    assert "Unable to locate package" in out


# ---------------------------------------------------------------------------------------------
# C21-C24  env file parsing, and that it is not a shell
# ---------------------------------------------------------------------------------------------


def test_env_file_line_that_would_execute_under_source_is_rejected(tmp_path):
    """The line is written so that `source` really would run it -- the quote closes and a second
    command follows. An earlier version of this case used $(...) inside single quotes, which a
    shell would not have expanded either, so it could not tell the two implementations apart.
    """
    marker = tmp_path / "pwned"
    env = tmp_path / "evil.env"
    env.write_text(f"REPO='a'; touch {marker}\n", encoding="utf-8")

    with pytest.raises(gru.Failure) as excinfo:
        gru.read_env_file(str(env))
    assert "not a single quoted value" in str(excinfo.value)
    assert not marker.exists()


def test_that_line_really_would_execute_under_a_shell(tmp_path):
    """Positive control for the case above, kept in the suite: proves the payload is live, so the
    rejection is doing work rather than describing a harmless string."""
    marker = tmp_path / "pwned-by-shell"
    script = tmp_path / "evil.env"
    script.write_text(f"REPO='a'; touch {marker}\n", encoding="utf-8")
    subprocess.run(["sh", "-c", f". {script}"], check=True)
    assert marker.exists()


def test_unknown_setting_is_rejected(tmp_path):
    env = tmp_path / "bad.env"
    env.write_text("REPO='a/b'\nRM_RF='/'\n", encoding="utf-8")
    with pytest.raises(gru.Failure) as excinfo:
        gru.read_env_file(str(env))
    assert "unknown setting RM_RF" in str(excinfo.value)


def test_comments_and_blank_lines_ignored(tmp_path):
    env = tmp_path / "ok.env"
    env.write_text("# a comment\n\nREPO='a/b'\n", encoding="utf-8")
    assert gru.read_env_file(str(env)) == {"REPO": "a/b"}


def test_value_with_spaces_survives_quoting(tmp_path):
    env = tmp_path / "ok.env"
    env.write_text("POST_UPDATE_COMMAND='systemctl try-restart example.service'\n",
                   encoding="utf-8")
    assert gru.read_env_file(str(env))["POST_UPDATE_COMMAND"] == \
        "systemctl try-restart example.service"


def test_flag_outranks_env_file(tmp_path, capsys):
    env = write_env(tmp_path, REPO="acme/wrong")
    install_fake_binary(tmp_path, "1.0.0")
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"RIGHT"})
    release = release_with_asset("v1.0.1", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/right", release)

    code, out = run(["--env-file", str(env), "--api-base", api, "--repo", "acme/right",
                     "--version-command", str(tmp_path / "bin" / "tool")], capsys)
    assert code == 0, out
    assert (tmp_path / "bin" / "tool").read_bytes() == b"RIGHT"


# ---------------------------------------------------------------------------------------------
# C25-C27  validation, defaults, symlink
# ---------------------------------------------------------------------------------------------


def test_tarball_without_binary_in_archive_is_rejected(tmp_path):
    config = {"REPO": "a/b", "ASSET_PATTERN": "x", "ARCHIVE_TYPE": "tarball",
              "BINARY_IN_ARCHIVE": ""}
    with pytest.raises(gru.Failure) as excinfo:
        gru.validate(config)
    assert "requires BINARY_IN_ARCHIVE" in str(excinfo.value)


def test_unknown_archive_type_is_rejected(tmp_path):
    config = {"REPO": "a/b", "ASSET_PATTERN": "x", "ARCHIVE_TYPE": "zip", "BINARY_IN_ARCHIVE": ""}
    with pytest.raises(gru.Failure) as excinfo:
        gru.validate(config)
    assert "ARCHIVE_TYPE must be one of" in str(excinfo.value)


def test_stamp_path_defaults_beside_the_binary(tmp_path):
    env = write_env(tmp_path, TAG_STAMP_PATH="")
    args = gru.parse_args(["--env-file", str(env)])
    config = gru.build_config(args)
    assert config["TAG_STAMP_PATH"] == str(tmp_path / "bin" / "tool") + ".release-tag"


def test_symlink_skipped_when_it_would_point_at_the_binary(tmp_path):
    """Several callers install straight into the link directory, where SYMLINK_PATH resolves to
    BINARY_PATH. That must be a no-op, not an attempt to link a file to itself."""
    binary = install_fake_binary(tmp_path, "1.0.0")
    gru.refresh_symlink({"SYMLINK_PATH": str(binary), "BINARY_PATH": str(binary)})
    assert not os.path.islink(binary)


def test_symlink_refuses_to_replace_a_regular_file(tmp_path):
    binary = install_fake_binary(tmp_path, "1.0.0")
    occupied = tmp_path / "occupied"
    occupied.write_text("owned by another package", encoding="utf-8")
    with pytest.raises(gru.Failure) as excinfo:
        gru.refresh_symlink({"SYMLINK_PATH": str(occupied), "BINARY_PATH": str(binary)})
    assert "not a symlink" in str(excinfo.value)
    assert occupied.read_text() == "owned by another package"


def test_symlink_restored_when_removed_by_hand(tmp_path):
    binary = install_fake_binary(tmp_path, "1.0.0")
    link = tmp_path / "link"
    config = {"SYMLINK_PATH": str(link), "BINARY_PATH": str(binary)}
    gru.refresh_symlink(config)
    assert os.readlink(link) == str(binary)
    link.unlink()
    gru.refresh_symlink(config)
    assert os.readlink(link) == str(binary)


# ---------------------------------------------------------------------------------------------
# C28  dry run
# ---------------------------------------------------------------------------------------------


def test_dry_run_reports_without_touching_anything(tmp_path, capsys):
    install_fake_binary(tmp_path, "1.0.0")
    binary = tmp_path / "bin" / "tool"
    before = binary.read_bytes()
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"NEW"})
    release = release_with_asset("v1.1.0", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release)
    env = write_env(tmp_path, VERSION_COMMAND=str(binary))

    code, out = run(["--env-file", str(env), "--api-base", api, "--dry-run"], capsys)
    assert code == 0, out
    assert out.startswith("WOULD-UPDATE")
    assert "1.0.0 -> 1.1.0" in out
    assert binary.read_bytes() == before


# ---------------------------------------------------------------------------------------------
# C29  pinned release tag
# ---------------------------------------------------------------------------------------------


def test_release_tag_uses_the_tags_endpoint(tmp_path, capsys):
    install_fake_binary(tmp_path, "1.0.0")
    archive = make_tarball(tmp_path, "tool-linux-amd64.tar.gz", {"tool": b"PINNED"})
    release = release_with_asset("v0.9.0", "tool-linux-amd64.tar.gz", f"file://{archive}")
    api = api_tree(tmp_path, "acme/tool", release, ref="tags/v0.9.0")
    env = write_env(tmp_path, RELEASE_TAG="v0.9.0", VERSION_COMMAND=str(tmp_path / "bin" / "tool"))

    code, out = run(["--env-file", str(env), "--api-base", api], capsys)
    assert code == 0, out
    assert (tmp_path / "bin" / "tool").read_bytes() == b"PINNED"
