# docker_compose_wyoming_faster_whisper

Deploys [faster-whisper-cuda-docker](https://github.com/andyattebery/faster-whisper-cuda-docker) —
wyoming-faster-whisper on CUDA, serving speech-to-text over the Wyoming protocol on TCP 10300.
Home Assistant's Assist pipeline is the intended client. (`latest` was wyoming-faster-whisper
3.6.0 / CUDA 12.9.2 as of 2026-08-27; the tag floats, so check upstream rather than trusting that
here.)

Speech-to-text only. Piper (TTS) and openwakeword are separate services and would be separate
roles.

## Status: Production

## Inputs

All optional — the role deploys a working service with nothing set.

- `wyoming_faster_whisper_image_tag` — default `latest`. Published tags are `latest`, `3.6.0`
  (the wyoming-faster-whisper version), `3.6.0-cuda12.9.2` (fully qualified) and `sha-<short>`.
- `wyoming_faster_whisper_model` — default `turbo`. Becomes `--model`. faster-whisper downloads
  it into `/data` on first start; nothing pre-seeds it.
- `wyoming_faster_whisper_extra_params` — default empty. A **flat string** of extra arguments,
  appended after `--model`. See *`extra_params` is one string* below for what that costs and what
  it does not.
- `wyoming_faster_whisper_port` — default `10300`. Host side only. The container side is fixed;
  see below.

## Example

```yaml
- role: docker_compose_wyoming_faster_whisper
  vars:
    wyoming_faster_whisper_model: turbo
    wyoming_faster_whisper_extra_params: >-
      --compute-type int8_float16 --language en --beam-size 5 --vad-filter
  tags: whisper
```

## The image already supplies four arguments

Its entrypoint is `bash /run.sh`, and there is no `CMD`. `run.sh` is:

```bash
python3 -m wyoming_faster_whisper \
    --uri 'tcp://0.0.0.0:10300' \
    --data-dir /data \
    --device cuda \
    --download-dir /data "$@"
```

So a compose `command:` is **appended**, not substituted, and three things follow:

- **The container-side port cannot be changed from this role.** `--uri` is hard-coded, which is
  why `wyoming_faster_whisper_port` only moves the host side of the mapping.
- **Never pass `--data-dir` in `extra_params`.** Upstream declares it `action="append"`, so a
  second one *adds* a directory rather than replacing the first.
- Re-passing an ordinary flag is fine — argparse takes the last one — so `--device cpu` in
  `extra_params` really does override the image's `--device cuda`.

## `extra_params` is one string, and Compose splits it

Compose interpolates `${WYOMING_FASTER_WHISPER_EXTRA_PARAMS}` into the `command:` line **first**
and splits the resulting string shlex-style **after**. That ordering is not documented, so it was
measured, and it is what `tests/test.yml` pins:

| `extra_params` | resulting argv after `--model turbo` |
| --- | --- |
| empty | *(nothing — no stray empty argument)* |
| `--compute-type int8_float16 --language en --beam-size 5 --vad-filter` | 7 separate arguments |
| `--initial-prompt "a b c" --vad-filter` | `--initial-prompt`, `a b c`, `--vad-filter` — quoted value stays **one** argument |

So a flat string loses nothing versus a list: quote any value containing spaces and it survives.

There is no shell anywhere in this path, so `$VAR` expansion, globbing and `&&` do not work.

## No ` # ` in `extra_params`

The value is written into the host's shared `.env` **unquoted**, and Docker's env-file parser
treats a space-preceded `#` as an inline comment and discards the rest of the line.
`--language en # note` reaches the container as `--language en`, silently.

`tests/test.yml` asserts this, so if Docker ever changes it the test fails and this section comes
out rather than quietly becoming false.

## Four host-global env names

`WYOMING_FASTER_WHISPER_IMAGE_TAG`, `_MODEL`, `_EXTRA_PARAMS`, `_PORT`.

There is one `.env` per host, shared by every stack in the compose directory, and it *accumulates*
— see `roles/docker_compose/README.md`. The prefix is what keeps these from colliding with the
other stacks on whichever host runs this one; see the calling playbook for what that is in
practice.

Worth knowing when debugging: an **unset** variable is a *warning* to Compose, not an error — it
substitutes a blank and carries on. Dropping one of these four names would blank it rather than
fail loudly.

## `/data` is root-owned on purpose

The role does **not** pre-create the bind source; Docker does, as root. That is correct here — the
image sets no `USER`, so the container runs as root and downloads models into `/data` itself.

Do not add the `docker_compose_kohya_ss`-style `file:` task. It is wrong twice: `docker_compose_uid`
is a default of the `docker_compose` role and is undefined in this one, so its `| default('1000')`
would *guess* an owner that the rest of the stack does not use; and kohya_ss only needs a
user-owned directory because its container runs as `${PUID}`.

## amd64 only — this does not replace the Jetson stack

The image is published `linux/amd64` only, deliberately: ctranslate2's aarch64 wheels carry no
CUDA. `ansible/files/jetson-01/docker-compose-home-assistant-wyoming.yml` runs a *different*
thing — a locally-built Tegra image (`pull_policy: never`, aarch64) that exists in no registry.
This role cannot be pointed at that host.

## Driver floor, and CUDA 12 specifically

- **Driver ≥ 570.124.06.** Stricter than the base image's own `NVIDIA_REQUIRE_CUDA` (≥ 535). An
  older driver starts the container fine and then fails at **inference** with
  `cudaErrorUnsupportedPtxVersion` — so a green `docker ps` proves nothing here.
- **CUDA 12.x, not 13.** ctranslate2 `dlopen`s `libcublas.so.12`; CUDA 13 images ship `.so.13`.
- The NVIDIA Container Toolkit must be configured, i.e. `nvidia_driver` and
  `nvidia_container_toolkit` run before this role.

## No Traefik

Wyoming is a raw TCP protocol, not HTTP, so Traefik cannot route it. The published port is the
only way in, and clients address the host directly.

## First start downloads the model

The image ships its own `HEALTHCHECK` — it speaks Wyoming (`{"type":"describe"}` over the port)
rather than just probing the socket — with `--start-period=10m` to cover that download. Expect
`starting`, not `unhealthy`, for the first few minutes.

`--model turbo` resolves to `mobiuslabsgmbh/faster-whisper-large-v3-turbo`, and the download is
unauthenticated: the container logs a HF Hub warning asking for an `HF_TOKEN`. It is only a rate
limit, and only on a cache miss, so nothing is wired in — but `hugging_face_access_token` exists in
`group_vars/all` if a future host ever hits it.

Once loaded, `turbo` at `int8_float16` sits at roughly 1.2 GB of VRAM.

## GPU contention

`count: all`, unconditionally — this role does not reserve a specific device, and it does not get
the card to itself. On a host also running image-generation, transcoding or embedding stacks, the
GPU is shared; check the calling playbook for the neighbours. Whisper `turbo` at `int8_float16` is
small, but "small" is not "free".

## Not usable through `extra_params`

`--hass-token` (Home Assistant entity-name biasing) needs the `hass` extra; the image installs the
bare sdist, so passing it raises `ImportError`. Same for `--zeroconf`. The role does not block
them.
