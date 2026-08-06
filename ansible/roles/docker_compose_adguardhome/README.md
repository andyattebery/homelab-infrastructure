# docker_compose_adguardhome

Deploys [AdGuard Home](https://github.com/AdguardTeam/AdGuardHome) as a network-wide DNS
server with ad and tracker filtering, and performs its first-run setup so the instance comes
up already configured rather than waiting at a setup wizard.

## Status: Production

## Requirements

`pip3 install bcrypt` on the Ansible controller — the admin password is hashed in a template
at render time.

## Inputs

Required:

- `adguardhome_hostname` — hostname the instance is served on.
- `adguardhome_username` / `adguardhome_password` — admin credentials, seeded at first run.

Optional:

- `adguardhome_config_directory` — default `<compose_dir>/adguardhome/conf`.
- `adguardhome_upstream_dns` — default is three DoH resolvers, one per operator
  (Cloudflare, Quad9, Google).
- `adguardhome_bootstrap_dns` — default is ten plain-IP resolvers, v4 and v6, spread across
  the same three operators.
- `adguardhome_upstream_mode` — default `parallel`.
- `adguardhome_filters` — default is three blocklists (AdGuard DNS filter, AdAway, HaGeZi
  Normal).

## Example

```yaml
- role: docker_compose_adguardhome
  vars:
    adguardhome_hostname: "dns.{{ domain_name }}"
    adguardhome_username: "{{ adguardhome_username }}"
    adguardhome_password: "{{ adguardhome_password }}"
```

## Bootstrap DNS must span operators

Bootstrap resolvers are what resolve the *hostnames* of the DoH upstreams. If they all
belong to one operator and that operator is unreachable, **no** DoH upstream can start —
including the ones from other providers. The default list therefore carries at least one
address per operator, v4 and v6.

This is the failure mode that makes a DNS server look completely dead rather than degraded.

## `parallel` vs `load_balance`

`parallel` queries every upstream and takes the first answer. `load_balance` sends each
query to one upstream, so a single slow resolver slows that share of all queries — with no
symptom other than intermittent latency.

`parallel` costs more upstream traffic and is the right trade for a home network.

## Removing an upstream

A dead DoH endpoint does not fail loudly; it just never answers, and with `load_balance` it
degrades a fraction of queries. Verify an upstream actually resolves before adding it, and
remove ones that stop.
