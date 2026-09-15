# vdesktop role tests

Container harness for the parts of the vdesktop build that depend on a real Debian: the
apt-source halves of the `sunshine` and `firefox` roles, the Wayland session's package set,
the syntax of the udev rule that goes on the hypervisor, and the client-mode helper's
behaviour under **dash** (the controller's /bin/sh is bash, the host's is not).

The apt sources are **third-party** repositories on a host that is production, and a broken
apt source takes down every role that runs after it. The udev rule is worse: writing a rules
file **is** activating it, because udevd reloads on its own when it notices the change, so
there is no installed-but-inert window on the real node in which to check it. Both get proven
here first, and a host is only touched once this is green.

Nothing here talks to a real host. The containers are disposable and recreated from
scratch on every `setup.yml` run.

This is a separate directory from `tests/apt-sources/` rather than an extension of it,
per `ansible/tests/README.md` — the containers, the fixtures and the subject are
different. The one thing it *does* share is `apt-sources/no-vault.sh`, which that file
says itself is not specific to either subject.

## Running it

```
cd ansible

# 1. create + bootstrap the containers (recreates from scratch)
tests/vdesktop/run.sh setup.yml

# 2. positive controls: prove the harness reproduces the defects the roles guard against
tests/vdesktop/run.sh setup.yml repro.yml

# 3. prove a role (setup first — see Isolation)
tests/vdesktop/run.sh setup.yml verify-sunshine-repo.yml
tests/vdesktop/run.sh setup.yml verify-firefox-repo.yml
tests/vdesktop/run.sh setup.yml verify-wayland-packages.yml
tests/vdesktop/run.sh setup.yml verify-udev-rule.yml
tests/vdesktop/run.sh setup.yml verify-client-mode.yml

# 4. clean up
tests/vdesktop/run.sh teardown.yml
```

Requires Docker running locally and the `community.docker` collection (already in
`requirements.yaml`).

## The containers

| Host | Image | Why it exists |
| --- | --- | --- |
| `vdesktop-test-trixie` | `debian:13` (arm64) | Native and fast. **The leg that catches an `Architectures:` field hardcoded to `amd64`** — which the first hand-written version of these sources had. Both vendor repos publish arm64, so it can prove them end to end rather than only rendering a file. |
| `vdesktop-test-trixie-amd64` | `amd64/debian:13` | Emulated, therefore only justified by something the native leg cannot answer: `intel-media-va-driver` is published for **amd64 only** — `trixie/arm64` has no such package — and the real container is amd64. This leg's architecture matches production. |

Per-architecture Docker Hub namespaces (`amd64/debian:13`), not `debian:13` + `platform:`.
Docker will not hold one tag for two platforms; the second create fails with *"image with
reference debian:13 was found but its platform does not match"*.

**This Mac is arm64, and that is a feature.** The native leg is not a compromise — it is
the only leg that can fail when a source hardcodes an architecture, because on amd64 a
hardcoded `amd64` is indistinguishable from a correct one.

## Never run two of these at once

Every run uses the same fixed container names, so a second invocation — especially
anything running `setup.yml` — destroys and recreates the containers underneath the
first. The victim fails in ways that look like a role bug and are not.

## Isolation: one `setup.yml` per verify playbook

`repro.yml` deliberately constructs broken apt state, and `verify-firefox-repo.yml`
deliberately leaves the pin demoted to priority 100 at the end. Neither is a safe
starting point for the other. Give `setup.yml` in the same command.

**Run every verify playbook twice.** The second run against unchanged containers is what
catches non-idempotence. Both verifies are `changed=0` on their second run today.

## Always use `run.sh` — never call ansible directly

`ansible.cfg` points `vault_password_file` at `scripts/vault-password-op.sh`, which
prompts 1Password, and ansible calls it on nearly every invocation. A loop run without
the wrapper queues one prompt per run. `run.sh` points `ANSIBLE_VAULT_PASSWORD_FILE` at
the shared `no-vault.sh` stub, which returns a deliberately wrong password so that
anything genuinely needing a secret fails loudly rather than proceeding.

## Three things that will bite you

**Roles are found through a symlink.** `tests/vdesktop/roles -> ../../roles`. Ansible
resolves roles relative to the playbook directory. Without it every `include_role` fails
with "the role was not found", which looks like a role bug and is not one.

**`python3-debian` is deliberately NOT pre-installed.** `deb822_repository` fails without
it, and whether each role installs its own is one of the things under test. `setup.yml`
installs only `python3`, `python3-apt` and `ca-certificates`.

**A candidate is not proof of anything.** See CONTROL 1 below.

## The controls, and why CONTROL 1 looks over-specified

`repro.yml` proves the harness can fail. Both controls **construct the bad state by
hand** rather than running an unmodified role and expecting it to break — a
run-the-role control stops being runnable the moment the role is fixed, and becomes a
control that cannot fail.

**CONTROL 1 — a wrong architecture is quiet.** The first version of this control asserted
that a source pinned to the wrong architecture yields *no candidate*. It did not
reproduce. apt fetches the foreign index perfectly happily and **does** report a
candidate at priority 500. The real symptom is one step later: apt names the package
`sunshine:<foreign arch>:` and `apt-get install --simulate` fails rc=100 on
unsatisfiable dependencies.

That mattered, because it meant the verify playbook's original "a candidate exists"
assertion proved only that the repository was reachable — nothing about architecture.
Both verifies now assert a clean **install simulation** instead. Keep it that way.

**CONTROL 2 — two sources, one repository, different `Signed-By`.** apt refuses every
operation: `E: Conflicting values set for option Signed-By`, `E: The list of sources
could not be read`, rc=100. That is why both roles remove predecessors **before** writing
the new source: written the other way round there is a window where every apt call
fails, including the role's own, so an interrupted run could not be repaired by
re-running it. The `rescue` firing is the success path.

## The pin is tested by flipping it

`verify-firefox-repo.yml` does not merely assert the pin file rendered. Debian trixie
ships no `firefox` package at all, so nothing contests that name and a pin would be
invisible there. The pin is about `firefox-esr`, which **both** archives ship. The test
applies the role at the default priority, then re-applies it at 100, and asserts the
winner changes — today `153.2.0esr~build1` (Mozilla) versus `140.15.0esr-1~deb13u1`
(Debian). If those ever come out equal, the pin is decoration and the role should stop
claiming otherwise.

## `udevadm verify` resolves group names, and that is the point

`verify-udev-rule.yml` does not merely parse the rule's syntax. `udevadm verify` **resolves the
user and group names a rule references against the local system**, so a rule naming a group
nobody has created fails with `Unknown group '...'` and rc=1.

That makes this file a test of the calling playbook's ORDERING, not just its text: the group
must be created before the rule is installed. The control proves it by verifying once with the
group absent (expecting failure), then creating the group and verifying again.

It is **self-isolating** — it removes the group at the start — so unlike the other verifies it
is correct run twice without `setup.yml` in between. That is deliberate: a control that only
fires against a pristine container silently stops working the first time someone forgets.

## What this cannot cover

Everything that needs a GPU, a kernel, systemd or udev:

- **VA-API / Quick Sync.** `vainfo` needs a real render node. Proven on the host instead.
- **Sunshine actually running**, its systemd *user* unit, and `loginctl enable-linger`.
- **The compositor starting**, EGL reaching a GPU, or libinput opening a device.
- **Whether the udev rule MATCHES anything.** Only a host with the devices answers that; this
  covers syntax and name resolution and stops there.
- **Firefox actually launching.**

That is exactly why each role's `tasks/apt_repo.yaml` is split from `tasks/main.yaml` —
this harness imports the repo half alone. The service and GPU halves are still only
exercised on a host, and that is the part to be careful with.
