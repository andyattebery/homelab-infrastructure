# docker_compose_gpu_encoder_sweep_node

Deploys one gpu-encoder-sweep agent: the process that claims a run from the hub, executes the argv
the hub composed, and publishes the result to the share.

One invocation deploys one **component** — `encode` or `score` — from one template, to its own
compose file, under its own `.env` names. A host running both invokes the role twice. The agent
itself installs nothing and holds no credential but its own bearer token: every mount, device and
environment variable is this role's to provide.

## Status: Deployed. Fixture-tested and wired into `playbook-media-01.yaml` (twice) and
`playbook-wsl-01.yaml`; not yet run live

## Inputs

Required — no default that can work, all asserted before anything is written:

- `docker_compose_gpu_encoder_sweep_node_component` — `encode` or `score`. Selects the image, the
  service name, the deployed file name and the `.env` suffix. Empty renders a service called
  `gpu_encoder_sweep_` and pulls an image called `gpu-encoder-sweep-node-`.
- `docker_compose_gpu_encoder_sweep_node_hub_url` — `SWEEP_HUB`, e.g.
  `https://ges-hub.{{ domain_name }}`. No default on purpose: a default here would silently couple
  this role to the hub role's hostname default, so moving one would break the other quietly.
- `docker_compose_gpu_encoder_sweep_node_token` — `SWEEP_TOKEN`, **this host's** token, from vault —
  the one the hub holds for it, not the operator's. Asserted by length only, so nothing reaches the
  play output.
- `docker_compose_gpu_encoder_sweep_node_host` — `SWEEP_HOST`, the **host row** name the hub knows
  this agent by. It is not always the inventory name: one machine can carry two rows, an encode row
  and a score row, and the hub's quiet-box rule keys off the shared `machine` field to keep them
  from measuring at the same time.
- `docker_compose_gpu_encoder_sweep_node_work_root` — absolute. See *The work root is mounted at the
  same path on both sides*.

Optional, all with defaults in `defaults/main.yaml`:

- `docker_compose_gpu_encoder_sweep_node_env_suffix` — default `_ENCODE` / `_SCORE`, derived from
  the component. See *One `.env` name, and why the suffix is derived rather than chosen*.
- `docker_compose_gpu_encoder_sweep_node_image_registry` / `_image_name` / `_image_tag` — default
  `ghcr.io/andyattebery` / `gpu-encoder-sweep-node-<component>` / `main`. See *The image tag is a
  campaign decision*.
- `docker_compose_gpu_encoder_sweep_node_local_view` — default empty. Only meaningful on a scorer;
  rejected on an encoder. See *The local view is read-write, and this role will not create it*.
- `docker_compose_gpu_encoder_sweep_node_nvidia_gpu` / `_nvidia_gpu_wsl` / `_intel_gpu` — all
  `false`. See *The three GPU shapes*.

## Example

A host running both components invokes the role twice. The **second** invocation must go in
`tasks:` as an `include_role`, not as a second `roles:` entry: no `docker_compose_*` role in this
repo has a `meta/`, and without one a role listed twice under `roles:` runs once and the second
entry is silently skipped.

In `playbook-media-01.yaml`, `roles:` — abridged; the play repeats `_hub_url` on both invocations:

```yaml
- role: docker_compose_gpu_encoder_sweep_node
  vars:
    docker_compose_gpu_encoder_sweep_node_component: encode
    docker_compose_gpu_encoder_sweep_node_host: media-01
    docker_compose_gpu_encoder_sweep_node_token: "{{ gpu_encoder_sweep_agent_tokens['media-01'] }}"
    docker_compose_gpu_encoder_sweep_node_work_root: "{{ media_sweep_work_root }}"
    docker_compose_gpu_encoder_sweep_node_nvidia_gpu: true
    docker_compose_gpu_encoder_sweep_node_intel_gpu: true
    docker_compose_gpu_encoder_sweep_node_image_tag: sha-4d7c4e0
  tags: gpu_encoder_sweep
```

and in the same play's `tasks:`

```yaml
- name: Deploy the gpu-encoder-sweep score node
  tags: gpu_encoder_sweep
  ansible.builtin.include_role:
    name: docker_compose_gpu_encoder_sweep_node
    # Required: tags on an include_role task gate the include itself, they do not propagate to
    # the tasks inside the role — without this the include runs and every task in it is filtered
    # out, deploying nothing while reporting success.
    apply:
      tags: gpu_encoder_sweep
  vars:
    docker_compose_gpu_encoder_sweep_node_component: score
    docker_compose_gpu_encoder_sweep_node_host: media-01-score
    docker_compose_gpu_encoder_sweep_node_token: "{{ gpu_encoder_sweep_agent_tokens['media-01-score'] }}"
    docker_compose_gpu_encoder_sweep_node_work_root: "{{ media_sweep_score_work_root }}"
    docker_compose_gpu_encoder_sweep_node_local_view: "{{ media_sweep_work_root }}"
    docker_compose_gpu_encoder_sweep_node_nvidia_gpu: true
    docker_compose_gpu_encoder_sweep_node_image_tag: sha-4d7c4e0
```

The two work roots are play vars defined once, because **the scorer's `local_view` must be the
encoder's `work_root`** — two spellings of the same path could drift, and the consequence would be a
scorer silently fetching every cell over the share instead of reading it in place.

`playbook-wsl-01.yaml` invokes the same role once, `component: score`, with
`_host: eta-wsl`, `_local_view: /mnt/d/sweep`, and both NVIDIA flags.

## The work root is mounted at the same path on both sides

The hub composes every argv from the host row's `work_root` and the agent runs it inside the
container. If the two paths differed, a path in a record, a log line or a failed command would name
something that does not exist on the host — so the mount is `<work_root>:<work_root>`, and the share
is the one place the inside and outside paths deliberately differ (the host row's `share_root` is
what says so).

**The role creates the work root, and sets nothing else on it.** No owner, no group, no mode. That
is deliberate: a work root can already exist and hold a campaign's stage cuts, owned by whatever
account put them there, and a role that asserted ownership over a directory it did not fill would
chown that away from the runtime that owns it on the next apply.

It is created rather than assumed because the agent does **not** fail when it is missing — it
reports the free space of its own working directory instead, and the run proceeds with a wrong
number. Everything below the work root is the agent's own (`runs/<run_id>/{tmp,records,progress}`,
made with `mkdir(parents=True)`), root-owned because no image sets a `USER`. That is why cleaning up
after a campaign needs sudo.

## The local view is read-write, and this role will not create it

A scorer's `local_view` is another runtime's work root as *this* host sees it — a scorer reading the
encoder's output on the same box, or a WSL scorer reading the Windows agent's `D:\` drive through
`/mnt/d`. Where it exists, scoring reads the encode in place instead of pulling it back over the
share.

Two things about it are easy to get wrong:

- **It is mounted read-write.** Scoring unlinks the encode it scored. Mounted read-only the scorer
  still works, and the other runtime's work root fills until it stops encoding.
- **An absent local view is not an error to Docker.** It would create the path at container start,
  root-owned and empty, and the scorer would find no encodes there and fetch every cell over the
  share instead — slower, a different measurement, and nothing announces it. So the role stats the
  path and refuses rather than creating it: it belongs to the other runtime.

Leaving it empty is legitimate — that scorer fetches from the share. Setting it on an **encode**
agent is not, and is rejected.

## The three GPU shapes

- **`_nvidia_gpu`** emits `runtime: nvidia`, the `deploy.resources.reservations.devices` block, and
  **both** `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video`. The
  first is load-bearing, not belt-and-braces: `Dockerfile.node-encode` sets only the capabilities, so
  without it an encode agent starts, sees no NVIDIA card, and encodes on the CPU while publishing the
  timings. Note the capabilities value is *not* tdarr's `all` — the harness asks for what it uses.
- **`_nvidia_gpu_wsl`** adds `LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/lib/x86_64-linux-gnu` and the
  `/usr/lib/wsl/lib:/usr/lib/wsl/lib:ro` bind. **It requires `_nvidia_gpu`, and the role asserts the
  pair.** `docker_compose_tdarr` leaves these two as independent flags; this role does not, because
  the bind without the runtime is a silent no-GPU and nothing downstream would notice.
- **`_intel_gpu`** bind-mounts the **whole** `/dev/dri`, adds `device_cgroup_rules: ['c 226:* rmw']`
  and `group_add: ["${RENDER_GID}"]`. The whole directory rather than a `devices:` entry because iHD
  requires a node's name to match its minor, and because a `devices:` entry is resolved to a
  major:minor at container *create* time and goes stale the first time a reboot renumbers the nodes.

  **Nothing may name a `renderD*` node** — not here, not in the catalogue. The hub's schema refuses
  an `encoder_unit` whose `device` contains `renderD` for the same reason, so a role that emitted one
  would fail at the database, long after the document looked fine. The fixture test asserts the
  string appears nowhere in the rendered document.

  On a host with no `render` group, `RENDER_GID` is empty and `group_add` renders `[""]`, which fails
  at `up`. `docker_compose` discovers that GID with no assert, deliberately, because every host has
  to be able to run it — so only set `_intel_gpu` on a host with a DRM device.

Both components accept all three flags. A scorer needs CUDA exactly as much as an encoder needs its
encoder, so the blocks key off the caller's flags rather than off the component.

## This role mounts no share, and it used to mount one

Six inputs are gone: `_storage_host`, `_share_subpath`, `_share_volume_name` and four `_smb_*`. So is
the CIFS volume they configured and the `/share` mount that used it.

**What it was.** The pool arrived as a CIFS volume with an explicit `name:`, so two invocations on one
host converged on a single Docker volume rather than each getting a project-prefixed copy — otherwise
an encode published on a host would have been invisible to the scorer beside it. Four SMB credentials
landed in the host-global `.env`, unsuffixed and shared with the other roles on the host.

**What replaced it.** A file crosses machines through the hub's HTTPS API: the agent `PUT`s it with
its sha and size declared, and pulls the same way, under the bearer token it already holds.
`host.share_root` no longer exists in the hub's schema, and the hub — which sits on the storage host
with the pool local — is the only writer of the exchange.

**Why that is better than a working CIFS mount.** It removed a credential from every node's `.env`,
a volume definition from every node's compose file, and an entire class of failure from the Windows
runtime, whose boot-task token could not authenticate to SMB at all and had no supported way to be
given a credential that would.

This role still writes `SMB_STORAGE_*` nowhere. `docker_compose_tdarr` and `docker_compose_comfyui`
write those names for the roles that do read them, and `.env` is never pruned, so anything already
there stays.

## One `.env` name, and why the suffix is derived rather than chosen

`.env` is a host-global namespace: it is merged rather than rewritten, and **never pruned**. Two
invocations on one host therefore must not write the same names, or the second silently redefines
the first — and here that means an agent authenticating as the wrong host, which answers 401 on
every call.

`docker_compose_tdarr` solves this with a caller-chosen suffix defaulting to empty. This role
derives the suffix from the component instead, so the collision is impossible by construction rather
than by the caller remembering. It remains an input, which is what lets the fixture test reproduce
the collision from a legal setting.

Only the token goes through `.env`; everything else is a literal in the compose file, because each
component gets its own file and a name written to `.env` is permanent whether or not anything still
reads it. The compose file is `0644` and `.env` is `0600`, which is the whole point.

## The image tag is a campaign decision

`main` is the right default and the wrong thing to be running during a campaign. The hub hands a run
only to an agent whose reported artifact matches the one the run was planned for, so a tag that moves
under already-planned runs changes the artifact and **every claim then answers 409** until the runs
are re-planned. Pin `sha-<short>` in the playbook before planning anything, and do not `pqup` or pull
mid-campaign.

The image also pins the ffmpeg the measurements are made with. **Do not bind-mount the host's
ffmpeg over it**, the way the tdarr roles do — the tdarr node does that because its base image ships
an ffmpeg too old to use, while here the pinned build *is* the measurement instrument, and a host
that measured with a different one is not comparable with the others.

## `restart: unless-stopped` is what makes the deployment order forgiving

An agent whose host row does not exist yet exits at start — it cannot even run `identify`. Because
these are Compose services, that is harmless: the container crashloops until the row is authored and
then comes up on its own, with no redeploy. The catalogue can be authored after the roles are
applied.

The systemd and scheduled-task runtimes have no equivalent — systemd stops retrying after five
starts in 300 s, a boot task fires once — which is why deployment order matters more for those.

## Tests

`tests/test.yml` renders both components through a real `docker compose config` and asserts on the
parsed document. It needs the docker **CLI** and no daemon; this role makes no docker call of its own
once `should_pull`, `should_run_up` and `should_prune` are false.

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook \
    -i roles/docker_compose_gpu_encoder_sweep_node/tests/inventory \
    roles/docker_compose_gpu_encoder_sweep_node/tests/test.yml
```

Three of the four failure modes listed at the top of that file have been shown to go red, by making
the change and watching the case fail: dropping `NVIDIA_VISIBLE_DEVICES`, mounting the local view
read-only, and naming a `renderD` node. The fourth — two invocations sharing one `.env` name — is
reproduced on purpose by case D-CONTROL, which overrides the suffix to a single shared value and
asserts the encode agent comes back holding the score agent's token.
