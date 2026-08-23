# apt_add_launchpad_ppa

Adds a Launchpad PPA as a deb822 `.sources` file, with the signing key fetched
into `/etc/apt/keyrings/` and referenced by path.

## Status: Production

## Why this role exists

**No builtin module can add a PPA on Ubuntu 26.04.** Both halves of that are
verified in `ansible/tests/apt-sources/probe-ppa-module.yml`:

- `ansible.builtin.deb822_repository` has **no PPA support at all** — no `ppa:`
  shorthand, no Launchpad key lookup. It writes the format we want and knows
  nothing about Launchpad.
- `ansible.builtin.apt_repository` **does** have PPA support, and is otherwise
  current — it already queries `api.launchpad.net` and points at
  `ppa.launchpadcontent.net`. But it cannot import the key on a host without
  `apt-key`, and 26.04 / Debian 13 ship none.

The second one is an upstream bug rather than a missing dependency. With
`apt-key` absent, `apt_repository.py` runs:

    gpg --no-tty --keyserver hkp://keyserver.ubuntu.com:80 --export <fingerprint>

`gpg --export` reads the **local** keyring and `--keyserver` is inert for it, so
nothing is fetched, stdout is empty, and the module reports *"Unable to get
required signing key"*. The `apt-key` branch does it correctly with
`apt-key adv --recv-keys`. Installing `gpg` does not help — confirmed on a 26.04
container with `gpg` present.

So the gap is not correctness in general, it is Launchpad specifically: this role
does the two-step (fingerprint from the API, key from the keyserver) that
`deb822_repository` does not do for you.

**That bug will not be fixed.** ansible-core 2.21 *deprecates* both
`apt_repository` and `apt_key` in favour of `deb822_repository`, so the module
carrying the working PPA support is on its way out while the module replacing it
still has none. Migrating PPAs into this role is therefore the upstream-endorsed
direction, not a workaround around a temporary gap.

Checked against the 2.21 source directly: it contains **zero** occurrences of
`ppa` or `launchpad`.

### Nothing else in the ecosystem fills the gap either

Searched current releases, not just what happens to be installed:

| Where | Result |
| --- | --- |
| `ansible-core` 2.21.3 (73 modules) | only `apt`, `apt_key`, `apt_repository`, `deb822_repository`, `debconf`. The two that could help are deprecated; the one replacing them has no PPA support. |
| `community.general` 13.3.0 (latest, 577 modules) | `apt_repo` is for **ALT Linux** `apt-repo`, not PPAs; `apt_rpm` likewise. Zero `ppa`/`launchpad` mentions in its changelog. |
| all 95 collections in the `ansible` 14 bundle | none named for apt / deb / ppa / launchpad / ubuntu |
| Galaxy, third-party | `tuxinvader.launchpad`, `shubhamtatvamasi.ppa` — neither in the bundle |

`tuxinvader.launchpad` is the only serious-looking candidate, and it solves the
opposite problem: its modules (`ppa`, `ppa_upload_package`, `prune_ppa`,
`start_interactive_login`) **publish and manage** PPAs you own, via `launchpadlib`
and an interactive OAuth login. Nothing in it adds a PPA to a host's apt sources.
It is also 1 star, last pushed 2022-10-30.

So *consuming* a PPA on a host where `apt-key` is gone is unserved by the entire
current ecosystem, and this role is the supported way to do it here.

## Inputs

Required:

- `apt_add_launchpad_ppa_user` — Launchpad owner, the part before the slash in
  `ppa:owner/name`. A wrong value 404s at the API task, before anything is
  written.
- `apt_add_launchpad_ppa_repository` — the PPA name, the part after the slash.
  For `ppa:awesometic/ppa` that is `ppa`.
- `apt_add_launchpad_ppa_ubuntu_version_name` — the Ubuntu series codename the
  PPA publishes for, e.g. `noble` or `resolute`. Callers normally pass
  `{{ ansible_facts['distribution_release'] }}`. A series the PPA does not
  publish for gets a source that 404s on `apt update`, so check the PPA first
  when adding a new one.

Optional:

- `apt_add_launchpad_ppa_name` — default `<user>-<repository>`. **This is the
  filename**: `deb822_repository` derives both
  `/etc/apt/sources.list.d/<slug>.sources` and `/etc/apt/keyrings/<slug>.asc`
  from it, and offers no separate filename parameter. The slug is
  version-dependent, which is a trap worth understanding:

  | ansible-core | slug |
  | --- | --- |
  | 2.20 (installed) | `re.sub('[^a-z0-9-]+', '', re.sub('[_\s]+', '-', name.lower()))` — lowercased, underscores/spaces to hyphens, dots and colons **deleted** |
  | 2.21+ | `name.replace(' ', '-')` — case and punctuation preserved ([#86243](https://github.com/ansible/ansible/issues/86243)) |

  2.21 reuses the old filename when one already exists, so an upgrade does not
  orphan a source. But a name that is **not already slug-safe** produces a
  different filename on a fresh host under each version — `Fish_Shell.4` becomes
  `fish-shell4` on 2.20 and `Fish_Shell.4` on 2.21.

  **Keep names lowercase with only hyphens and digits** and the two rules agree,
  making the role version-independent. Every name this repo uses
  (`fish-shell-release-4`, `awesometic-ppa`, `jdxcode-mise`) satisfies that.
- `apt_add_launchpad_ppa_legacy_name` — default `<user>_<repository>`, the
  filename earlier versions of this role used. Removed on every run. Override
  only if a caller once passed a custom `filename` to `apt_repository`.

## Example

From `roles/realtek_dkms/tasks/install_ppa.yaml`:

```yaml
- name: Add awesometic PPA via repo helper role
  ansible.builtin.include_role:
    name: apt_add_launchpad_ppa
  vars:
    apt_add_launchpad_ppa_user: awesometic
    apt_add_launchpad_ppa_repository: ppa
    apt_add_launchpad_ppa_ubuntu_version_name: "{{ ansible_distribution_release }}"
```

## The key goes in keyrings, not trusted.gpg.d

`signed_by` is passed as a **URL**. The module downloads it, writes
`/etc/apt/keyrings/<slug>.asc`, and references that path from the `.sources`.

Two alternatives are deliberately not used:

- **An inline armored key block.** `deb822_repository` accepts one, and
  `add-apt-repository` writes one. That is the shape Launchpad bug
  [#2150614](https://bugs.launchpad.net/ubuntu/+source/ubuntu-release-upgrader/+bug/2150614)
  truncates during `do-release-upgrade` — still unfixed — leaving a corrupt key
  and an unverifiable repo after a release upgrade.
- **`/etc/apt/trusted.gpg.d/`**, which earlier versions of this role used. A key
  there is trusted for **every** repository on the host, not just this one.

## The key is fetched once, not every run

`signed_by` is a keyserver URL on the first run and the **path** to the
already-fetched key on every run after. That is not an optimisation, it is what
makes the role idempotent.

`deb822_repository` re-downloads a URL every run and rewrites the keyring when
the bytes differ. `keyserver.ubuntu.com` is served through a caching proxy whose
backends do not agree byte-for-byte, so the task reported `changed` on roughly
every other run — forever — and refreshed the apt cache each time. Observed
directly: the `.sources` content was identical across runs while the module still
reported a change, alternating true/false/true.

The module short-circuits when `signed_by` is an existing file
(`write_signed_by_key`: `if os.path.isfile(v): return changed, v, None`), so
passing the path skips the fetch entirely. Both `.asc` and `.gpg` are checked,
because the module chooses the extension by sniffing the downloaded bytes for the
PGP armor header.

**Consequence: a rotated PPA signing key is not picked up automatically.** If a
PPA rotates its key, `apt update` starts failing with `NO_PUBKEY`; delete
`/etc/apt/keyrings/<name>.asc` and re-run the role. That is the deliberate
trade: a visible failure on a rare event, instead of a permanently dirty
changelog on every run.

## What it cleans up

Three things, on every run, because apt reads every file in `sources.list.d` and
a leftover naming the same PPA is a second definition of the same source —
"configured multiple times" at best, a `Signed-By` conflict at worst:

- `sources.list.d/<user>_<repo>.list` and `trusted.gpg.d/<user>_<repo>.asc`, from
  earlier versions of this role.
- `sources.list.d/<user>-ubuntu-<repo>-*.sources`, from `add-apt-repository`.
  Globbed, not named: that tool bakes the **series** into the filename, so a host
  upgraded from noble to resolute keeps a file named for noble. The glob is what
  catches it.

The apt cache is refreshed only when one of those actually changed.

## Requirements

`python3-debian`, installed by the role. `deb822_repository` fails without it,
and its own `install_python_debian` option is not used — that makes the module
shell out to its own `apt update`, which fails on exactly the hosts with a broken
source and reports an error naming the wrong problem.
