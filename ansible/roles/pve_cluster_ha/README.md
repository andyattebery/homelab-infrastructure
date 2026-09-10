# pve_cluster_ha

Converges Proxmox HA resources and HA rules from a declaration, refuses anything on the cluster it
was not told about, and never deletes.

## Status: Production — converged the prod cluster 2026-09-08 with changed=0 and both
`/cluster/ha` digests unchanged. 15 fixture cases, each shown red under a mutation.

## Required inputs

### `pve_cluster_ha_resources`

List of HA resources to manage. Default `[]`. Each entry:

| key | default | meaning |
| --- | --- | --- |
| `sid` | *required* | `vm:<id>` or `ct:<id>`. Malformed or duplicated sids fail in `validate.yaml`. |
| `state` | `started` | `disabled`, `enabled`, `ignored`, `started`, `stopped`. Anything else fails. |
| `failback` | `true` | See the trap section below before changing this. |
| `max_relocate` | `1` | PVE's own default. |
| `max_restart` | `1` | PVE's own default. |
| `comment` | *none* | Removing it from the declaration emits `--delete comment`, not `--comment ''`. |

Empty is not the same as "do nothing": with resources on the cluster and none declared, the
undeclared-extras gate fails on purpose.

### `pve_cluster_ha_rules`

List of HA rules. Default `[]`. `rule` and `type` together identify a rule and are never written.

| key | default | node-affinity | resource-affinity |
| --- | --- | --- | --- |
| `rule` | *required* | identity | identity |
| `type` | *required* | `node-affinity` | `resource-affinity` |
| `resources` | *required* | yes | yes |
| `nodes` | *required for this type* | yes | **rejected** |
| `strict` | `false` | yes | **rejected** |
| `affinity` | `positive` | yes | **required — PVE gives it no default here** |
| `comment` | *none* | yes | yes |
| `disable` | `false` | yes | yes |

Every sid a rule names must also appear in `pve_cluster_ha_resources`, or the two would disagree
about what is HA-managed.

## Optional inputs

### `pve_cluster_ha_resource_keys`, `pve_cluster_ha_rule_keys`

The settings this role converges, and by implication the ones it refuses to see anything outside of.
Defaults are in `defaults/main.yaml`. Adding a key here means teaching the role to emit it; it is not
a free switch.

### `pve_cluster_ha_resource_ignored_keys`, `pve_cluster_ha_rule_ignored_keys`

Read from the cluster and never compared: `digest` and `order` are server-side, a resource's `type`
is derived from its sid, a rule's `type` is half of its identity.

### `pve_cluster_ha_manager_command`, `pve_cluster_ha_pvesh_command`

Default `ha-manager` and `pvesh`, bare because the play runs with `become`, whose `PATH` has
`/usr/sbin`. Overridden by `tests/test.yml` to point at stubs.

## Example

From `playbook-prod-proxmox-cluster.yaml`, inside the designated-runner block:

```yaml
    - name: Configure cluster-wide PVE state
      when: inventory_hostname == pve_cluster_designated_runner
      block:
        ...
        - name: Configure cluster HA resources and rules
          tags: ha
          ansible.builtin.import_role:
            name: pve_cluster_ha
```

with the declaration in `group_vars/<cluster group>/vars.yaml` — hostnames and VMIDs belong there,
never in this role:

```yaml
pve_cluster_ha_resources:
  - {sid: "vm:102", state: started, failback: true, max_relocate: 3, max_restart: 2}

pve_cluster_ha_rules:
  - rule: prefer-first-node
    type: node-affinity
    nodes: "<node-c>:1,<node-a>:3,<node-b>:2"
    resources: "vm:102"
    strict: false
```

## Reads with `pvesh`, writes with `ha-manager`

Not a preference. `ha-manager config` has no `--output-format`, so it cannot be parsed reliably;
`pvesh get … --output-format json` can. Writes go the other way because `ha-manager rules add`
validates options per rule type and says which one is wrong. The two CLIs also disagree about
argument shape, which is a live trap: `ha-manager rules add|set` take `<type> <rule>` **positionally**,
while `pvesh create /cluster/ha/rules` takes them as `--type` / `--rule`. Do not copy one form
into the other.

## Absent is not the same as unset

The API fills in some defaults and omits others, in the same response. On this cluster a rule read
back carries `affinity: positive` that `/etc/pve/ha/rules.cfg` never stored, yet omits `strict`
entirely; two of three resources carry an explicit `failback` and the third does not. Comparing on a
key's presence would rewrite settings that already match, every run. So both sides of every
comparison are normalised against the documented default first, and booleans are emitted as `1`/`0`
rather than Ansible's `True`/`False`.

## Why you cannot hand-migrate a preferred resource off its top-priority node

`ha-manager add|set --failback <boolean> (default=1)`:

> Automatically migrate HA resource to the node with the highest priority according to their node
> affinity rules, if a node with a higher priority than the current node comes online.

PVE 9.2 refuses a migration that this would immediately undo. With `failback` on and a **non-strict**
node-affinity rule, a resource may only be moved among the nodes tied at the *highest* priority — so
a rule reading `<node-c>:1,<node-a>:3,<node-b>:2` makes every target except `<node-a>` fail with
*"Cannot migrate VM, because HA resource vm:NNN is not allowed on the selected target node."*

That is the configuration working as declared, not a fault. To empty such a node, use
`ha-manager crm-command node-maintenance enable <node>` — which is what
[pve_node_rebuild](../pve_node_rebuild/README.md) does. Setting `failback: false` here would make
hand-migration work and stop HA bringing the resource home afterwards; that is a real trade, not a
fix.

## It never deletes

An HA resource or rule on the cluster that the declaration does not mention stops the run, naming
it. Same for a setting outside the managed key list — otherwise it would drift silently forever.
Both are fixed by declaring the thing, or by removing it by hand with `ha-manager remove` /
`ha-manager rules remove`. A role that pruned would let one typo in `group_vars` un-HA a VM.

A rule whose live `type` differs from the declaration is also refused: `ha-manager rules set` takes
the type positionally and cannot change it, so that is a different rule wearing the same name.

## A declared resource whose guest does not exist is skipped

So a cluster can be rebuilt before its VMs are restored. The rules naming that sid are skipped with
it — skipping the resource alone would only move the failure one step later. Both are reported.
Guests are matched on `vmid`, not on the row's `type`, so `vm:` and `ct:` sids take one code path.

## No `--digest` on writes

`ha-manager set --digest` exists, but the digest covers the whole file and every resource shares
one, so the second write in a loop would always fail on a stale digest. The role runs on a single
designated node inside an already-serialised block.

## Tests

```sh
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/pve_cluster_ha/tests/inventory \
    roles/pve_cluster_ha/tests/test.yml
```

Pass is `failed=0`; each negative case catches its own refusal in `rescue:`, so a green run shows
`rescued=6`. The `ha-manager` stub logs each argument separated by `|`, so assertions pin argument
boundaries — a quoting bug that split the comment `Generated from HA group 'main'.` into several
arguments would fail case 4, where joining on spaces would hide it.

Covers: the live capture converging to no writes at all; resource add and a single-key set; rule add
and single-key set; `strict` absent live and declared both ways; a resource-affinity rule getting
neither `--nodes` nor `--strict`; undeclared resource, undeclared rule, unmanaged key, and rule-type
change each refused by name; a malformed declaration refused by `validate.yaml` with the CLI paths
pointed at `/nonexistent`, proving it runs before the cluster is contacted; a missing guest skipping
both its resource and its rule; and a removed comment emitting `--delete`.

Each of the 15 cases was shown red under a mutation before it counted (2026-09-08), and the mutation
that catches a case was recorded, not just the fact that the suite went red. Two of the mutations
abort at an earlier case than intended, so case 6 needed one written specifically for it.

**Not covered, on purpose:** whether `ha-manager rules add --resources` accepts a sid that is not yet
an HA resource. Answering it requires creating a rule on a real cluster, and the role's behaviour is
the same either way, because it skips such a rule.
