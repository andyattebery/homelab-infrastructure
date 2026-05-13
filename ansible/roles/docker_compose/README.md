# docker-compose

## Variables

| Name                                   | Required? | Default             |Description              |
|----------------------------------------|-----------|---------------------|-------------------------|
| docker_compose_dst_base_directory_path | no        | /opt/docker_compose |                         |
| docker_compose_dst_directory_name      | no        | UUID                |                         |
| container_user_id                      | no        | root                |                         |
| container_user_gid                     | no        | root                |                         |
| timezone                               | yes       |                     |                         |
| domain_name                            | yes       |                     |                         |
| docker_compose_envs (array)            | no        |                     |                         |
| docker_compose_src_config_files (list) | no        | `[]`                | Per-file copy via `ansible.builtin.template` (renders `.j2`). Each entry: `src_file_path`, `dst_relative_file_path`, optional `mode`, `service_name_to_restart`, `run_command`. |
| docker_compose_src_config_dirs (list)  | no        | `[]`                | Recursive directory copy via `ansible.builtin.copy` (does NOT render `.j2`). Each entry: `src_dir_path`, `dst_relative_dir_path`, optional `mode`, `directory_mode`, `service_name_to_restart`. |

## Sets facts
- docker_compose_gid
- docker_compose_uid
- docker_compose_dst_directory_path