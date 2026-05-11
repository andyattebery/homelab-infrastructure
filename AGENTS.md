## Subagent usage

Never use `Explore` — it reads excerpts. For multi-file research and audits, use `general-purpose`.

## Reviews and audits

Triggered by: "review", "audit", "is this OK?", "any issues?", "look this over", "check this".

Required artifact: a matrix or checklist with explicit ✓/✗ per cell. Rows = required inputs / preconditions; columns = each caller / usage. No matrix in the output = not done.

For role audits: `grep` every invocation in the codebase, then check each invocation's `vars:` against the role's required-input list.

## Coherence pass

Triggered by: end of any multi-step edit, before declaring done / running / committing.

Required artifact: a short written summary covering — naming consistency, structure consistency, leftovers (commented code, unused vars, stale references), and goal alignment vs original ask. No summary = not done.

## Bulk renames

For `replace_all` or any cross-file substitution:

1. `grep` old name — read each match for intent.
2. Run replace.
3. `grep` old name — confirm zero remaining.
4. `grep` new name — confirm no accidental new matches.

Each step is a visible tool call.

## Ansible

- ansible directory holds homelab provisioning playbooks/roles.
- ansible runs from `ansible/.venv` (managed by mise).
- `gh` and `yq` are in `$PATH`.
