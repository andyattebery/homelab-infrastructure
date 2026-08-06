# pve_cluster_ceph

Creates the cluster-wide Ceph objects on a Proxmox cluster: the RBD pool and the CephFS
filesystem, both registered as Proxmox storages.

## Status: Production

## Inputs

None. The role takes no variables.

## Example

```yaml
- role: pve_cluster_ceph
```

## Runs once per cluster, not once per node

This role creates objects that exist **cluster-wide** — the pool and the filesystem. Running
it against every node would attempt to create the same pool repeatedly; the tasks are
idempotent (they treat "already defined" as unchanged), but the work belongs to one host.

Per-node work — `pveceph init`, monitors, managers, OSDs — is `pve_node_ceph`. Run that on
each node **first**: a pool cannot be created before there are OSDs to place its PGs on.

## PG autoscaling

The pool is created with `--pg_autoscale_mode on`, so Ceph adjusts the placement-group count
as the pool grows rather than leaving it at the initial `--pg_num 32`.

Without it, a pool that starts small and grows ends up with far too few PGs for its data,
which shows up as uneven OSD utilisation — some near full while others are idle — rather
than as an error.

`--pg_num 32` remains the starting point; autoscaling moves it from there.
