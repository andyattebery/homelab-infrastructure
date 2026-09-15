# firefox

Installs Firefox from Mozilla's own apt repository, and pins that origin.

Debian's archive carries only `firefox-esr`. This role exists for hosts that want the current
release, or any other channel Mozilla publish, without hand-managing a third-party source.

## Status: Production

Deployed 2026-09-12. The apt source is proven on both architectures in
`ansible/tests/vdesktop/`, and the pin is proven load-bearing there rather than asserted: the
test applies the role at priority 1000, re-applies at 100, and requires the winning
`firefox-esr` version to change (Mozilla 153.2.0 against Debian 140.15.0).

## Inputs

Everything has a default; none of them are secrets.

Optional:

- `firefox_apt_source_name` — default `mozilla`. **This is the filename**:
  `deb822_repository` derives both `/etc/apt/sources.list.d/<slug>.sources` and
  `/etc/apt/keyrings/<slug>.asc` from it. Lowercase, hyphens and digits only — the slug rule
  differs between ansible-core 2.20 and 2.21.
- `firefox_apt_repo_url` / `firefox_apt_gpg_key_url` — upstream's repository and key. The key
  is served as `repo-signing-key.gpg` but is **ASCII-armored**, which is what makes
  `signed_by:` work with it directly.
- `firefox_apt_suite` — default `mozilla`. See "One suite, not one per codename". Changing
  this to the Debian codename produces a valid, signed, empty source.
- `firefox_apt_components` — default `[main]`.
- `firefox_arch_map` — kernel architecture to Debian architecture, templated into
  `Architectures:`. `sources.list(5)` documents apt's `$(ARCH)` substitution for suites, not
  for this field.
- `firefox_package` — default `firefox` (current stable). The channel is the **caller's**
  choice, not the role's; see "Channels are separate package names".
- `firefox_apt_pin_priority` — default `1000`. Set to `500` or below to defer to Debian
  instead. See "What the pin is actually for" — this is not decoration, and the tests prove it.
- `firefox_apt_preferences_path` — default `/etc/apt/preferences.d/mozilla`. An input so the
  fixture test can redirect it to a scratch directory.

## Example

```yaml
- name: Configure the apt repository and pin
  ansible.builtin.include_role:
    name: firefox
    tasks_from: apt_repo.yaml
```

A full example lands here when `tasks/main.yaml` exists.

## One suite, not one per codename

Mozilla publish a single distro-agnostic suite literally named `mozilla`, covering
`all amd64 arm64 i386`. It is **not** a suite per Debian codename, and this is the most
likely thing for a future reader to "fix" by templating `distribution_release` into it. Doing
so yields a source that is valid, signed, parses cleanly, and contains nothing.
`verify-firefox-repo.yml` asserts the suite is the literal `mozilla` **and** that the Debian
codename does not appear in it, for exactly that reason.

## Channels are separate package names

`firefox`, `firefox-beta`, `firefox-devedition`, `firefox-esr` and `firefox-nightly` all live
in that one suite as distinct packages. So plain `firefox` is stable and **cannot** drift onto
a nightly, even though nightlies sit in the same suite at much higher version numbers. Pick a
channel by setting `firefox_package`, never by pinning a version.

## What the pin is actually for

Not `firefox`. Debian trixie ships no package by that name, so nothing contests it and a pin
there would be invisible.

The pin is about **`firefox-esr`, which both archives ship**. Mozilla's ESR is numerically far
ahead of Debian's, so without a pin anything that pulls `firefox-esr` silently migrates to
Mozilla's build on version alone. The pin makes that a decision rather than an accident, in
whichever direction you want it.

This is measured, not asserted. `verify-firefox-repo.yml` applies the role at priority 1000,
re-applies it at 100, and asserts the winner changes — currently Mozilla's
`153.2.0esr~build1` against Debian's `140.15.0esr-1~deb13u1`. If those ever come out equal the
pin has stopped doing anything and the test fails, which is the point.

## Predecessors are removed before the new source is written

Not after. Two sources describing the same repository with different `Signed-By` values make
apt refuse every operation — including this role's own apt calls, so an interrupted run in
that window could not be repaired by re-running it. `tests/vdesktop/repro.yml` CONTROL 2
reproduces it.

The pin file is written *after* the source, deliberately: a pin naming an origin that has no
source yet is inert, not harmful, so it does not need the same ordering care.

## A wrong architecture is quiet

As with `sunshine`: a source pinned to the wrong architecture still reports a candidate at
priority 500 and only fails at dependency resolution, reported as `firefox:<foreign arch>:`.
The verify playbook therefore asserts a clean `apt-get install --simulate`, not merely that a
candidate exists. Do not weaken that.

## There is deliberately no fixture test

`ansible/tests/README.md` says to use the cheapest pattern that can **actually fail for the
right reason**. This role's only rendering decision is the apt source and the pin, and a
localhost fixture could assert only that the right bytes landed in a file. The container
harness asserts something strictly stronger: that apt *accepts* the source, that the package
resolves and simulates a clean install on this architecture, and that flipping the pin
priority changes which archive wins. A fixture test here would be a weaker duplicate, so
there isn't one. See `ansible/tests/vdesktop/`.

## The apt half is split out so it can be tested

`tasks/apt_repo.yaml` installs nothing and starts nothing, which is what lets
`ansible/tests/vdesktop/` import it into a throwaway container. Package installation belongs
in `tasks/main.yaml`.
