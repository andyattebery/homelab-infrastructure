# ipmitool_asrock_fan_control

Installs [ipmitool-asrock-fan-control](https://github.com/andyattebery/ipmitool-asrock-fan-control),
a fan-control script for ASRock Rack boards with an AST2500 BMC, from its latest GitHub release,
and writes its fan labels file.

## Status: Not deployed

## What it does and does not do

It installs the script and names the fans. **It writes nothing to the BMC.** No fan mode or duty
is set, read or reset, so running the role leaves the fans exactly as they were. Writes stay
manual: `sudo ipmitool-asrock-fan-control.sh set_duty|set_mode|reset …`. The one script command
the role runs is the version check, `--version`, which a release with that switch answers without
calling ipmitool.

The download goes through `github_release_install`, so the host also gets that role's on-host
updater, `github-release-update` and `github-release-update-all`, and an env file at
`/etc/github-release-install/ipmitool-asrock-fan-control.sh.env`. Between playbook runs,
`sudo github-release-update --name ipmitool-asrock-fan-control.sh` installs a newer release. Every
run makes one unauthenticated GitHub API call (see that role's README, "Rate limit").

Debian only: it installs `bsdextrautils` for `column`, which Debian ships outside util-linux.

## Required inputs

None. With every default the role installs the latest release with no labels.

## Optional inputs

### `ipmitool_asrock_fan_control_labels` (default `{}`)

Slot number to label. Adds a `LABEL` column to every table the script prints. Labels are
display-only, and the script never accepts one in place of a slot number. Empty removes the labels
file, so the column goes away.

If it is wrong, the column misnames a fan and nothing else changes. The script ignores a slot
outside the board's range with a warning on stderr. A label cannot contain `#`, because the
script treats everything after `#` as a comment and cuts the label off there.

### `ipmitool_asrock_fan_control_repo` (default `andyattebery/ipmitool-asrock-fan-control`)

`owner/repo`, as `github_release_install` takes it. The repository's latest release must carry an
asset named `ipmitool-asrock-fan-control.sh`. A repository with no release fails the API call, and
a release without that asset fails the task that picks it.

The asset must also be **stamped**. The release workflow writes the tag into the script's
`VERSION`, so `--version` prints `ipmitool-asrock-fan-control.sh vX.Y.Z`, and
`github_release_install` compares the `X.Y.Z` it extracts with the release tag. An asset that
prints no `X.Y.Z` (an unstamped `dev` copy, or v1.0.0, which predates `--version`) never matches,
so every run enters the install steps, which report a change whether or not the bytes moved.
v1.0.0 also treats `--version` as an unknown action, and reads the BMC's SDR to print its help.

### Paths

| variable | default |
|---|---|
| `ipmitool_asrock_fan_control_directory_path` | `/opt/ipmitool-asrock-fan-control` |
| `ipmitool_asrock_fan_control_command_path` | `/usr/local/sbin/ipmitool-asrock-fan-control.sh` |
| `ipmitool_asrock_fan_control_labels_file_path` | `/etc/ipmitool-asrock-fan-control/fan-labels.conf` |

If you move the directory, the next run installs the script there and rewrites the wrapper and the
updater's env file to follow it. The old directory stays on disk.

## Example

From `playbook-prod-proxmox-cluster.yaml`:

```yaml
- name: Install ipmitool-asrock-fan-control
  when: install_ipmitool_asrock_fan_control | default(false)
  tags: fan_control
  ansible.builtin.import_role:
    name: ipmitool_asrock_fan_control
```

From the calling host's `host_vars`:

```yaml
install_ipmitool_asrock_fan_control: true
ipmitool_asrock_fan_control_labels:
  1: CPU fan
  2: rear 80mm fans (dual fan adapter)
  3: HBA fan
  # 4 is empty
  5: 120mm PCIe fan
  6: front 120mm fan 3
  7: front 120mm fans 1 and 2 (dual fan adapter)
```

`--tags fan_control` reaches the tasks `github_release_install` adds, nested `include_tasks`
included, because the tag comes from the enclosing `import_role`. A tag set on the `include_role`
task itself would gate only the include, and would need `apply:`.

## Why a wrapper and not a symlink

The script looks for its labels file at `$(dirname "$0")/fan-labels.conf`. Through a symlink on
`PATH`, `$0` is the link, so the script would look in `/usr/local/sbin`. The wrapper exports
`FAN_LABELS_FILE` and `exec`s the installed script. An existing `FAN_LABELS_FILE` wins, which
keeps the script's documented override working. `github_release_install_symlink` is left off for
the same reason.

The wrapper has the script's own name. The script prints its usage under the name of the file
that runs, which is the real file the wrapper `exec`s, so the commands in its help work as
printed.

## Traps

- **The script is AST2500-only.** An AST2600 board uses different raw commands. The role cannot
  tell the two apart, and neither can the script.

## Tests

No fixture test. The role hands the install to `github_release_install`, which has its own tests,
and writes two short files, so a fixture would only check that a template renders its input. The
checks that can fail for the right reason are on the host:

```sh
sudo ipmitool-asrock-fan-control.sh --version
sudo ipmitool-asrock-fan-control.sh show
```

`--version` printing the release's tag shows that the stamped asset is installed, and a second
playbook run that reports no change for this role shows that the comparison matches. A `LABEL`
column holding the declared labels shows that the wrapper found the labels file and that the
script parsed it. Without the labels file the column is absent, so its presence is the signal.
