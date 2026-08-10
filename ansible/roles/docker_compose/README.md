# docker_compose

Deploys one Docker Compose stack: renders the compose file, merges the host's shared
`.env`, copies config files and directories, then optionally pulls and brings it up.

Almost every other `docker_compose_*` role wraps this one via `include_role`. It does not
manage the Docker daemon, users, or networks — the caller's compose file does that.

## Status: Production

## Required input

| Name | Notes |
| --- | --- |
| `docker_compose_src_file_path` | Path to the compose file, relative to the playbook directory. **Always rendered through `ansible.builtin.template`**, so it renders Jinja whether or not it is named `.j2`. |

## Required globals

From `group_vars/all/vars.yaml`: `timezone`, `domain_name`, `lang_two_letter`,
`language_region_with_underscore`. All four are written into every stack's `.env`.

Optional: `tailscale_tailnet` — when defined it is added as `TAILSCALE_TAILNET`.

## Variables

| Name | Default | Notes |
| --- | --- | --- |
| `docker_compose_dst_directory_path` | `/opt/docker-compose` | Where compose files and `.env` are written. Also `set_fact`-ed — see Facts. |
| `docker_compose_dst_data_directory_path` | = `dst_directory_path` | Where config files/dirs and container data live. Exposed to compose as `DOCKER_DATA_DIRECTORY`. Set this per host when data belongs on a different filesystem from the compose files. |
| `docker_compose_dst_file_name` | source basename | **`.j2` is not stripped.** A `.j2` source deploys a `.j2` destination, which `files/dc` then cannot see because it globs `docker-compose*.y*ml`. Set explicitly for any `.j2` source. |
| `docker_compose_uid` / `_gid` | `ansible_non_become_user_id` / `_gid` | Owner of everything written. When those facts are missing the role includes `ansible_non_become_user_facts` to gather them. |
| `docker_compose_should_pull` | `true` | Pulls one service at a time, from `config --services`, to avoid the TLS handshake timeouts a parallel `compose pull` causes on a large stack. Scoped by `--file` to this role's own compose file. Set `false` for stacks whose services are `build:`-only. |
| `docker_compose_should_run_up` | `true` | |
| `docker_compose_should_prune` | `false` | `docker system prune --all --force` after `up`. |
| `docker_compose_copy_scripts` | `true` | Installs the `dc` and `dcup` helpers into `/usr/local/bin`. |
| `docker_compose_up_command` | `<base> up --detach` | Override to add `--build`, `--wait`, `--remove-orphans`. |
| `docker_compose_envs` | `{}` | Merged over `docker_compose_default_envs` into the shared `.env`. |
| `docker_compose_src_config_files` | `[]` | Per file, via `ansible.builtin.template` — **renders Jinja**. Keys: `src_file_path`, `dst_relative_file_path`; optional `mode`, `service_name_to_restart`, `run_command`, `command_arguments`, `changed_when`. |
| `docker_compose_src_config_dirs` | `[]` | Recursive, via `ansible.builtin.copy` — **does not render Jinja**. Use for source trees that must land verbatim. Keys: `src_dir_path`, `dst_relative_dir_path`; optional `mode`, `directory_mode`, `service_name_to_restart`. |
| `docker_compose_docker_gid` | discovered | From `getent group docker`; the role asserts the group exists before continuing. |

`vars/main.yaml` derives `docker_compose_src_file_name`, `docker_compose_dst_file_path`,
`docker_compose_dst_env_path` and `docker_compose_base_command`. Those are internal — they
sit at a higher precedence than role defaults and are not meant as caller overrides.

## Example

```yaml
- name: Deploy searxng
  vars:
    docker_compose_src_file_path: files/docker-compose-searxng.yml
    docker_compose_envs:
      SEARXNG_DOMAIN_NAME: "searxng.{{ domain_name }}"
    docker_compose_src_config_files:
      - src_file_path: templates/settings.yml.j2
        dst_relative_file_path: searxng/settings.yml
        service_name_to_restart: searxng
  ansible.builtin.include_role:
    name: docker_compose
```

## Facts this role sets

| Fact | Set in | Consequence |
| --- | --- | --- |
| `docker_compose_docker_gid` | `tasks/main.yaml` | Looked up once per host per play. |
| `docker_compose_dst_directory_path` | `tasks/main.yaml` | Set to itself, which pins it as a **fact** for the rest of the play — above host_vars and play vars. Only role params (`vars:` on the `roles:` entry or `include_role`) and extra vars can override it after that. |
| `docker_compose_existing_envs` | `tasks/copy_env.yaml` | The `.env` as read from disk before merging. |
| `ansible_non_become_user_*` | indirectly | Via `ansible_non_become_user_facts`, when uid/gid are not already resolvable. |

## The shared `.env`

There is **one** `.env` per host, at `<dst_directory_path>/.env`, shared by every compose
file in that directory. `tasks/copy_env.yaml` reads it, merges the new values over it, and
rewrites it.

Two consequences worth knowing before adding variables:

- Env names are a **host-global namespace**. Two roles using the same name on one host must
  agree on its value, because whichever runs last wins for every stack on that host.
- Values **accumulate**. A variable a role stops setting is not removed from `.env`; it
  persists until the file is deleted.

## Alternate entrypoint

`tasks/upgrade.yaml` — pull, up, prune, without re-rendering the compose file or config.
Useful for a scheduled image refresh.
