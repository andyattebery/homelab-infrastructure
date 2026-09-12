#!/usr/bin/env python3
"""Every github_release_install caller must be able to reach an update.

The role offers two ways to answer "is the installed build current?". One of them can be wired so
that it never says no:

    github_release_install_version_command: "echo latest"
    github_release_install_version_regex: "(.*)"

That compares a literal string against itself. Both sides move together, the binary already
exists, so `needs_install` is false on every run, forever. It is idempotent and it is useless --
the host installs once and never updates again, with every playbook run reporting no change.

That is not theory. playbook-wsl-01.yaml carried exactly this against BtbN/FFmpeg-Builds, whose
`latest` tag is rolling: the host took one ffmpeg build and then silently declined every later
one. The role's own defaults/main.yaml warns about the idiom; the warning was not enough on its
own, which is why this check exists.

The fix is `github_release_install_use_tag_stamp: true`, which compares the installed tag AND
asset digest against what the release now offers -- so a moved tag, or a rebuilt asset under an
unchanged tag, both reinstall.

This walks every playbook and role task file, recursing through block/rescue/always, and fails on
any include_role/import_role of github_release_install whose `version_command` starts with `echo`
without `use_tag_stamp` set.

Python rather than a Jinja expression on purpose, for the reason check-until-waits.py gives: the
nesting is arbitrary-depth and a Jinja flatten has to hard-code how deep to look, which is the
same vacuous pass the guard exists to catch.
"""
import sys
from pathlib import Path

import yaml

ROLE = "github_release_install"


def truthy(value):
    return str(value).strip().lower() in ("true", "yes", "on", "1")


def walk(tasks, path, out):
    """Collect every include/import of the role, including inside block/rescue/always."""
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in ("block", "rescue", "always"):
            if key in task:
                walk(task[key], path, out)
        for action in ("ansible.builtin.include_role", "ansible.builtin.import_role",
                       "include_role", "import_role"):
            spec = task.get(action)
            if isinstance(spec, dict) and spec.get("name") == ROLE:
                name = str(task.get("name", "<unnamed>")).split("\n")[0].strip()
                out.append((path, name, task.get("vars") or {}))


def walk_roles_keyword(entries, path, out):
    """`roles:` entries, which name the role directly rather than through include_role."""
    if not isinstance(entries, list):
        return
    for entry in entries:
        if isinstance(entry, str) and entry == ROLE:
            out.append((path, "roles: keyword", {}))
        elif isinstance(entry, dict) and entry.get("role") == ROLE:
            out.append((path, "roles: keyword", entry))


def main():
    root = Path(__file__).resolve().parent.parent
    targets = sorted(root.glob("roles/**/*.yaml")) + sorted(root.glob("roles/**/*.yml"))
    targets += sorted(root.glob("playbook-*.yaml")) + sorted(root.glob("playbook-*.yml"))

    callers, unparseable = [], []
    for path in targets:
        rel = str(path.relative_to(root))
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        try:
            docs = yaml.safe_load(path.read_text())
        except Exception as exc:  # noqa: BLE001 - any parse failure is a finding
            unparseable.append((rel, str(exc).split("\n")[0]))
            continue
        if not isinstance(docs, list):
            continue
        for entry in docs:
            if isinstance(entry, dict) and any(
                k in entry for k in ("tasks", "pre_tasks", "post_tasks", "handlers", "roles")
            ):
                for section in ("pre_tasks", "tasks", "post_tasks", "handlers"):
                    walk(entry.get(section), rel, callers)
                walk_roles_keyword(entry.get("roles"), rel, callers)
            else:
                walk([entry], rel, callers)

    unreachable = []
    for path, name, cvars in callers:
        command = str(cvars.get("github_release_install_version_command", "")).strip()
        stamped = truthy(cvars.get("github_release_install_use_tag_stamp", False))
        if command.startswith("echo") and not stamped:
            unreachable.append((path, name, command))

    print(f"checked {len(targets)} files, found {len(callers)} {ROLE} call sites")
    for path, name, cvars in callers:
        mode = ("tag stamp" if truthy(cvars.get("github_release_install_use_tag_stamp", False))
                else "version command")
        print(f"  {path}: {name} [{mode}]")

    if unreachable:
        print(f"\n{len(unreachable)} caller(s) whose comparison CAN NEVER FAIL:")
        for path, name, command in unreachable:
            print(f"  {path}\n      {name}\n      -> version_command: {command!r}")
        print(
            "\nThat compares a literal against itself, so the binary is installed once and never\n"
            "updated again. Replace both version_command and version_regex with:\n"
            "    github_release_install_use_tag_stamp: true"
        )

    if unparseable:
        print(f"\n{len(unparseable)} file(s) that are NOT VALID YAML and were not checked:")
        for rel, err in unparseable:
            print(f"  {rel}\n      {err}")

    if unreachable or unparseable:
        return 1

    print(f"every {ROLE} caller can reach an update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
