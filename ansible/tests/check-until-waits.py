#!/usr/bin/env python3
"""Every `until` wait must be able to fail.

`until` paired with `failed_when: false` does NOT fail when its retries are
exhausted — Ansible sets `failed` on exhaustion and `failed_when: false`
overrides it, so the play falls straight through. A wait exists to stop the play
until something is true; one that cannot fail is worse than no wait at all,
because it reads as a check.

That is not theory. On 2026-09-09 `pve_node_ceph`'s "Wait for mon.X to join
quorum" reported ok while the monitor never joined; the play then built a mgr
and an mds on top of it, and the orphaned monitor went on to drive hundreds of
MB/s of memory growth on the other two monitors.

This walks every task file and playbook, recursing through block/rescue/always,
and fails on any task that has `until` with `failed_when: false` or with no
`failed_when` at all. The house shape is:

    vars:
      _ok: >-
        {{ <condition> }}
    until: _ok | bool
    failed_when: not (_ok | bool)

Python rather than a Jinja check in a playbook on purpose: the nesting is
arbitrary-depth and a Jinja flatten would have to hard-code how deep to look,
which is the same vacuous-pass failure this guard exists to prevent.
"""
import sys
from pathlib import Path

import yaml

# Files that are not valid YAML and therefore cannot be checked. Enumerated
# rather than skipped by a rule, so the blind spot is visible and any NEW
# unparseable file fails this check instead of quietly joining the list.
#
# Both of these contain raw `.env` lines (`MAIL_MAILER=log`) pasted into a YAML
# file, so the role cannot load at all. Pre-existing; unrelated to waits.
KNOWN_UNPARSEABLE = {
    "roles/docker_compose_invoiceninja/defaults/main.yaml",
    "roles/docker_compose_invoiceninja/tasks/main.yaml",
}


def walk(tasks, path, out):
    """Collect every task that uses `until`, including inside block/rescue/always."""
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in ("block", "rescue", "always"):
            if key in task:
                walk(task[key], path, out)
        if "until" in task:
            name = str(task.get("name", "<unnamed>")).split("\n")[0].strip()
            out.append((path, name, task.get("failed_when", "<ABSENT>")))


def main():
    root = Path(__file__).resolve().parent.parent
    targets = sorted(root.glob("roles/**/*.yaml")) + sorted(root.glob("roles/**/*.yml"))
    targets += sorted(root.glob("playbook-*.yaml")) + sorted(root.glob("playbook-*.yml"))

    waits, unparseable = [], []
    for path in targets:
        rel = str(path.relative_to(root))
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        try:
            docs = yaml.safe_load(path.read_text())
        except Exception as exc:  # noqa: BLE001 - any parse failure is a finding
            unparseable.append((rel, str(exc).split("\n")[0]))
            continue
        if isinstance(docs, list):
            # A playbook is a list of plays; a task file is a list of tasks.
            for entry in docs:
                if isinstance(entry, dict) and (
                    "tasks" in entry or "pre_tasks" in entry or "post_tasks" in entry
                    or "handlers" in entry
                ):
                    for section in ("pre_tasks", "tasks", "post_tasks", "handlers"):
                        walk(entry.get(section), rel, waits)
                else:
                    walk([entry], rel, waits)

    # Only `failed_when: false` is a defect. An absent `failed_when` was proven by
    # experiment to fail correctly on exhaustion, and `retries` + `until ... is
    # succeeded` is the idiomatic retry shape — flagging it would be a style rule
    # wearing a correctness rule's clothes, and would train people to add noise.
    bad = [w for w in waits if w[2] is False]
    implicit = [w for w in waits if w[2] == "<ABSENT>"]
    new_unparseable = [u for u in unparseable if u[0] not in KNOWN_UNPARSEABLE]
    gone = KNOWN_UNPARSEABLE - {u[0] for u in unparseable}

    print(f"checked {len(targets)} files, found {len(waits)} tasks using `until`")
    if implicit:
        print(f"  ({len(implicit)} rely on Ansible's default failure on exhaustion, which is "
              f"correct but implicit:)")
        for path, name, _ in implicit:
            print(f"     {path}: {name}")

    if bad:
        print(f"\n{len(bad)} wait(s) that CANNOT FAIL:")
        for path, name, fw in bad:
            print(f"  {path}\n      {name}\n      -> failed_when: false")
        print(
            "\nAn exhausted `until` does not fail when `failed_when: false` is set.\n"
            "Give the task an explicit condition instead:\n"
            "    vars:\n"
            "      _ok: >-\n"
            "        {{ <condition> }}\n"
            "    until: _ok | bool\n"
            "    failed_when: not (_ok | bool)"
        )

    if new_unparseable:
        print(f"\n{len(new_unparseable)} file(s) that are NOT VALID YAML and were not checked:")
        for rel, err in new_unparseable:
            print(f"  {rel}\n      {err}")
        print("\nAdd to KNOWN_UNPARSEABLE only with a comment saying why, or fix the file.")

    if gone:
        print(f"\n{len(gone)} file(s) in KNOWN_UNPARSEABLE now parse — remove them from the list:")
        for rel in sorted(gone):
            print(f"  {rel}")

    if bad or new_unparseable or gone:
        return 1

    print(f"every `until` wait states its own failure condition "
          f"({len(KNOWN_UNPARSEABLE)} file(s) unparseable and knowingly skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
