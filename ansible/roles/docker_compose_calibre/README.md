# docker_compose_calibre

Deploys the LinuxServer Calibre image: the full Calibre desktop GUI in a browser, plus Calibre's
own content server, behind Traefik.

## Status: Production

## Inputs

All optional — the role deploys with no vars set, but with no access to anything but its own
`/config`.

| Name | Default | If it is wrong |
| --- | --- | --- |
| `calibre_config_directory` | `<data_dir>/calibre` | Mounted at `/config`. **The library lives here** (`Calibre Library/metadata.db`), not just settings. Point it at a path on a filesystem you back up, or accept that the library is not backed up. Pointing it at an empty directory starts Calibre with a fresh, empty library — it does not fail, so a typo looks like data loss. |
| `calibre_extra_mount_paths` | `[]` | Host paths bind-mounted at the **same path** inside the container. Empty means books can only arrive by upload through the browser. A path that does not exist on the host is **not** an error: Docker creates it as an empty root-owned directory and Calibre shows an empty tree, so a typo looks like an empty share. |
| `calibre_desktop_hostname` | `calibre` | Router for the desktop UI (container port 8080), before `.<domain_name>`. Also the router dashboard-services-manager advertises, so changing it changes the DNS record. |
| `calibre_server_hostname` | `calibre-server` | Router for the content server (container port 8081). DSM does **not** publish this one — see below. |
| `calibre_password` | `""` | Upstream `PASSWORD` — sets a password for the GUI. Empty means no password, which is what has been running: anyone who can reach Traefik gets a desktop session with write access to every path in `calibre_extra_mount_paths`. |
| `calibre_cli_args` | `""` | Upstream `CLI_ARGS` — start arguments passed to calibre. Empty leaves the image's defaults. |

## Required globals

Inherited from `docker_compose`: `timezone`, `domain_name`, `lang_two_letter`,
`language_region_with_underscore`, and `docker_compose_dst_data_directory_path` for the default
config path.

## Example

From `playbook-nas-01.yaml`:

```yaml
- role: docker_compose_calibre
  vars:
    calibre_extra_mount_paths:
      - /mnt/storage
  tags: calibre
```

## Two routers, one container

The image serves two different things on two ports: the desktop GUI on 8080 and Calibre's own
content server on 8081. Both are declared as explicit Traefik routers, which also disables
Traefik's `defaultRule` for this container — so the hostnames come from `calibre_desktop_hostname`
and `calibre_server_hostname`, not from the compose service name.

**The content server is off until you turn it on.** Upstream: port 8081 "needs to be enabled in
gui settings first". Until then `calibre_server_hostname` resolves and Traefik returns a gateway
error, which reads like a routing problem and is not one.

dashboard-services-manager can only advertise one hostname per container. Left to itself it picks
nondeterministically and the DNS rewrite flaps between the two, so `dsm.traefik.router=calibre`
pins it to the desktop router. The consequence is that **the content server hostname gets no DNS
record from DSM** — it needs a static entry in the network inventory
(`network-inventory/network_hosts_inventory.yaml.tpl`, `services:` block) pointing at whichever
host runs this role.

## Extra mounts are same-path and rslave

Entries in `calibre_extra_mount_paths` are mounted at the identical path inside the container.
That is deliberate: Calibre stores absolute paths in dialogs and its file browser, and matching
them to the host means what you see over SMB is what you type into Calibre.

They use the long `type: bind` syntax with `propagation: rslave` rather than the short
`host:container` form, because the intended targets are real mounts — a mergerfs pool is FUSE, and
a plain bind mount of one captures the directory as it looked at container start and goes stale if
the host remounts it.

These must be paths **local to the host running this role**. A CIFS/SMB mount would technically
bind in, but Calibre's add/convert paths rename and hardlink, and neither behaves over SMB.

## `.env` names this role claims

`CALIBRE_CONFIG_DIRECTORY`, `CALIBRE_PASSWORD`, `CALIBRE_CLI_ARGS`. The `.env` is shared by every
stack on the host, so those three names are taken host-wide once this role runs.

## Differences from upstream's example

Upstream's compose also sets `shm_size: "1gb"` and publishes ports 8080/8081/8181. Neither is
carried here, because neither was in the docker-01 deployment this role was lifted from and both
would be untested changes:

- **No `shm_size`**, so the container gets Docker's default 64 MB `/dev/shm`. That has been enough
  for this library. Raise it if the GUI starts dying under large covers or conversions.
- **No published ports.** Everything goes through Traefik on the `traefik` network, so nothing is
  reachable on the host's own ports. Port 8181 (the desktop GUI over HTTPS) is unused — Traefik
  terminates TLS.
