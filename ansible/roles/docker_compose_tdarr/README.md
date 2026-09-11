# docker_compose_tdarr

Deploys a Tdarr **server** or a Tdarr **node** — one component per invocation. The server holds the
library and flow definitions; nodes do the transcoding and connect back to it. A host running both
invokes this role twice; see "One host running both server and node".

Deploys no flows, plugins or test scripts — see "What this role does not deploy".

## Status: Production

## Inputs

Required:

- `docker_compose_tdarr_component` — `"server"` or `"node"`. No default; the role asserts it,
  because an empty value would render a node and deploy it to `docker-compose-tdarr-.yaml`. It also
  names the deployed file: `docker-compose-tdarr-<component>.yaml`.
- `docker_compose_tdarr_storage_host` — the host serving the media over SMB. Empty renders the CIFS
  volume names and device paths blank and the container starts with nothing at `/media`, so the
  role asserts it.
- `docker_compose_tdarr_smb_username` / `_password` / `_uid` / `_gid` — credentials for those CIFS
  volumes. All four are asserted non-empty: this role always mounts the share, and an empty value
  produces mount options reading `username=,password=` that fail on the host rather than here.
  They are written **unsuffixed** as `SMB_STORAGE_*`, deliberately the same four names
  `docker_compose_comfyui` uses, so both roles converge on one credential set per host — pass the
  same values to both.

Namespacing, for a host running two invocations:

- `docker_compose_tdarr_env_suffix` — default `""`. Appended to every `TDARR_*` name this role
  writes into the host's shared `.env`. Leave it empty on a host running one component. Give each
  invocation its own value (`_SERVER`, `_NODE`) on a host running two, or the later invocation
  redefines the earlier one's worker counts and `nodeName`.
- `docker_compose_tdarr_extra_env` — default `{}`, one `environment:` entry per key. Written
  **straight into the compose file, not through `.env`**, so `docker_compose_tdarr_env_suffix`
  does not apply and two components on one host get independent values without needing a suffix.
  That is the point: this exists to tell them apart. Keys are emitted sorted, so the rendered
  file does not churn when the dict is reordered. ⚠ The compose file is world-readable — nothing
  secret. See "Labelling a component for flow routing".

Node connection — read only when the component is `node`:

- `docker_compose_tdarr_server_ip` — default `tdarr.{{ domain_name }}`. The address the **node**
  dials. Not a server setting: a server listens on `0.0.0.0:8266` unconditionally.
- `docker_compose_tdarr_server_port` — default `8266`.
- `docker_compose_tdarr_api_key` — default empty.

Identity and workers — one set, used by whichever component this invocation deploys:

- `docker_compose_tdarr_node_name` — default `{{ inventory_hostname }}`. The name this component
  registers under in the Tdarr UI; for a server it names the internal node. Two components on one
  host must not share it.
- `docker_compose_tdarr_transcode_gpu_workers` — default `0`.
- `docker_compose_tdarr_transcode_cpu_workers` — default `2`.
- `docker_compose_tdarr_healthcheck_gpu_workers` — default `0`.
- `docker_compose_tdarr_healthcheck_cpu_workers` — default `1`.
- `docker_compose_tdarr_server_manage_workers` — default `false`, and read only when the component
  is `server`. A node always emits the four counts. The server emits them only when this is true;
  left false the internal node's counts stay whatever the Tdarr UI holds, which is the historical
  behaviour and the reason for the default. See "Worker counts are environment-only".

  Setting it true while leaving the four at their defaults gives the internal node 2 CPU transcode
  workers and 1 CPU healthcheck worker. On a server that had other counts in the UI that is a real
  change, not a no-op.

GPU — set per invocation, so each component can hold a different card:

- `docker_compose_tdarr_nvidia_gpu` — default `false`. Adds `runtime: nvidia`, the `NVIDIA_*` env
  vars, and the `deploy.resources.reservations.devices` block.
- `docker_compose_tdarr_nvidia_gpu_wsl` — default `false`. WSL2 library passthrough; needs
  `docker_compose_tdarr_nvidia_gpu` as well.
- `docker_compose_tdarr_intel_gpu` — default `false`. Bind-mounts the whole `/dev/dri` and adds
  `device_cgroup_rules` and `group_add`. See "Intel render node".
- `docker_compose_tdarr_intel_render_device` — default `/dev/dri/renderD128`. **Documentation
  only.** The role emits it nowhere — not into `.env`, not into the compose file. Which card a flow
  uses is set by hand in the Tdarr UI; this records which one the host was wired for, so the
  playbook and the UI can be checked against each other. **Use the by-path name**,
  `/dev/dri/by-path/pci-<addr>-render`, which is fixed by the PCI address; the `renderD*` number is
  not stable.

Intel GPU access needs `RENDER_GID` in the host's shared `.env`; the `docker_compose` role
discovers it from `getent group render`. On a host with no `render` group it is empty, which
makes `group_add` an empty entry and the container fails at `up` — see "Intel render node".

Storage:

- `docker_compose_tdarr_hardlink_disks` — default `[]`. Per-disk CIFS mounts at
  `/media-raw/<disk>`, mounted **without** `noserverino` so inode numbers are stable and
  hardlink detection works. The merged pool at `/media` uses `noserverino` and cannot be
  used for that. Leave empty if no flow manipulates hardlinks.
- `docker_compose_tdarr_transcode_cache_path` — default `/transcode_cache`.

Other:

- `docker_compose_tdarr_image_tag` — default `latest`.
- `docker_compose_tdarr_custom_ffmpeg_path` — host directory mounted at `/ffmpeg`. Needed only when
  the container's bundled ffmpeg lacks a required encoder or flag. **Deliberately has no default**:
  the template gates on `is defined`, so absence is the switch. Giving it a default of `""` would
  make that test permanently true and mount `/ffmpeg` from an empty source on every host.

## Example

Server, on the host with the library:

```yaml
- role: docker_compose_tdarr
  vars:
    docker_compose_tdarr_component: server
    docker_compose_tdarr_storage_host: nas-01
    docker_compose_tdarr_smb_username: "{{ smb_nas_01_username }}"
    docker_compose_tdarr_smb_password: "{{ smb_nas_01_password }}"
    docker_compose_tdarr_smb_uid: "{{ smb_nas_01_uid }}"
    docker_compose_tdarr_smb_gid: "{{ smb_nas_01_gid }}"
    docker_compose_tdarr_nvidia_gpu: true
    docker_compose_tdarr_hardlink_disks: [data01, data02, data03]
  tags: tdarr
```

Node, on a transcoding host:

```yaml
- name: Deploy Tdarr node
  ansible.builtin.include_role:
    name: docker_compose_tdarr
  vars:
    docker_compose_tdarr_component: node
    docker_compose_tdarr_storage_host: nas-01
    docker_compose_tdarr_smb_username: "{{ smb_nas_01_username }}"
    docker_compose_tdarr_smb_password: "{{ smb_nas_01_password }}"
    docker_compose_tdarr_smb_uid: "{{ smb_nas_01_uid }}"
    docker_compose_tdarr_smb_gid: "{{ smb_nas_01_gid }}"
    docker_compose_tdarr_nvidia_gpu: true
    docker_compose_tdarr_nvidia_gpu_wsl: true
    docker_compose_tdarr_transcode_gpu_workers: 3
    docker_compose_tdarr_transcode_cpu_workers: 0
    docker_compose_tdarr_custom_ffmpeg_path: /opt/ffmpeg-btbn/bin
```

## One template, one service per render

There is a single template, `templates/docker-compose-tdarr.yaml.j2`, and each render emits exactly
one service. The two files it used to be were 71% identical — 80 of 113 lines — and bought nothing:
every compose file in `docker_compose_dst_directory_path` is already **one Compose project**,
because `docker_compose`'s command passes no `--project-name` and Compose derives the project from
the directory, and `files/dc` globs them all into a single invocation.

So the split was duplication without isolation. Merging the source keeps the two deployed
filenames — `docker-compose-tdarr-server.yaml` and `docker-compose-tdarr-node.yaml` — and removes
the copy-paste. Because a render emits one service, nothing needs sharing *within* a file: there are
no YAML anchors and no macros, only `{% if %}`.

## Worker counts are environment-only

There is no way to set worker counts from a config file. `Tdarr_Node_Config.json` has no key for
them — Tdarr documents them separately, under *"Worker Configuration (Node Only - Environment
Variables)"* — so an environment variable is the only configuration route. Tdarr's stated
precedence is *"Environment Variables take precedence, followed by JSON files, then defaults"*.

The server image runs an internal node (`internalNode=true`), which is why
`docker_compose_tdarr_server_manage_workers` exists: the counts are node settings, but that node
lives inside the server container.

⚠ **Worker TYPE is a gate, not a label.** A transcode CPU worker reads the ffmpeg arguments and
refuses any job containing `nvenc`, `cuda`, `vaapi` and the like; a transcode GPU worker is the one
that takes them. A node with only CPU transcode workers registers, reports healthy, and silently
takes nothing from a hardware-accelerated library.

⚠ **The worker names go into the host's shared `.env` whenever this role runs**, whichever
component, and whether or not the template reads them. On a host running two invocations they are
kept apart by `docker_compose_tdarr_env_suffix`, not by being different variables.

## Intel render node

When `docker_compose_tdarr_intel_gpu` is true the template bind-mounts the **whole** `/dev/dri`
and grants access by DRM major:

```yaml
volumes:
  - type: bind
    source: /dev/dri
    target: /dev/dri
device_cgroup_rules:
  - 'c 226:* rmw'
group_add:
  - "${RENDER_GID}"
```

**Not a `devices:` entry, and not one node renamed to a fixed target.** Both were tried and both
fail, for two separate reasons measured on a two-GPU host:

- **iHD requires a node's name to match its minor.** Presenting the Intel card's `renderD129` as
  `/dev/dri/renderD128` fails with `Failed to a DRM display` whether passed via `--device`, via a
  bind mount, or with the matching `card` node alongside it. Under its real name it works
  immediately. So the container has to see the real names, which means the whole directory.
- **Docker resolves a `devices:` entry to a major:minor at container *create* time** and reuses it
  on restart. The first reboot that renumbers the nodes leaves the container silently using the
  other card. A directory bind mount is re-established at *start*, so the names inside always
  match the host and `/dev/dri/by-path` resolves live.

The consequence is that nothing in the compose file names a card. Selection happens in the Tdarr
UI, per flow. `docker_compose_tdarr_intel_render_device` records which card the host was wired for
but is not plumbed anywhere — see its entry under Inputs.

The container will see every render node on the host, including a discrete card's. That is the
cost of keeping the names real.

## Labelling a component for flow routing

A Tdarr flow **cannot set an environment variable** — the Execute plugin spawns ffmpeg with no
environment override. So anything ffmpeg or its libraries read at runtime has to be on the
container. That is what `docker_compose_tdarr_extra_env` is for; the live user is
`AMD_DEBUG=noefc` on a VAAPI node.

⚠ **Do not use it to tell one component from another in a flow.** Node Tags are the native
mechanism and a flow reads them directly as `args.nodeTags`. The Tdarr UI gates editing that
field, but it **is writable over the API** —
`POST /api/v2/update-node {"data":{"nodeID":"…","nodeUpdates":{"nodeTags":"…"}}}` — so it is
settable without a licence. ⚠ Resolve the `nodeID` from `/api/v2/get-nodes` at run time; node
IDs are **not** stable across restarts.

⚠ **Tag by the specific card, not by encoder or vendor.** Settings are measured per card:
`-qp 15` is a property of an A4000, not of `hevc_nvenc`. And an encoder probe cannot separate
vendors that implement the same encoder — an Intel Arc and an AMD card both pass a `hevc_vaapi`
probe, so a recipe whose VAAPI settings were measured on one would silently be applied to the
other.

## One host running both server and node

Supported, with **two invocations** — one per component. Two things make that work.

**Use `include_role` for the second one.** The role has no `meta/main.yml`, and Ansible runs a role
listed twice under `roles:` **once**. A second `roles:` entry is skipped in silence: nothing fails,
the component simply never deploys. `ansible.builtin.include_role` has no such dedup.

**Give each invocation its own `docker_compose_tdarr_env_suffix`.** `.env` is a **host-global
namespace**: the `docker_compose` role slurps the host's existing file and merges new values over
it, so every role on the host shares one file, the later writer wins, and nothing is ever pruned.
Without distinct suffixes the second invocation would define the first's worker counts and
`nodeName` as a side effect — an internal node coming back up with the node container's counts, and
both registering under one name.

Because the flags are per-invocation, the two components can hold different cards. That is the
point: give the server one and the node the other, so a flow routed at one cannot land on the
other. A component that can reach both defeats the routing.

`SMB_STORAGE_*` is deliberately **not** suffixed — it is shared with `docker_compose_comfyui` on
purpose, so both roles converge on one credential set. Pass the same credentials to every
invocation on the host, or the later one redefines them for the earlier.

Nothing else collides on disk: the containers are `tdarr` and `tdarr-node`, the data directories
`tdarr/` and `tdarr-node/`, and the compose files `docker-compose-tdarr-server.yaml` and
`docker-compose-tdarr-node.yaml` — both matched by the `docker-compose*.y*ml` glob the
`docker_compose` scripts use. Both renders declare the CIFS volumes under the same explicit
`name:`, which is intended: the two files then converge on one Docker volume instead of creating
two.

Changing a suffix does **not** clean the old keys out of a host's existing `.env` — nothing in
`docker_compose` deletes keys. Superseded names sit there inert.

One limitation: `container_name: tdarr-node` is fixed in the template, so a host can run one node.
A second node on the same host needs a container-name input first.

## Tests

`tests/test.yml` exercises this role against a throwaway directory — localhost only, no container
started, no daemon needed, only the docker CLI because `docker compose config` renders and exits.
See `ansible/tests/README.md` for the invocation and for why the `tests/roles/` symlinks exist.

## What this role does not deploy

Three kinds of artefact used to live in this role and were moved out, because they are one
deployment's configuration rather than reusable role content. They now live under
`ansible/files/<host>/tdarr/`:

| Artefact | Deployed by |
| --- | --- |
| Flow definitions (`tdarr-flow-*.json`) | **Nothing.** Flows are imported through the Tdarr web UI. The files are version control only. |
| Test scripts (`test-av1-*.sh`) | **Nothing.** Run by hand against a node. |
| Custom flow plugins (`tdarr-plugins/`) | **The calling playbook**, as `docker_compose_src_config_files` entries. |

The plugins are not deployed here on purpose. Some embed a service URL that has to be
templated, and the only directory-copy mechanism available
(`docker_compose_src_config_dirs`) uses `ansible.builtin.copy`, which never renders Jinja.
Passing them per file as `docker_compose_src_config_files` routes them through
`ansible.builtin.template` instead. See `playbook-media-01.yaml` for the wiring, and
`docs/tdarr-av1-flow.md` for what the flows do.
