# podman_quadlet_caddy

Deploys Caddy as a Podman Quadlet reverse proxy, with a Cloudflare DNS-01 TLS block per
virtual host. Wraps `podman_quadlet` twice: once for the network, once for the container.

The Podman-host equivalent of `docker_compose_traefik` — for hosts running Quadlet rather
than Docker Compose.

## Status: Production

## Inputs

Required — both asserted, because a wrong value fails silently rather than loudly:

- `podman_quadlet_caddy_data_dir` — host directory for Caddy's certificate store, config
  and Caddyfile. **No default on purpose**: any default would encode one host's disk layout,
  and a wrong one plants the certificate store somewhere unintended and works until the
  next change loses the certs.
- `podman_quadlet_caddy_sites` — list of `{ host, upstream }`. `upstream` is a container
  name and port on the Caddy network. An empty list would deploy Caddy serving nothing.

Optional:

- `podman_quadlet_caddy_image` — default `ghcr.io/caddybuilds/caddy-cloudflare:latest`. The
  Cloudflare build is required; stock Caddy has no `dns cloudflare` provider.
- `podman_quadlet_caddy_network` — default `caddy.network`.
- `podman_quadlet_caddy_cloudflare_api_token` — default `{{ cloudflare_api_token }}`.
  Written to the container's `EnvironmentFile` at mode `0600`.

## Example

```yaml
- name: Deploy Caddy reverse proxy
  ansible.builtin.include_role:
    name: podman_quadlet_caddy
  vars:
    podman_quadlet_caddy_data_dir: "{{ host_data_mount_path }}/caddy"
    podman_quadlet_caddy_sites:
      - host: "comfyui.{{ inventory_hostname }}.{{ domain_name }}"
        upstream: "comfyui:8188"
      - host: "llama-swap.{{ inventory_hostname }}.{{ domain_name }}"
        upstream: "llama-swap:8080"
```

## Invoke it before the containers it proxies

The `.network` unit has to exist before any container declaring
`Network=caddy.network` is generated, so this role runs **ahead of** those containers in the
playbook. The reverse order is not fine: unit generation fails on a missing network.

Caddy starting before its backends is harmless — it resolves upstreams lazily, per request,
so a backend that appears later is picked up without a restart.

Every container Caddy proxies must join the same network, or the container name will not
resolve.
