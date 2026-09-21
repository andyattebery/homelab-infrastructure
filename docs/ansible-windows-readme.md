# Managing Windows hosts with Ansible

How this repo provisions a Windows machine, and the one-time host-side bootstrap that has to happen
before Ansible can reach it.

`eta` (Windows 11) is the only such host today. Its Ansible account is `andya`; the two names appear
literally throughout, so substitute for a second Windows host.

## Context

Ansible connects to Windows over **SSH**, not WinRM. Official support for the `ssh` connection plugin
against Windows landed in ansible-core 2.18; this repo's venv is on 2.21.3. The minimum Win32-OpenSSH
version is 7.9.0.0, which every Windows 11 build exceeds.

SSH was chosen over WinRM because it is far less to configure in a non-domain environment — no
listener, no certificate, no CredSSP — and because key auth is already how every other host here is
reached.

**Two** Windows collections are available, and they are declared explicitly:
`ansible.windows` (`ansible/requirements.yaml:22`) and `community.windows` (`:47`).
`mise run bootstrap` in `ansible/` installs them with everything else.

`chocolatey.chocolatey` and `microsoft.ad` are **not** available. Nothing declares them, and nothing
bundles them either: `requirements.txt` pins `ansible-core`, not the `ansible` umbrella — its own
comment explains why, and the umbrella is what would otherwise have carried 93 collections along for
the ride. A task referencing a module from either fails at module resolution. Add it to
`requirements.yaml` if one is ever wanted.

To confirm what is actually installed:

```
cd /Users/andy/Projects/homelab-infrastructure/ansible
.venv/bin/ansible-galaxy collection list | grep -iE 'ansible.windows|community.windows|chocolatey'
```

Scope on eta is no longer a connectivity baseline. `playbook-eta.yaml` installs the
`andyattebery/jellyfin-ffmpeg` fork build, deploys the Tdarr node, installs `uv`, and deploys the
gpu-encoder-sweep agent as a boot-triggered scheduled task.

`wsl-01` is a separate inventory entry for the WSL install on the same physical machine, pointed at
the same `eta.<domain_name>:22`. That install is being retired, and as of 2026-08-21 Windows sshd owns
port 22 on that name — so `ansible wsl-01 -m ping` now fails with `Permission denied (publickey...)`
from the *Windows* sshd rejecting the `services` account. That is the retirement showing through, not
a broken inventory. Remove the `wsl-01` entry, `host_vars/wsl-01/`, and `playbook-wsl-01.yaml` once
its services are rehomed.

## Prerequisites

- The connecting account (`andya`) is a member of the local **Administrators** group. Ansible does
  not use `become` here (see Traps), so everything runs with whatever token the SSH login produces.
- Console, RDP, or PiKVM access to the machine. Phases 1-3 all need a UAC elevation that an SSH
  session cannot give you before SSH works.
- `eta.<domain_name>` resolves from the control node.

## Phase 1 — OpenSSH Server

Run in an elevated PowerShell on the Windows host.

```powershell
Get-WindowsCapability -Name OpenSSH.Server* -Online |
    Add-WindowsCapability -Online

Set-Service -Name sshd -StartupType Automatic -Status Running

$firewallParams = @{
    Name        = 'sshd-Server-In-TCP'
    DisplayName = 'Inbound rule for OpenSSH Server (sshd) on TCP port 22'
    Action      = 'Allow'
    Direction   = 'Inbound'
    Enabled     = 'True'  # an enum, not a boolean
    Profile     = 'Any'
    Protocol    = 'TCP'
    LocalPort   = 22
}
New-NetFirewallRule @firewallParams
```

Installing the capability creates the rule and the service on most builds; the block is idempotent
and is here so a rebuild does not depend on remembering which parts Windows did for you.

Check:

```powershell
Get-Service sshd | Format-List Name, Status, StartType
Get-NetFirewallRule -Name sshd-Server-In-TCP | Format-List Name, Enabled, Direction, Action
```

## Phase 2 — Authorized keys

**For members of the Administrators group, sshd does not read `%USERPROFILE%\.ssh\authorized_keys`.**
`C:\ProgramData\ssh\sshd_config` ends with:

```
Match Group administrators
    AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
```

so the only file that counts for an admin login is
`C:\ProgramData\ssh\administrators_authorized_keys`. A key dropped in the user profile is silently
ignored and the connection falls through to password auth — which looks like "the key didn't work"
rather than "the key was never read". This is the single easiest thing to get wrong.

Put the control node's public key in **both** places: the ProgramData file for as long as the account
is an admin, and the profile file so nothing breaks if the account is ever demoted.

```powershell
$key = 'ssh-ed25519 AAAA... andy@mac'

# Admin path — the one that is actually used
Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value $key
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r `
    /grant 'Administrators:F' /grant 'SYSTEM:F'

# Profile path — used if the account is not an admin
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
Add-Content -Path "$env:USERPROFILE\.ssh\authorized_keys" -Value $key
```

The `icacls` line is required, not cosmetic: sshd refuses to read
`administrators_authorized_keys` if any account beyond `Administrators` and `SYSTEM` has access to
it, and logs `Permission denied` without saying why.

## Phase 3 — Default shell

Win32-OpenSSH defaults to `cmd.exe`. Ansible's `powershell` shell plugin emits PowerShell syntax
*outside* the base64 `-EncodedCommand` payload — `wrap_for_exec` returns `& <cmd>; exit $LASTEXITCODE`
(`ansible/plugins/shell/powershell.py:426`) — which `cmd.exe` cannot parse. The upstream docs also
call PowerShell "better tested and should be faster". Treat this as required.

```powershell
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
    -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
    -PropertyType String -Force
```

It applies to the next SSH connection; `sshd` does not need restarting. To revert:

```powershell
Remove-ItemProperty -Path HKLM:\SOFTWARE\OpenSSH -Name DefaultShell
```

The value must agree with `ansible_shell_type` in `ansible/host_vars/eta/vars.yaml`. If you ever
leave `DefaultShell` at the `cmd.exe` default, that var has to be `cmd` instead, and several core
code paths degrade.

## Phase 4 — Verify from the control node

```
cd /Users/andy/Projects/homelab-infrastructure/ansible

# Connection, shell type, and token elevation in one call
.venv/bin/ansible eta -m ansible.windows.win_whoami

# Facts, which exercise the setup.ps1 -> ansible.windows.setup redirect
.venv/bin/ansible eta -m ansible.builtin.setup

# The playbook
.venv/bin/ansible-playbook playbook-eta.yaml
```

What a pass looks like:

- `win_whoami` returns `account.account_name` for the connecting user, and
  `label.account_name: High Mandatory Level` (SID `S-1-16-12288`). `Medium Mandatory Level`
  (`S-1-16-8192`) means the login is not landing in the Administrators group, and later privileged
  tasks will fail in confusing ways.
- `setup` returns Windows facts (`ansible_os_family: Windows`), not a Python interpreter error. If
  `ansible_distribution` and `ansible_os_name` come back `null` while the rest of the facts are
  present, the token is not elevated — `setup.ps1` skips its two WMI-sourced facts on a non-admin
  logon. That is the same signal as `win_whoami`, from a different direction.
- `playbook-eta.yaml` → `failed=0`.

## Traps

**No `become`.** An SSH login by a local Administrator already gets an elevated token, with no UAC
prompt — Win32-OpenSSH runs as SYSTEM and hands over the full token. `become` on Windows buys
credential delegation and needs a password to do it. Every other playbook in this repo opens with
`become: true`; `playbook-eta.yaml` deliberately does not, and the comment saying so should stay.
Setting `become: true` without a `become_user` sends Ansible into the `runas` plugin and fails.

This does **not** mean network paths are out of reach. Key auth produces a `Network` logon with no
delegated credentials, which is the classic double-hop setup — but whether a given share is
reachable depends on that share, not on the logon type. Measured on eta: `Test-Path` on the nas-01
UNC paths returns `True` from an ordinary Ansible session. Test the specific path rather than
assuming either way; reach for `become` only when a test actually fails.

**Replacing a file that is in use.** Windows holds a lock on an open executable, so writing over a
running `.exe` fails with *"The process cannot access the file because it is being used by another
process"*. There is no Linux equivalent of this — there, the old inode simply survives until the
last reader closes it. Any task that updates a binary has to assume the host might be busy, and the
honest response is to fail rather than half-write: some files at the new version, some at the old,
and nothing recording which.

**`architecture2`, not `architecture`.** `ansible_architecture` on Windows is a localized string
(`"64-bit"`) and is `null` on a non-elevated logon. `ansible_architecture2` carries the
POSIX-shaped `x86_64` / `arm64` value. Anything keyed on architecture must use the latter —
`ansible/roles/github_release_install_win/README.md` has the detail.

**No winget.** winget fails in a non-interactive session any time it has to set up its source, and no
installed collection ships a winget module. `community.windows.win_scoop` is available and is the one
to reach for; `chocolatey.chocolatey.win_chocolatey` is **not installed** — see the collections note
above before writing a task against it. Everything installed from a GitHub release here goes through
`roles/github_release_install_win/` instead, which is what both callers on eta use.

**Scheduled tasks.** `community.windows.win_scheduled_task` is how a process is made to survive a
reboot here; there is no service-wrapper tooling in this repo. `roles/gpu_encoder_sweep_node_win/` is
the first and so far only user, and its README carries the detail. Four things are worth knowing
before writing a second one:

- **`logon_type: s4u` stores no password**, which is the property worth having — the account's
  password never enters the vault. The module documents the cost in its own words: "Means no network
  or encrypted files access." A task that must reach a UNC path therefore needs either a
  machine-wide `New-SmbGlobalMapping`, or `logon_type: password` and a stored credential.
- **The account needs `SeBatchLogonRight`.** Registration is the check — the module fails without it
  — and the fix is a `community.windows.win_user_right` task ahead of it. A member of the local
  Administrators group normally holds it already.
- **`execution_time_limit` defaults to three days**, after which the Task Scheduler kills the task
  mid-run. A long-running task needs `PT0S`.
- **A boot trigger can fire before the network is up.** Give it a `delay` if the first thing it does
  needs to resolve a name or fetch anything.

**Backslashes in YAML.** Unquoted and single-quoted scalars pass `\` through untouched; double quotes
make it an escape character. `C:\Windows\Temp` and `'C:\Windows\Temp'` are correct;
`"C:\Windows\Temp"` yields `C:\Windows<TAB>emp`.

Building a path from parts:

- `| path_join` always yields **forward** slashes. It is controller-side `os.path.join`, and the
  controller is always POSIX because Ansible cannot run on Windows.
- `| join(sep)` with `sep: "\\"` defined in **YAML** yields backslashes. The same thing written as a
  Jinja literal, `join("\\")`, silently joins with *two* — Ansible does not unescape `\\` inside a
  Jinja string literal.
- A single `"\"` cannot be written as a Jinja string literal at all: the lexer takes it as escaping
  the closing quote.

**Which core modules work.** Most `ansible.builtin` modules are Python and will not run on Windows.
The ones that do: `add_host`, `assert`, `async_status`, `debug`, `fail`, `fetch`, `group_by`,
`include*`, `meta`, `pause`, `raw`, `script`, `set_fact`, `set_stats`, `setup`, `slurp`, `template`,
`wait_for_connection`. Everything else needs a `win_*` equivalent.

**No SSH multiplexing.** Win32-OpenSSH lists "Client ControlMaster" among the features "scoped out
and will not work on Windows yet". `ansible/ansible.cfg` already sets `ssh_args = -o ControlMaster=no`
globally, so this is handled — but do not add `ControlPersist` back for the Linux hosts without
excluding Windows.

## Reference

- ansible-core 2.21 — [Windows SSH](https://docs.ansible.com/projects/ansible-core/2.21/os_guide/windows_ssh.html)
- ansible-core 2.21 — [Managing Windows hosts with Ansible](https://docs.ansible.com/projects/ansible-core/2.21/os_guide/intro_windows.html)
- ansible-core 2.21 — [Using Ansible and Windows](https://docs.ansible.com/projects/ansible-core/2.21/os_guide/windows_usage.html)
- [Win32-OpenSSH](https://github.com/PowerShell/Win32-OpenSSH)
- [Win32-OpenSSH — Project Scope](https://github.com/PowerShell/Win32-OpenSSH/wiki/Project-Scope) (what does not work on Windows)
- [OpenSSH Server Configuration for Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration) (`administrators_authorized_keys` permissions)
