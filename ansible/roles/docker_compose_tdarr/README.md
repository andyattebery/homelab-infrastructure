# docker_compose_tdarr

Deploys a Tdarr **server**, a Tdarr **node**, or both, from one role. The server holds the
library and flow definitions; nodes do the transcoding and connect back to it.

Deploys no flows, plugins or test scripts — see "What this role does not deploy".

## Status: Production

## Inputs

Pick at least one, or the role does nothing:

- `docker_compose_tdarr_server` — default `false`. Deploys the server container.
- `docker_compose_tdarr_node` — default `false`. Deploys a worker node.

Node connection (node only):

- `docker_compose_tdarr_server_ip` — default `tdarr.{{ domain_name }}`.
- `docker_compose_tdarr_server_port` — default `8266`.
- `docker_compose_tdarr_node_name` — default `{{ inventory_hostname }}`.
- `docker_compose_tdarr_api_key` — default empty.

Workers (node only):

- `docker_compose_tdarr_transcode_gpu_workers` — default `0`.
- `docker_compose_tdarr_transcode_cpu_workers` — default `2`.
- `docker_compose_tdarr_healthcheck_gpu_workers` — default `0`.
- `docker_compose_tdarr_healthcheck_cpu_workers` — default `1`.

GPU — pick the one matching the host:

- `docker_compose_tdarr_nvidia_gpu` — default `false`.
- `docker_compose_tdarr_nvidia_gpu_wsl` — default `false`. WSL2 library passthrough; needs
  `docker_compose_tdarr_nvidia_gpu` as well.
- `docker_compose_tdarr_intel_gpu` — default `false`.

Storage:

- `docker_compose_tdarr_hardlink_disks` — default `[]`. Per-disk CIFS mounts at
  `/media-raw/<disk>`, mounted **without** `noserverino` so inode numbers are stable and
  hardlink detection works. The merged pool at `/media` uses `noserverino` and cannot be
  used for that. Leave empty if no flow manipulates hardlinks.
- `docker_compose_tdarr_transcode_cache_path` — default `/transcode_cache`.

Other:

- `docker_compose_tdarr_image_tag` — default `latest`.
- `docker_compose_tdarr_custom_ffmpeg_path` — host directory mounted at `/ffmpeg`. Needed
  only when the container's bundled ffmpeg lacks a required encoder or flag.

Server deployment also needs the host's `smb_*` credentials in scope, for the CIFS volume
holding the media library.

## Example

Server, on the host with the library:

```yaml
- role: docker_compose_tdarr
  vars:
    docker_compose_tdarr_server: true
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
    docker_compose_tdarr_node: true
    docker_compose_tdarr_nvidia_gpu: true
    docker_compose_tdarr_nvidia_gpu_wsl: true
    docker_compose_tdarr_transcode_gpu_workers: 3
    docker_compose_tdarr_transcode_cpu_workers: 0
    docker_compose_tdarr_custom_ffmpeg_path: /opt/ffmpeg-btbn/bin
```

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
