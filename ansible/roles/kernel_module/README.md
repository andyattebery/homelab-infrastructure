# kernel_module

Loads a kernel module and keeps it loaded across reboots.

## Status: In use — `playbook-vdesktop-01.yaml`, play 1, loads `uinput` with it.

A thin wrapper over `community.general.modprobe`, and deliberately thin. It exists because the
state this repo keeps ending up in is *"someone ran `modprobe` by hand"*: correct until the next
reboot, and then a container that will not start, with nothing on disk to explain why.

## Inputs

Required:

- `kernel_module_name` — the bare module name, e.g. `uinput`. Letters, digits, `_`, `-`.
  Asserted, with no default. Wrong: a name that does not resolve does nothing at all (the
  module reports failure, but a *typo* that happens to name a real module loads that instead).
  A **path** (`/lib/modules/…/uinput.ko`) is refused — `modprobe` resolves names against the
  running kernel's module tree, and the persisted file would be named after the path.

Optional:

- `kernel_module_state` — `present` (default) or `absent`. Drives the running kernel **and** the
  boot configuration together. Wrong: nothing else is accepted, and `absent` really does unload
  — see below.
- `kernel_module_params` — module parameters, e.g. `numdummies=2`. Default empty. These persist
  to `/etc/modprobe.d/`, a **different file** from the load list, and they only take effect at
  the next load — setting them on an already-loaded module changes nothing until it is
  reloaded.

## Example

Lifted from `playbook-vdesktop-01.yaml`, play 1, where it runs **before** `pve_lxc`:

```yaml
- name: Load uinput on the node, now and at every boot
  ansible.builtin.include_role:
    name: kernel_module
    apply:
      tags: [uinput]
  tags: [uinput]
  vars:
    kernel_module_name: uinput
```

That ordering is load-bearing, not tidiness. PVE resolves a `dev[n]` passthrough by calling
`PVE::LXC::Tools::get_device_mode_and_rdev()` on the **host** path to read its major and minor,
so `/dev/uinput` has to exist on the node before the container starts or the start fails. And
`uinput` is not auto-loaded on a headless node: the misc-device alias
(`MODULE_ALIAS_MISCDEV(UINPUT_MINOR)`) only fires when something opens the node, and nothing on
a hypervisor does.

## `state` drives the running kernel and the boot config together

`community.general.modprobe` has two independent options — `state` for the running kernel,
`persistent` for the boot configuration. This role sets both from one input, because *"loaded
now but not after a reboot"* is not a state anyone wants on purpose. It is exactly what a
hand-run `modprobe` leaves behind, and it is the failure this role exists to end.

The consequence is that **`absent` unloads the module**, and that fails loudly if anything is
using it. That is the correct outcome: a module still in use is one a running guest or service
depends on, and *"removed from the boot config, still loaded"* is a state that survives
undetected until a reboot nobody connects to the change.

## Where the files land

Verified against `community.general` 13.3.0 (`plugins/modules/modprobe.py`), not assumed:

| what | where | written by |
| --- | --- | --- |
| the module name | `/etc/modules-load.d/<name>.conf`, containing just the name | `create_module_file()` |
| the parameters | `/etc/modprobe.d/` | `create_module_options_file()` |

`/etc/modules-load.d/` is read at boot by `systemd-modules-load.service`, which is why the
module's own docs note the `persistent` option needs systemd.

One gotcha in how it detects the existing state: `modules_files()` lists **every** file in
`/etc/modules-load.d/`, so if some other package already lists the module in its own file, this
role finds it persistent and writes nothing. Correct, and worth knowing before going looking for
a `<name>.conf` that was never created.

## What the test proves, and what it does not

`tests/test.yml` covers the validation and nothing else, which is the whole of this role's own
decision-making. Three accepted cases (a plain name, a hyphenated name, an explicit `absent`)
and three controls that construct a broken **caller**: an unset name, a path instead of a name,
and an unsupported state.

It does **not** exercise the load itself. It cannot: `community.general.modprobe` hardcodes its
two write locations as module-level constants (`MODULES_LOAD_LOCATION`,
`PARAMETERS_FILES_LOCATION`), so there is no seam to aim at a tempfile and no way to run it here
without writing to the controller's own `/etc` and loading a module into the laptop. Whether a
given module loads on a given host is a question only that host answers.

```
cd ansible
ANSIBLE_VAULT_PASSWORD_FILE=tests/apt-sources/no-vault.sh \
  .venv/bin/ansible-playbook -i roles/kernel_module/tests/inventory \
    roles/kernel_module/tests/test.yml
```
