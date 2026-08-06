# docker_compose_onyx

Deploys [Onyx](https://github.com/onyx-dot-app/onyx) — a RAG / retrieval layer over
connected document sources, backed by Postgres and OpenSearch, talking to an
OpenAI-compatible LLM endpoint.

The compose file is vendored from upstream rather than pulled, so this role owns the
service topology; see "Re-vendoring" before bumping it.

## Status: Production

## Inputs

Required — asserted, because Onyx will otherwise start into a broken state rather than fail:

- `onyx_user_auth_secret`, `onyx_postgres_password`, `onyx_opensearch_admin_password` —
  from vault. The API server refuses to start on an empty `USER_AUTH_SECRET`, and
  OpenSearch rejects a weak admin password (8+ chars, upper, lower, digit, special).
- `onyx_llm_api_base` — the OpenAI-compatible endpoint, e.g.
  `https://llama-swap.<host>.{{ domain_name }}/v1`. Host config, so no default.
- `onyx_llm_models` — models to advertise in the UI. Host config, so no default; see
  "Token budgets" for how each entry is derived.

Optional:

- `onyx_encryption_key_secret` — encrypts stored connector credentials. Set it **before**
  any connector exists; changing it later orphans them.
- `onyx_image_tag` — default `latest`.
- `onyx_domain_name` / `onyx_web_domain` — default `onyx.{{ domain_name }}` and
  `https://<that>`. Onyx builds absolute URLs from `WEB_DOMAIN`; upstream's default of
  `http://localhost:3000` produces broken links behind a reverse proxy.
- `onyx_file_store_backend` — default `postgres`, which avoids running MinIO at all.
- `onyx_searxng_base_url` — web-search provider, registered as a database row.
- `onyx_opensearch_heap` — default `2g`.
- `onyx_llm_socket_read_timeout` — default `300`. Max gap between response chunks, not a
  total request timeout. Upstream's 60 is too tight when the endpoint cold-loads a model.
- `onyx_gen_ai_temperature` — default `1.0`. See "Temperature" below.
- `onyx_memory_*` — per-container limits.
- `onyx_zfs_parent_dataset` — default empty, meaning "just make directories". Set to a pool
  name to give Postgres and OpenSearch their own datasets, which is the only way per-path
  properties can be set.
- `onyx_llm_provider_name` — default `llama-swap`.

## Example

```yaml
- role: docker_compose_onyx
  tags: onyx
```

with the host config in `host_vars/<host>/vars.yaml`:

```yaml
onyx_zfs_parent_dataset: data
onyx_llm_api_base: "https://llama-swap.htpc-01.{{ domain_name }}/v1"
onyx_llm_models:
  - { name: gemma-4-12b-it, is_visible: true, max_input_tokens: 55296 }  # ctx 65536
```

## Token budgets

`max_input_tokens` is deliberately **below** each model's llama.cpp `-c`, never equal:

    max_input_tokens = ctx - 8192 output - 2048 reserve

llama.cpp's context covers the prompt *and* the generation, so an input budget of the full
context leaves nothing to answer with — and thinking tokens come out of it too.

The reserve is not padding-by-feel. It covers the chat template, BOS, system and tool
scaffolding, and any disagreement between Onyx's tokenizer and the model's own vocabulary —
Onyx enforces this limit with its own tokenizer, not the server's. An earlier 24576/8192
split summed to exactly 32768 with zero slack, which under `--no-context-shift` is a hard
400 rather than a graceful trim.

Each value is **half of a setting that lives in two files**. Change a model's `ctx` in the
playbook that deploys the LLM server and you must recompute the matching value here.

## Temperature

Onyx defaults `GEN_AI_TEMPERATURE` to 0 and sends it on **every** request, which overrides
whatever the model server put on its own command line. Left unset, the model runs greedy no
matter what its per-model sampler flags say.

That matters beyond sampling quality: greedy decoding makes the search / no-search branch
deterministic, so a question the model marginally prefers to answer from memory is answered
from memory *every* time. Set it to match the value the server already passes, which should
be the model publisher's recommendation.

## Re-vendoring

`templates/docker-compose-onyx.yml.j2` is copied from upstream at a pinned version while
`IMAGE_TAG` floats. Measured churn across several releases: patch releases do not change it;
minor bumps move ~10-14 lines, and only comments, build hints or deletions.

**Re-vendor when the minor version moves, not on patches.**

The nginx config under `files/` is vendored verbatim and deployed with
`docker_compose_src_config_dirs` (copy, no Jinja) specifically so it stays byte-identical to
upstream and re-vendoring is a clean diff.
