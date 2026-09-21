# podman_quadlet_gpu_encoder_sweep_node

Deploys the gpu-encoder-sweep encode agent as a rootful podman quadlet, for a host that runs
quadlets rather than docker compose.

Same application as `docker_compose_gpu_encoder_sweep_node`, separate role because the container
runtime differs — the same split this repo already has between `docker_compose_tdarr` and
`podman_quadlet_tdarr`. It shares no template, no `.env` and no `docker_compose` include with its
compose sibling.

## Status: Deployed. Fixture-tested where it can be, and wired into `playbook-htpc-01.yaml`;
not yet run live

The rendered unit and the input asserts have fixtures. `mountpoint`, the share's ownership,
`podman pull` and systemd need the real host, and are covered by *Verification* below.

## Inputs

Required — no default that can work, all asserted before anything is written:

- `podman_quadlet_gpu_encoder_sweep_node_hub_url` — `SWEEP_HUB`.
- `podman_quadlet_gpu_encoder_sweep_node_token` — `SWEEP_TOKEN`, this host's token from vault.
  Asserted by length only, so nothing reaches the play output.
- `podman_quadlet_gpu_encoder_sweep_node_host` — `SWEEP_HOST`, the **host row** name.
- `podman_quadlet_gpu_encoder_sweep_node_work_root` — absolute. Mounted at the same path inside and
  out. `podman_quadlet` creates every `Volume=` bind source, so this needs no task of its own.
- `podman_quadlet_gpu_encoder_sweep_node_puid` — the uid that owns the work root. `podman_quadlet`
  creates the bind source, so without this it is root-owned and the agent cannot write its runs.

Optional, all with defaults in `defaults/main.yaml`:

- `podman_quadlet_gpu_encoder_sweep_node_image_registry` / `_image_name` / `_image_tag` — default
  `ghcr.io/andyattebery` / `gpu-encoder-sweep-node-encode-mesarc` / `main`. **The image name is not
  interchangeable with the plain encode build** — see *Why the mesarc image*. The tag is a campaign
  decision — see *The tag is a campaign decision*.
- `podman_quadlet_gpu_encoder_sweep_node_config_dir` — default `/etc/gpu-encoder-sweep`. Holds the
  `0600` environment file carrying the token. Outside every mount on purpose.
- `podman_quadlet_gpu_encoder_sweep_node_devices` — default `[/dev/dri, /dev/kfd]`, emitted as
  `AddDevice=`. **Never a `renderD*` node**; the role asserts that.
- `podman_quadlet_gpu_encoder_sweep_node_group_add` — default `[keep-groups]`, for parity with the
  production node on the same card, whose own comment flags it as "probably inert here".
- `podman_quadlet_gpu_encoder_sweep_node_amd_debug` — default `noefc`. See *`AMD_DEBUG` is its own
  input for a reason*.
- `podman_quadlet_gpu_encoder_sweep_node_extra_env` — default `{}`. Extra `Environment=` lines for
  the ffmpeg the agent spawns as a child, which inherits this environment.
- `podman_quadlet_gpu_encoder_sweep_node_timezone` — default `{{ timezone }}`.
- `podman_quadlet_gpu_encoder_sweep_node_install_wanted_by` — default `multi-user.target`. Pass `""`
  on a host where a GPU-arbitration script owns boot policy — see *Boot policy may not be this
  role's*.
- `podman_quadlet_gpu_encoder_sweep_node_start_limit_interval_sec` / `_start_limit_burst` — default
  `300` / `5`. See *systemd gives up where Docker would not*.

## Example

One piece. There is no CIFS mount to arrange first — that requirement is gone.

```yaml
- name: Deploy the gpu-encoder-sweep node
  tags: gpu_encoder_sweep
  ansible.builtin.include_role:
    name: podman_quadlet_gpu_encoder_sweep_node
    # Required: tags on an include_role task gate the include itself, they do not propagate to
    # the tasks inside the role.
    apply:
      tags: gpu_encoder_sweep
  vars:
    podman_quadlet_gpu_encoder_sweep_node_hub_url: "https://ges-hub.{{ domain_name }}"
    podman_quadlet_gpu_encoder_sweep_node_token: "{{ gpu_encoder_sweep_agent_tokens['htpc-01'] }}"
    podman_quadlet_gpu_encoder_sweep_node_host: htpc-01
    podman_quadlet_gpu_encoder_sweep_node_work_root: "{{ htpc_data_mount_path }}/sweep"
    # Owns the work root that podman_quadlet creates for the bind source.
    podman_quadlet_gpu_encoder_sweep_node_puid: "{{ smb_nas_01_uid }}"
    # Boot policy belongs to gpu-mode on this host.
    podman_quadlet_gpu_encoder_sweep_node_install_wanted_by: ""
    podman_quadlet_gpu_encoder_sweep_node_image_tag: sha-4d7c4e0
```

```yaml
# 4. the unit joins the watchdog's consumer list in the same play:
systemd_unit_watchdog_units:
  - tdarr-node.service
  - comfyui.service
  - gpu-encoder-sweep-node.service
```

and `ansible/files/htpc-01/gpu-mode.sh` gains a `sweep` mode — see *Boot policy may not be this
role's*. Without it nothing installs the `[Install]` drop-in and the agent never starts at boot.

## This role mounts no share, and it used to need one mounted for it

Three inputs are gone — `_share_mount_point`, `_share_container_path` and the guards around them —
along with the host's CIFS mount entry that fed them.

**What it was.** The pool arrived as a `systemd_cifs_mount` entry in the host's mount list, and this
role took only the mount point, because `podman_quadlet_tdarr` had already had its own `manage_mounts`
and `smb_*` inputs extracted into that role and a sweep role reintroducing them would have rebuilt
what the repo had just consolidated. It then carried two guards that are also gone:

- a **`mountpoint -q` check before the quadlet deployed**, because `RequiresMountsFor=` does not
  substitute for one: `systemd.unit(5)` says it adds dependencies "for all mount units required to
  access the specified path", so a path that is *not itself* a mount point resolves to its nearest
  parent mount and the unit starts cleanly against an empty directory — and `podman_quadlet` creates
  a directory for every `Volume=` bind source it finds, so an unmounted share was silently created on
  the way past and the agent published into something that looked fine and reached nobody.
- an **ownership assert**, because the agent published there: a mount owned by someone else was not a
  mount failure but an agent that could read the pool and not write to it, surfacing as a failed claim
  long after the play succeeded.

**What replaced it.** A file crosses machines through the hub's HTTPS API — the agent `PUT`s it with
its sha and size declared and pulls the same way, under the bearer token it already holds.
`host.share_root` no longer exists in the hub's schema. So there is no mount to order against, to own,
or to accidentally create.

`_puid` survives all of that, for a smaller reason: `podman_quadlet` creates the work root as a bind
source, and without a uid it belongs to root.

## Three deliberate divergences from `podman_quadlet_tdarr`

They look like oversights next to the tdarr node on the same host, so they are listed together:

1. **No `AutoUpdate=registry`.** The hub hands a run only to an agent whose reported artifact matches
   the one the run was planned for, so an image that moves under already-planned runs makes every
   claim answer 409 until they are re-planned. `pqup` runs auto-update across the host; this unit
   must not participate. The fixture test asserts the line is absent.
2. **No ffmpeg bind mount, and no input for one.** The tdarr node mounts a host build over the
   image's because its base ships an ffmpeg too old to use. Here the image's pinned build **is the
   measurement instrument**, and a host that measured with a different one is not comparable with the
   others — so there is no `_ffmpeg_dir` to set, deliberately, rather than an input the README tells
   you not to use.
3. **It mounts nothing**, as above.

## The token goes in a `0600` EnvironmentFile

Quadlet unit files are written world-readable at `0644`, so a bearer token cannot be an
`Environment=` line. `SWEEP_HUB` and `SWEEP_HOST` are; `SWEEP_TOKEN` lives in
`<config_dir>/gpu-encoder-sweep-node.env` at `0600`, root-owned, in a directory this role creates at
`0700` — outside every mount, because systemd reads it as root before the container starts and the
container never needs the file itself.

This is the same problem as on the other two runtimes, with a third mechanism: `.env` at `0600` on
the compose hosts, an NTFS ACL on the Windows one, an `EnvironmentFile` here.

The file is read once at container start, so a changed token does nothing until a restart — hence
`restart_service: true` on it.

## Why the mesarc image

The stock node image's base carries a Mesa old enough to sit below the VCN floor for this card, and
the damaging part is not that it fails: it **silently ignores `-compression_level`**, which *is* the
vaapi preset ladder. Every rung of a sweep would produce identical output while reporting success,
and nothing in the record would say so.

The mesarc build is the same tdarr layer with Mesa replaced from a fresher PPA, so the rig still
matches production, and it asserts its own Mesa version at build time.

**One parity check before the acceptance run**, because the production node pins a channel tag while
the harness image pins a digest of it:

```
podman image inspect ghcr.io/andyattebery/tdarr-node-mesa-fresh:mesarc \
  --format '{{index .RepoDigests 0}}'
```

It must equal the digest the harness's mesarc Dockerfile builds `FROM`. If they have diverged that
is a decision point — bump the harness's base and rebuild, or hold the production node at the older
digest — not something a role should paper over.

## `AMD_DEBUG` is its own input for a reason

`noefc` disables EFC, which is unstable in upstream Mesa; jellyfin disables it for the same reason.
It has to be a container-level variable because the ffmpeg the agent spawns inherits this
environment — the harness builds an argv and cannot set it.

It is a separate input rather than an entry in `_extra_env` precisely so that a caller overriding
`_extra_env` for something else cannot silently drop it. Emptying it gives unstable encodes on an AMD
card **and** divergence from what production runs on the same hardware. Empty is correct on a host
with no AMD GPU.

## Boot policy may not be this role's

`_install_wanted_by` defaults to `multi-user.target`, which is the ordinary answer. On a host where a
GPU-arbitration script decides which container may hold the card, pass `""`: that script adds and
removes a `<unit>.container.d/` drop-in supplying the `WantedBy`, and a unit carrying its own
`[Install]` would fight it. That is why the other GPU containers on such a host have none either.

With `""` the unit exists and **nothing starts it at boot until that script has run once** — so
after a first deployment, run it. The fixture test asserts that an empty value produces no
`[Install]` section at all.

Two consequences worth knowing on such a host:

- Switching the arbiter away from this unit kills an in-flight encode. The harness recovers — the
  heartbeat TTL fails the run and the queue entry waits for the agent — but the run is lost.
- The host's existing sleep inhibitor already covers the encode itself: it matches any `ffmpeg`
  process host-wide, in a container or not, so this agent's ffmpeg holds the inhibitor without any
  change. The residual gap is the window *between* cells, where a suspend drops the heartbeat and
  the hub fails the run at the TTL. Wrap a campaign in the host's existing sleep-inhibit CLI rather
  than adding a second check here.

## systemd gives up where Docker would not

`StartLimitIntervalSec=300` and `StartLimitBurst=5`: a unit that exits five times in five minutes
**stops retrying**. An agent whose host row does not exist yet exits at start, hits that in seconds,
and stays failed — `restart: unless-stopped` on the compose hosts has no equivalent limit and simply
crashloops until the row appears.

So on this runtime the deployment order is a requirement, not tidiness: author the catalogue first.
If that was missed, the recovery is `systemctl reset-failed <unit> && systemctl start <unit>`.
Raising the burst is the alternative to the ordering, not a replacement for it.

## Register the unit with the watchdog

A failed `.mount` has no way back on its own: `Restart=` is not a mount-unit option, and a consumer
whose `RequiresMountsFor=` dependency failed never runs its own `Restart=` either. This has happened
on this host — a reboot of the file server left exactly that.

So the sweep unit belongs in `systemd_unit_watchdog_units` alongside the host's other consumers of
the same shares. Listing it is safe despite the empty `[Install]`: that role never starts a unit
whose `WantedBy` is empty, which is exactly how the arbiter marks the modes it turned off.

## Tests

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook \
    -i roles/podman_quadlet_gpu_encoder_sweep_node/tests/inventory \
    roles/podman_quadlet_gpu_encoder_sweep_node/tests/test.yml
```

The first test of any `podman_quadlet*` role in this repo. There is no `podman generate` equivalent
of `docker compose config`, so the assertions are on the rendered unit text — which is what systemd
reads anyway. The asserts are imported on their own through `tasks_from: assert`, which is why they
live in `tasks/assert.yaml`.

Three properties have been shown to go red by making the change and watching the case fail: dropping
`AMD_DEBUG`, adding `AutoUpdate=registry`, and moving the token into an `Environment=` line in the
`0644` unit.

## Verification

On the host, after applying:

```
systemctl status gpu-encoder-sweep-node.service
systemd-analyze cat-config /etc/containers/systemd/gpu-encoder-sweep-node.container
stat -c '%U:%G %a' /etc/gpu-encoder-sweep/gpu-encoder-sweep-node.env   # root:root 600
mountpoint -q <share mount point> && echo mounted
journalctl -u gpu-encoder-sweep-node.service -n 50
```

Then `sweep status` from the operator CLI: this host heartbeating, with the artifact reading
`node-encode-mesarc:<version>`. Read the unit's log as well as its status — an agent that started
and is refusing every claim looks identical to a healthy one from `systemctl` alone.
