# github_release_install

Idempotently installs an executable from a GitHub release. Stat's the
installed binary, runs its version command, compares to the latest
release tag, and only downloads + installs when missing or outdated.
Does not handle services, users, configs — caller's responsibility.

## Inputs

Required:

- `github_release_install_repo` — `owner/repo` (e.g. `henrygd/beszel`).
- `github_release_install_asset_patterns` — dict keyed by
  `ansible_architecture`, value is a substring used to identify the
  desired asset filename in the release's `assets[*].name` list.
  Substring match handles assets whose names contain the version
  number (you don't need to predict it).
- `github_release_install_archive_type` — one of `deb`, `tarball`,
  `binary`.
- `github_release_install_binary_path` — final on-disk path of the
  executable. Used as install destination for `binary` and `tarball`,
  and as the path the idempotency check stat's / version-checks.

Required when `archive_type == 'tarball'`:

- `github_release_install_binary_in_archive` — path of the binary
  inside the extracted archive (relative to the archive root).

Optional:

- `github_release_install_version_command` — default
  `{{ github_release_install_binary_path }} --version`. Override when
  the binary uses a non-standard flag (e.g. `-V`, `-v`).
- `github_release_install_version_regex` — default
  `'([0-9]+\.[0-9]+\.[0-9]+)'`. Capture group 1 is compared
  string-equal against `releases/latest.tag_name` with leading `v`
  stripped.

## Examples

### deb

```yaml
- name: Install topgrade
  ansible.builtin.include_role:
    name: github_release_install
  vars:
    github_release_install_repo: topgrade-rs/topgrade
    github_release_install_asset_patterns:
      x86_64: "_amd64.deb"
      aarch64: "_arm64.deb"
    github_release_install_archive_type: deb
    github_release_install_binary_path: /usr/local/bin/topgrade
    github_release_install_version_command: "/usr/local/bin/topgrade -V"
```

### tarball

```yaml
- name: Install beszel-agent
  ansible.builtin.include_role:
    name: github_release_install
  vars:
    github_release_install_repo: henrygd/beszel
    github_release_install_asset_patterns:
      x86_64: "beszel-agent_linux_amd64.tar.gz"
      aarch64: "beszel-agent_linux_arm64.tar.gz"
    github_release_install_archive_type: tarball
    github_release_install_binary_in_archive: beszel-agent
    github_release_install_binary_path: /usr/local/bin/beszel-agent
    github_release_install_version_command: "/usr/local/bin/beszel-agent -v"
```

### binary

```yaml
- name: Install scrutiny-collector
  ansible.builtin.include_role:
    name: github_release_install
  vars:
    github_release_install_repo: AnalogJ/scrutiny
    github_release_install_asset_patterns:
      x86_64: "scrutiny-collector-metrics-linux-amd64"
      aarch64: "scrutiny-collector-metrics-linux-arm64"
    github_release_install_archive_type: binary
    github_release_install_binary_path: /opt/scrutiny/bin/scrutiny-collector-metrics-linux-amd64
```
