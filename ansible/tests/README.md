# Tests

Nothing here runs automatically — there is no CI. These are run by hand, before
declaring a change done, and they exist because the alternative is finding out on
a production host.

Four patterns live in this repo, in increasing order of cost. **Use the cheapest
one that can actually fail for the right reason.**

| Pattern | Lives in | Contacts | Use it for |
| --- | --- | --- | --- |
| Invariant check | `tests/test-*.yml` | nothing (`connection: local`) | facts about inventory, `host_vars`, vault wiring — things that must hold across hosts |
| Role fixture test | `roles/<role>/tests/test.yml` | nothing (localhost + tempdir) | a role's decision logic, with its paths pointed at a scratch directory |
| Container integration | `tests/<subject>/` | throwaway containers | anything whose result depends on a real distro — apt, packages, systemd-free service config |
| pytest | `roles/<role>/tests/*.py` | nothing (I/O injected) | vendored Python that ships inside a role |

## Running them

```
cd ansible

# invariant checks — safe any time, contact no host
ANSIBLE_ROLES_PATH=roles .venv/bin/ansible-playbook -i localhost, \
  tests/test-tdarr-node-win-config.yml
.venv/bin/ansible-playbook tests/test-network-interface-pinning.yml

# role fixture tests
.venv/bin/ansible-playbook -i roles/e1000e_disable_offloads/tests/inventory \
  roles/e1000e_disable_offloads/tests/test.yml

# container integration — see tests/apt-sources/README.md, and use its wrapper
tests/apt-sources/run.sh setup.yml verify-fish.yml

# pytest
.venv/bin/pytest roles/docker_compose_certbot_asrock_ipmi/tests/ -q
```

## Role resolution: the thing that bites first

Ansible resolves roles relative to the **playbook's** directory. A playbook in
`tests/` therefore cannot see `ansible/roles/` and every `include_role` fails with
"the role was not found" — which looks like a role bug and is not one.

Two fixes are in use, both fine:

- `ANSIBLE_ROLES_PATH=roles` on the command line — see
  `tests/test-tdarr-node-win-config.yml`. Good for a single file.
- a `roles -> ../../roles` symlink inside the test directory — see
  `tests/apt-sources/`. Better when several playbooks share a directory, since
  nobody has to remember the variable.

Role fixture tests under `roles/<role>/tests/` need neither: they are already
inside the roles tree.

## Where a new test goes

Ask what could actually be wrong, and pick the pattern that can catch it.

- **"the inventory or host_vars must say X"** → `tests/test-<subject>.yml`,
  `connection: local`. `test-network-interface-pinning.yml` is the model: it
  asserts every cluster node declares its NIC pins, without touching a node.
- **"this role decides the wrong thing given input Y"** → a role fixture test.
  Point the role's path variables at a `tempfile` directory and `import_role` the
  **real** role. `roles/e1000e_disable_offloads/tests/test.yml` is the model.
  This is why roles take their paths from `defaults/main.yaml` rather than
  hardcoding them — a role that hardcodes `/etc/...` cannot be tested this way.
- **"this only breaks on a particular distro/release"** → container integration.
  Expensive, so reserve it for things a fixture genuinely cannot answer: whether
  apt accepts a file, whether a package resolves, whether two releases differ.
- **"this Python script mishandles a response"** → pytest, with the I/O boundaries
  injected so no network or device is needed.

## Rules that came from real failures

Each of these is here because ignoring it produced a green test over a broken
thing.

**Assert non-emptiness before asserting equality.** A check like

```yaml
- _extracted | difference(_expected) | length == 0
```

passes on an empty list. A regex that silently matches nothing then reports
itself as a perfect result. Pair every extraction with `| length > 0`, and print
the extracted values in `success_msg` so a vacuous pass is visible rather than
hidden behind "All assertions passed".

**Run it twice.** The second run against unchanged state is what catches
non-idempotence, and it has caught two real bugs here: a module that refetched a
key through a caching proxy and rewrote it on alternate runs, and a
create-before-delete ordering that broke apt in the window between the two tasks.
A single green run proves much less than it looks like it does.

**Seed realistic fixtures, not placeholders.** Seeding `# stale` proves a file
gets removed; it does not prove the situation that made removal necessary. Five
roles' worth of tests passed while a real ordering bug survived, because the
placeholder never actually conflicted with anything. Seed what the host really
has — a genuine source line, the real published file, the actual key path.

**Prove the defect before fixing it.** If a test cannot reproduce the problem, it
cannot prove the fix either. `tests/apt-sources/repro.yml` is the worked example.
Note the trap: a control that runs the *unmodified role* stops being runnable the
moment that role is fixed. Prefer controls that construct the broken condition
directly and therefore survive the fix.

**Test what the code promises, not more.** An assertion broader than the role's
contract fails on hosts where the role worked correctly. A check that globbed
`shells_fish_release_*.asc` failed on a key for a version the role never managed.
Scope the assertion; report the rest as information.

## What is durable and what is not

`tests/apt-sources/` is a **permanent** harness: it tests the roles, not any
particular rollout, and it is how those roles get re-checked after an
`ansible-core` bump or an upstream repository change. Keep it.

The `playbook-apt-sources*.yaml` files at `ansible/` top level are the opposite —
one-off rollout artifacts, and they say so in their own headers. Deleting them
does not affect the harness.

If you add a container harness for another subject, give it its own directory
alongside `apt-sources/` with its own `README.md` and wrapper script, rather than
extending that one: the containers, the fixtures and the vault stub are all
subject-specific.

## Fixtures and secrets

Test fixtures must not need the vault. `tests/apt-sources/` ships a stub
(`no-vault.sh`) returning a deliberately-wrong password, so anything that
genuinely needs a secret fails to decrypt loudly instead of silently proceeding —
and so that a test loop does not queue hundreds of 1Password prompts. Do the same
for any new container harness; never point a stub at a play that touches a real
host.
