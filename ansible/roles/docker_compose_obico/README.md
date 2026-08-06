# docker_compose_obico

Deploys [Obico](https://github.com/TheSpaghettiDetective/obico-server), 3D-print monitoring
with an ML failure detector.

The app and the ML server are separate compose files, so they can run on the same host or on
different ones — the ML side wants a GPU, the app side does not.

## Status: Production

## Inputs

- `obico_no_machine_learning` — default `false`. Deploys the app only.
- `obico_only_machine_learning` — default `false`. Deploys the ML server only.
- `obico_machine_learning_cuda` — default `false`. Selects the CUDA ML image.

Leave both booleans `false` to deploy the whole stack on one host. Setting both deploys
nothing.

Secrets and per-instance settings come through `docker_compose_envs`, including
`OBICO_ML_API_TOKEN`, which must match between the two halves when they are split.

## Example

Split deployment — ML server on the GPU host:

```yaml
- role: docker_compose_obico
  vars:
    obico_only_machine_learning: true
    obico_machine_learning_cuda: true
    docker_compose_envs:
      OBICO_ML_API_TOKEN: "{{ obico_ml_api_token }}"
```

## LLM / VLM passthrough

Recent Obico uses an LLM and a vision model for print analysis and its JusPrin assistant.
Both are passed through as environment variables with upstream defaults, so an unset value
leaves upstream behaviour unchanged:

| Variable | Default |
| --- | --- |
| `OBICO_LLM_API_KEY` | empty |
| `OBICO_LLM_BASE_URL` | `https://api.openai.com/v1` |
| `OBICO_LLM_MODEL_NAME` | `gpt-4o` |
| `OBICO_VLM_API_KEY` | empty |
| `OBICO_VLM_BASE_URL` | `https://api.openai.com/v1` |
| `OBICO_VLM_MODEL_NAME` | `gpt-4o` |
| `OBICO_JUSPRIN_BRAND_NAME` | `JusPrin` |

Point `*_BASE_URL` at a local OpenAI-compatible endpoint to keep this off third-party APIs.

## Splitting the two halves

The app and ML server talk over HTTP, so `OBICO_ML_API_TOKEN` must be identical on both
sides — a mismatch shows up as failure detection silently never running rather than an
error at startup.

`obico_machine_learning_cuda` selects the CUDA image in
`templates/docker-compose-obico-ml.yaml.j2`; it only has an effect on the half that actually
deploys the ML server.
