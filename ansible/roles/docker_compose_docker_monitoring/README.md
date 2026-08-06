# docker_compose_docker_monitoring

Deploys cAdvisor, exporting per-container CPU, memory and network metrics for Prometheus to
scrape on port 8080.

## Status: Not deployed

**No playbook currently invokes this role.** It is kept, with its tuning applied, so
re-enabling it is a one-line change rather than a rebuild. The matching Prometheus scrape
job and Grafana dashboard were removed at the same time — restoring those is part of turning
it back on.

## Inputs

None. The role takes no variables; it deploys `files/docker-compose-docker-monitoring.yml`
through `docker_compose`.

## Example

```yaml
- role: docker_compose_docker_monitoring
```

Then add a scrape job pointing at `<host>:8080`.

## Tuning

cAdvisor defaults are expensive for a homelab. The compose file sets:

- `--docker_only=true` — skip non-Docker cgroups.
- `--housekeeping_interval=30s`, `--max_housekeeping_interval=60s` — the default sub-second
  interval is the main CPU cost.
- `--disable_metrics=disk,diskIO,tcp,udp,advtcp,referenced_memory,resctrl,cpu_topology,memory_numa,process,hugetlb`
  — the per-container series that dominate cardinality and are not used by any dashboard
  here.

These were added while trying to make the exporter cheap enough to keep. It was retired
anyway; the settings remain so that decision does not have to be rediscovered.

## Requirements

Needs `/dev/kmsg` and a privileged container to read cgroup and container state.
