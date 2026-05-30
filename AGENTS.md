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

## Ansible

- ansible directory holds homelab provisioning playbooks/roles.
- ansible runs from `ansible/.venv` (managed by mise).
- `gh` and `yq` are in `$PATH`.
