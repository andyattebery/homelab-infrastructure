# docker_compose_network_inventory_manager

Deploys network-inventory-manager: reconciles a declarative host inventory kept in this
repository against the live network, writing DHCP reservations into AdGuard Home and reading
device state from the UniFi controller.

The inventory is fetched from GitHub at runtime, not baked into the image.

## Status: Production

## Inputs

Required, all from vault:

- `network_inventory_manager_github_token` — reads the inventory file from the repo.
- `network_inventory_manager_unifi_username` / `_password` — UniFi controller credentials.
- `network_inventory_manager_op_service_account_token` — 1Password service account, used to
  resolve the `op://` references inside the inventory template.
- `network_01_adguardhome_username` / `_password` — AdGuard Home admin credentials.

Optional, all with defaults in `defaults/main.yaml`:

- `network_inventory_manager_sync_interval` — default `1800` seconds. Lower it and every
  cycle re-reads GitHub and 1Password; raise it and a bad inventory lives longer.
- `network_inventory_manager_removal_grace_cycles` — default `8`. Consecutive cycles an
  entry must be absent from the desired state before it is deleted from AdGuard Home; at
  the default sync interval that is four hours, so a service stopped for debugging keeps
  its DNS rewrite. Set too low and transient absences delete records; set too high and
  genuinely retired hosts linger. `0` deletes as soon as an entry stops being desired.
- `network_inventory_manager_dsm_url` — default is the published Dashboard Services Manager
  port on the host running it, reached by address rather than by name (see below). Point it
  somewhere unreachable and NIM syncs without service discovery; DSM's last known-good
  rewrites are protected from removal rather than deleted.
- `network_inventory_manager_adguardhome_url` — default `http://192.168.1.224`.
- `network_inventory_manager_unifi_url` — default `https://192.168.1.1`.

## Example

```yaml
- role: docker_compose_network_inventory_manager
```

## The inventory lives in this repo and is fetched over the network

`settings.yaml` points the container at `config_repo` and `repo_config_path` —
`network-inventory/network_hosts_inventory.yaml.tpl`. The container pulls that file from
**GitHub**, not from the local checkout, so a change only takes effect once it is pushed.

That file is a `.tpl`: MAC addresses and the domain are `{{ op://... }}` references, and the
container resolves them with `op_service_account_token` at runtime. Nothing sensitive is
stored in the file itself — which matters, because this repository is public.

Add a new host by editing that template, not by touching this role.

## Writes to AdGuard Home and reads from UniFi

Reservations are written into AdGuard Home's DHCP configuration. A host removed from the
inventory has its reservation removed too, so treat the template as the source of truth
rather than a partial overlay.

The UniFi side is read-only — it supplies observed device state for reconciliation.

## Reach DSM by IP, not through Traefik

`network_inventory_manager_dsm_url` points at the DSM host's published port rather than
`dashboard-services-manager.<domain_name>`, and that is deliberate. NIM manages the DNS
rewrite for that name. Reaching DSM through it means a bad sync can delete the record NIM's
own recovery depends on — and because an unreachable DSM blocks removals, the bad entries
that sync just wrote cannot then be cleaned up. That is exactly what happened on
2026-08-06. The published port has no such loop.

Traefik still serves the browser-facing name; this is only the machine-facing path.
