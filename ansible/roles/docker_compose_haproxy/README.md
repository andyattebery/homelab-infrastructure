# docker_compose_haproxy

Deploys one [HAProxy](https://www.haproxy.org/) HTTP load balancer as a compose stack. It spreads
requests over a list of servers, and stops sending them to a server that fails its health check. A
host can run several, one per `haproxy_name`.

## Status: Production

## Inputs

Required. The role asserts each one before it deploys anything (`tasks/validate.yaml`).

| Name | Default | If it is wrong |
| --- | --- | --- |
| `haproxy_name` | none | Lower-case letters, digits and dashes. It names the container, its compose file `docker-compose-haproxy-<name>.yaml`, its config directory `haproxy-<name>/` and HAProxy's frontend. Clients reach the balancer by this name. Two entries with one name on a host overwrite each other. |
| `haproxy_port` | none | The port HAProxy listens on inside the container, and the one clients use. It must be above 1023: the image runs as the unprivileged `haproxy` user, which can't bind a lower port. |
| `haproxy_servers` | none | A list of `host:port`. Each host is resolved through Docker's DNS, so a container on a shared network and a name the host's resolvers know both work. The host part names the server in the config and the logs, so give each host one entry. A server that never passes its health check never gets a request. |
| `haproxy_networks` | none | External Docker networks the container joins. Its clients must be on one of them, since no port is published. A network that doesn't exist fails `up`, so the stack that creates it must run first. |

Optional:

| Name | Default | If it is wrong |
| --- | --- | --- |
| `haproxy_image` | `docker.io/library/haproxy:3.4-alpine` | 3.4 is an LTS branch, and `templates/haproxy.cfg.j2` is written against its manual. Another branch may reject or change a keyword, and then HAProxy doesn't start. |
| `haproxy_balance` | `roundrobin` | Any of HAProxy's `balance` algorithms; a misspelled one stops HAProxy from starting. `roundrobin` uses each server in turn. `leastconn` picks the server with the fewest connections, in turn among equals. |
| `haproxy_health_check_path` | `/` | Each server gets `GET <path>` and must answer 2xx or 3xx. A path no server answers takes every server out, and HAProxy then answers 503 to every request. |
| `haproxy_timeout_connect` | `5s` | How long HAProxy waits to connect to a server. Too short on a slow network, and connections fail and are retried. |
| `haproxy_timeout_server` | `1m` | How long a server may stay silent, including while it works on a request. Shorter than the slowest request, and HAProxy answers 504 while the server is still working. |
| `haproxy_timeout_client` | `1m` | How long a client may stay silent. The example sets it to the server timeout. |

## Required globals

Inherited from `docker_compose`: `timezone`, `domain_name`, `lang_two_letter`,
`language_region_with_underscore`, and `docker_compose_dst_data_directory_path`. The config is
written to `<data>/haproxy-<name>/haproxy.cfg`, mode `0644`, and that directory is mounted
read-only at `/usr/local/etc/haproxy`, where the image reads `haproxy.cfg`.

## Example

From the calling playbook, which balances Immich's machine learning over two hosts:

```yaml
- role: docker_compose_haproxy
  vars:
    haproxy_name: immich-machine-learning-lb
    haproxy_port: 3003
    haproxy_networks: [immich]
    haproxy_servers:
      - "ml-host-1:3003"
      - "ml-host-2:3003"
    # Requests last seconds, so the less-busy node gets the next one.
    haproxy_balance: leastconn
    haproxy_health_check_path: /ping
    # A host's first request downloads its models, which takes minutes.
    haproxy_timeout_client: 15m
    haproxy_timeout_server: 15m
```

Immich's server, on the `immich` network, then uses `http://immich-machine-learning-lb:3003` as
its ML URL.

## Reached only over Docker networks

No port is published on the host. A container on one of `haproxy_networks` reaches the balancer at
`http://<haproxy_name>:<haproxy_port>`; the LAN can't reach it at all.

## Every request is balanced

HAProxy runs in HTTP mode, so it picks a server for each request, not for each connection. A client
that keeps one connection open, as an HTTP client's pool does, still has its requests spread. The
option that would pin them to one server, `prefer-last-server`, isn't set (HAProxy 3.4
`doc/configuration.txt`).

## Health checks, retries and DNS

- **Each server is checked every 2 s,** HAProxy's default. Three failed checks in a row take it
  out, and two passes bring it back. So a dead server stops getting requests within about 6 s.
- **A request whose connection to a server fails is retried,** the last time on another server
  (`option redispatch`).
- **With no server up, HAProxy answers 503.** A client that checks the balancer's health sees that,
  and can fall back to a URL of its own.
- **Server names are resolved at run time** through the container's `/etc/resolv.conf`, which is
  Docker's DNS (`parse-resolv-conf`).
  - HAProxy starts even when a name doesn't resolve yet (`init-addr last,libc,none`). That server
    stays out until it does.
  - A changed address is picked up while HAProxy runs.

## A config change restarts it

`docker_compose` restarts the container when `haproxy.cfg` changes (`service_name_to_restart`), so
requests in flight at that moment can fail.

## Removing one

Dropping its playbook entry removes nothing. Its compose file stays in the compose directory, and
`dc` and `dcup` keep including it, since they glob `docker-compose*.y*ml`. To remove it, run this
from the compose directory:

```sh
docker compose --file docker-compose-haproxy-<name>.yaml --env-file .env down
```

Then delete that file and `<data>/haproxy-<name>/`.

## Nothing outside the host is told about it

The container has no Traefik or `dsm.*` labels, and `docker_compose_traefik` routes only containers
that opt in (`exposedbydefault=false`).

## `.env` names this role claims

None. The compose file uses only `docker_compose`'s `DOCKER_DATA_DIRECTORY`.
