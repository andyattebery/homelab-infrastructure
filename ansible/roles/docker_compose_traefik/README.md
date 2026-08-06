# docker_compose_traefik

Deploys [Traefik](https://traefik.io/) as the host's reverse proxy, with Let's Encrypt
certificates issued over the Cloudflare DNS-01 challenge and routes discovered from Docker
container labels.

Creates the `traefik` network that every other compose file on the host attaches to, so it
generally runs first in a playbook.

## Status: Production

## Inputs

All optional:

- `docker_compose_traefik_version` — default `3`.
- `docker_compose_traefik_log_level` — default `ERROR`.
- `docker_compose_traefik_enable_dashboard` — default `false`.
- `docker_compose_traefik_enable_host_network` — default `false`. Needed when Traefik must
  see real client IPs or reach host-network services.
- `docker_compose_traefik_enable_access_log` — default `false`.
- `docker_compose_traefik_enable_tailscale` — default `false`. Adds a Tailscale entrypoint.
- `docker_compose_traefik_file_provider_path` — default empty. Path to a dynamic-config
  file for routes that are not Docker containers.

Requires `CERTBOT_EMAIL` and a Cloudflare API token in scope for ACME.

## Example

```yaml
- role: docker_compose_traefik
  vars:
    docker_compose_traefik_enable_dashboard: true
    docker_compose_traefik_enable_tailscale: true
    docker_compose_traefik_log_level: ERROR
  tags: traefik
```

Tags in a `roles:` block propagate to every task in the role. On an `include_role` they do
not — that needs `apply: { tags: ... }`.

## Traefik logs to a file, not stdout

`docker logs traefik` is empty or near-empty by design. The log goes to a file inside the
container, so debugging means reading that file — not the container's stdout. This has cost
real time during outages; check the file before concluding Traefik is silent.

## The ACME propagation check

lego v5 (bundled in Traefik >= 3.7.6) enables a **recursive-nameserver** propagation check
by default, and Traefik only disables it when a `propagation.*` option is set.

That check asks the container's own resolver for the `_acme-challenge` TXT record lego just
created. If that resolver is a local DNS server, it answers `NXDOMAIN` and caches it for the
zone's SOA minimum — which outlives lego's ~2 minute window. Every issue and renewal then
fails, with the cause several layers away from the symptom.

`--certificatesresolvers.*.acme.dnschallenge.propagation.requireallrns=false` turns it off.
The authoritative-nameserver check still runs, and that is the one that actually proves
propagation.

This surfaces on a **Traefik version bump**, not a config change, so it looks like a
spontaneous certificate outage.

## Routing

Containers opt in with `traefik.enable=true`. The hostname comes from the default rule
(built from the compose **service name** plus the domain) unless the container defines an
explicit router rule — so renaming a service renames its URL.
