# github_release_install

Idempotently installs an executable from a GitHub release. Stat's the
installed binary, runs its version command, compares to the latest
release tag, and only downloads + installs when missing or outdated.
Does not handle services, users, configs — caller's responsibility.

For builds whose version output can never equal the release tag, see
`github_release_install_use_tag_stamp` under Optional.

The extraction directory is removed after every install attempt,
successful or not. `unarchive` extracts the whole archive rather than
just the requested binary, and on a host with a `tmpfs` `/tmp` that is
RAM held until reboot.

## Inputs

Required:

- `github_release_install_repo` — `owner/repo` (e.g. `henrygd/beszel`).
- `github_release_install_asset_patterns` — dict keyed by
  `ansible_facts['architecture']`, value is a substring used to identify the
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
  string-equal against the release `tag_name` with leading `v`
  stripped.
- `github_release_install_release_tag` — default empty, meaning
  `releases/latest`. Set to a tag to pin, e.g.
  `autobuild-2026-05-31-13-22`.

  Pinning **requires** matching idempotency settings, because the
  default `version_command` asks the binary for a semver that a
  pinned tag may not contain:

  ```yaml
  github_release_install_release_tag: autobuild-2026-05-31-13-22
  github_release_install_version_command: "echo autobuild-2026-05-31-13-22"
  github_release_install_version_regex: "(.*)"
  ```

  That makes the comparison "pinned tag vs release `tag_name`", which
  is stable. Leave the defaults in place and the role re-downloads on
  every run, or fails to match at all.

  The same pattern tracks a rolling tag such as `latest`:
  `version_command: "echo latest"` with `version_regex: "(.*)"`.

  **What this idiom cannot do:** both sides of the comparison derive
  from the same string, so it is idempotent but **never reinstalls when
  the pinned tag is bumped** — the values still match and the binary
  still exists. That is harmless for a genuinely rolling tag that never
  changes its name, and silently wrong for a pin you intend to move.
  Use the tag stamp below when the tag is a real version.

- `github_release_install_use_tag_stamp` — default `false`. When true, a
  stamp is written to a file beside the binary and compared against the
  release on the next run. The version command is not executed at all in
  this mode. The stamp holds the release `tag_name` **and** the digest of
  the asset it resolved to:

  ```
  v8.1.2-2+nvenc-n13.0.19.1 sha256:727ea81a7051034a8f756f2ea660c40228...
  ```

- `github_release_install_tag_stamp_path` — default
  `{{ github_release_install_binary_path }}.release-tag`.

- `github_release_install_symlink` — default `false`. When true, links the
  installed binary onto PATH.

  `_binary_path` is often deliberately off PATH: a directory bind-mounted
  wholesale into a container, or one holding a build that must not shadow the
  distro's. That is the right place for the file and the wrong place for a
  human who wants to run it. This adds a link without moving the install.

  **Left `false`, the binary is reachable only at `_binary_path`** — which is
  all a container mount or an explicit `ffmpegPath` ever needs. Off by default
  because putting a name into `/usr/local/bin` is a decision about the host's
  PATH, not a detail of installing a binary.

  The link is refreshed on every run, not only when the binary is reinstalled,
  so one deleted by hand comes back. It will **not** replace a regular file
  already at the target: that fails the run rather than silently clobbering
  something another package owns. Point `_symlink_path` elsewhere, or remove
  the file deliberately, if that happens.

  **Skipped entirely when the link would point at the binary itself.** Several
  callers install straight into `/usr/local/bin`, and there the default
  `_symlink_path` resolves to `_binary_path`. Setting this true on one of those
  is a no-op rather than an error: the binary is already on PATH, which is all
  the option was asking for.

  ```yaml
  github_release_install_symlink: true
  ```

- `github_release_install_symlink_path` — default
  `/usr/local/bin/{{ github_release_install_binary_path | basename }}`. Set it
  to put the link somewhere else, or to give it a different name from the
  installed file.

  Use the stamp when the binary's own version output **cannot** equal
  the release tag, no matter the regex — typically a fork that appends
  a suffix upstream knows nothing about. Example: a build reporting
  `8.1.2-Jellyfin` published under tag `v8.1.2-2+nvenc-n13.0.19.1`.
  No capture group over the former can produce the latter, so the
  default comparison makes `needs_install` true on every run.

  Unlike `echo <tag>`, the stamp compares what is *actually installed*
  against what the release *now offers*, so bumping a pin — or
  publishing a new release while following `latest` — does reinstall.

  ```yaml
  github_release_install_use_tag_stamp: true
  ```

  The stamp is written as the **last** step of the install, so a failed
  download or extract leaves the previous stamp in place and the next
  run retries rather than believing itself converged.

  It compares the raw `tag_name`, not the `v`-stripped form the version
  command path uses.

  **Why the digest is in there.** A tag is not an identity. A release can
  have its assets replaced in place, under a tag that never changes, and
  some projects do exactly that — re-uploading a rebuilt binary onto the
  existing release rather than cutting a new one. A tag-only stamp then
  matches forever, and the host keeps a build the release no longer
  offers, with no run ever correcting it. Not hypothetical: it left one
  host three days behind on a release whose assets moved, and nothing in
  the output said so, because "no change" is what converged looks like.

  Including the asset digest makes the stamp answer *which bytes did I
  install*, which is the question idempotence actually needs. `digest` is
  a recent addition to the releases API; when it is absent the asset `id`
  is used instead, which also changes on re-upload. That fallback is
  explicit because an unguarded lookup would evaluate to empty and
  quietly collapse the comparison back to tag-only — reintroducing the
  bug while looking like a fix.

  Both sides read one `set_fact`, `github_release_install_stamp_value`,
  computed in its own task because a fact is not visible in the `vars` of
  the task that sets it. Two expressions that must agree are two
  expressions someone can edit apart.

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
