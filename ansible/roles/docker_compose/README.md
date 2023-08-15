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

## Sets facts
- docker_compose_gid
- docker_compose_uid
- docker_compose_dst_directory_path