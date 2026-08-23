# snapper_install

Installs [snapper](http://snapper.io/) from the openSUSE Build Service, on
Debian and Ubuntu.

## Status: Production

Not currently enabled by any playbook — its one caller has it commented out. It
is kept working because the alternative is a role that rots silently until
someone needs it.

## Inputs

Both optional.

- `snapper_install_apt_source_name` — default `filesystems-snapper`. **This is
  the filename**: `deb822_repository` derives both
  `/etc/apt/sources.list.d/<slug>.sources` and `/etc/apt/keyrings/<slug>.asc`
  from it, and there is no separate filename parameter. Keep it lowercase with
  only hyphens and digits; the slug rule differs between ansible-core 2.20 and
  2.21 and names in that shape are identical under both.
- `snapper_install_obs_url` — default
  `https://download.opensuse.org/repositories/filesystems:/snapper/<dir>`, where
  `<dir>` is `xUbuntu_<version>` on Ubuntu and `Debian_<major>` on Debian. The
  signing key is fetched from `<url>/Release.key`. A release OBS does not publish
  for gets a source that 404s on `apt update`.

## amd64 only

OBS publishes **amd64 and nothing else** for every distro directory —
`Debian_12`, `Debian_13`, `xUbuntu_24.04`, `xUbuntu_26.04` each contain a single
`amd64/`. On an arm64 host the source is valid and `apt update` succeeds, but no
`snapper` package is ever a candidate and the install fails with no installation
candidate. There is no workaround here; the packages do not exist.

## What was wrong with it

The Debian and Ubuntu paths were separate files, and the Debian one was a
lightly-edited copy of `fish_install` that still said "fish" in three places.
Four defects, all fixed by collapsing the two into one file whose only
distro-dependent value is a single path segment:

1. **It installed the wrong package.** `install_debian.yaml` ended in a task
   named "Install fish" that ran `apt: name=fish`. A Debian host running this
   role got fish and no snapper.
2. Two tasks were named "Add fish apt repository key" / "Add fish apt
   repository".
3. `filename: filesystems_snapper.list` produced
   **`filesystems_snapper.list.list`**. `apt_repository` appends `.list` to
   whatever filename it is given (`apt_repository.py:283`,
   `'%s.list' % _cleanup_filename(...)`), and the caller had already included the
   extension. Ubuntu passed it without, so the two halves wrote differently-named
   files for the same repository.
4. The two halves escaped the OBS project name differently in the key URL —
   Ubuntu used `filesystems:snapper`, Debian `filesystems:/snapper/`. Both happen
   to resolve, which is why it went unnoticed. There is now one variable.

Both `install_ubuntu.yaml` and `install_debian.yaml` also called **`apt-key`**,
which Ubuntu 26.04 and Debian 13 do not ship — `command:` with no `failed_when`,
so it failed the play rather than degrading. On Debian 13 that made this role
already broken before any of the above mattered. It was a one-shot cleanup of a
key moved out of the deprecated `/etc/apt/trusted.gpg` years ago, and it ran
unconditionally on every run, so any host this repo has managed had that key
removed long ago.

The key now lands in `/etc/apt/keyrings/` rather than `/etc/apt/trusted.gpg.d/`,
where it was trusted for every repository on the host.

## Verification

`ansible/tests/apt-sources/verify-snapper.yml`, on four containers. The
predecessors — including the doubled `.list.list` — are seeded first so the
cleanup assertions cannot pass vacuously, and the install leg asserts
**snapper is installed and fish is not**, which is the only check that would have
caught defect 1.
