# podman_quadlet

Deploys a single Podman Quadlet unit — `.container`, `.network`, `.volume`, `.pod`,
`.image`, `.build` or `.artifact` — into `/etc/containers/systemd/`, creates the host
directories its `Volume=` lines reference, pulls its image, and manages the generated
service.

The Podman equivalent of the `docker_compose` role: one call deploys one unit.

## Status: Production

## Inputs

Required:

- `podman_quadlet_src` — path to the unit file, relative to the playbook directory. A
  `.j2` suffix means the file is templated and the suffix is dropped at the destination;
  anything else is copied verbatim.

Optional:

- `podman_quadlet_volume_owner` / `_group` — default `ansible_user`. Owner applied to every
  host directory created for a `Volume=` bind mount.
- `podman_quadlet_config_files` — default `[]`. Files templated alongside the unit. Each
  entry: `src`, `dest`; optional `mode`, and `restart_service: true` to restart the unit
  when that file changes.
- `podman_quadlet_service_state` — default `started`. Set `stopped` to deploy a unit
  without running it.
- `podman_quadlet_service_enabled` — default unset. Unset means "enable the types that have
  an `[Install]` section, leave the rest alone". An explicit `true`/`false` always wins.

## Example

```yaml
- name: Deploy llama-swap quadlet
  tags: llama-swap
  ansible.builtin.include_role:
    name: podman_quadlet
    apply:
      tags: llama-swap
  vars:
    podman_quadlet_src: files/<host>/llama-swap.container.j2
    podman_quadlet_volume_owner: root
    podman_quadlet_volume_group: root
    podman_quadlet_config_files:
      - src: files/<host>/llama-swap.yaml.j2
        dest: /var/data/llamacpp/config/llama-swap.yaml
        # Read once at startup, so a changed config does nothing until the unit restarts.
        restart_service: true
```

`apply:` is required when tagging an `include_role` — a tag on the include gates only the
include itself, not the tasks inside the role.

## Service naming

Quadlet derives the service name from the unit type. The role knows the mapping and asserts
on an unsupported extension rather than deploying something systemd will ignore:

| Unit | Generated service |
| --- | --- |
| `.container`, `.kube` | `<name>.service` |
| `.network` | `<name>-network.service` |
| `.volume` | `<name>-volume.service` |
| `.pod`, `.image`, `.build`, `.artifact` | `<name>-<type>.service` |

A `ServiceName=` line in the unit overrides all of this, and the role honours it.

## `enabled` is effectively a no-op

`podman-systemd.unit(5)`: the services Quadlet creates are transient, so they cannot be
`systemctl enable`d — the generator applies the `[Install]` section itself at generation
time. Their `UnitFileState` reads as `generated`, which Ansible treats as already-enabled,
so the task reports *ok* and changes nothing.

**Boot behaviour is controlled by `WantedBy=` in the unit file**, not by this role.

## Deliberately uninstalled units are left alone

If a unit exists, is not running, and has no `WantedBy`, the role reports it and leaves it
stopped rather than starting it. That combination only arises when an operator turned it
off on purpose — for example a GPU-arbitration script that removes the `[Install]` drop-in
to keep a container down. A playbook run must not silently undo that.

The check is deliberately narrow. It does **not** fire for a brand-new unit
(`LoadState=not-found`), so first deploys start normally; nor for a running unit, so
nothing live is ever left behind; nor for `.network`/`.volume` units, which are
`active (exited)` oneshots.

## Config-file restarts

Container config is read at start, so changing a file leaves the running container serving
the old copy. `restart_service: true` on a `podman_quadlet_config_files` entry restarts the
unit when that specific file changes. It is opt-in because not every config is read only at
startup.

The restart is skipped when the service was not already running — the deploy task has just
started it with the new config, so restarting again would be redundant, and a
deliberately-stopped unit must not be started as a side effect.
