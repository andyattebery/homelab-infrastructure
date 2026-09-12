#!/usr/bin/env python3
"""github-release-update -- update one binary installed by the github_release_install role.

    github-release-update --name <name> [--config-dir DIR] [--dry-run] [--force]
    github-release-update --env-file /etc/github-release-install/<name>.env
    github-release-update --repo owner/repo --asset-pattern PAT --archive-type tarball \\
                          --binary-path /usr/local/bin/thing --binary-in-archive thing

Applies the same "is the installed build current?" decision the Ansible role applies, reading the
same settings from an env file the role writes:

  * tag-stamp mode (USE_TAG_STAMP=true) compares "<tag_name> <digest|id:N>" against a stamp file
    beside the binary. This is the mode for builds whose own version output can never equal the
    release tag, and for repos that replace assets in place under an unchanged tag. The digest
    half is what makes a replaced asset visible; a tag alone is not an identity.
  * version-command mode runs VERSION_COMMAND and matches VERSION_REGEX group 1 against the
    release tag with one leading 'v' stripped.

It does NOT install a binary that is absent -- that is Ansible's job. A missing BINARY_PATH prints
SKIP and exits 0, which is also how an env file left behind by a role you no longer call stops
resurrecting something you removed. The check runs BEFORE the API call so an orphan costs no
request against the unauthenticated 60/hour limit.

Prints exactly one status line: OK | CHANGED | WOULD-UPDATE | SKIP | FAILED.
Exit status is 0 unless the update failed. Stdlib only.

THIS IS A SECOND IMPLEMENTATION of the role's decision logic -- the two can drift, and nothing
here prevents it; see the role's README. Python's `re` is used deliberately because it is the
engine behind Ansible's `regex_search`, so every pattern behaves identically on both sides.
"""

import argparse
import filecmp
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

PROG = "github-release-update"

DEFAULT_CONFIG_DIR = "/etc/github-release-install"
DEFAULT_API_BASE = "https://api.github.com"

# Mirrors defaults/main.yaml. Keys are the env-file names; the second element is the default,
# and None means "no default, must be supplied". VERSION_COMMAND and TAG_STAMP_PATH default to
# expressions over BINARY_PATH, which the role renders before writing -- resolved here too so the
# script still works when driven entirely from flags.
SETTINGS = (
    "NAME",
    "REPO",
    "ASSET_PATTERN",
    "ARCHIVE_TYPE",
    "BINARY_PATH",
    "BINARY_IN_ARCHIVE",
    "VERSION_COMMAND",
    "VERSION_REGEX",
    "RELEASE_TAG",
    "USE_TAG_STAMP",
    "TAG_STAMP_PATH",
    "SYMLINK",
    "SYMLINK_PATH",
    "POST_UPDATE_COMMAND",
)

DEFAULTS = {
    "VERSION_REGEX": r"([0-9]+\.[0-9]+\.[0-9]+)",
    "RELEASE_TAG": "",
    "USE_TAG_STAMP": "false",
    "SYMLINK": "false",
    "POST_UPDATE_COMMAND": "",
    "BINARY_IN_ARCHIVE": "",
}

ARCHIVE_TYPES = ("deb", "tarball", "binary")


class Failure(Exception):
    """An expected, reportable failure. Printed as FAILED; never a traceback."""


def log(msg):
    print(f"{PROG}: {msg}", file=sys.stderr)


def truthy(value):
    """Match Ansible's `| bool` for the strings a template can produce."""
    return str(value).strip().lower() in ("true", "yes", "on", "1")


# --------------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------------


def read_env_file(path):
    """Parse KEY='value' lines. Deliberately parsed, never sourced: the file is valid shell to
    read, but handing it to a shell would make every env file a command-injection surface."""
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        raise Failure(f"cannot read env file {path}: {exc}") from exc

    config = {}
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Failure(f"{path}:{lineno}: not a KEY=value line")
        key, _, value = line.partition("=")
        key = key.strip()
        if key not in SETTINGS:
            raise Failure(f"{path}:{lineno}: unknown setting {key}")
        parts = shlex.split(value, comments=False, posix=True)
        if len(parts) > 1:
            raise Failure(f"{path}:{lineno}: {key} is not a single quoted value")
        config[key] = parts[0] if parts else ""
    return config


def build_config(args):
    config = dict(DEFAULTS)

    if args.env_file:
        env_path = args.env_file
    elif args.name:
        env_path = os.path.join(args.config_dir, f"{args.name}.env")
    else:
        env_path = None

    if env_path:
        config.update(read_env_file(env_path))
        config.setdefault("NAME", os.path.splitext(os.path.basename(env_path))[0])

    # Explicit flags outrank the env file, so a single install can be driven entirely from argv.
    for key in SETTINGS:
        value = getattr(args, key.lower(), None)
        if value is not None:
            config[key] = value

    for key in SETTINGS:
        config.setdefault(key, "")

    if not config["BINARY_PATH"]:
        raise Failure("BINARY_PATH is required (env file, or --binary-path)")
    if not config["NAME"]:
        config["NAME"] = os.path.basename(config["BINARY_PATH"])
    if not config["VERSION_COMMAND"]:
        config["VERSION_COMMAND"] = f"{config['BINARY_PATH']} --version"
    if not config["TAG_STAMP_PATH"]:
        config["TAG_STAMP_PATH"] = f"{config['BINARY_PATH']}.release-tag"
    if not config["SYMLINK_PATH"]:
        base = os.path.basename(config["BINARY_PATH"])
        config["SYMLINK_PATH"] = f"/usr/local/bin/{base}"

    validate(config)
    return config


def validate(config):
    """Mirrors the role's `Validate required inputs` assert."""
    if not config["REPO"]:
        raise Failure("REPO is required")
    if not config["ASSET_PATTERN"]:
        raise Failure("ASSET_PATTERN is required")
    if config["ARCHIVE_TYPE"] not in ARCHIVE_TYPES:
        raise Failure(f"ARCHIVE_TYPE must be one of {'|'.join(ARCHIVE_TYPES)}, got {config['ARCHIVE_TYPE']!r}")
    if config["ARCHIVE_TYPE"] == "tarball" and not config["BINARY_IN_ARCHIVE"]:
        raise Failure("ARCHIVE_TYPE=tarball requires BINARY_IN_ARCHIVE")


# --------------------------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------------------------


def open_url(url, accept=None):
    request = urllib.request.Request(url)
    # Headers are pointless on file:// (the test fixtures' scheme) and GITHUB_TOKEN must never be
    # attached to a non-GitHub URL, so both are gated on the scheme rather than added blindly.
    if url.startswith(("http://", "https://")):
        request.add_header("User-Agent", PROG)
        if accept:
            request.add_header("Accept", accept)
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(request)


def fetch_release(api_base, repo, release_tag):
    ref = f"tags/{release_tag}" if release_tag else "latest"
    url = f"{api_base.rstrip('/')}/repos/{repo}/releases/{ref}"
    try:
        with open_url(url, accept="application/vnd.github+json") as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code == 403:
            hint = " (unauthenticated GitHub allows 60 requests/hour per source IP; set GITHUB_TOKEN)"
        raise Failure(f"GET {url} failed: HTTP {exc.code}{hint}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Failure(f"GET {url} failed: {exc}") from exc


def select_asset(release, pattern):
    """Mirrors `select('search', pattern) | first`: re.search, first match wins."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise Failure(f"ASSET_PATTERN is not a valid regex: {exc}") from exc

    assets = release.get("assets") or []
    matches = [asset for asset in assets if compiled.search(asset.get("name", ""))]
    if not matches:
        names = ", ".join(sorted(asset.get("name", "") for asset in assets)) or "(none)"
        raise Failure(f"no asset matches {pattern!r}; release publishes: {names}")
    if len(matches) > 1:
        # The role takes the first match without complaint. Behaviour is mirrored exactly -- this
        # only says so out loud, because an ambiguous pattern is how you end up installing the
        # arm64 build on an amd64 host and finding out much later.
        chosen = matches[0].get("name")
        others = ", ".join(asset.get("name", "") for asset in matches[1:])
        log(f"warning: {pattern!r} matches {len(matches)} assets; using {chosen} (also: {others})")
    return matches[0]


def asset_fingerprint(asset):
    """Mirrors the role's digest-or-id fallback.

    `digest` is a recent addition to the releases API. The fallback is explicit because an
    unguarded lookup evaluates to empty and quietly collapses the comparison back to tag-only --
    which is the bug the digest was added to fix.
    """
    digest = asset.get("digest") or ""
    if digest:
        return digest
    return f"id:{asset.get('id')}"


# --------------------------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------------------------


def installed_version(config):
    """Run VERSION_COMMAND and extract group 1 of VERSION_REGEX.

    Split with shlex and executed directly -- no shell -- matching ansible.builtin.command, which
    is what makes `echo latest` resolve to /bin/echo rather than a builtin. Failure is not fatal:
    a binary without a version flag leaves this empty and the update fires, exactly as the role
    treats a fresh host.
    """
    try:
        argv = shlex.split(config["VERSION_COMMAND"])
    except ValueError as exc:
        raise Failure(f"VERSION_COMMAND is not parseable: {exc}") from exc
    if not argv:
        raise Failure("VERSION_COMMAND is empty")

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        log(f"warning: VERSION_COMMAND failed to execute: {exc}")
        return ""

    try:
        match = re.search(config["VERSION_REGEX"], proc.stdout)
    except re.error as exc:
        raise Failure(f"VERSION_REGEX is not a valid regex: {exc}") from exc
    if not match:
        return ""
    return match.group(1) if match.groups() else match.group(0)


def strip_leading_v(tag):
    """Mirror `regex_replace('^v', '')`: anchored, so only a single leading 'v' is removed.

    A plain replace() would turn 'v8.1.2-2+nvenc' into '8.1.2-2+nenc' -- silently mangling any tag
    with a 'v' later in it, which is most of the interesting ones.
    """
    return re.sub(r"^v", "", tag)


def read_stamp(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise Failure(f"cannot read stamp {path}: {exc}") from exc


def decide(config, release, asset):
    """Return (needs_update, installed_repr, wanted_repr)."""
    tag = release.get("tag_name") or ""
    if not tag:
        raise Failure("release has no tag_name")

    if truthy(config["USE_TAG_STAMP"]):
        wanted = f"{tag} {asset_fingerprint(asset)}"
        current = read_stamp(config["TAG_STAMP_PATH"])
    else:
        wanted = strip_leading_v(tag)
        current = installed_version(config)

    return current != wanted, current or "(unknown)", wanted


# --------------------------------------------------------------------------------------------
# Installing
# --------------------------------------------------------------------------------------------


def download(url, dest):
    try:
        with open_url(url) as response, open(dest, "wb") as handle:
            shutil.copyfileobj(response, handle)
    except (urllib.error.URLError, OSError) as exc:
        raise Failure(f"download of {url} failed: {exc}") from exc


def digest_of(path):
    if not os.path.exists(path):
        return None
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def place(src, dest):
    """Replace dest with src only when the bytes differ. Returns True if the file changed.

    The byte comparison is not an optimisation. ansible.builtin.copy compares content, so the
    binary's mtime shifts only on a real change -- and a caller keys a service restart off that
    mtime. A script that rewrote the file unconditionally would make the next playbook run report
    a change that did not happen.
    """
    if os.path.exists(dest) and filecmp.cmp(src, dest, shallow=False):
        return False

    parent = os.path.dirname(dest) or "."
    if not os.access(parent, os.W_OK):
        raise Failure(f"{parent} is not writable; run with sudo")

    tmp = os.path.join(parent, f".{os.path.basename(dest)}.{PROG}.tmp")
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o755)
        if os.geteuid() == 0:
            os.chown(tmp, 0, 0)
        os.replace(tmp, dest)  # same directory, so same filesystem, so atomic
    except OSError as exc:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise Failure(f"installing {dest} failed: {exc}") from exc
    return True


def extract_tarball(archive, dest_dir):
    try:
        with tarfile.open(archive, "r:*") as tar:
            try:
                tar.extractall(dest_dir, filter="data")
            except TypeError:
                # `filter` landed in 3.12 and was backported to 3.8.17+/3.9.17+/3.10.12+/3.11.4+.
                # Every host here is newer than that; the fallback is for the one that is not.
                tar.extractall(dest_dir)  # noqa: S202
    except (tarfile.TarError, OSError) as exc:
        raise Failure(f"extracting {archive} failed: {exc}") from exc


def resolve_in_archive(pattern, tag):
    """Substitute ${VERSION} / ${TAG} in BINARY_IN_ARCHIVE.

    Needed because at least one upstream names the directory inside the tarball after the release
    version, so a literal captured at deploy time is wrong for every later release. The
    architecture is NOT substituted here -- the role resolves it when it renders the env file,
    which is per-host and therefore already correct.
    """
    return pattern.replace("${VERSION}", strip_leading_v(tag)).replace("${TAG}", tag)


def install(config, asset, release, workdir, apt_get):
    url = asset.get("browser_download_url")
    if not url:
        raise Failure(f"asset {asset.get('name')!r} has no browser_download_url")

    archive_type = config["ARCHIVE_TYPE"]
    binary_path = config["BINARY_PATH"]

    if archive_type == "deb":
        # dpkg owns the destination, so bytes cannot be compared before the fact. Hash either
        # side of apt instead, which answers the same question the byte comparison does.
        before = digest_of(binary_path)
        deb = os.path.join(workdir, asset.get("name") or "package.deb")
        download(url, deb)
        proc = subprocess.run(
            [apt_get, "install", "-y", deb],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        if proc.returncode != 0:
            # No pre-flight euid check: apt-get reports its own permission failure perfectly well,
            # and a check here would sit in front of the injected apt-get the tests rely on. The
            # hint is added only when being non-root is a plausible cause.
            detail = proc.stderr.strip() or proc.stdout.strip()
            hint = "; run with sudo" if os.geteuid() != 0 else ""
            raise Failure(f"{apt_get} install failed: {detail}{hint}")
        return digest_of(binary_path) != before

    if archive_type == "tarball":
        archive = os.path.join(workdir, asset.get("name") or "asset.tar")
        download(url, archive)
        extracted = os.path.join(workdir, "extract")
        os.mkdir(extracted)
        extract_tarball(archive, extracted)
        relative = resolve_in_archive(config["BINARY_IN_ARCHIVE"], release.get("tag_name", ""))
        source = os.path.join(extracted, relative)
        if not os.path.isfile(source):
            raise Failure(f"{relative} is not in the archive")
        return place(source, binary_path)

    staged = os.path.join(workdir, os.path.basename(binary_path))
    download(url, staged)
    return place(staged, binary_path)


def write_stamp(config, value):
    """Written last on purpose: a failed download or extract never reaches here, so the previous
    stamp survives and the next run retries instead of believing itself converged."""
    path = config["TAG_STAMP_PATH"]
    parent = os.path.dirname(path) or "."
    tmp = os.path.join(parent, f".{os.path.basename(path)}.{PROG}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(f"{value}\n")
        os.chmod(tmp, 0o644)
        if os.geteuid() == 0:
            os.chown(tmp, 0, 0)
        os.replace(tmp, path)
    except OSError as exc:
        raise Failure(f"writing stamp {path} failed: {exc}") from exc


def refresh_symlink(config):
    """Asserted on every run, not only on install, so a link removed by hand comes back.

    Skipped when the link would point at the binary itself: a caller that installs straight into
    the link directory resolves SYMLINK_PATH to BINARY_PATH, and the binary is already on PATH.
    Never replaces a regular file -- that fails loudly rather than clobbering something another
    package owns.
    """
    link = config["SYMLINK_PATH"]
    target = config["BINARY_PATH"]
    if os.path.abspath(link) == os.path.abspath(target):
        return
    if os.path.islink(link):
        if os.readlink(link) == target:
            return
        os.unlink(link)
    elif os.path.exists(link):
        raise Failure(f"{link} exists and is not a symlink; refusing to replace it")
    try:
        os.symlink(target, link)
    except OSError as exc:
        raise Failure(f"linking {link} -> {target} failed: {exc}") from exc


def run_post_update(command):
    """Run through a shell, unlike VERSION_COMMAND: this one is a command a human wrote to be run
    that way. Only ever reached when the binary's bytes actually changed."""
    proc = subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise Failure(
            f"POST_UPDATE_COMMAND failed ({proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Update one binary installed by the github_release_install Ansible role.",
        epilog="Settings come from an env file the role writes; any of them can be overridden by "
        "the matching flag. A binary that is not already installed is skipped, not installed.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--env-file", help="path to an env file written by the role")
    source.add_argument("--name", help="install name; resolved to <config-dir>/<name>.env")

    parser.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR,
                        help=f"where env files live (default: {DEFAULT_CONFIG_DIR})")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE,
                        help=f"GitHub API base URL (default: {DEFAULT_API_BASE})")
    parser.add_argument("--apt-get", default="/usr/bin/apt-get",
                        help="apt-get to use for ARCHIVE_TYPE=deb (default: /usr/bin/apt-get)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change; download nothing")
    parser.add_argument("--force", action="store_true",
                        help="reinstall even when current, and even when the binary is absent")

    # NAME is deliberately absent here: `--name` above already sets it. The install name and the
    # env file's basename are the same value by design, so a second flag for it would be two ways
    # to say one thing, and argparse rejects the duplicate anyway.
    overrides = parser.add_argument_group("setting overrides")
    for key in SETTINGS:
        if key == "NAME":
            continue
        overrides.add_argument(f"--{key.lower().replace('_', '-')}", dest=key.lower(),
                               help=f"override {key}")
    return parser.parse_args(argv)


def run(args):
    config = build_config(args)
    name = config["NAME"]

    # Before the network call, deliberately: an orphaned env file must not spend one of the 60
    # unauthenticated requests per hour to discover it has nothing to do.
    if not os.path.exists(config["BINARY_PATH"]) and not args.force:
        print(f"SKIP    {name}  binary absent at {config['BINARY_PATH']}")
        return 0

    release = fetch_release(args.api_base, config["REPO"], config["RELEASE_TAG"])
    asset = select_asset(release, config["ASSET_PATTERN"])
    needs_update, current, wanted = decide(config, release, asset)

    if not needs_update and not args.force:
        print(f"OK      {name}  {wanted}")
        return 0

    if args.dry_run:
        print(f"WOULD-UPDATE {name}  {current} -> {wanted}")
        return 0

    workdir = tempfile.mkdtemp(prefix=f"{PROG}.")
    try:
        changed = install(config, asset, release, workdir, args.apt_get)
    finally:
        # The whole archive is extracted, not just the requested file, and on a host with a tmpfs
        # /tmp that is RAM held until reboot. Removed whether or not the install succeeded.
        shutil.rmtree(workdir, ignore_errors=True)

    if truthy(config["USE_TAG_STAMP"]):
        write_stamp(config, wanted)
    if truthy(config["SYMLINK"]):
        refresh_symlink(config)

    if not changed:
        # Reached when a release moved but the bytes did not. The stamp is now current, so the
        # next run is a no-op; nothing consuming the binary needs telling.
        print(f"OK      {name}  {wanted} (metadata refreshed, bytes unchanged)")
        return 0

    if config["POST_UPDATE_COMMAND"]:
        run_post_update(config["POST_UPDATE_COMMAND"])

    print(f"CHANGED {name}  {current} -> {wanted}")
    return 0


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return run(args)
    except Failure as exc:
        name = args.name or (os.path.splitext(os.path.basename(args.env_file))[0]
                             if args.env_file else "-")
        print(f"FAILED  {name}  {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
