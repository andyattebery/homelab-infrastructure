# github_release_install

Idempotently installs an executable from a GitHub release. Stat's the
installed binary, runs its version command, compares to the latest
release tag, and only downloads + installs when missing or outdated.
Does not handle services, users, configs — caller's responsibility.

## Status: Production

Eight callers across the fleet. Also deploys `github-release-update` and
`github-release-update-all` to every host it runs on, so a binary can be
updated between playbook runs — see "The on-host updater" below.

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

- `github_release_install_name` — default
  `{{ github_release_install_binary_path | basename }}`. Names the env file the
  updater reads: `<config_dir>/<name>.env`.

  The eight callers in this repo produce eight distinct basenames, so no two can
  collide on one host. **Wrong value:** two installs share an env file, the
  second overwrites the first, and one binary silently stops being updated.

- `github_release_install_config_dir` — default
  `/etc/github-release-install`.

- `github_release_install_updater_path` — default
  `/usr/local/bin/github-release-update`.
- `github_release_install_updater_all_path` — default
  `/usr/local/bin/github-release-update-all`.

- `github_release_install_binary_in_archive_pattern` — default
  `{{ github_release_install_binary_in_archive }}`. What the updater looks for
  inside the extracted tarball.

  Set this only when the caller builds `_binary_in_archive` **from the release
  version**, because the rendered literal is correct for exactly one release.
  `${VERSION}` (leading `v` stripped) and `${TAG}` (raw `tag_name`) are
  substituted by the script at run time:

  ```yaml
  github_release_install_binary_in_archive_pattern: "zfs_exporter-${VERSION}.{{ zfs_exporter_arch_suffix | trim }}/zfs_exporter"
  ```

  The architecture stays a Jinja expression and is resolved when the env file is
  written — the file is per-host, so it is already correct there. **Wrong
  value:** substituting the architecture too, or hardcoding `linux-amd64`,
  produces a path that is silently wrong on the aarch64 hosts the role's own
  `_asset_patterns` declare support for.

- `github_release_install_post_update_command` — default `""`. Run by the
  updater through `sh -c`, and **only when the binary's bytes actually
  changed**.

  Empty is right for most callers: a consumer that spawns the binary per job
  picks up a replacement on its own. Set it where the consumer holds the old
  binary open — a service reading it from a read-only bind mount will not see a
  new build until it restarts, and nothing on the host would otherwise tell it.

  Prefer a form that does nothing to a stopped unit:

  ```yaml
  github_release_install_post_update_command: "systemctl try-restart <unit>.service"
  ```

  **Wrong value:** a non-zero exit fails the run *after* the binary was
  replaced, so the install stands and the run reports failure.

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

## The on-host updater

The tasks above converge a binary *while `ansible-playbook` is running*. Between
runs the host has no way to pick up a new release. The role therefore also
deploys two scripts and one env file per install:

| path | what it is |
|---|---|
| `/usr/local/bin/github-release-update` | updates one install |
| `/usr/local/bin/github-release-update-all` | walks every env file on the host |
| `/etc/github-release-install/<name>.env` | one per install, written by this role |

```
github-release-update-all --dry-run
github-release-update-all
github-release-update --name <name>
github-release-update --env-file /etc/github-release-install/<name>.env --force
```

Both need root — they write to `/usr/local/bin`, `/opt`, and run `apt-get`. They
do **not** self-elevate the way `gpu-mode` does: the meta script loops over every
install, and a self-elevating child would raise a sudo prompt per iteration,
hanging an unattended run.

### It is a second implementation, and it can drift

`files/github_release_update.py` re-implements the decision that
`tasks/main.yaml` makes. **Nothing keeps the two in step.** They are not
generated from a common source, and no test compares them directly. Editing one
without the other is entirely possible and nothing will say so.

What narrows it, honestly labelled:

- **Structural.** The script uses Python's `re`, which is the engine behind
  Ansible's `regex_search`, so `_version_regex` and `_asset_patterns` behave
  identically on both sides rather than merely similarly.
- **Structural.** `roles/github_release_install/tests/` pins the behaviours the
  two must agree on — both idempotency modes, all three archive types, the
  digest/`id:` fallback, the byte comparison.
- **Exhortation.** "Change both." There is no artifact for this.

The one check that can catch a live disagreement is operational: converge a host
with the script, then run its playbook and confirm `changed=0` for this role's
tasks. Do that when you change either side.

### It never installs a binary that is absent

A missing `BINARY_PATH` prints `SKIP` and exits 0. Installing is Ansible's job.

That is not only a scoping rule, it is the orphan handling. The role is included
once per install and cannot know a host's full set, so it never removes an env
file left behind by a caller you stopped invoking — the same gap
`remote_power_control` has with its `/etc/remote_power_control/*.env`. Because
the updater refuses to bootstrap, that stale file reports `SKIP` instead of
resurrecting something you deliberately removed.

The existence check runs **before** the API call, so an orphan costs nothing
against the rate limit below. `--force` overrides it for a deliberate reinstall.

### Rate limit

Unauthenticated GitHub allows **60 requests per hour per source IP**, shared by
every host behind one WAN address — one request per env file per run. Set
`GITHUB_TOKEN` in the environment if that bites; the role does not deploy one.

### The env file is parsed, not sourced

Values go through Ansible's `quote` filter (`shlex.quote`), so a value is quoted
only when it needs to be — a mix of `KEY=value` and `KEY='value'` is expected and
both read the same. The script reads it with `shlex`, and never hands it to a
shell, so a value cannot become a command. A line that *would* execute under
`source` is rejected rather than run.

`VERSION_COMMAND` is likewise split and executed directly, matching
`ansible.builtin.command` — which is what makes `echo <tag>` resolve to
`/bin/echo`. `POST_UPDATE_COMMAND` is the one exception and does go through
`sh -c`, because it is a command a human wrote to be run that way.

Mode is `0644`: the file holds a repo name, a path and a regex. Nothing in it is
a secret, and a file only root can read is a file nobody can debug.

### Bytes, not tags, decide whether anything changed

The script replaces the binary only when the downloaded bytes differ, matching
`ansible.builtin.copy`. This matters beyond tidiness: a caller keys a service
restart off the binary's mtime, and a script that rewrote the file
unconditionally would make the next playbook run report a change that did not
happen.

A release can move without the bytes moving. That case reports
`OK … (metadata refreshed, bytes unchanged)`: the stamp is brought up to date so
the next run is a no-op, and `POST_UPDATE_COMMAND` does **not** run.

### Why `deploy_updater.yaml` is a separate task file

So a fixture test can render the env file without executing everything above it —
the earlier tasks call the GitHub API and write to real paths, and a test must do
neither. Same split, for the same reason, as `systemd_unit_watchdog`.

Those three tasks also set no `owner`/`group`. Every caller runs under
`become: true` (the one exception connects as a root-equivalent inventory user),
so the files land root-owned anyway, and hardcoding `owner: root` would make the
role impossible to run in a fixture test on a controller that is not root.

## Tests

```
cd ansible

# the two scripts
.venv/bin/pytest roles/github_release_install/tests/ -q

# the env file this role renders
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/github_release_install/tests/inventory \
  roles/github_release_install/tests/test.yml

# every caller in the repo can actually reach an update
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i localhost, tests/test-github-release-update-reachable.yml
```

The third exists because one caller could not. It used
`version_command: "echo latest"` with `version_regex: "(.*)"`, comparing a
literal against itself: both sides moved together, the binary existed, so the
comparison could never fail. That host took one build of a rolling release and
then declined every later one, reporting no change on every run.
`defaults/main.yaml` warned about the idiom in prose; the prose was not enough,
so there is now a check.
