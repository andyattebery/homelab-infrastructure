# docker_compose_gpu_encoder_sweep_hub

Deploys the gpu-encoder-sweep hub: the FastAPI service that holds the campaign's record, plans and
hands out runs, verifies what an agent publishes to the share, and answers the operator CLI — plus
the Redis queue the agents claim work from.

One hub per fleet, and it is the only part of the harness that is not disposable. Every agent is a
container that can be rebuilt from an image; the hub's SQLite store **is** the measurement database.

## Status: Deployed. Fixture-tested, and running the exchange-through-the-hub shape

## Inputs

Required — no default that can work, both asserted before anything is written:

- `docker_compose_gpu_encoder_sweep_hub_operator_token` — the bearer token the operator CLI
  presents, from vault. The hub enables its auth middleware when *either* token set is non-empty,
  and this role always writes the agent tokens file, so leaving this empty does **not** leave the
  hub open — it locks the operator out. No bearer can match an empty operator token, every operator
  route answers 401, and the agents carry on working, which makes it look like a CLI problem.
- `docker_compose_gpu_encoder_sweep_hub_host` — the hub's **own** host row name, for `SWEEP_HOST`.
  The hub has no other way to know which row is itself, and `sweep inventory` runs on the hub's
  runtime and nowhere else — so an unset value does not degrade inventory, it removes it. No default:
  a host row name is host configuration and this role must not carry one.
- `docker_compose_gpu_encoder_sweep_hub_agent_token` — the bearer the hub's **own agent** presents.
  It must equal `_agent_tokens[_host]`; the role asserts that rather than trusting it, because a
  drift between the two is a 401 on every call the agent makes while the hub itself looks healthy.
- `docker_compose_gpu_encoder_sweep_hub_agent_tokens` — `{host: token}` for every agent, keyed on
  the **host row name** each agent reports as `SWEEP_HOST`, which is not always its inventory name.
  Rendered to `agent-tokens.json` at
  `0600`. A host missing from this dict gets 401 on every call and never heartbeats. A host present
  with an **empty** value is worse: the hub compares the presented bearer against each held token,
  so an empty held token authenticates a request that sends `Bearer ` and nothing else. Both are
  rejected here rather than deployed.

Optional, all with defaults in `defaults/main.yaml`:

- `docker_compose_gpu_encoder_sweep_hub_image_registry` / `_image_name` — default
  `ghcr.io/andyattebery` / `gpu-encoder-sweep-hub`. Split so a caller can move the tag without
  restating the repository.
- `docker_compose_gpu_encoder_sweep_hub_image_tag` — default `main`. Correct as a default and wrong
  during a campaign; see *The image tag is a campaign decision*.
- `docker_compose_gpu_encoder_sweep_hub_redis_image` — default `redis:8-alpine`. The floor is
  **6.2**, and it is a real floor: the queue is a Redis stream read through a consumer group, and the
  hub reclaims entries a dead agent was holding with `XAUTOCLAIM`, which 6.2 introduced. An older
  image starts, serves, and fails at the first reclaim rather than at deploy time.
- `docker_compose_gpu_encoder_sweep_hub_web_hostname` — default `ges-hub`, the label before the
  domain. It must be a valid hostname on its own; see *Why the router rule is explicit*.
- `docker_compose_gpu_encoder_sweep_hub_data_subdirectory` — default `gpu-encoder-sweep`, under the
  host's `docker_compose_dst_data_directory_path`. Holds `data/` (the store, `frames/` and
  `agent-tokens.json`) and `redis/`. Changing it after deployment strands the store: the hub creates
  a fresh empty database and every planned run, every claim and every published artifact is gone
  from its view while still sitting on disk under the old name.
- `docker_compose_gpu_encoder_sweep_hub_share_path` — the pool's share as *this* host sees it. The
  hub runs on the storage host, so the default is a local path and no CIFS volume or SMB credential
  is involved; an agent elsewhere reaches the same directory over SMB. Asserted absolute: Compose
  reads a bind source with
  no leading `/` as a named volume, which would give the hub an empty `/share` and make it refuse
  every claim with nothing to verify.

## Example

From `playbook-nas-01.yaml`, in `tasks:` rather than `roles:` — the share directory has to exist
first and every role in `roles:` runs before any task:

```yaml
- name: Create the gpu-encoder-sweep share directory
  tags: gpu_encoder_sweep
  ansible.builtin.file:
    path: /mnt/storage/temp/gpu-encoder-sweep
    state: directory
    owner: "{{ smb_nas_01_uid }}"
    group: "{{ smb_nas_01_gid }}"
    mode: "0775"

- name: Deploy the gpu-encoder-sweep hub
  tags: gpu_encoder_sweep
  ansible.builtin.include_role:
    name: docker_compose_gpu_encoder_sweep_hub
    # Required: tags on an include_role task gate the include itself, they do not propagate to
    # the tasks inside the role.
    apply:
      tags: gpu_encoder_sweep
  vars:
    # Pinned for the M2 smoke. Read "The image tag is a campaign decision" before moving it.
    docker_compose_gpu_encoder_sweep_hub_image_tag: sha-4d7c4e0
```

with, in `group_vars/all/vars.yaml`:

```yaml
# docker_compose_gpu_encoder_sweep_hub
docker_compose_gpu_encoder_sweep_hub_operator_token: "{{ vault_gpu_encoder_sweep_operator_token }}"
docker_compose_gpu_encoder_sweep_hub_agent_tokens: "{{ gpu_encoder_sweep_agent_tokens }}"
```

`gpu_encoder_sweep_agent_tokens` is assembled there from one vault scalar per agent, because this
repo has no dict-valued vault variables — all 192 entries in `vault.yaml.tpl` are scalars.

The share directory itself is created by the playbook, not by this role: it is a host path, and it
must exist with the same owner and mode as the rest of the pool's temp directory, or the agents
publish into a directory they cannot write.

## Why the router rule is explicit

Traefik on these hosts runs with

```
--providers.docker.defaultRule=Host(`{{ index .Labels "com.docker.compose.service" }}.$DOMAIN_NAME`)
```

so a service with no explicit rule advertises *its compose service name* as a hostname. This stack's
services are `gpu_encoder_sweep_hub` and `gpu_encoder_sweep_redis` — the underscored names you
asked for, and greppable across roles, vars and units — and `gpu_encoder_sweep_hub.<domain_name>`
is not a valid hostname. Traefik would take the router, Let's Encrypt would never issue for it, and
the failure arrives as a certificate error rather than as anything pointing at a label.

So the template sets the rule itself, to `Host(`ges-hub.$DOMAIN_NAME`)`, pairs it with
`traefik.http.routers.gpu_encoder_sweep_hub.service=gpu_encoder_sweep_hub`, and names the port. The
service key stays greppable and the URL stays short. There is no certresolver label because
`--entryPoints.websecure.asDefault=true` and `--entryPoints.websecure.http.tls.certResolver=cloudflare`
supply one for every router, and no `dsm.traefik.router` label because that is only for a container
with more than one router.

The AdGuard rewrite needs no static entry either — dashboard-services-manager derives it from the
router's advertised host. Only a hostname that never becomes a router's host needs one.

## The tokens never touch the compose file

`docker_compose` writes the rendered compose file `0644` and `.env` `0600`. Both bearer credentials
therefore go to the restricted file:

- the operator token is `GES_HUB_SWEEP_TOKEN` in `.env`, referenced from the compose file as
  `- SWEEP_TOKEN=${GES_HUB_SWEEP_TOKEN}`;
- the agent tokens go to `agent-tokens.json`, delivered through `docker_compose_src_config_files`
  with `mode: "0600"`, and named to the hub by `SWEEP_AGENT_TOKENS`.

The `.env` names are `GES_*` and the container-side names are `SWEEP_*` on purpose. `.env` is a
host-global namespace that is merged rather than rewritten and **never pruned**, so a name written
there survives forever and must not collide with another role's; `GES_` is the same family as the
`ges-hub` route and nothing else on the host uses it. Reading `- SWEEP_TOKEN=${GES_HUB_SWEEP_TOKEN}`
then tells you which side of the host/container boundary each name lives on.

This role writes exactly one name into `.env`. There is no per-invocation suffix, unlike
`docker_compose_tdarr`, because a second hub on one host is not a thing that happens — if it ever
becomes one, add the suffix then.

A missing `agent-tokens.json` makes the hub **refuse at start** rather than come up
unauthenticated. That is the loud half of the auth config, and it is deliberate upstream.

## `/share` is read-write, and it used to be the opposite

This inverted, so the old reasoning is worth keeping beside the new one.

**It was read-only** because the hub only ever read the exchange: agents wrote to it directly over
SMB, the hub checked a published file was a file, stat'd it and sha256'd it, and refused a differing
republish by telling the operator to remove the old one *by hand*. Mounting it read-write then would
have turned that refusal into a silent overwrite.

**It is read-write now** because the hub is the only writer. A file crosses machines through the hub's
HTTPS API: an agent `PUT`s it with its sha and size declared, the hub streams it to a temporary file
beside the target, hashes it as it goes, renames it into place and records it. No node mounts this
directory, and none of them holds an SMB credential for it any more — which is the point, and what
removed a whole class of per-host credential problems.

The refusal on a differing republish still stands. It is enforced by the record, not by the mount.

## The stack is three services, and the third is an agent

The hub image's entrypoint is `sweep-hub`. A second service overrides it to `sweep-node serve`, from
the **same image and the same tag**, giving the hub host an ordinary agent of its own.

It exists for one verb. `sweep inventory` runs on the hub's runtime and nowhere else, because the hub
host is the one with the media library mounted — so without this service the fleet has no way to
inventory anything, and the hub refuses by name when `SWEEP_HOST` is unset.

Three things about it are easy to get wrong:

- **It reaches the hub over the stack network**, `http://gpu_encoder_sweep_hub:8000` — not through
  traefik, not over TLS, not by the public hostname. That skips the entrypoint timeouts entirely and
  keeps the hub's own agent working even when the route is misconfigured.
- **It carries no traefik labels and is not on the traefik network.** It serves nothing. A label here
  would hand it a router derived from a service name containing underscores, which is not a valid
  hostname for a certificate — the same trap the hub's explicit rule exists for.
- **Its token lives in two places**: presented by this service, and held in `agent-tokens.json` for the
  hub to check against. One value, written twice. The role asserts they match, because when they drift
  the symptom is a runtime that never heartbeats while the hub looks entirely healthy.

The library is mounted **read-only** — inventory probes files, it never writes them. ⚠ The *container*
path is recorded in every title row permanently. Changing it later does not move what is already
recorded; it just makes new rows disagree with old ones.

## Four variables this role deliberately does not set

`SWEEP_STORE`, `SWEEP_SHARE`, `SWEEP_FRAMES` and `SWEEP_BIND` are all set by the image
(`docker/Dockerfile.hub:16`), and the *code* defaults behind them are wrong for a container —
`SWEEP_BIND` would be `127.0.0.1:8000`, which nothing outside the container can reach, and
`SWEEP_STORE` a relative `hub.sqlite` next to the working directory. Setting them here would be a
second source of truth for four values nobody looks at until one is wrong. The fixture test asserts
they are absent.

`SWEEP_REDIS` is the opposite case and the one genuinely dangerous variable in the stack: the hub
builds a Redis queue when it is set and an **in-memory queue when it is not**. Nothing logs a
complaint, agents claim nothing, and the campaign simply never starts. It is set here to
`redis://gpu_encoder_sweep_redis:6379`, and the host in that URL must stay identical to the compose
service key beside it. The test asserts the relation rather than the string, so a rename of the
service fails the test instead of the campaign.

## Redis holds the queue, so it is persisted — and runs as the deploying user

`--appendonly yes` departs from this repo's only other `appendonly` setting (`docker_compose_onyx`
sets it to `no`, deliberately ephemeral) because this Redis is not a cache: it holds queued and
pending entries. Without persistence, a restart drops them and every affected run needs
`sweep abandon` and a re-plan.

It runs as `${PUID}:${PGID}` so the data directory this role creates is writable as-is. The
alternative — letting the image's entrypoint take ownership of `/data` on every start while Ansible
chowns it back on every apply — is exactly the ownership flip this repo avoids elsewhere.
`docker_compose_metrics` runs grafana, influxdb and prometheus the same way. The fixture test
asserts a second apply changes neither `mtime` nor `ctime` on anything the role wrote.

Redis is **not** on the `traefik` network. It does not need to be, and keeping it off means the
defaultRule can never invent a router for it. It does need the stack's own internal network: a
Compose service that declares any network is not attached to the project default, so without
`gpu_encoder_sweep` the hub could not resolve `gpu_encoder_sweep_redis` at all.

## The image tag is a campaign decision

`main` is the right default and the wrong thing to be running during a campaign. The hub hands a run
only to an agent whose reported artifact matches the one the run was planned for, so a tag that
moves under already-planned runs changes the artifact and **every claim then answers 409** until the
runs are re-planned. Pin `sha-<short>` in the playbook before planning anything, and do not `pqup`
or pull the hub mid-campaign.

## The catalogue comes before the agents, not after

The hub learns the fleet from `sweep add-host` / `add-unit` / `add-scorer`, never from Ansible. An
agent whose host row does not exist yet exits at start — it cannot even run `identify`. So the order
is: deploy this role, confirm the hub answers, author the catalogue, *then* deploy the agents.

An agent deployed as a Compose service crashloops harmlessly until its row exists
(`restart: unless-stopped`) and comes up on its own afterwards. One deployed as a systemd unit or a
boot-triggered task does not: systemd stops retrying after five starts in 300 s, and a boot task
fires once. For those the ordering is a requirement, not tidiness.

## Tests

`tests/test.yml` renders the stack through a real `docker compose config` and asserts on the parsed
document. It needs the docker **CLI** and no daemon — the role's one docker call, the
running-container check behind `service_name_to_restart`, is answered by a stub on `PATH`, and the
test asserts the stub is what answered so that claim cannot quietly become false.

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook \
    -i roles/docker_compose_gpu_encoder_sweep_hub/tests/inventory \
    roles/docker_compose_gpu_encoder_sweep_hub/tests/test.yml
```

Two of the four failure modes listed at the top of that file have been shown to go red, by making
the change and watching the case fail: dropping `:ro` from the share mount, and renaming the redis
service while leaving `SWEEP_REDIS` pointing at the old name. The second is also why the name check
comes first in the file and why nothing in it — `success_msg` included, since Ansible renders task
args before running the assertion — looks a service up by name.

## Confirm the data directory is backed up before you rely on it

Every other part of the harness can be rebuilt from an image. This one cannot: the store is the
campaign's measurement database, and re-measuring is weeks of GPU time. Whether the host's docker
data directory is actually covered by a backup is a property of the host, not of this role — check
it rather than assume it, and check before the acceptance run rather than after. The open question
for this deployment is recorded in `tasks/gpu-encoder-sweep-roles.md`.
