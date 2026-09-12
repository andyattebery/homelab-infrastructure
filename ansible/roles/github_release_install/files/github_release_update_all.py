#!/usr/bin/env python3
"""github-release-update-all -- update every binary the github_release_install role deployed here.

    github-release-update-all [--dry-run] [--force] [--config-dir DIR]

Walks <config-dir>/*.env -- one file per install, written by the role -- and runs
github-release-update against each, then prints a summary.

Each install runs in its own process rather than being imported, so one failure cannot abort the
rest: a host with five managed binaries should update the four that are fine and tell you about
the fifth, not stop at the first bad one. The exit status is non-zero if any install failed.

An env file whose binary is absent reports SKIP and is not an error. That is how an install you
stopped deploying stops being updated, without anything here needing to know the role's full
caller list. Stdlib only.
"""

import argparse
import glob
import os
import subprocess
import sys

PROG = "github-release-update-all"

DEFAULT_CONFIG_DIR = "/etc/github-release-install"

# The worker's status vocabulary. Anything else in column one is counted as a failure, because an
# unrecognised status means the worker changed and this script did not.
STATUSES = ("OK", "CHANGED", "WOULD-UPDATE", "SKIP", "FAILED")


def default_updater():
    """The worker beside this script.

    Deployed, the pair are `github-release-update` and `github-release-update-all`. In a repo
    checkout they still carry their `.py` names, and being able to run the pair straight out of
    the checkout is worth the two-line lookup.
    """
    here = os.path.dirname(os.path.realpath(__file__))
    for candidate in ("github-release-update", "github_release_update.py"):
        path = os.path.join(here, candidate)
        if os.path.exists(path):
            return path
    return os.path.join(here, "github-release-update")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Update every binary installed by the github_release_install Ansible role.",
    )
    parser.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR,
                        help=f"where env files live (default: {DEFAULT_CONFIG_DIR})")
    parser.add_argument("--updater", default=None,
                        help="path to github-release-update (default: beside this script)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change; download nothing")
    parser.add_argument("--force", action="store_true",
                        help="reinstall every install even when current")
    parser.add_argument("--api-base", default=None, help="passed through to the updater")
    parser.add_argument("--apt-get", default=None, help="passed through to the updater")
    return parser.parse_args(argv)


def run_one(updater, env_file, args):
    """Run the worker for one env file. Returns (status, output_line)."""
    command = [sys.executable, updater, "--env-file", env_file]
    if args.dry_run:
        command.append("--dry-run")
    if args.force:
        command.append("--force")
    if args.api_base:
        command += ["--api-base", args.api_base]
    if args.apt_get:
        command += ["--apt-get", args.apt_get]

    proc = subprocess.run(command, capture_output=True, text=True, check=False)

    # The worker's stderr carries warnings that are worth seeing but are not the result.
    if proc.stderr.strip():
        print(proc.stderr.rstrip(), file=sys.stderr)

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        name = os.path.splitext(os.path.basename(env_file))[0]
        return "FAILED", f"FAILED  {name}  updater produced no output (exit {proc.returncode})"

    line = lines[-1]
    status = line.split(maxsplit=1)[0]
    if status not in STATUSES:
        return "FAILED", line
    return status, line


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    updater = args.updater or default_updater()

    if not os.path.exists(updater):
        print(f"{PROG}: updater not found at {updater}", file=sys.stderr)
        return 2
    if not os.path.isdir(args.config_dir):
        print(f"{PROG}: no config directory at {args.config_dir}; nothing to update")
        return 0

    env_files = sorted(glob.glob(os.path.join(args.config_dir, "*.env")))
    if not env_files:
        print(f"{PROG}: no env files in {args.config_dir}; nothing to update")
        return 0

    counts = dict.fromkeys(STATUSES, 0)
    for env_file in env_files:
        status, line = run_one(updater, env_file, args)
        counts[status] += 1
        print(line, flush=True)

    print(
        f"\n{len(env_files)} install(s): "
        f"{counts['CHANGED']} changed, "
        f"{counts['WOULD-UPDATE']} would update, "
        f"{counts['OK']} already current, "
        f"{counts['SKIP']} skipped, "
        f"{counts['FAILED']} failed"
    )
    return 1 if counts["FAILED"] else 0


if __name__ == "__main__":
    sys.exit(main())
