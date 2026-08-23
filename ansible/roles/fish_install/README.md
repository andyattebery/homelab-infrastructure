# fish_install

Installs a current fish shell from an upstream repository, and optionally makes
it the login shell.

## Status: Production

The distro's own fish is usually well behind upstream, so this role adds a
third-party source rather than using `apt install fish` alone — except on
armv6l, where no upstream build exists.

## Inputs

All optional.

- `fish_version` — default `4`. The upstream **major** series, used to pick the
  PPA (`ppa:fish-shell/release-<v>`) and the OBS project
  (`shells:/fish:/release:/<v>`). A version neither publishes gets a source that
  404s on `apt update`; check both before bumping it.
- `fish_install_change_shell` — default `false`. When true, sets
  `{{ ansible_user }}`'s login shell to whatever `which fish` returns.
  `configure_server` sets this true for every host.
- `fish_install_debian_source_name` — default `shells-fish-release-<v>`. Debian
  only. **This is the filename**: `deb822_repository` derives both
  `/etc/apt/sources.list.d/<slug>.sources` and `/etc/apt/keyrings/<slug>.asc`
  from it. Keep it lowercase with only hyphens and digits — the slug rule
  changed between ansible-core 2.20 and 2.21, and names in that shape are
  identical under both.
- `fish_install_debian_repo_url` — default the openSUSE Build Service project for
  the chosen `fish_version` and the host's Debian major version. The key is
  fetched from `<url>/Release.key`.

## Where fish comes from

| Host | Source |
| --- | --- |
| Ubuntu | `ppa:fish-shell/release-<v>`, via the `apt_add_launchpad_ppa` role |
| Debian (not armv6l) | openSUSE Build Service, via `deb822_repository` |
| Debian armv6l | the distro's own package; **no** third-party source |

armv6l gets no upstream source because none exists: the PPA is not built for it
and OBS publishes no armhf for `Debian_13`. An earlier version of this role
carried ~55 lines of commented-out attempts to pin raspbian and backports around
that. They are in git history rather than in the file.

## `apt_repo.yaml` is separate on purpose

The apt-source tasks live in `tasks/apt_repo.yaml`, included by `main.yaml`. That
lets `ansible/tests/apt-sources/verify-fish.yml` exercise them in a container
without the `chsh` in `main.yaml`, which needs a real user with a real shell
entry. Verified on Debian 12, Debian 13, Ubuntu 24.04 and Ubuntu 26.04.

## What changed, and why it mattered

**The Ubuntu path used to call `apt-key`, and 26.04 does not ship it.** The task
was `ansible.builtin.command` with no `failed_when`, so it did not degrade — it
failed the play. And because this role runs on **every** host via
`configure_server` → `standard.yaml`, early, it took the whole playbook down with
it, including the post-upgrade run that would have restored the third-party
repos. Reproduced in `tests/apt-sources/repro.yml`.

That task was a one-shot cleanup of a key moved out of the deprecated
`/etc/apt/trusted.gpg` years ago. It ran unconditionally on every run of this
role, so any host this repo manages had that key removed long ago, and a host
built since never had it. Deleting it loses nothing.

**The Ubuntu path also used `add-apt-repository`**, which writes a `.sources`
file with the signing key **inline**, and bakes the series into the filename
(`fish-shell-ubuntu-release-4-noble.sources`). Both are liabilities across a
release upgrade: Launchpad bug
[#2150614](https://bugs.launchpad.net/ubuntu/+source/ubuntu-release-upgrader/+bug/2150614)
truncates inline keys during `do-release-upgrade`, and the noble-named file
survives onto a resolute host. `apt_add_launchpad_ppa` writes the key to
`/etc/apt/keyrings/` and removes the stale files.

**The Debian path templated its own `.sources`** and put the key in
`/etc/apt/trusted.gpg.d/`, where it was trusted for every repository on the host.
Its two halves also disagreed with each other: the template used `http://` while
the key fetch beside it used `https://`, and the OBS project colons were escaped
one way in one and another way in the other. Both now come from one variable.

## Fedora is deliberately not dispatched

`tasks/install_fedora.yaml` exists and `main.yaml` does **not** call it. That is
intentional, not an oversight: it runs `dnf config-manager --add-repo`, and the
only Fedora host here is Bazzite, which is image-based — the command does not
apply. `configure_server`'s Fedora path still includes this role, which lands on
the `which fish` task and expects fish to already be present in the image.
