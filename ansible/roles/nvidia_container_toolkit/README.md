# nvidia_container_toolkit

Adds NVIDIA's `libnvidia-container` apt repository, installs `nvidia-container-toolkit`, and
registers the `nvidia` runtime with Docker so containers can request GPUs via
`runtime: nvidia` or `deploy.resources.reservations.devices`.

Does **not** install the NVIDIA driver — see "What this role does not do".

## Status: Production

## Inputs

All optional; the defaults are correct for every current caller.

- `nvidia_container_toolkit_gpgkey_url` — default
  `https://nvidia.github.io/libnvidia-container/gpgkey`. Passed to
  `deb822_repository` as `signed_by`, which downloads it to
  `/etc/apt/keyrings/<name>.asc` and references it from the `.sources` by path.
  A wrong or unreachable URL fails the play at that task; apt would otherwise
  reject the repo as unsigned.
- `nvidia_container_toolkit_apt_source_name` — default
  `nvidia-container-toolkit`. **This is the filename.** `deb822_repository`
  derives both `/etc/apt/sources.list.d/<slug>.sources` and
  `/etc/apt/keyrings/<slug>.asc` from it and offers no separate filename
  parameter. Keep it lowercase with only hyphens and digits: the slug rule
  differs between ansible-core 2.20 and 2.21, and names in that shape are
  identical under both.
- `nvidia_container_toolkit_apt_channel` — default `stable`. Set to
  `experimental` for pre-release toolkit builds. NVIDIA publishes both channels
  under the same layout, so this is a one-word change.
- `nvidia_container_toolkit_arch_map` — default maps `x86_64` → `amd64` and
  `aarch64` → `arm64`. An architecture not in the map falls through to
  `ansible_facts['architecture']` verbatim, which will not match a published
  directory and shows up as a 404 on `apt update`.
- `nvidia_container_toolkit_apt_repo_url` — built from the channel and the mapped
  architecture. Override it whole only to point at a mirror.
- `nvidia_container_toolkit_docker_config_path` — default `/etc/docker/daemon.json`. Must be the
  file `nvidia-ctk runtime configure --runtime=docker` actually writes. If it points somewhere
  else, both checksums come back empty, they compare equal, and Docker is **never** reloaded —
  the runtime silently fails to register on a fresh host.

### Inputs that no longer exist

`nvidia_container_toolkit_keyring_path` and
`nvidia_container_toolkit_apt_sources_list_path` are **gone**.
`deb822_repository` derives both paths from the source name, so they could only
have disagreed with reality. A playbook still setting either will not fail — the
variable is simply ignored — so grep for them when adopting this version.

`nvidia_container_toolkit_apt_repo_url` also changed shape: it used to be a
literal URL ending in `$(ARCH)`, and the previous README told callers to override
it with `experimental/deb/$(ARCH)`. That instruction no longer applies; use
`nvidia_container_toolkit_apt_channel: experimental` instead.

## Example

From `playbook-media-01.yaml`:

```yaml
- role: nvidia_container_toolkit
```

From `playbook-wsl-01.yaml`:

```yaml
- name: Install NVIDIA Container Toolkit
  ansible.builtin.include_role:
    name: nvidia_container_toolkit
```

Both run it after `geerlingguy.docker`, which is required — the role reloads `docker.service`
and expects the `docker` group and daemon config to exist.

## Reload, not restart

The final task is `systemd: state=reloaded`, deliberately. Docker's `dockerd` reference lists
`runtimes` and `default-runtime` among the options that "can be reconfigured when the daemon is
running without requiring to restart the process" via `SIGHUP`. Registering the runtime
therefore costs no container downtime.

This role previously ended in an unconditional `state: restarted`, which stopped every container
on the host on every play run, whether or not the runtime config had changed.

**Requires `docker.service` to declare `ExecReload`.** The upstream docker-ce unit does
(`ExecReload=/bin/kill -s HUP $MAINPID`); confirm with `systemctl show docker -p CanReload`. A
unit without it makes `systemctl reload` fail, which fails the play.

## Why the change detection is a checksum bracket

`nvidia-ctk runtime configure` rewrites the daemon config in place and is idempotent in effect,
but it is a `command:` — Ansible cannot tell whether it changed anything. It does have a
`--dry-run` flag, but no documented stdout contract, so parsing its output would be a guess
about a format that can change between toolkit releases.

Instead the config file is `stat`-ed before and after and the checksums compared.
`ansible.builtin.stat` returns a sha1 `checksum` by default for regular files and omits the key
entirely when the path does not exist, hence the `| default('')` on both sides: a config that
did not exist before and does after compares unequal, which is the correct answer.

## Not a handler

The reload is an inline task with a `when:`, not a `notify:` + handler. Handlers notified from a
play's `roles` section are flushed at the end of the `tasks` section — after every other role
has run. Callers invoke this role before any `docker_compose_*` role, so a handler would mean a
first provisioning run deploys `runtime: nvidia` containers against a daemon that has not yet
loaded the runtime. Ordering matters more than handler deduplication here.

## What this role does not do

**It does not install or manage the NVIDIA driver**, and it assumes one is already present.
`nvidia.github.io/libnvidia-container` is a *different* apt repository from
`developer.download.nvidia.com/compute/cuda/...`; using the toolkit does not pull the host into
the CUDA repo for drivers.

The driver is `roles/nvidia_driver`, which must run **before** this role. Callers that do not use
it leave the driver to `apt` on the host; either way this role only assumes one is there. See
`docs/media-01-nvidia-driver.md` for the package-set reasoning.

## Why the architecture is resolved by Ansible, not `$(ARCH)`

NVIDIA publishes the repository as `…/stable/deb/$(ARCH)`, and apt expands
`$(ARCH)` in the one-line `.list` format. `sources.list(5)` documents that
substitution for the **suite** field and says nothing about `URIs:` in the deb822
format, so carrying it across would have been a bet on undocumented behaviour
that fails as a 404 on every index.

The architecture is therefore templated here. Both published paths were checked
directly rather than assumed:

    https://nvidia.github.io/libnvidia-container/stable/deb/amd64/InRelease  -> 200
    https://nvidia.github.io/libnvidia-container/stable/deb/arm64/InRelease  -> 200

## What the migration removes from a long-lived host

The file this role used to write is not the file on an existing host. A host set
up by following NVIDIA's install docs by hand carries their **stock** published
`.list`, which enables a second, legacy `stable/ubuntu18.04/$(ARCH)` suite
alongside the current one. Deleting the `.list` removes both.

The signing key also moves out of `/etc/apt/trusted.gpg.d/`, where it was trusted
for **every** repository on the host, into `/etc/apt/keyrings/` where it signs
only this one.

Both removals are mandatory rather than cosmetic: `deb822_repository` writes
`<name>.sources`, so leaving the `.list` in place means two files defining the
same repository — "configured multiple times" on every `apt update`, or a
`Signed-By` conflict.

Verified in `ansible/tests/apt-sources/verify-nvidia.yml`, which seeds NVIDIA's
stock two-line file verbatim before running the role so the cleanup assertions
cannot pass vacuously, and asserts the toolkit actually installs from
`nvidia.github.io` on both amd64 and arm64.
