# beszel_agent

Installs the Beszel agent from its GitHub releases and runs it as a systemd service, updated daily.
The agent connects out to the hub over WebSocket, as the NixOS hosts' agents do
(`nix/modules/base.nix`). Without a WebSocket connection, the hub reaches the agent over SSH on its
port.

## Status: Production

Runs on every host `configure_server` sets up (`roles/configure_server/tasks/standard.yaml`), and on
the hosts whose playbooks call it directly.

## Inputs

### Required, from `group_vars/all` (no defaults in the role)

- **`beszel_hub_url`**: the hub's URL, scheme included.
  - Without the scheme the agent logs `invalid HUB_URL … must include scheme and host`, never dials the
    hub, and only waits on its port for the hub to connect over SSH.
- **`beszel_token`**: the token the agent presents over WebSocket. Here it is the hub's universal
  token (hub `/settings/tokens`), which lets an agent the hub doesn't know register itself.
  - With a wrong token the WebSocket registration fails, and the host shows in the hub only if the hub
    reaches it over SSH.
- **`beszel_key`**: the hub's public key, which the agent authenticates the hub with.
  - With a wrong key the agent rejects the hub.

### Optional

- **`beszel_agent_port`** (default `45876`): where the agent's SSH server listens (`LISTEN`). It must
  match the port the hub dials for SSH.
- **`beszel_agent_bin_path`** (default `/usr/local/bin/beszel-agent`).
- **`beszel_agent_username`** (default `beszel`): the system user the agent runs as.
- **`beszel_agent_env_path`** (default `/etc/beszel-agent.env`): the root-only file holding `KEY` and
  `TOKEN`.
- **`beszel_agent_extra_filesystems`** (default `[]`): disks to show besides the root one
  (`EXTRA_FILESYSTEMS`).
  - Each entry is a device, a partition or a mount point, optionally followed by `__<name>` for the
    hub's charts, for example `sdc1__Media`.
  - A mount point works whatever the device is called on each host.
  - Empty, the agent shows only the root disk it finds itself. Btrfs filesystems and ZFS pools show
    regardless, as storage pools (agent 0.21.1: `agent/storage_pool.go`, `agent/btrfs/`), so a host
    whose disks are all btrfs or ZFS needs no entry here. Any other filesystem, ext4 or XFS for
    example, shows only when listed.

## Example

`group_vars/all/vars.yaml`, with the values from the vault:

```yaml
beszel_key: "{{ vault_beszel_key }}"
beszel_token: "{{ vault_beszel_universal_token }}"
beszel_hub_url: "https://beszel.{{ domain_name }}"
```

`configure_server` includes the role along with the rest of a host's baseline:

```yaml
- name: Run roles
  ansible.builtin.include_role:
    name: "{{ role_item }}"
  loop:
    - geerlingguy.security
    - fish_install
    - configure_dotfiles
    - beszel_agent
    - topgrade
```

## What it does

1. Installs or updates the binary from `henrygd/beszel`'s latest release (`github_release_install`).
   It picks the asset by architecture: x86_64, aarch64 or armv7l.
2. Installs smartmontools, for the agent's S.M.A.R.T. data.
3. Creates the agent's system user.
4. Writes:
   - the root-only env file (`KEY`, `TOKEN`);
   - the unit (`LISTEN`, `HUB_URL`, `EnvironmentFile`, `EXTRA_FILESYSTEMS` when set, and the group
     and capabilities smartctl needs);
   - a daily `beszel-agent update` timer.
5. Enables and starts the agent and the timer. A changed env file or unit restarts the agent.

## Traps

- **Moving a host from SSH to WebSocket can leave a second system in the hub.**
  - With the universal token the agent registers itself. The entry the hub had for its SSH
    connection then goes stale, as it did for hosts that moved to NixOS.
  - Those moves were reinstalls. How the hub matches an agent switching in place is not documented.
  - Delete a stale entry in the hub; its history goes with it.
- **The hub still falls back to SSH.** "By default, the hub tries to reach an agent over SSH whenever
  that agent has no active WebSocket connection" (beszel.dev, hub `DISABLE_SSH`). So a host whose
  WebSocket fails still reports if the hub can reach its port.
- **`KEY` and `TOKEN` are not in the unit.** The unit is world-readable, and `systemctl show` prints
  its `Environment=` lines to any user. They are in the env file instead, which systemd reads as root
  before starting the agent as its user. The task that writes it has `diff: false`, so `--diff`
  doesn't print them.
- **S.M.A.R.T. needs more than smartctl.**
  - The agent runs as its own user, and smartctl inherits its permissions. The unit adds:
    - the `disk` group, which opens the block devices (`/dev/sdX`, `/dev/nvmeXnY`);
    - `CAP_SYS_RAWIO`, which SATA needs for ATA passthrough;
    - `CAP_SYS_ADMIN`, which NVMe needs for admin commands (beszel.dev/guide/smart-data).
  - Without them, smartctl can't open the disks, and the agent logs `smartctl failed` for each one.
  - The cost: CAP_SYS_ADMIN is close to root, and `disk` can read every disk raw.
  - `NoNewPrivileges=yes` doesn't block the capabilities. It stops privileges being gained from
    setuid or file-capability binaries, and neither the agent nor smartctl is one.
  - NVMe controllers (`/dev/nvme0`) are often `root root 0600`, so `disk` can't open them. The agent
    then reads the namespace (`/dev/nvme0n1`) instead and tries that first from then on (agent
    0.21.1, `agent/smart.go`, `attemptsFor`).
  - eMMC is different: the agent reads its health from sysfs, with no smartctl and no privileges.
    So a host's eMMC root disk can show S.M.A.R.T. data while its NVMe or SATA disks show none.
- **On Debian and Ubuntu, smartmontools also starts smartd.** The package enables and starts
  `smartmontools.service` on a fresh install. Its `ConditionVirtualization=no` skips it in a VM, so it
  runs only on bare metal. It sends no mail without `/usr/bin/mail`: its mail hook
  (`/etc/smartmontools/run.d/10mail`) says so and exits 1.
- **PiKVM's root is read-only.** With `pikvm_os` true, the update service remounts it read-write
  around the update and read-only after.
