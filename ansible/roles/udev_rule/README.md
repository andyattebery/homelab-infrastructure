# udev_rule

Writes one udev rules file and tells udevd about it. The rule **body is an input** — this role
has no opinion about what it matches, because a role that knew what it was matching would be a
role with a particular host's hardware baked into it.

## Status: In use

Written 2026-09-14. Its first caller publishes a set of virtual input devices to a group that an
unprivileged container can reach.

## Inputs

Required — both asserted, with no defaults:

- `udev_rule_name` — the file's basename **without** the `.rules` suffix, e.g. `99-lxc-input`.
  The suffix is appended by this role. Wrong: a name already ending in `.rules` is refused (it
  would produce `x.rules.rules`), and so is any name containing a path separator — it is joined
  to `udev_rule_directory_path`, so `../` would write outside the rules directory as root,
  silently, somewhere udev never reads.
- `udev_rule_content` — the rule body, one rule per line. Wrong: an empty body is refused,
  because it writes a valid, empty rules file that udev loads, matches nothing with, and reports
  no error about — a rule that silently never fires rather than anything that looks broken.

Optional:

- `udev_rule_state` — `present` (default) or `absent`. Wrong: nothing else is accepted. See
  "Removing a rule does not undo it".
- `udev_rule_directory_path` — default `/etc/udev/rules.d`. Wrong: a directory udev does not read
  produces a file that exists and is never loaded, with nothing reporting it. This is the **admin**
  directory and it outranks `/usr/lib/udev/rules.d` — a file of the same name here masks the
  packaged one entirely.
- `udev_rule_reload` — default `true`. Wrong/skipped: see "Writing the file is what activates it".
- `udev_rule_trigger` — default `false`. Wrong/skipped: a rule meant to change an **existing**
  device's group, mode or symlinks does not take effect until that device is re-added or the host
  reboots. See "Triggering is off by default".
- `udev_rule_trigger_subsystem` — default empty, and **required when `udev_rule_trigger` is
  true**, asserted. Wrong: an unrestricted `udevadm trigger` re-runs every rule against every
  device on the host.
- `udev_rule_settle_timeout_seconds` — default `30`, used only when triggering.
- `udev_rule_udevadm_path` — default `/usr/bin/udevadm`. An input so a fixture test can point it
  at a stub and a caller on another distro is not stuck.
- `udev_rule_file_owner` / `_file_group` / `_file_mode` — default `root`/`root`/`0644`. Inputs so
  the fixture test can render as an unprivileged user.

## Example

Lifted from the calling playbook, where it runs against the hypervisor and is tagged so the rule
can be installed without running the rest of the play:

```yaml
- name: Publish the virtual input devices to a group the container can reach
  tags: [udev-input]
  ansible.builtin.include_role:
    name: udev_rule
    apply:
      tags: [udev-input]
  vars:
    udev_rule_name: 99-lxc-input
    udev_rule_content: >-
      SUBSYSTEM=="input", KERNEL=="event*", ATTRS{id/vendor}=="1209",
      ATTRS{id/product}=="0002|0003", GROUP="lxc-input", MODE="0660"
```

## Writing the file is what activates it

There is no installed-but-inert window, and a plan that assumes one is wrong. udevd reloads its
rules **on its own** when it notices a rules file changed: systemd v257
`src/udev/udev-manager.c:590` calls `manager_reload()` from `event_queue_start()`, and `:268`
reloads when `udev_rules_should_reload()`. That check runs as the next event is processed.

So `udev_rule_reload` does not make the rule live — it makes it live *now* rather than *at the
next uevent*. On a host where the next uevent is the thing the rule was written for, that
difference is the whole point; everywhere else it is cosmetic.

The real consequence is for review, not for this option: **a rule that must not fire on existing
hardware has to be written so that it cannot match any**, rather than installed carefully.
Verifying that after the fact is too late — the file is live the moment it lands.

`udevadm test` is not a pre-flight for this. It has no alternate-rules-directory option
(`man/udevadm.xml`), so the file must already be installed for `test` to see it. The only genuine
pre-install check is `udevadm verify FILE`, which takes an uninstalled path and can run anywhere.

## Triggering is off by default, and that is a decision

A rule written for devices that **do not exist yet** — virtual input devices some daemon will
create later — gains nothing from a trigger, because rules are applied when a device is added.
What a trigger *does* do is re-run every matching rule against every matching device on the host
right now. On a hypervisor running other guests that is a real action with real consequences that
no caller asked for.

Set `udev_rule_trigger: true` only when the intent is to change devices that are **already
present**, and name the subsystem. The unrestricted form is refused rather than discouraged.

`udevadm trigger` only queues the events, which is why `udevadm settle` follows it. Without the
settle the play continues while udevd is still working, and a later task that checks a device's
group can read the old value and report a failure that repairs itself a second later.

## Removing a rule does not undo it

`state: absent` removes the file, so the rule stops applying to devices added **after** that.
Devices already carrying attributes it set keep them until they are re-added or the host reboots.
If the point is to put an existing device back, removing the rule is not enough.

## This role needs a running udevd

It assumes udevd is running on the target — true of an ordinary host, false of an unprivileged
container, which runs no udevd and receives no kernel uevents in its network namespace.
Installing a rule in such a container is inert: nothing would ever evaluate it. A caller that
points this role at one gets a loud failure from `udevadm control`, which is the right outcome.

Faking udev **inside** a container is a different problem with a different answer — a synthesised
netlink event, not a rules file — and it does not belong in this role.

## configure.yaml / main.yaml

`configure.yaml` validates and writes, and runs no command; `main.yaml` is the only place that
calls `udevadm`. That split is what lets the fixture test import the rendering half alone against
a tempdir, with no udevd, no root and no `/etc/udev`.

`udev_rule_changed` is set by `configure.yaml` in both directions (written or removed) so
`main.yaml` and any caller can branch on one fact rather than on two registers, only one of which
ran.

## What the test proves, and what it does not

`tests/test.yml` proves the rule body survives templating verbatim and lands on a single line,
that the file is suffixed exactly once, that a second render changes nothing, that `absent`
removes it and is itself idempotent, and that four bad callers are refused **before anything is
written** — empty body, a name already ending in `.rules`, a name containing path separators, and
a trigger with no subsystem.

It proves **nothing** about whether udev accepts the rule's syntax, whether it matches any real
device, or whether `udevadm` exists. None of that is answerable on a controller. `udevadm verify`
in a container harness covers the syntax; only a host with the devices covers the match.

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/udev_rule/tests/inventory \
    roles/udev_rule/tests/test.yml
```
