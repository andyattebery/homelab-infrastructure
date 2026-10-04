# docker_compose_forgejo_runner

Deploys a Forgejo Actions runner (`forgejo-runner`) as a compose stack. The runner starts each
job's container on the host's own Docker.

## Status: WIP

## Inputs

Required. The role asserts that each is non-empty.

| Name | Default | If it is wrong |
| --- | --- | --- |
| `forgejo_runner_instance_url` | none | The Forgejo instance's URL, ending in `/`. If it's wrong, the runner can't connect and no job starts. |
| `forgejo_runner_uuid` | none | The UUID Forgejo shows when the runner is created ("Register it on one repository"). Without the matching UUID and token, the runner can't connect. |
| `forgejo_runner_token` | none | The token shown with that UUID. It ends up in `<data>/forgejo-runner/runner-config.yml`, mode `0600`. |
| `forgejo_runner_labels` | none | A list of `<name>:docker://<image>`. A job runs only on a runner with its `runs-on` label, in that label's image. If no workflow asks for the label, the runner sits idle. Pin the image by digest: the runner doesn't pull an image it already has (`container.force_pull: false`), so a bare tag stays at whatever it first pulled. |

Optional:

| Name | Default | If it is wrong |
| --- | --- | --- |
| `forgejo_runner_image` | `data.forgejo.org/forgejo/runner:13.2.0` | The runner itself. `templates/runner-config.yml.j2` is this version's `generate-config` output. A different version needs it regenerated ("Upgrading the runner"), or the config can miss new keys and keep removed ones. |
| `forgejo_runner_capacity` | `1` | How many jobs run at once, each in its own container on the host. |

## Required globals

Inherited from `docker_compose`: `timezone`, `domain_name`, `lang_two_letter`,
`language_region_with_underscore`, and `docker_compose_dst_data_directory_path`. The directory
`forgejo-runner/` under that path is the container's `/data`.

## Example

From the calling playbook, with `forgejo_runner_uuid` and `forgejo_runner_token` taken from the
host's vault:

```yaml
- role: docker_compose_forgejo_runner
  vars:
    forgejo_runner_instance_url: "https://forgejo.{{ domain_name }}/"
    forgejo_runner_labels:
      - "l4t-build:docker://docker.io/library/ubuntu:24.04@sha256:a853f94d226358a79c740cfc7bce0c289748f3fe3488d921d038ccd752c61b60"
  tags: forgejo_runner
```

## Register it on one repository

Create the runner in the settings of the repository whose workflows it runs: Settings → Actions →
Runners → Create new runner. Don't create it on a user, an org or the instance.
- Forgejo runs push workflows when a mirror syncs, and it reads `.github/workflows`. So a runner
  registered on a user who owns GitHub mirrors is offered every mirror's jobs.
- A repository-level runner "will execute workflows from the single repository" (Forgejo v15
  docs, "Register Forgejo Runner").

## Host-socket mode

The runner gets the host's Docker socket and starts each job's container there, on a network of
its own. That gives the runner root-equivalent control of the host's Docker. Anything that can
change its config or its image has the same control.

Jobs get neither: the config keeps `container.docker_host: "-"`, `container.privileged: false`
and `container.valid_volumes: []`. A job runs as root inside its container, but it can't reach the
host's Docker or mount the host's files.

Forgejo's docs also show a Docker-in-Docker setup. It needs a privileged container, and its daemon
listens on TCP without authentication (`-H tcp://0.0.0.0:2375 --tls=false`).

## Never run `forgejo-runner register` in `/data`

The config connects through `server.connections`, with the UUID and token from Forgejo's UI.
`forgejo-runner register` writes a `.runner` file instead, and with both present the daemon refuses
to start (runner 13.2.0, `internal/app/cmd/registration.go`). `register` has been deprecated since
runner 12.8.0.

## Upgrading the runner

`templates/runner-config.yml.j2` is the output of `forgejo-runner generate-config` from the
version in `forgejo_runner_image`, with the role's values swapped in. Its header lists them. For a
new version:
1. Regenerate it with `docker run --rm <image> forgejo-runner generate-config`.
2. Carry the same changes over.
3. Diff it against the old template before deploying.

## Nothing outside the host is told about it

- The container has no Traefik labels, and `docker_compose_traefik` routes only containers that
  opt in (`exposedbydefault=false`).
- dashboard-services-manager drops services that have no URL, and neither the runner nor its job
  containers has one.

## `.env` names this role claims

None. The compose file uses only `docker_compose`'s defaults: `PUID`, `PGID`, `DOCKER_GID` and
`DOCKER_DATA_DIRECTORY`.
