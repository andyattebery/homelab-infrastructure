## Reading files

When told to read a file, read every line. Do not skim, summarize, or skip sections that look "standard." If the task depends on the contents of a file, produce an artifact (checklist, matrix, line-by-line accounting) that proves every item was seen. "I read it" is not evidence.

## Subagent usage

Never use `Explore` — it reads excerpts, not full files. For multi-file research and audits, use `general-purpose`.

## Reviews

Triggered by: "review", "audit", "verify", "is this OK?", "any issues?", "look this over", "check this", or end of any multi-step edit before declaring done.

Required checks:

1. **Coherence**: every part references the correct names, paths, and values from other parts. No stale references after renames or restructuring. No leftovers (commented code, unused vars, stale references).
2. **Consistency**: naming conventions, code style, and patterns are uniform throughout.
3. **Correctness**: all option names, types, and values verified against the actual version in use. All paths resolve. All cross-file references exist.
4. **Operational walkthrough**: for every script and workflow, trace the full execution as a specific user on a specific machine. At each step state: who is the user, what is the working directory, what files are read/written and who owns them, what the previous step left on disk. Flag any step where the user, permissions, or file state differs from what the prior step produced.
5. **Unknowns**: flag anything that requires a runtime value, an external dependency, or a decision not yet made. No deferring to implementation time.
6. **Reads as one doc**: no artifacts from iterative editing. No contradictions between sections. Goal alignment vs original ask.

For role/module audits: `grep` every invocation in the codebase, then check each invocation's inputs against the required-input list.

Required artifact: a checklist or matrix covering all checks. No artifact = not done.

## Bulk renames

For `replace_all` or any cross-file substitution:

1. `grep` old name — read each match for intent.
2. Run replace.
3. `grep` old name — confirm zero remaining.
4. `grep` new name — confirm no accidental new matches.

Each step is a visible tool call.

## No hedging with "optional"

Never label a step as "optional" in a script, plan, or workflow without stating what happens if it's skipped. If skipping it breaks something, it's required — make it part of the script. If skipping it changes nothing, it shouldn't exist — remove it. "Optional" without a consequence analysis is a deferred decision, not a design choice.

## Absence is not evidence

When a config key, flag, or setting is missing from output, do not assume what the default is. Look up the documented default for the specific tool and version. "Not listed" often means "default is active," not "disabled."

## Version-pinned research

When researching changelogs, release notes, or API differences between specific versions, the agent prompt MUST name both versions explicitly (e.g., "changes between release-25.05 and release-25.11"). Never compare against `master` or `unstable` unless the user asked for that. Default to the versions actually used in the codebase.

## Nix

- Nix is not installed on the Mac. All nix commands run in Docker via `nix/scripts/nix-shell.sh`.
- `nix/scripts/nix-shell.sh flake check` to validate after changes.
- See `nix/README.md` for full details.
- **Secrets pipeline**: `nix/secrets/` has `.tpl` template files (`vars.nix.tpl`, `secrets.yaml.tpl`) that use `{{ op://... }}` 1Password references. `nix/scripts/populate-secrets-from-op.sh` runs `op inject` to generate the real files (`vars.nix`, `secrets.yaml`). Never edit `vars.nix` or `secrets.yaml` directly — edit the `.tpl` files.
- **Verify before asserting**: do not predict what a Nix expression evaluates to, what gets built, or where it gets built. Use `nix eval`, `nix build --dry-run`, or `nix derivation show` to verify. These are safe (read-only). "I think this will..." is not acceptable — show the output.

## Ansible

- ansible directory holds homelab provisioning playbooks/roles.
- ansible runs from `ansible/.venv` (managed by mise).
- `gh` and `yq` are in `$PATH`.

## Git

Never run `git commit`. Stage only; the user commits. This holds when a commit is the
obvious next step, and after the user approves a commit plan — approval covers the staging,
not the commit.

Required artifact: after each `git add`, print `git diff --cached --stat` and
`git status --short`. No staged-state output = not done.

## Roles must not bake in host config

A role is reusable infrastructure. This homelab's specifics belong in the playbook,
`group_vars/`, `host_vars/`, or `ansible/files/<host>/`. Inside `ansible/roles/<name>/`
there must be no hostname, domain, share path, absolute host path, model list, device name,
or credential *as a value*. A host-shaped path is allowed only in `defaults/main.yaml`,
where a caller can override it.

One role deploys one application. A role that builds a second, unrelated service gets split.

Triggered by: adding or editing a role.

Required artifact — both greps, as visible tool calls:

    grep -rn 'nas-01\|media-01\|htpc-01\|docker-01\|wsl-01\|<domain>' ansible/roles/<name>/
    grep -rn '/mnt/\|/run/media' ansible/roles/<name>/ | grep -v '/defaults/main.yaml:'

Hostname or domain hits are a miss anywhere — including a comment that states a real value
rather than an example. Path hits outside `defaults/main.yaml` are a miss. No greps = not
done.

## Every role has a README

Adding or editing a role means adding or updating `ansible/roles/<name>/README.md`. House
style: purpose line, `## Status:`, Required/Optional inputs each with its default and what
happens if it is wrong, a real example lifted from the calling playbook, then narrative
sections for the traps.

Required artifact:

    git status --porcelain --untracked-files=all \
      | grep -oE 'ansible/roles/[a-z_0-9]+' | sort -u \
      | while read -r r; do [ -f "$r/README.md" ] || echo "MISSING: $r"; done

Must print nothing. Re-run it at the end — editing a role's file pulls it into scope, so the
set grows as the work proceeds.

`## Status: WIP` on a role that is deployed is a stale marker, not documentation. Fix it.

## Playbooks: no silent commented-out blocks

A commented-out role or task needs a comment directly above saying why. The only exception
is a reference to a role that is not complete or not working — say that.

Triggered by: any playbook edit that comments something out.
Required artifact: the why-comment, visible in the diff. No comment = uncomment it or delete
it, not both-and-neither.

## Before editing any `docker_compose_*` role

Read `ansible/roles/docker_compose/` in full — all 16 files — and produce the file-by-file
accounting the Reading-files rule requires. Its behaviour decides things that are invisible
from the calling role:

- the compose file always goes through `ansible.builtin.template`, so it renders Jinja
  whether or not it is named `.j2`
- `docker_compose_dst_file_name` defaults to the source basename, so a `.j2` source deploys
  a `.j2` destination — and `files/dc` globs `docker-compose*.y*ml`, so it will not see it
- `docker_compose_src_config_files` templates; `docker_compose_src_config_dirs` copies and
  never renders Jinja
- `.env` is shared per host and accumulates every role's vars — env names are a host-global
  namespace
- `docker_compose_dst_directory_path` is `set_fact`-ed, so it outranks host_vars and play
  vars for the rest of the play

## Ansible semantics are looked up, not recalled

Variable precedence, where vars are searched from, role search path, tag inheritance,
`apply:`, and `is defined` behaviour are checked, never remembered.

Docs, pinned to the `ansible-core` version from `.venv/bin/ansible --version` — never
`latest`, never `devel`:
`raw.githubusercontent.com/ansible/ansible-documentation/stable-<X.Y>/docs/docsite/rst/…`

Anything testable locally gets tested instead of cited:

    .venv/bin/ansible localhost -c local -m debug -a 'msg={{ … }}' -e '{…}'

Required artifact: the quoted doc line or the command output. Neither = the claim does not
go in.

## This repo is public

`github.com/andyattebery/homelab-infrastructure` is public, and the domain is a secret —
`research/local-llm/bench/harness/test_sweep.py` asserts no literal URL reaches a committed file.

- Anything Ansible renders: `{{ domain_name }}`
- Prose, comments, READMEs, docs: `<domain_name>`
- An `op inject` `.tpl`: `{{ op://Personal/Home Lab/domains/internal }}`

Triggered by: before staging anything.
Required artifact — the domain is read from the local, never-committed secrets file rather
than written here, because spelling it out to grep for it would publish it:

    DOMAIN=$(sed -n 's/.*domainName = "\(.*\)".*/\1/p' nix/secrets/vars.nix)
    test -n "$DOMAIN" || { echo "run nix/scripts/populate-secrets-from-op.sh first"; }
    git diff --cached --name-only -z | xargs -0 grep -Fin "$DOMAIN"; echo "exit=$?"

`exit=1` is the pass. Per commit, not once per session.

## Audit the index, not the working tree

`git grep` and `grep` read the working tree, which for generated and `assume-unchanged`
files is not what is committed. `nix/secrets/vars.nix` is the live example: real values
locally, placeholders in `HEAD`, and `assume-unchanged` set (`git ls-files -v` shows `h`).

Before reporting that something is or is not committed, check it — `git show HEAD:<path>` or
`git diff --cached`. A working-tree grep is not evidence about repository content.
