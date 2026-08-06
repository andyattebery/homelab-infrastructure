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

Optional:

- `network_inventory_manager_sync_interval` — default `1800` seconds.

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
