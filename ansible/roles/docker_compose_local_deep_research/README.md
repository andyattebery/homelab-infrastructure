# docker_compose_local_deep_research

Deploys [local-deep-research](https://github.com/LearningCircuit/local-deep-research), a web
research assistant that runs search as a fixed pipeline stage rather than a tool call the
model may decline.

Vendored from upstream's compose file with the bundled `ollama` and `searxng` services
removed — this deployment supplies both from elsewhere.

## Status: Production

## Inputs

- `ldr_llm_endpoint_url` — OpenAI-compatible endpoint, e.g.
  `https://llama-swap.<host>.{{ domain_name }}/v1`. No model runs in this container: the
  image ships CPU-only torch wheels and faiss-cpu, and upstream's GPU override targets only
  the bundled ollama service, which this deployment drops.
- `ldr_llm_api_key` — default `dummy`. Most local servers ignore it, but the
  `openai_endpoint` provider requires one to be present.

## Example

```yaml
- role: docker_compose_local_deep_research
  tags: ldr
```

## Runs beside SearXNG

The container reaches SearXNG by **container name** over a shared Docker network
(`LDR_SEARCH_ENGINE_WEB_SEARXNG_DEFAULT_PARAMS_INSTANCE_URL=http://searxng:8080`), not
through a reverse proxy. That is the reason to place this role on whichever host already
runs SearXNG rather than next to the LLM.

The network is declared `external` with an explicit `name:`, because compose files on a
shared host carry a project-name prefix — `external: true` alone would look for a network
literally called `searxng` and fail.

## `LDR_*` env vars lock the UI

Upstream calls these "permanent overrides", not defaults: any setting passed as an `LDR_*`
environment variable is **removed from the web UI entirely**. Only infrastructure wiring is
forced here.

`LDR_LLM_MODEL` is deliberately **not** set, so the model stays a dropdown rather than a
playbook run per swap.

## The SearXNG full-content patch

`files/patches/sitecustomize.py` works around an upstream bug: SearXNG declares
`supports_full_search: true`, but the factory only passes `use_full_search` for a
hard-coded list of engines that does not include it. The flag that activates its own
advertised capability is never set, so results silently fall back to snippets — measured at
35-400 characters where a fetched page is thousands.

Deployment details that matter:

- Loaded by CPython's `site` module because the container sets `PYTHONPATH=/patches`.
  Nothing imports it explicitly.
- Deployed with `docker_compose_src_config_dirs` (copy), **not** `config_files`
  (template) — it is Python and must land verbatim.
- **Lazy.** It installs a meta-path hook and does nothing until something imports the target
  module, which costs ~5.7s against a 0.02s bare-interpreter baseline. Patching eagerly
  would add that to every Python process in the container.
- Not bind-mounted over site-packages: that path embeds the interpreter version, and this
  image is `latest` with `AutoUpdate=registry`, so a Python bump would break it — and a bind
  mount whose source does not match its target creates a *directory*, breaking the package.
- `LDR_DISABLE_SEARXNG_FULLTEXT_PATCH=1` turns it off without unmounting.

The patch is not filed upstream, so nothing external will make it redundant and nobody else
will notice if it rots. If upstream renames the wrapped function the patch becomes a silent
no-op and every subsequent measurement quietly returns to snippets — which is why its guard
tests fail loudly rather than skipping.

## Exposure

`LDR_WEB_HOST=0.0.0.0` is safe **only** because no port is published — the container is
reachable solely on its Docker networks. Upstream's reverse-proxy guide requires binding to
loopback or an internal network, because ProxyFix trusts `X-Forwarded-*` unconditionally:
anything that can reach the app directly can forge a client IP. Do not add a `ports:`
mapping without revisiting that.

`LDR_APP_ALLOW_REGISTRATIONS` is left at upstream's default of open self-signup, which is
scoped to a LAN-only deployment behind split-horizon DNS. Revisit if the hostname ever
becomes internet-reachable.
