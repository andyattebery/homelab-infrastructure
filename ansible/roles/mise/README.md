# mise

Installs [mise](https://mise.jdx.dev/), the polyglot runtime manager.

## Status: Production

## Supported distributions

`tasks/main.yaml` dispatches on `ansible_distribution` and handles **Debian, Ubuntu and
Fedora only**.

> **There is no `else` branch.** On any other distribution the role reports *ok* and
> **installs nothing**. A play using this role on an unsupported host succeeds while
> leaving no `mise` behind, and the failure surfaces later as `mise: command not found`.

Verified example: an image-based Fedora derivative such as Bazzite reports
`ansible_distribution: Bazzite`, so `- role: mise` there is a silent no-op.

## rpm-ostree hosts (Bazzite, Kinoite, Silverblue)

Not supported, and not fixable by relabelling the distribution check: `install_fedora.yaml`
uses `dnf config-manager` + `dnf install`, which cannot write to the read-only `/usr` of an
image-based OS. Layering with `rpm-ostree install` would work but demands a reboot.

**Use Homebrew instead** — it ships preinstalled on Bazzite:

```bash
brew install mise    # verified available: stable 2026.7.7, bottled
```

From Ansible that is `community.general.homebrew` with **`become: false`**, because
Homebrew refuses to run as root; the install tree is owned by the login user. Note that
`/home/linuxbrew/.linuxbrew/bin` is **not** on the non-interactive `PATH`, so any task
using the result must call the absolute path.

A calling playbook in this repo installs the HuggingFace CLI this way, if an example is
wanted.

## Where mise comes from

| Host | Source | Why |
| --- | --- | --- |
| Ubuntu 26.04+ **amd64** | `ppa:jdxcode/mise` | what upstream's install docs point 26.04+ at |
| Ubuntu 26.04+ **arm64** | `https://mise.jdx.dev/deb` | the PPA has no arm64 build — see below |
| Ubuntu < 26.04, Debian | `https://mise.jdx.dev/deb` | upstream's own repository, `Architectures: amd64 arm64` |
| Fedora | `dnf config-manager --add-repo` | see the rpm-ostree caveat above |

Inputs, all optional and all in `defaults/main.yaml`: `mise_apt_source_name`
(**this is the filename** — `deb822_repository` derives both
`/etc/apt/sources.list.d/<slug>.sources` and `/etc/apt/keyrings/<slug>.asc` from
it, so keep it lowercase with only hyphens and digits), `mise_apt_repo_url`,
`mise_apt_gpg_key_url`, `mise_ppa_user`, `mise_ppa_repository`, and
`mise_arch_map`.

### The PPA is amd64-only, and that is measured

`ppa:jdxcode/mise` publishes **one** binary, for `resolute/amd64`. It publishes
nothing for `resolute/arm64`, and nothing at all for `noble` or `jammy` —
counted from the PPA's own `Packages.gz` indexes, not inferred:

    resolute amd64  1        noble amd64  0        jammy amd64  0
    resolute arm64  0        noble arm64  0        jammy arm64  0

An arm64 Ubuntu 26.04 host pointed at the PPA gets a perfectly valid, signed,
**empty** source: `apt update` succeeds with rc 0 and `apt install mise` then
fails with *"No package matching 'mise' is available"*. So the branch is gated on
architecture, not just release, and arm64 falls through to the deb repository
which publishes both. Both paths are covered by
`ansible/tests/apt-sources/verify-mise.yml`, including an emulated amd64 26.04
container specifically so the PPA path is actually exercised.

Worth noting when re-checking this: `dists/<suite>/main/binary-<arch>/Packages`
**404s** on Launchpad — only `Packages.gz` and `Packages.xz` are published. A
plain `curl` of `Packages` reports zero packages for every suite, which is a
false negative that briefly made the PPA look entirely empty.

### The old PPA name did not exist

This role previously used `ppa:mise-en-place/mise`. **That PPA does not exist** —
`launchpad.net` and the Launchpad API both return 404 — so
`add-apt-repository --yes ppa:mise-en-place/mise` fails with
*"ERROR: ppa 'mise-en-place/mise' not found"*. Nothing had noticed because the
branch only fires on Ubuntu 26.04 and no host had reached it. Reproduced in
`ansible/tests/apt-sources/repro.yml`.

### Crossing 24.04 → 26.04 removes the deb repository

A host that reaches 26.04 by upgrading still carries the `mise.sources` this role
configured beforehand. The PPA branch removes it, along with the legacy
`mise.list` and the old keyring. Two sources for the same package is not a
duplicate apt *target*, so apt does not warn — which is worse than if it did: the
host silently has two candidates and pinning decides the winner.

## This role does not write mise config

Installation only. The profile is selected by the
[dotfiles](https://github.com/andyattebery/dotfiles), not here: fish exports
`MISE_ENV=workstation` when `IS_WORKSTATION=true`, and the default config installs no
languages — already the wanted behaviour on a server.

On a host with the dotfiles deployed, `~/.config/mise/config.toml` is a **symlink into the
dotfiles tree**, so anything this role wrote there would be redundant at best and would
fight the symlink at worst.
