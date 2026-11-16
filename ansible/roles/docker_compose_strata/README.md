# docker_compose_strata

Deploys [Strata](https://github.com/Niko1221/Strata), a local LLM server for large MoE models (Qwen3.8-Flash-Next and
others) with OpenAI- and Anthropic-compatible APIs. It runs from the published NVIDIA image, behind the host's Traefik.

## Status: Production

## Required input

- `strata_api_key`: no default.
  - It must be 16 or more letters and digits. Anything else fails the role's first task before anything is written.
  - Clients send it as `Authorization: Bearer <key>`.
  - The character set is restricted because the value goes into the host's shared `.env` unquoted, where a
    space-preceded `#` starts a comment.

## Optional inputs

| Variable | Default | If it is wrong |
| --- | --- | --- |
| `strata_image_tag` | `latest-cuda13` | A flavor that does not match the card makes the container exit 3 at start ("the engine in this image does not match"). `cuda13` needs driver ≥ 580. |
| `strata_family` | `qwen` (the ISTA-DASLab original packs) | An unknown family fails `strata launch`, and the container restarts into the same error. |
| `strata_model` | empty: Strata picks for the card and logs which | Changing it later is a new download of tens of GB into `/data`. |
| `strata_context` | empty: "the largest that fits" | Past the model's trained 262,144 tokens, "fits" means YaRN rope scaling, which upstream calls experimental. Set it. |
| `strata_parallel` | empty: fit to the card | More than the card holds shrinks the expert cache. |
| `strata_vision` | `"off"` | On a card under 24 GB the picture reader runs on the CPU, or costs ~850 expert slots on the GPU. |
| `strata_tune` | `skip` | `quick` takes up to ~20 minutes, once, on the first start. |
| `strata_set` | empty | Space-separated `KEY=VALUE` pairs, each passed to `strata launch --set`. An unknown name is a warning, not a refusal, so a typo silently does nothing. No ` # ` in the value. |

## Example

From the calling playbook, with `strata_api_key` set in that host's `host_vars`:

```yaml
- role: docker_compose_strata
  vars:
    strata_model: IQ3_S
    strata_context: 128k
    strata_set: "ple-io=direct"
  tags: strata
```

## What Strata needs

Upstream's own sizing (`setup.py` and docs/DETAILS.md at commit `baf16363`):

- **VRAM: all of it.**
  - ~5 GB for the dense weights, buffers and a 32K KV window, and ~1 GB for the MTP draft layer.
  - The rest becomes an expert cache. More VRAM only makes it faster; it never lowers the RAM needed.
  - Keep a little free: one run with 0 MiB free decoded 7x slower.
- **RAM: every expert, page-locked**, plus 10 GB beside them. Below that, low-RAM mode reads experts from the SSD, "much
  slower".
  - Qwen3.8-Flash-Next IQ3_S is 50.3 GB of experts.
  - From 64K of context the KV cache lives in RAM, at ~13.7 KB per token with 8-bit KV.
  - A conversation cache takes up to 8 GiB of what is left after loading.
- **No container memory limit.** The engine plans from `/proc/meminfo`, and upstream says not to set one.

## The n-gram table moves into RAM on its own

The model's 28.8 GB n-gram table is read from the SSD by default, but two rules can move it into RAM:
- setup does it when `MemTotal` reaches the model's need plus the table plus 16 GB (~107 GB for IQ3_S);
- the engine does it when the machine has room for the table plus 8 GiB (`STRATA_PLE_AUTO_RAM`).

Either costs 28.8 GB of RAM for a prompt-speed gain of a few percent to ~20%. The image tag floats, so either rule can
change in a release. A caller that needs a predictable RAM footprint pins it: `strata_set: "ple-io=direct"`. An
explicit `--ple-io` always wins.

## The key leaks its first 10 characters

Strata's masking shows the first 10 characters of the key (`strata_cli/launch/access.py`, `mask_key`, and
`harness.py`, `mask`). That masked form appears in:
- the launch summary, which is the container's stdout, so `docker logs strata` is not shareable;
- the env lines of `strata connect <app>`, plain or JSON.

Read those for specific lines only, never in full. `docker inspect strata` without `--format` prints the whole `API_KEY`.
The image's health check and `strata bench` read the key themselves, and `strata bench` redacts it from every file it
writes.

## Settings persist in `/data`

The entrypoint saves the env settings as a preset in the volume. New settings replace the saved ones, and tuning results
are kept. Recreate the container (re-run the role) to change one.

## First start

The first start downloads the model anonymously from Hugging Face: tens of GB, resumable if interrupted. The health check
reports `starting`, not `unhealthy`, for up to 2 h while it downloads and loads.

## Updates

The engine is part of the image. `strata update` inside the container is not the update path: pull a new tag and
recreate. Diun reports new digests of the floating tag. A new engine can make old tuning results less useful; a start
with `TUNE` set and `RETUNE=1` measures again.

## Traefik

The default rule routes `strata.<domain_name>` from the service name. Strata always requires a key. With the key set,
requests through Traefik pass Strata's DNS-rebinding host check: this deployment answers by name with no
`STRATA_ALLOWED_HOSTS`. If a client ever gets `403 Host … not allowed`, that variable in the compose environment is the
fix (upstream docs/LLAMA_SWAP.md). Traefik v3's default `writeTimeout` and `responseHeaderTimeout` are 0, so long generations are not
cut off.

## Not done here

- Strata's Prometheus `/metrics` endpoint is not scraped.
- The `docker/smoke-test.sh` in Strata's repo starts its own container. Beside this one, that would pin a second set of
  experts on the same card.
