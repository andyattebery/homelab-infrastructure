# tdarr_node_win

Installs a Tdarr node on a Windows host and manages selected keys in `Tdarr_Node_Config.json`.

**It installs. It does not update.** On a host that already has Tdarr it does not run the updater
and does not touch `Tdarr_Updater_Config.json` — see
[Why the updater runs only on bootstrap](#why-the-updater-runs-only-on-bootstrap) and
[Updating Tdarr afterwards](#updating-tdarr-afterwards).

## Status: Written and unit-tested; no successful end-to-end run yet

## Required inputs

None.

## Optional inputs

### `tdarr_node_win_install_dir`

Default `C:\Program Files\Tdarr` — where Tdarr's own installer puts things. The role creates it and
`configs\` beneath it, places `Tdarr_Updater.exe` in the first, and merges the node config in the
second. Point it elsewhere and the role creates that directory instead; it does not move an existing
install.

Note that it is one input and the [node config inputs](#node-config-inputs) are nine others. Nothing
derives from it — overriding it redirects where files land and changes nothing about what is written
into the config.

### `tdarr_node_win_owner`

Default `{{ ansible_user }}` — the identity that runs Tdarr: the tray app, and any by-hand
`Tdarr_Updater.exe` run. It is granted **Full Control** of the install directory on every run.

That grant is not optional. Under `C:\Program Files` a new directory inherits that tree's ACLs,
where only administrators can write, and the updater runs as the logged-in user. Without it the
updater fails.

`inherit` is left at the module default, which `ansible-doc ansible.windows.win_acl` documents as
`ContainerInherit, ObjectInherit` for directories. That is relied on: the updater creates
`.staging\`, `Tdarr_Node\` and the rest *after* the ACE exists, and they inherit it.

**On a bootstrap this must be the connecting user, and the role asserts it.** The startup shortcut
can only be written into `ansible_user`'s profile, so a different value would grant permissions to
one account and autostart Tdarr for another.

Worth knowing rather than arguing: a standard user with Full Control on a subtree of
`C:\Program Files` can replace the binaries in it. That is inherent to running Tdarr from there as
that user.

## Node config inputs

Nine keys of `Tdarr_Node_Config.json` can be managed. **All are optional, and unset means
unmanaged** — the key is left exactly as the host has it. Absent from `defaults/main.yaml` on
purpose, so `is defined` distinguishes "not set" from "set to empty".

| var | JSON key | type |
|---|---|---|
| `tdarr_node_win_node_name` | `nodeName` | str |
| `tdarr_node_win_server_url` | `serverURL` | str |
| `tdarr_node_win_ffmpeg_path` | `ffmpegPath` | str |
| `tdarr_node_win_path_translators` | `pathTranslators` | list |
| `tdarr_node_win_node_type` | `nodeType` | str |
| `tdarr_node_win_unmapped_node_cache` | `unmappedNodeCache` | str |
| `tdarr_node_win_priority` | `priority` | int |
| `tdarr_node_win_api_key` | `apiKey` | str |
| `tdarr_node_win_log_level` | `logLevel` | str |

Three things about this that are not obvious:

**It merges, it never replaces.** Any key the host has that is not in the table survives, including
keys a future Tdarr version adds. A whole-file render would strip those on the next run, which
turns a second play run into damage.

**Outside bootstrap it never creates the file, only merges into it.** On a host where Tdarr is
installed but has no config, the role says so and skips — it does not invent one. The single
exception is bootstrap, which writes the complete skeleton described under
[The role writes the initial config because nothing else will](#the-role-writes-the-initial-config-because-nothing-else-will);
that is what lets a fresh host converge in one run. The role starts no process, ever.

**It does not convert path separators.** Tdarr wants forward slashes for local paths
(`C:/Program Files/...`) and backslashes for UNC (`\\host\share`) — counter-intuitive, and its
own documentation says so. Values are passed through exactly as written. Getting that right is the
caller's job, in `host_vars`.

`priority` must be an `int` and `path_translators` a `list`; the role asserts both. Types are not
cosmetic — the file is compared by parsed value, so `-1` and `"-1"` are different configs.

`pathTranslators` is replaced wholesale when set, not appended to. `combine`'s `list_merge`
defaults to `replace`; appending would grow the list on every run.

## Example

From `playbook-eta.yaml`:

```yaml
- name: Deploy the Tdarr node
  tags: tdarr
  ansible.builtin.include_role:
    name: tdarr_node_win
    apply:
      tags: tdarr
  vars:
    tdarr_node_win_path_translators: >-
      {{ eta_tdarr_media_raw_translators
         + [{'server': '/media', 'node': eta_tdarr_storage_unc},
            {'server': '/temp', 'node': eta_tdarr_transcode_cache}] }}
```

**That is the whole `vars:` block, and the omission is the point.** Every other input —
`_updater_version`, `_install_dir` and the eight remaining config keys — is set in
`host_vars/eta/vars.yaml`, not here. An `include_role` param outranks `host_vars`, so setting one in
both places means this block silently wins over the file the tests assert against. `pathTranslators`
is the exception because it is the one value that has to be assembled at the call site.

`apply:` is required, not decorative: a tag on an `include_role` task gates the include itself and
does not propagate to the tasks inside the role.

## Tests

`ansible/tests/test-tdarr-node-win-config.yml` drives the role's computation directly — the real
task files, not copies of their expressions — with `connection: local`, no host contacted and no
network:

| task file | what it decides | cases |
|---|---|---|
| `tasks/set_node_config.yaml` | the nine managed keys merged over the host's config | C1-C8, C10-C12 |
| `vars/main.yaml` (the skeleton) | the 17-key file a fresh host gets | C9, C13, C20 |
| `tasks/select_updater_url.yaml` | which updater to download, and from what URL | C14-C16 |
| `tasks/check_updater_result.yaml` | whether an updater run failed | C17-C19 |

The last two exist as separate files **because** they need testing. `check_updater_result.yaml` is
the whole failure detector for a tool that dismantles an install and then exits 0, so the string
check is the only thing standing between a failed play and silent destruction.

Every case has a positive control — the mutation that must make it fail is recorded in
`ansible/tests/fixtures/README.md` alongside where each fixture came from. Two lessons are baked in
there: against the *live* version index `sort` and `version_sort` agree, so live data cannot test
the filter choice; and the real default config's install directory is already forward-slashed, so it
cannot test `regex_replace` against `replace` either. Both needed fixtures built to discriminate.

```
cd ansible
ANSIBLE_ROLES_PATH=roles .venv/bin/ansible-playbook -i localhost, tests/test-tdarr-node-win-config.yml
```

The computation is split out of `main.yaml` into `set_node_config.yaml` precisely so it can be
tested this way. `ANSIBLE_ROLES_PATH` is needed because role resolution is relative to the
playbook's directory and the test lives in `tests/`.

## Which updater gets installed

Not a pinned version. The role fetches `https://storage.tdarr.io/versions.json`, selects the newest
version that publishes a `win32_x64` `Tdarr_Updater`, and takes the download URL from the index.

That is not ceremony over a version string. **Most versions do not publish an updater at all** —
2.86.01, 2.85.01, 2.84.01, 2.83.01 and 2.82.02 have no `Tdarr_Updater` key, and 2.81.01 is the
newest that does. Assembling `https://storage.tdarr.io/versions/<version>/win32_x64/Tdarr_Updater.zip`
from a version number produces a well-formed 404 for any of them; selecting from the index cannot.

The updater's version is **not** the module version and does not need to match anything — one host
here ran updater `2.81.01` against modules `2.85.01`. The updater tracks the node and server loosely.

`community.general.version_sort`, not `sort`: plain string order puts `2.9` after `2.10`.

**It is downloaded only when `Tdarr_Updater.exe` is absent, and never replaced.** It runs once, to
bootstrap; after that updates are manual, so there is no version here to keep current. To refresh
it, delete it and re-run.

Consequence, stated rather than buried: two hosts bootstrapped months apart can get different
updaters. For a tool used once and then driven by a human, that is acceptable.

## Updating Tdarr afterwards

By hand, and that is not a limitation to work around.

`Tdarr_Node.exe` has no graceful stop — no CLI surface at all; `--help`, `-h`, `/?` and `--version`
are ignored. From Ansible a "stop" is `taskkill` on a process that may be mid-transcode. Doing it
safely would mean pausing the node through the server API and polling until its jobs drain: server
API, an apiKey, and a wait loop, to replace what a human does by watching the UI.

A human can observe drain state. Ansible cannot, cheaply. That is where the line falls.

The procedure: pause the node in the Tdarr UI, wait for its jobs to drain, quit the tray app, run
`Tdarr_Updater.exe`, start the tray again. The server and its nodes have to move together, and only
a human knows when that is.

## Why the updater runs only on bootstrap

`Tdarr_Updater.exe` is **destructive when it fails, and exits 0**. Its sequence is: extract the new
module to `.staging`, move the live tree aside, then put the new one in place. With a node running
it completes the first two steps and only then hits a file `Tdarr_Node_Runtime.exe` holds open:

```
[ERROR] Tdarr_Updater - Tdarr_Node | Access is denied. (os error 5)
[INFO]  Tdarr_Updater - Finished!
```

Return code 0. What it leaves is a gutted install. Observed on a real host: `assets\`,
`node_modules\` and `public\` removed, `Cannot find module 'adm-zip'` on every subsequent plugin
refresh, and nothing in the updater's own `toDelete` to restore from. `currentVersion` does not move
either, which is exactly what a converged run looks like — so the exit code and the version record
together still report "nothing happened".

Two earlier versions of this role ran the updater and tried to detect that afterwards — first by
grepping stdout for `[ERROR]`, then by refusing to run while a node process was up. Neither is good
enough: by the time an error line exists the install is already dismantled, and a guard only covers
the failure modes you thought of. Both guard against a state the role puts itself in.

So the role keeps it away from anything already installed. The updater runs **only when
`<install_dir>\Tdarr_Node\` does not exist** — nothing to dismantle, nothing holding a lock.

### The gate is the directory, and that choice is about which way it fails

It stats `Tdarr_Node\`, not `Tdarr_Node\Tdarr_Node.exe` inside it, because the two failure
directions do not cost the same:

| gate is wrong | result |
|---|---|
| skips when it should have run | green play, nothing installed — visible, recoverable |
| runs when it should have skipped | the updater dismantles a real install |

A tree that is missing only its exe is exactly the second case. That is not hypothetical: on the
host above, `assets\`, `node_modules\` and `public\` were destroyed and `Tdarr_Node.exe` survived by
luck. Had the failure taken the exe instead, an exe-gate would have run the updater on the wreckage.

So anything present at all means skip, and a partially-extracted tree needs a human. That is the
right trade: it costs a failed bootstrap that has to be cleaned up by hand, and it buys never
running the updater against files somebody cares about.

**This is one boolean.** It is not a structural impossibility, and nothing here should be read as
claiming the destructive path cannot be reached — only that it is gated in the direction that fails
safely.

There is deliberately **no process check**. A node that is merely stopped passes it, which is the
state a damaged install is usually in, so it would read as protection while providing none.

### Trap: a failed bootstrap does not retry

Once the updater has created `Tdarr_Node\`, the gate is false on the next run and the whole
bootstrap block is skipped — no startup shortcut, no config, a half-installed host and a green play.
The `[ERROR]` check makes the first failure loud; nothing makes the second run notice.

Recovery is manual: remove the partial `Tdarr_Node\` and re-run, or finish the install by hand.

## What bootstrap does

On a host with no `Tdarr_Node.exe`, in order:

1. runs `Tdarr_Updater.exe`, which installs the modules
2. asserts `tdarr_node_win_owner` is the connecting user
3. creates a startup shortcut to `Tdarr_Node_Tray.exe` in that user's Startup folder
4. writes a complete default `Tdarr_Node_Config.json` — see below

Step 4 is why a fresh host converges in one run: the config has to exist before the merge that
follows has anything to merge into. Autostart is created **on bootstrap only** — a shortcut later moved or
deleted is left alone.

### The role writes the initial config because nothing else will

The node **does not create its own config. It polls for one.** Observed on a real host:

```
Polling for config file to exist: ...\configs\Tdarr_Node_Config.json
Unable to check server engine: Get "http://0.0.0.0:8266/api/v2/status": connection refused; retrying in 5s
```

and it sits there indefinitely. `Tdarr_Node_Tray.exe` over SSH does not write one either — 60
seconds, process alive, no file. Only an interactive tray session produces it, which is no use to a
playbook. And there is no CLI surface to coax one out: `--help`, `-h`, `/?` and `--version` are all
ignored, and the launcher just starts polling in each case.

A written config is accepted immediately — `Config file found after 0ms` — so the role writes one.

**The skeleton in `vars/main.yaml` is complete: all 17 keys**, including the 9 this role can also
manage. That is deliberate. It means the file is valid on its own and does not depend on which
`tdarr_node_win_*` vars a caller happened to set, and the merge is then purely an overlay of
preferences. The values are **not** taken from the documentation — they are lifted from a real default config,
generated by pointing the tray app at a fresh install. That distinction is load-bearing: the docs
give `serverURL` as `http://192.168.1.100:8266` where the real default is `http://0.0.0.0:8266`, and
they do not mention `logLevel` at all. Two keys deviate from that reference, both noted in
`vars/main.yaml` with the reason.

The write uses `force: false`, which `ansible-doc ansible.windows.win_copy` defines as "the file
will only be transferred if the destination does not exist". That is a hard guarantee it can never
overwrite a real config, and it holds independently of the bootstrap gate.

## `architecture2`, not `architecture`

The role asserts `ansible_facts['architecture2'] == 'x86_64'`, because Tdarr's version index
publishes only a `win32_x64` Windows build — there is no `win32_arm64`.

It must be `architecture2`. On Windows, `ansible_architecture` is a **localized** string from
`Win32_OperatingSystem.OSArchitecture` (`"64-bit"` on an English install) and is `null` outright
when the connecting token is not in the Administrator role — `setup.ps1` skips the WMI call rather
than eat a five-second access denied. `ansible_architecture2` is the non-localized, POSIX-shaped
value: `i386`, `arm`, `ia64`, `x86_64`, `arm64`.

`ansible.windows.setup` ships no `RETURN` documentation, so the fact list is not published. To see
what a given host returns, run `ansible <host> -m setup`.
