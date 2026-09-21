# gpu_encoder_sweep_node_win

Deploys the gpu-encoder-sweep agent natively on a Windows host: `uvx` runs the package straight from
git, a templated PowerShell launcher carries the three variables the agent reads, and a
boot-triggered scheduled task starts it.

Native rather than containerised because a WSL2 container has no GPU Vulkan, so the encoder has to
run on Windows itself. The scoring half of this machine is a container elsewhere, reading this
host's work root through its own `local_view` — which is why nothing here scores.

## Status: Fixture-tested where it can be, wired into `playbook-eta.yaml`; the boot task is not yet registered live

Only two parts of this role have fixtures: the input asserts and the launcher template. Everything
else is a `win_*` module, and there is no Windows runner and no CI here. *Verification* below is what
covers the rest, and it is not optional — it is the only evidence this role works.

## Inputs

Required — no default that can work, all asserted before anything is written:

- `gpu_encoder_sweep_node_win_hub_url` — `SWEEP_HUB`.
- `gpu_encoder_sweep_node_win_token` — `SWEEP_TOKEN`, this host's token from vault, not the
  operator's. Asserted by length only, so nothing reaches the play output.
- `gpu_encoder_sweep_node_win_host` — `SWEEP_HOST`, the **host row** name. Not the inventory name:
  this machine carries a second row for the scorer that reads its work root.
- `gpu_encoder_sweep_node_win_work_root` — an absolute Windows path, single-quoted in YAML. Also the
  task's working directory and where the agent's log goes.
- `gpu_encoder_sweep_node_win_uv_dir` — the directory holding `uvx.exe`. This role does not install
  uv; see *What this role does not do*.

Optional, all with defaults in `defaults/main.yaml`:

- `gpu_encoder_sweep_node_win_install_dir` — default `C:\Program Files\gpu-encoder-sweep`. **Its own
  directory, never shared** — the role rewrites the whole ACL on it.
- `gpu_encoder_sweep_node_win_package_repo_url` / `_package_version` — default the harness repo and
  `main`. Together they are the `uvx --from` spec. **`_package_version` is a GIT REF** — a branch, a
  tag, or a commit sha — **not a container tag.** The three container roles in this family pin
  `sha-<short>` because that is what CI tags the images with; the harness repository has no tags at
  all, so a `sha-`-prefixed value here resolves to nothing and the agent fails at its first boot,
  unattended, with a git error in a log nobody is watching. See *The version is a campaign decision*.
- `gpu_encoder_sweep_node_win_owner` — **required, no default.** The account the task runs as, as a
  bare name; the role adds the `.\` prefix where a module needs it. Deliberately not the connecting
  user: see *Why a dedicated service account*. Wrong value and the task registers against an identity
  with no rights on the work root or on uv, and fails at its first boot.
- `gpu_encoder_sweep_node_win_task_name` / `_script_name` — default `gpu-encoder-sweep-node` and
  `gpu-encoder-sweep-node.ps1`. Both show up in Task Scheduler.
- `gpu_encoder_sweep_node_win_logon_type` — default and **only accepted value** `password`. s4u is
  rejected by the asserts; see *Why a dedicated service account*.
- `gpu_encoder_sweep_node_win_password` — **required.** The service account's password, from the
  vault. Passed with `no_log`, because the module marks it no_log nowhere.
- `gpu_encoder_sweep_node_win_update_password` — default `false`. Leave it: the module documents that
  a set password *"will always result in a change unless update_password is set to no"*, so `true`
  makes the task re-register and report changed on every single apply.
- `gpu_encoder_sweep_node_win_ffmpeg_path` — **required.** Full path to `ffmpeg.exe`, for the boot
  NVENC probe. See *What the launcher logs at every boot*.
- `gpu_encoder_sweep_node_win_boot_delay` — default `PT1M`. The first run of a pinned version
  resolves and downloads from GitHub, so the network has to be up; a boot trigger on its own can fire
  before it is. Lower it on a fast host, raise it if the first boot log shows a resolution failure.
- `gpu_encoder_sweep_node_win_relaunch_interval` — default `PT5M`. The repetition on the boot
  trigger. See *The repetition is the supervision*.

## Example

From `playbook-eta.yaml`. **The uv install comes first and is not part of this role**, exactly as the
jellyfin-ffmpeg install already works on this host:

```yaml
# The role does not create its destination — ACLs on it are the caller's business.
- name: Create uv directory
  tags: [gpu_encoder_sweep, uv]
  ansible.windows.win_file:
    path: "{{ eta_uv_dir }}"
    state: directory

- name: Install uv
  tags: [gpu_encoder_sweep, uv]
  ansible.builtin.include_role:
    name: github_release_install_win
    # Required: tags on an include_role task gate the include itself, they do not propagate to
    # the tasks inside the role.
    apply:
      tags: [gpu_encoder_sweep, uv]
  vars:
    github_release_install_win_repo: astral-sh/uv
    # uv publishes aarch64, i686 and x86_64 Windows zips, each with a .sha256 sidecar, and the role
    # fails the run on anything but exactly one match. Measured: this matches 1, dropping the
    # trailing $ matches 2 (the sidecar), `pc-windows-msvc\.zip$` alone matches 3.
    github_release_install_win_asset_patterns:
      x86_64: '^uv-x86_64-pc-windows-msvc\.zip$'
    github_release_install_win_files_in_archive: [uv.exe, uvx.exe]
    github_release_install_win_dest_dir: "{{ eta_uv_dir }}"
    github_release_install_win_release_tag: "0.12.10"

- name: Deploy the gpu-encoder-sweep node agent
  tags: gpu_encoder_sweep
  ansible.builtin.include_role:
    name: gpu_encoder_sweep_node_win
    apply:
      tags: gpu_encoder_sweep
  vars:
    gpu_encoder_sweep_node_win_hub_url: "https://ges-hub.{{ domain_name }}"
    gpu_encoder_sweep_node_win_token: "{{ gpu_encoder_sweep_agent_tokens['eta'] }}"
    gpu_encoder_sweep_node_win_host: eta
    gpu_encoder_sweep_node_win_work_root: "{{ eta_sweep_work_root }}"
    gpu_encoder_sweep_node_win_uv_dir: "{{ eta_uv_dir }}"
    gpu_encoder_sweep_node_win_package_version: "4d7c4e0"
```

The two Windows paths come from `host_vars`, not from the playbook, because **they carry
backslashes and YAML is the only place those can be written safely**: unquoted and single-quoted
scalars pass `\` through untouched, while double quotes make it an escape character, so
`"D:\sweep"` is `D:`, a tab, and `weep`. `github_release_install_win` also needs a distinct
`_tag_stamp_path` per caller if two callers ever share a destination — they do not here, since uv
and ffmpeg get their own directories.

Note `github_release_install_win` keys its pattern dict on `ansible_architecture2`, **not**
`ansible_architecture`: the latter is a localized string (`"64-bit"`) and is null outright on a
non-elevated logon.

## Why a scheduled task, and not a shortcut or a service

A Startup shortcut — which is how the Tdarr node on this host autostarts — fires only on interactive
logon. After a reboot with nobody logged in, the agent is simply absent and the hub shows a dead
runtime. That is acceptable for a tray app and not for a measurement runtime, where an absent agent
means a campaign quietly stops making progress.

There is no service here because the harness ships no service wrapper and this repo has no
service-wrapper tooling. The scheduled task *is* the supervision — and with the repetition below it
is not a weaker one. A real service would buy `Get-Service` visibility and SCM failure actions, at
the cost of a third-party wrapper binary (`github_release_install_win` is zip-only and WinSW ships a
bare `.exe`) and a second file the token can leak into.

## Why a dedicated service account

The account is a purpose-made local one, not the connecting user and not SYSTEM, and the reasoning is
worth keeping because every alternative looks cheaper than it is.

**A boot task needs a stored password whatever the identity.** `logon_type: s4u` was the original
choice precisely to avoid one — it does not work. The module refuses to register an s4u task without
a password anyway (`win_scheduled_task.ps1:739-741`); Windows takes it once at
`RegisterTaskDefinition` and does not store it, but Ansible must still hold it, so the property was
never achievable this way. Worse, an S4U task firing before a logon is documented to trigger
credential loading early and leave lsass with the empty-string hash, **wiping that account's
Credential Manager**. The role now rejects s4u outright rather than letting a stale playbook reach it.

**The only passwordless logon type cannot do the job.** `logon_type: service_account` is restricted to
SYSTEM / LOCAL SERVICE / NETWORK SERVICE (`:748`). None of them can start this machine's WSL distro,
which is registered in a user hive — so a single identity cannot be both passwordless and useful here.

**So the question is whose password, not whether.** A generated service credential is rotatable and a
leak is contained to one service; a person's login is neither. The account is denied interactive and
remote-interactive logon by the calling play, so its name states a contract that is actually enforced.

**What it costs, and what the play therefore grants.** A fresh account inherits nothing useful: it is
not an Administrator, so it needs `SeBatchLogonRight` explicitly, and nothing establishes that it
lands in `BUILTIN\Users`, so it needs an explicit ACE on the uv directory as well as on the work root.
Those grants live in `playbook-eta.yaml`, not here — this role deploys one application, it does not
own the machine's accounts or its security policy. ⚠ Every `win_user_right` call there passes
`action: add`; the module's default is `set`, which *replaces* a right's holders.

## What the launcher logs at every boot

Two lines, in the only context that can produce them — an Ansible session runs as a different account
with a different token, so it cannot answer either on the task's behalf.

There used to be a third, a `Test-Path` on the pool's share, and its removal is the headline of this
role's history. This runtime could not reach SMB at all: a boot task's token carries no credential,
Windows refuses unauthenticated guest SMB by default, and there is no supported way to hand the task's
identity a credential that a network logon cannot also reach — so `New-SmbGlobalMapping`, a global
`Z:` and several other routes were tried and none worked. The harness then removed the requirement
entirely: a file crosses machines through the hub's HTTPS API, and `host.share_root` no longer exists
in its schema. The problem was deleted rather than solved.

1. **identity** — `whoami` and the session id, so the log says what actually ran.
2. **NVENC** — a one-frame `av1_nvenc` encode, discarded. `logon_type: password` performs a **batch**
   logon, which lands in **session 0**, and the session-0 NVENC failures people report are D3D11
   device creation with no interactive desktop; ffmpeg's `*_nvenc` takes the CUDA path instead.
   Measured green on eta from a session-0 logon before this was wired in — `sessionId 0`, exit 0 —
   so this line is a per-boot confirmation rather than an open question.

Both are logged, never fatal. A runtime that cannot encode should be visible as a bad probe line
and a failing run, not as a host that silently never appeared.

The account needs `SeBatchLogonRight` to run a task at all. **Registration is the check**: the module
fails if the right is missing, and the fix is a `community.windows.win_user_right` task ahead of it.
An account in the local Administrators group normally holds it already.

Two settings on the task are worth knowing about:

- `multiple_instances: 2` — do not start a second instance while one is running. Two agents for one
  host row would both heartbeat and both claim, and the hub would hand runs to what it thinks is one
  agent.
- `execution_time_limit: PT0S` — no limit. The default is three days, after which the Task Scheduler
  kills the task mid-run; this agent is meant to run until the machine reboots.

## The launcher holds the token, and `mode:` is inert on Windows

This is the third instance of one problem across these four roles: the obvious place to put an
environment variable is world-readable on every runtime. On the container hosts the answer is `.env`
at `0600`; in the quadlet it is an `EnvironmentFile` at `0600`; here it is an NTFS ACL, because
`mode:` does nothing on Windows and a new directory under `C:\Program Files` inherits an ACL that
grants `BUILTIN\Users` read.

**The role authors the whole ACL rather than removing the `Users` ACE**, and that is deliberate.
`ansible.windows.win_acl` matches an existing rule on identity *and* rights *and* type *and*
inheritance *and* both flag sets before it will remove anything (`win_acl.ps1:227-238`); anything
short of an exact match is a silent no-op reporting `changed: false`. Here that would mean reporting
success while leaving a bearer token readable by every local account. Three ACEs we wrote are
checkable; one removal we hope matched is not.

So: inheritance is broken with `reorganize: false`, then three ACEs are granted —
`BUILTIN\Administrators` and `NT AUTHORITY\SYSTEM` full control, and the task account read-and-execute
— and the launcher is templated afterwards so it inherits exactly those. A `win_powershell` task then
reads the file's effective ACL and **fails the play** if `BUILTIN\Users` still appears.

One consequence to know: `reorganize: false` drops the inherited ACEs rather than copying them down,
so between that task and the three grants the directory has an empty DACL and only its owner can
reach it. That window is three tasks long and this directory belongs to no other role — but a run
that dies inside it leaves a directory an administrator has to take ownership of. That is also why
the install directory must not be shared with another role's.

## `uvx`, not a zipapp and not an executable

`uvx` collapses interpreter, dependency resolution and entry point into one command. A zipapp
collapses only the last two and still needs a Python on the host, which here would most likely be
installed by uv — two artifacts where there was one, with the uv dependency intact. That is why the
`pyz` mentioned in the harness's architecture notes would not simplify this role, and nothing builds
one today.

**The real defect in this path is pinning, not packaging, and it is not this repo's to fix.** The
three container images run `uv sync --locked`; `uvx --from "<pkg>[node] @ git+…"` installs from
package metadata instead — `uv.lock` is a project lockfile consumed by `uv sync` and `uv run`, not by
`uvx --from` against an external spec — and the `node` extra carries no version constraint. So this
host can resolve a different httpx than every other runtime, decided by whatever resolves on first
run, on the machine whose timings are being measured. One line in the harness's `pyproject.toml`
(`node = ["httpx==0.28.1"]`) closes it.

If an artifact is ever wanted here, the shape that actually removes work is a single-file executable:
no interpreter, no dependencies, no git, no network at start, pinned at build time, installed by
`github_release_install_win` exactly as jellyfin-ffmpeg already is. It would also let this host report
a stamped artifact instead of the `uvx:<version>` fallback.

## The version is a campaign decision

`main` is the right default and the wrong thing to be running during a campaign. The hub hands a run
only to an agent whose reported artifact matches the one the run was planned for, so a version that
moves under already-planned runs changes the artifact and **every claim then answers 409** until the
runs are re-planned.

It matters more here than on the container hosts: there is no `/etc/sweep-artifact` outside the
images, so this agent reports `uvx:<version>` and nothing else. The version in the playbook is the
only thing that distinguishes one build from another in the record.

## The repetition is the supervision

This role used to carry `restart_count` / `restart_interval`, which supervised only a **failed** task
and gave up after three attempts over fifteen minutes. It has been replaced by a `repetition` on the
boot trigger, with `duration` left unset — the module documents an unset duration as repeating
indefinitely — and `multiple_instances: 2` (IgnoreNew), so each firing is a no-op while the agent is
running and a restart when it is not, however it stopped.

That is a genuine `restart: unless-stopped` equivalent and it removes the old caveat: an agent
deployed before its host row exists now recovers on its own once the row is authored, instead of
needing a hand-start. Authoring the catalogue first is still the right order, but it is no longer
load-bearing on this runtime.

## What this role does not do

- **It does not install uv.** The play does, through `github_release_install_win`, because that role
  does not create its own destination directory and the ACLs on it are the caller's business. This
  role stats `uvx.exe` and refuses if it is missing, so a forgotten prerequisite fails at deploy time
  rather than at the first unattended boot.
- **It does not set an ACL on the work root.** That directory can already hold this machine's stage
  cuts, and a role that asserted ownership over a directory it did not fill would take it away from
  whatever put them there.

## Tests

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook \
    -i roles/gpu_encoder_sweep_node_win/tests/inventory \
    roles/gpu_encoder_sweep_node_win/tests/test.yml
```

Covers the input asserts (imported on their own through `tasks_from: assert`, which is why they live
in their own file) and a real render of the launcher: the three environment assignments, the uvx
spec, the derived paths, that no Jinja delimiter survives, and that an apostrophe in the token is
doubled so the PowerShell literal still closes where it should.

Two of those have been shown to go red by making the change and watching the case fail: dropping the
apostrophe escaping, and dropping the `[node]` extra from the uvx spec.

## Verification

None of the `win_*` half is fixture-testable, so this is the evidence, on the host:

```powershell
Get-ScheduledTask -TaskName 'gpu-encoder-sweep-node' | Format-List TaskName, State
Get-ScheduledTaskInfo -TaskName 'gpu-encoder-sweep-node' | Format-List LastRunTime, LastTaskResult
(Get-Acl 'C:\Program Files\gpu-encoder-sweep\gpu-encoder-sweep-node.ps1').Access |
    Format-Table IdentityReference, FileSystemRights
Get-Content '<work root>\node-agent.log' -Tail 40
```

What a pass looks like: the task is registered with a boot trigger, `LastTaskResult` is 0, the ACL
lists no `BUILTIN\Users` entry (the role already fails the play if it does), and the log's first
lines show the host and hub it started with, which identity and session actually ran, and whether
NVENC initialised **from the task's own token**.

**The check that actually matters is a reboot with nobody logged in**, after which `sweep status`
still shows this host's heartbeat. That is the whole reason for choosing a task over a shortcut, and
nothing else tests it.
