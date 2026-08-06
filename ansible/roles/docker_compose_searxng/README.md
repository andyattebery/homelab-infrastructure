# docker_compose_searxng

Deploys [SearXNG](https://github.com/searxng/searxng), a self-hosted metasearch engine,
with a Valkey cache alongside it.

Used both directly and as the search backend for other services on the same host, which
reach it by container name.

## Status: Production

## Inputs

- `searxng_secret_key` — required, from vault. SearXNG refuses to start without it.

Everything else is fixed in `templates/settings.yml.j2` and `templates/limiter.toml.j2`.

## Example

```yaml
- role: docker_compose_searxng
```

## The config key is `valkey:`, not `redis:`

SearXNG replaced its Redis client with Valkey and **renamed the settings key**. A
`settings.yml` still saying `redis:` is not an error — the key is ignored, the cache is
silently disabled, and the only symptom is slower searches and rate-limiter state that does
not persist.

## Both config files are templated

`limiter.toml` and `settings.yml` are deployed through `docker_compose_src_config_files`,
which renders Jinja. `settings.yml` also carries `service_name_to_restart: searxng`, because
SearXNG reads it once at startup — without that, a changed setting does nothing until the
container happens to restart.

## Other services reach it by container name

Consumers on the same host use `http://searxng:8080` over a shared Docker network rather
than a reverse-proxy round trip. That network is owned by this role's compose file, so a
consumer joining it must declare it `external` **with an explicit `name:`** — compose
prefixes network names with the project name, so `external: true` alone looks for a network
that does not exist.
