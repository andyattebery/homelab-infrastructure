# owntone

Installs [OwnTone](https://owntone.github.io/owntone-server/) (formerly forked-daapd)
from the gyfgafguf.dk repository.

## Status: Production, but see the two caveats below

Not currently enabled by any playbook.

## Inputs

All optional.

- `owntone_apt_source_name` — default `owntone`. **This is the filename**:
  `deb822_repository` derives both `/etc/apt/sources.list.d/<slug>.sources` and
  `/etc/apt/keyrings/<slug>.asc` from it. Named for the software, not for this
  role — see below.
- `owntone_apt_repo_url` / `owntone_apt_gpg_key_url` — the repository and its
  signing key, both over **https**. The previous version fetched the key over
  plain `http` while using the same host for the repository; https was verified
  available and is now used for both.
- `owntone_package_name` — default `owntone`.
- `owntone_supported_releases` — default `[bullseye, bookworm]`. See below.

## Caveat 1: the role installed a package that does not exist

For its whole life this role ended in `package: name=owntune`. The repository it
configures publishes `owntone`, `owntone-dbgsym`, `airptpd` and
`airptpd-dbgsym` — there is no `owntune`. The role therefore could never have
worked; it added a repository and then failed to install from it.

**The role was called `owntune` too** — the directory itself carried the typo.
It has been renamed to `owntone`, and every variable with it
(`owntune_*` → `owntone_*`). No playbook referenced it, so nothing else changed.

One thing deliberately kept the old spelling: the predecessor file this role
removes is `/etc/apt/sources.list.d/owntune.list`, because that is what the old
role actually wrote (`apt_repository` with `filename: owntune`). Renaming the
role does not rename what is already on a host's disk.

## Caveat 2: it cannot be used on Debian 13 or later

The repository signs with a **SHA1-certified key**. Debian 13 verifies
signatures with `sqv`, whose policy has rejected SHA1 since 2026-02-01:

```
OpenPGP signature verification failed: ... trixie InRelease:
Sub-process /usr/bin/sqv returned an error code (1) ...
Signing key on E0AD26FB82525DC958B0A1D4F62793319870F4F5 is not bound
E:The repository '...' is not signed.
```

An unverifiable source does not merely fail to install its own package — **apt
refuses to update at all**, so it breaks every other role on the host. The role
therefore asserts the release is in `owntone_supported_releases` and **fails
before writing anything**, with a message naming the cause.

There is nothing to fix on this side; the key has to be re-issued upstream. Add a
release to `owntone_supported_releases` only after confirming that has happened.

Both behaviours are covered by `ansible/tests/apt-sources/verify-tail.yml`: the
bookworm leg asserts `owntone` becomes an installation candidate, and the trixie
leg asserts the role refuses and says why.
