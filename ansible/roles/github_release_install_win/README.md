# github_release_install_win

Installs files out of a zip asset attached to a GitHub release, onto a Windows host, and keeps
them at the release the repo currently offers.

The Windows counterpart to `github_release_install`. That role is Linux end to end —
`ansible.builtin.uri`, `unarchive`, `get_url`, `apt`, `file: state=link` — so none of it runs
here; this one is `win_uri` / `win_get_url` / `win_unzip` / `win_copy` / `win_stat`. Input names
mirror it where the behaviour matches, and the differences are called out under
[Differences from github_release_install](#differences-from-github_release_install).

## Status: In use

## Required inputs

### `github_release_install_win_repo`

`owner/name` of the GitHub repo. No default. Wrong value: the release lookup 404s and the run
fails on the `win_uri` task.

### `github_release_install_win_asset_patterns`

Dict mapping architecture to a regex matched against release asset names.

**Keyed on `ansible_facts['architecture2']`, not `ansible_facts['architecture']`.** This is the
one input that silently does the wrong thing if a caller is copied over from
`github_release_install`. On Windows:

- `ansible_architecture` is a **localized** string from `Win32_OperatingSystem.OSArchitecture`
  (`"64-bit"` on an English install), and it is `null` outright when the connecting token is not
  in the Administrator role — `setup.ps1` skips the WMI call rather than eat a five-second access
  denied.
- `ansible_architecture2` is the non-localized, POSIX-shaped value: `i386`, `arm`, `ia64`,
  `x86_64`, `arm64`.

So the usual `x86_64:` key still works, but only through the other fact. Wrong value, or a key
for an architecture the host is not: the run fails on the architecture assert with the declared
keys printed.

The pattern is a **search**, not a full match, so anchor it. It must match **exactly one** asset —
matching two fails the run rather than picking whichever GitHub listed first.

### `github_release_install_win_dest_dir`

Directory the files are installed into. No default. Not created by this role — the caller creates
it, because ownership and ACLs on it are the caller's business. Missing: the `win_copy` fails.

### `github_release_install_win_files_in_archive`

List of paths **inside the zip** to install. Forward slashes, as zip entries use. Each is copied
to `<dest_dir>\<basename>`, so `bin/ffmpeg.exe` lands as `ffmpeg.exe`. A path not in the archive
fails the run.

## Optional inputs

### `github_release_install_win_release_tag`

Default `""` — follow the repo's `latest` release. Set to a tag to pin. When pinned, the stamp
still does the right thing: it compares what is installed against what that tag currently
resolves to, so a re-uploaded asset is still noticed.

### `github_release_install_win_tag_stamp_path`

Default `<dest_dir>\.release-tag`. The file holding `<tag_name> <asset-fingerprint>`.

**Not optional in effect** — there is no other idempotency mechanism in this role. Delete the
stamp and the next run reinstalls. Point two callers at the same path and they overwrite each
other's record, and both reinstall every run.

## Example

From `playbook-eta.yaml`:

```yaml
- name: Install jellyfin-ffmpeg (fork build with av1_nvenc)
  ansible.builtin.include_role:
    name: github_release_install_win
  vars:
    github_release_install_win_repo: andyattebery/jellyfin-ffmpeg
    github_release_install_win_asset_patterns:
      x86_64: 'win64-clang-gpl\.zip$'
    github_release_install_win_files_in_archive: [ffmpeg.exe, ffprobe.exe]
    github_release_install_win_dest_dir: "{{ eta_ffmpeg_dir }}"
```

That repo publishes four assets per release — `linux64`, `linuxarm64`, `win64-clang`,
`winarm64-clang`. `win64-clang-gpl\.zip$` selects exactly one: `winarm64-clang-gpl.zip` contains
no `win64`, so the ARM sibling is not caught.

## Tests

`ansible/tests/test-github-release-install-win.yml` drives `tasks/select_asset.yaml` — the real task
file — with `connection: local`, no host and no GitHub call:

```
cd ansible
ANSIBLE_ROLES_PATH=roles .venv/bin/ansible-playbook -i localhost, \
  tests/test-github-release-install-win.yml
```

`ANSIBLE_ROLES_PATH` is needed because role resolution is relative to the playbook's directory and
the test lives in `tests/`.

| case | covers |
|---|---|
| C1 | the production pattern selects `win64-clang-gpl.zip` and not its `winarm64` sibling |
| C2 | the stamp is `tag_name` + the *selected* asset's digest |
| C3 | two matches fails the run on the exactly-one assert |
| C4 | zero matches fails there too, rather than crashing on `\| first` |
| C5 | with no `digest`, the stamp falls back to `id:<n>` instead of collapsing to tag-only |

C5 cannot be reached with a live response — GitHub publishes digests now — so it runs against a
constructed fixture. What each fixture is and how far it can be trusted is recorded in
`ansible/tests/fixtures/README.md`.

The selection is in its own task file for exactly this reason: what this role gets wrong, it gets
wrong silently. A pattern matching two assets installs whichever GitHub listed first, and a broken
digest fallback makes a re-uploaded asset invisible forever.

## Why the stamp, and why it carries a digest

A tag alone is not an identity. A release can have its assets replaced in place under an
unchanged tag, and projects do exactly that — re-uploading a rebuilt binary onto the existing
release rather than cutting a new one. A tag-only comparison then matches forever and the host
silently keeps a build the release no longer offers. So the stamp is
`<tag_name> <digest-or-id>`, and the asset's `digest` field (falling back to `id:<n>` on older
API responses) is what makes a silent re-upload visible.

It is also written **last** in the install block. A failed download, extract or copy aborts
before it, leaving the previous stamp — or none — so the next run retries instead of believing
itself converged.

## Replacing a file that is running

Windows holds a file lock on an open executable. If one of the destination files is running, the
`win_copy` fails with *"The process cannot access the file because it is being used by another
process"*. For ffmpeg under Tdarr that means a transcode is in flight.

The role does not retry, wait, or skip. A half-replaced install is worse than a failed run: some
files at the new release, some at the old, and a stamp that never got written claiming neither.
Re-run when the host is idle.

## Differences from `github_release_install`

| | `github_release_install` | this role |
|---|---|---|
| Archive types | `deb`, `tarball`, `binary` | zip only |
| Files per invocation | one (`_binary_in_archive`) | a list (`_files_in_archive`) |
| Idempotency | version command **or** tag stamp | tag stamp only |
| Asset match | `\| first` | asserted to be exactly one |
| Architecture fact | `architecture` | `architecture2` |
| PATH symlink | `_symlink` | none |

**One file or a list.** htpc-01 installs `ffmpeg` and `ffprobe` by looping the whole Linux role
twice: two API calls and two 60 MB downloads to get two files out of one archive. The Windows
asset is 68 MB. One download, one extract, N files copied.

**Stamp only.** Every caller here installs a build whose compiled-in version cannot equal its
release tag — jellyfin-ffmpeg reports `8.1.2-Jellyfin` against a tag of
`v8.1.2-3+nvenc-n13.0.19.1`, so no regex over `-version` can ever match. The version-command mode
would be untested surface for a case that does not arise.

**No symlink.** On Linux that is `file: state=link` into `/usr/local/bin`. Windows has no
equivalent that is a file operation — it is a registry `Path` edit or a shim — and nothing needs
these binaries on `PATH`; Tdarr is handed an absolute `ffmpegPath`.
