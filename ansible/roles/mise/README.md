# mise

Installs [mise](https://mise.jdx.dev/), the polyglot runtime manager.

## Status: Production

## Supported distributions

`tasks/main.yaml` dispatches on `ansible_distribution` and handles **Debian, Ubuntu and
Fedora only**.

> **There is no `else` branch.** On any other distribution the role reports *ok* and
> **installs nothing**. A play using this role on an unsupported host succeeds while
> leaving no `mise` behind, and the failure surfaces later as `mise: command not found`.

Verified example: **htpc-01 reports `ansible_distribution: Bazzite`**, so `- role: mise`
there is a silent no-op.

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

`playbook-htpc-01.yaml` installs the HuggingFace CLI this way, if an example is wanted.

## This role does not write mise config

Installation only. The profile is selected by the
[dotfiles](https://github.com/andyattebery/dotfiles), not here: fish exports
`MISE_ENV=workstation` when `IS_WORKSTATION=true`, and the default config installs no
languages — already the wanted behaviour on a server.

On a host with the dotfiles deployed, `~/.config/mise/config.toml` is a **symlink into the
dotfiles tree**, so anything this role wrote there would be redundant at best and would
fight the symlink at worst.
