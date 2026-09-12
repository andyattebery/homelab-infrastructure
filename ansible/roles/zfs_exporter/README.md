# zfs_exporter

Installs [pdf/zfs_exporter](https://github.com/pdf/zfs_exporter) from its GitHub
release and runs it as a systemd service, exporting ZFS pool and dataset metrics
for Prometheus.

## Status: Production

Three callers, all storage hosts.

## Inputs

Required: none. Every input has a working default.

Optional:

- `zfs_exporter_bin_path` — default `/usr/local/bin/zfs_exporter`. Where the
  binary is installed and what the unit executes.

  **Wrong value:** the unit's `ExecStart` and the install path come from this one
  variable, so they cannot disagree — but point it somewhere not on the root
  filesystem and the service fails to start after a reboot that mounts late.

- `zfs_exporter_web_listen_address` — default `":9134"`, the project's own
  default port, on all interfaces.

  **Wrong value:** Prometheus scrapes a port nothing is listening on and the
  target goes down; nothing on the host reports a problem, because the exporter
  is running perfectly well on the other port.

## Example

From `playbook-backup-01.yaml`:

```yaml
- name: Configure zfs_exporter
  ansible.builtin.import_role:
    name: zfs_exporter
```

The other two callers use the `roles:` keyword form. No caller overrides either
input.

## The in-archive path is built from the release version

This is the role's one real trap, and the reason it looks more complicated than
the other exporter roles.

`pdf/zfs_exporter` tarballs extract to a directory named after the release *and*
the architecture:

```
zfs_exporter-2.3.12.linux-amd64/zfs_exporter
```

So `install.yaml` fetches the release tag itself before delegating to
`github_release_install`, purely to construct that path.

**Consequence: two unauthenticated GitHub API calls per run**, one here and one
inside `github_release_install`. Unauthenticated GitHub allows 60 per hour per
source IP. There is also a narrow race — a release cut between the two calls
leaves `zfs_exporter_version` describing one release and the selected asset
another, and the install fails on a path that is not in the archive. Re-running
fixes it.

## Two in-archive paths, and why

`install.yaml` sets both:

```yaml
github_release_install_binary_in_archive: "zfs_exporter-{{ zfs_exporter_version }}.{{ zfs_exporter_arch_suffix | trim }}/zfs_exporter"
github_release_install_binary_in_archive_pattern: "zfs_exporter-${VERSION}.{{ zfs_exporter_arch_suffix | trim }}/zfs_exporter"
```

They are not redundant. The first is what **this playbook run** extracts, resolved
against whatever release was current when it ran. The second goes into the env
file that `github_release_install` writes for `github-release-update`, the
on-host updater that runs between playbook runs.

A literal is correct for exactly one release. An updater reading the first line
would look for 2.3.12's directory inside 2.3.13's tarball and fail on every
release after the one that deployed it. `${VERSION}` is substituted by the script
at run time.

**The architecture is deliberately *not* a placeholder.** It stays a Jinja
expression and is resolved when the env file is written, because that file is
per-host and therefore already correct. Hardcoding `linux-amd64` there — or
inventing a `${ARCH}` — would be a second source of truth for something already
known, and silently wrong on the aarch64 hosts `_asset_patterns` supports.

## Idempotency

Both `github_release_install` idempotency settings are left at their defaults, so
the role runs `zfs_exporter --version` and compares the semver it prints against
the release tag. That works because the binary reports a version that equals its
tag — unlike the jellyfin-ffmpeg callers, which need `use_tag_stamp`.

See `roles/github_release_install/README.md` for what that choice means.
