# apt-source role tests

Container harness for the roles that configure apt sources. Every host these
roles run on is production, and a broken apt source takes down every role that
runs after it — `fish_install` runs on **every** host via `configure_server`, early
in the play. So changes get proven here first, and a host is only touched once
this is green.

Nothing here talks to a real host. The containers are disposable and recreated
from scratch on every `setup.yml` run.

## Running it

```
cd ansible

# 1. create + bootstrap the containers (recreates from scratch)
tests/apt-sources/run.sh setup.yml

# 2. positive controls: prove the harness reproduces the known defects
tests/apt-sources/run.sh setup.yml repro.yml

# 3. prove a fix (setup first — see Isolation below)
tests/apt-sources/run.sh setup.yml verify-realtek.yml

# 4. clean up
tests/apt-sources/run.sh teardown.yml
```

Give `setup.yml` and a verify playbook in one command so each run starts from a
pristine apt configuration.

Requires Docker running locally and the `community.docker` collection (already in
`requirements.yaml`).

## The containers

| Host | Image | Why it exists |
| --- | --- | --- |
| `apt-test-debian12` | `debian:12` | bookworm signs its archive `.gpg`; reproduces the duplicate-target **warning** seen on vm-host-01/02 |
| `apt-test-debian13` | `debian:13` | stock trixie signs `.pgp`; the same bug becomes a **fatal** `Signed-By` conflict, `apt-get update` rc=100 |
| `apt-test-pve9` | `debian:13` + forced `.gpg` | **the real Proxmox fleet shape**: PVE 9 is trixie but its installer writes `debian-archive-keyring.gpg`. Reproduces the warning actually reported from vm-host-01/02 |
| `apt-test-ubuntu2404` | `ubuntu:24.04` | current fleet release |
| `apt-test-ubuntu2604` | `ubuntu:26.04` | the upgrade target — apt 3.2.0, no `apt-key` |
| `apt-test-snapper-amd64` | `amd64/ubuntu:24.04` | snapper only; see below |

Three Debian legs, deliberately. The release is **not** what decides the symptom —
the keyring its installer named is. `apt-test-pve9` is stock `debian:13` with
`debian.sources` rewritten to sign with `.gpg`, which is what Proxmox VE 9 does;
that leg, not `apt-test-debian13`, is the one that matches the hosts this repo
actually manages. `setup.yml` applies the rewrite via `apt_test_force_signed_by`
in the inventory, so every playbook run afterwards sees a consistent host shape.

An earlier version of this harness had only bookworm and stock trixie, and led to
the wrong conclusion that the fleet was one upgrade away from breakage. It is
already on trixie; it is simply lucky in which keyring spelling it got.

## Never run two of these at once

Every run uses the same fixed container names, so a second invocation —
especially anything that runs `setup.yml` — **destroys and recreates the
containers underneath the first one**. The victim fails in ways that look like a
role bug and are not: `verify-mise.yml` failed twice in a background loop purely
because a foreground `setup.yml` was recreating its containers mid-test, then
passed cleanly twice the moment it had the machine to itself.

If a result surprises you, re-run that one playbook alone before believing it.

## Isolation: one `setup.yml` per verify playbook

`setup.yml` recreates the containers, and each verify playbook expects to start
from a pristine apt configuration. Chaining several verify playbooks against one
`setup.yml` does **not** work: `repro.yml` enables `non-free` via
`debian_extra_components`, which makes `verify-realtek.yml`'s first assertion
("the component is not enabled anywhere") false. Run `setup.yml` before each one.

`verify-realtek.yml` is the exception that also resets itself — it mutates the
host by design (step 3 enables the component), so it undoes that at step 0 and is
safe to run repeatedly.

**Run every verify playbook twice.** The second run against unchanged containers
is what catches non-idempotence, and it has caught real bugs twice: a
`deb822_repository` that reported `changed` on alternate runs because it
refetched a key through a caching proxy, and the ordering bug below.

## Always run these through `run.sh` — never call ansible directly

```
cd ansible
tests/apt-sources/run.sh setup.yml                    # recreate containers
tests/apt-sources/run.sh setup.yml verify-fish.yml    # recreate, then verify
tests/apt-sources/run.sh lint                         # lint the harness
tests/apt-sources/run.sh teardown.yml                 # clean up
```

**This is not a convenience wrapper.** `ansible.cfg` points `vault_password_file`
at `scripts/vault-password-op.sh`, which prompts 1Password, and ansible calls it
on nearly every invocation — `ansible-lint` most reliably, since it loads every
playbook in the project including vaulted ones. Running the suite in a loop
without the wrapper opens **one 1Password prompt per run** and leaves hundreds
queued waiting for a human. That has already happened once.

`run.sh` sets `ANSIBLE_VAULT_PASSWORD_FILE` to `no-vault.sh`, a stub that returns
a string which is deliberately **not** a real password. Nothing under
`tests/apt-sources/` uses a vaulted variable, so the stub is sufficient; and
because it is wrong rather than absent, any playbook that genuinely needs a
secret fails to decrypt loudly instead of silently misbehaving. That is what
stops the stub quietly becoming how real secrets get handled.

If you see `authorization timeout` or `promptError` from
`vault-password-op.sh`, you invoked ansible directly. Use the wrapper.

## Four things that will bite you

**Roles are found through a symlink.** `tests/apt-sources/roles -> ../../roles`.
Ansible resolves roles relative to the playbook directory, and these playbooks do
not live at the repo root. Without the symlink every `include_role` fails with
"the role was not found" — which looks like a role bug and is not one.

**The amd64 leg needs `amd64/ubuntu:24.04`, not `ubuntu:24.04` + `platform:`.**
Docker will not hold one tag for two platforms; the second create fails with
*"image with reference ubuntu:24.04 was found but its platform (linux/arm64/v8)
does not match the specified platform (linux/amd64)"*. The per-architecture Docker
Hub namespace sidesteps the tag collision. That leg is emulated and slow, so it is
used only where it is unavoidable: OBS publishes `filesystems:snapper/xUbuntu_*`
for amd64 with no `arm64/` directory, so snapper cannot install on the native legs.

**This Mac is arm64, and that is a feature, not a limitation.** It caught a
hardcoded `archive.ubuntu.com` in `realtek_dkms` that 404s on arm64, where Ubuntu
serves `ports.ubuntu.com/ubuntu-ports`. An amd64-only harness would have shipped it.

**`python3-debian` is deliberately NOT pre-installed.** `deb822_repository` fails
without it, and whether each role installs its own is one of the things under
test. `setup.yml` installs only `python3`, `python3-apt` and `ca-certificates`.

## Writing a new verify playbook

Two rules, both learned the hard way in this directory.

**Remove predecessors before writing the new source.** A migrated role writes
`<name>.sources` while the old `.list`/`.sources` for the same repository is still
present, and their `Signed-By` values differ. apt refuses that outright —
`E:Conflicting values set for option Signed-By` / `E:The list of sources could not
be read` — so between those two tasks every apt operation on the host fails. On
the happy path nothing runs apt in that window, but an interrupted play leaves apt
broken *and the role unable to repair it*, because its own first step is an apt
call. Every role here removes first for that reason.

Seeds in these tests must therefore be **realistic sources**, not `# stale`
placeholder text. A placeholder gets removed identically and proves the cleanup
ran, while never once producing the conflict the ordering exists to prevent —
which is exactly how this bug survived five roles' worth of green tests.

**Reproduce the defect before fixing it.** `repro.yml` asserts each known defect
actually occurs. If it cannot reproduce the symptom, the harness is wrong and every
green result afterwards is meaningless. Each check is written so the expected
outcome is a pass — a `rescue` that fires is the success path.

Two kinds of control live there, and the difference matters. Repros 1 and 2 run the
*unmodified role* and expect it to fail; they stop being runnable the moment that
role is fixed, so they are snapshots. Repro 3 instead **constructs the bad state by
hand** and asserts apt breaks. That one survives the fix, because it tests the
symptom rather than the role — which is what justifies the guard staying in the
role. When you fix a role covered by a run-the-role repro, convert it to the
construct-the-state form or it becomes a control that cannot fail.

**Assert non-emptiness before asserting equality.** A check like

```yaml
- _dropin_keys | difference(_stock_keys) | length == 0
```

passes on an empty list. A regex that silently extracts nothing then reports
itself as a perfect match. Every extraction gets a `| length > 0` alongside it,
and the `success_msg` prints the extracted values so a vacuous pass is visible in
the output rather than hidden behind "All assertions passed".

Also worth knowing: **role defaults go out of scope when `include_role` returns**,
so a test cannot assert on `{{ some_role_default }}` afterwards. `set_fact` and
`register` results do persist. Compute expected paths in the test itself — it is
the stronger assertion anyway, since it checks where the file really lands rather
than trusting the role's own description of it.

## Coverage, honestly

`verify-realtek.yml` walks one container through the whole state machine —
component absent → written → idempotent → component enabled elsewhere → removed →
idempotent — on all four Debian/Ubuntu legs.

What the containers **cannot** cover: anything needing systemd or a running
kernel. `nvidia_container_toolkit` reloads `docker.service`, `realtek_dkms` builds
a DKMS module, `fish_install` changes a login shell. That is why each role's
apt-source tasks are split into their own task file — the harness imports the repo
half alone. The service and kernel halves are still only exercised on a host.
