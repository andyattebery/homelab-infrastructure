# docker_compose_swarmui

Deploys [SwarmUI](https://github.com/mcmonkeyprojects/SwarmUI), a front-end that drives
ComfyUI as a backend. Clones the repository and builds it on the host — upstream publishes
no image, only a Dockerfile inside the repo.

Split out of `docker_compose_comfyui`, which used to deploy both.

## Status: Production

## Inputs

- `swarmui_repo` — default upstream GitHub URL.
- `swarmui_version` — default `master`. Passed to `ansible.builtin.git` as `version`.
- `swarmui_extra_networks` — default `[]`. Extra Docker networks to join beyond `traefik`.
  Each must already exist.
- `swarmui_models_path` — default `<data_dir>/swarmui/Models`. Host path mounted at
  `/SwarmUI/Models`. Point it at another app's model store to share one download; the role
  creates the directory either way, so it never depends on another role having run first.

## Example

```yaml
- role: docker_compose_swarmui
  vars:
    swarmui_extra_networks: [openwebui]
    # Share ComfyUI's model store rather than downloading a second copy.
    swarmui_models_path: "{{ docker_compose_dst_data_directory_path }}/comfyui/models"
```

## Deploy before ComfyUI when sharing extension nodes

SwarmUI ships ComfyUI custom nodes under
`src/BuiltinExtensions/ComfyUIBackend/ExtraNodes/`, which ComfyUI mounts through
`comfyui_extra_custom_nodes`. Those are compose-relative paths into **this role's clone**,
so this role has to run first or the mount source will not exist.

That works because both roles deploy into the same compose directory — a host-level
setting, not something either role chooses.

## The clone is the build context

`ansible.builtin.git` puts the repository beside the compose file, and the compose `build:`
block points at it with `dockerfile: launchtools/StandardDockerfile.docker`. Deleting the
clone breaks the build, not just an update.

`docker_compose_should_pull` is `false` for the same reason: there is no image to pull.
