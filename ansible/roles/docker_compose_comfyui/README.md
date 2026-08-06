# docker_compose_comfyui

Deploys [ComfyUI](https://github.com/comfyanonymous/ComfyUI), a node-graph interface for
diffusion models, built from `ghcr.io/lecode-official/comfyui-docker` with extra Python
packages layered on (see `files/comfyui/Dockerfile`).

Deploys ComfyUI only. SwarmUI, which used to share this role's compose file, is now
`docker_compose_swarmui`.

## Status: Production

## Inputs

All optional — the role deploys a working single-host ComfyUI with no variables set.

- `comfyui_base_tag` — default `latest`. Tag of the upstream image used as the build base.
- `comfyui_extra_networks` — default `[]`. Extra Docker networks to join beyond `traefik`.
  Each must already exist; the role marks them external and will not create them.
- `comfyui_output_share` — default empty. When set, output is written to a CIFS volume
  instead of a local directory. Give a full SMB path, e.g.
  `//nas.example.com/storage/ai/images`.
- `comfyui_output_volume_name` — default `comfyui_output`. Only used when the share is set.
- `comfyui_smb_username` / `_password` / `_uid` / `_gid` — credentials for that share.
  Ignored when it is unset.
- `comfyui_extra_custom_nodes` — default `[]`. Extra custom-node trees to bind-mount
  read-only at `/opt/comfyui/custom_nodes/<name>`. Each entry: `{ source, name }`.

## Example

```yaml
- role: docker_compose_comfyui
  vars:
    comfyui_extra_networks: [openwebui]
    comfyui_output_share: "//nas-01.{{ domain_name }}/storage/.f/ai/images"
    comfyui_output_volume_name: nas-01_ai_images
    comfyui_smb_username: "{{ smb_nas_01_username }}"
    comfyui_smb_password: "{{ smb_nas_01_password }}"
    comfyui_smb_uid: "{{ smb_nas_01_uid }}"
    comfyui_smb_gid: "{{ smb_nas_01_gid }}"
```

## `comfyui_extra_custom_nodes` paths are compose-relative

`source` is resolved by Docker Compose relative to the **compose file's directory**, not by
Ansible. That is how SwarmUI's ComfyUI extension nodes get mounted without this role knowing
SwarmUI exists:

```yaml
comfyui_extra_custom_nodes:
  - source: ./swarmui/src/BuiltinExtensions/ComfyUIBackend/ExtraNodes/SwarmComfyCommon
    name: SwarmComfyCommon
```

Do **not** build these from `docker_compose_dst_directory_path`. That variable is a default
of the `docker_compose` role, and role defaults are only in scope inside their own role — it
is not reliably defined at the call site.

When a `source` points into another role's directory, that role must run **first**.

## SMB env names are shared on purpose

The four credentials are written to the host's shared `.env` as `SMB_STORAGE_*` —
deliberately the same names `docker_compose_tdarr` uses. The `.env` is one file per host
(see `roles/docker_compose/README.md`), so on a host running both, whichever role runs last
wins and both callers must pass the same credentials.
