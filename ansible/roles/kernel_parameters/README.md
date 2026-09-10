# kernel_parameters

Sets Linux kernel command-line parameters, dispatching on how the host boots: GRUB on a
standard server, `/etc/kernel/cmdline` plus `proxmox-boot-tool` on a Proxmox node that uses
systemd-boot, `rpm-ostree kargs` on an image-based OS.

## Status: Production

## Inputs

### `kernel_parameters_new_parameters`

Required — the role does nothing without it. A dict of parameter name to value.

A value may be:

| value | renders as |
| --- | --- |
| a string | `key=value` |
| an empty string | `key`, a bare flag with no `=` |
| a **list** of strings | `key=v1 key=v2 …`, one occurrence per entry |

```yaml
kernel_parameters_new_parameters:
  amdgpu.cwsr_enable: "0"     # -> amdgpu.cwsr_enable=0
  pm_debug_messages: ""       # -> pm_debug_messages
  memmap:                     # -> memmap=32K$0x… memmap=4K$0x…
    - "32K$0x17fcb0000"
    - "4K$0x6ad451000"
```

Values are strings. Quote `"0"` — an unquoted `0` is a YAML integer, and an integer `0` is
falsy, so it renders as a bare flag rather than `key=0`.

The role only ever **adds or updates the keys it is given**. Parameters it was never told
about are left alone, *including their multiplicity* — a key that already appears twice on
the command line still appears twice afterwards. See "Why the merge is not a dict merge".

### Paths and commands

All optional, all in `defaults/main.yaml` so a fixture test can redirect them. Overriding one
in production is not expected; they exist to be pointed at a tempdir and at stub scripts.

| variable | default | if it is wrong |
| --- | --- | --- |
| `kernel_parameters_grub_config_path` | `/etc/default/grub` | the role reads and writes the wrong file; the real one is left stale and the host boots on its old command line |
| `kernel_parameters_systemd_boot_cmdline_path` | `/etc/kernel/cmdline` | same, and `proxmox-boot-tool refresh` then copies the *unchanged* file to every ESP |
| `kernel_parameters_update_grub_path` | `update-grub` | the file is edited but no bootloader config is regenerated, so nothing changes at boot |
| `kernel_parameters_proxmox_boot_tool_path` | `proxmox-boot-tool` | worse than the others: the dispatch runs `<path> status` to decide between systemd-boot and GRUB, so a wrong path makes it non-zero and the role silently takes the **GRUB** path, editing `/etc/default/grub` on a node that does not boot from it |
| `kernel_parameters_rpm_ostree_path` | `rpm-ostree` | the dispatch runs `which <path>`, so a wrong path means the host is not recognised as image-based and the role falls through to GRUB or fails as an unsupported distribution |

`kernel_parameters_new_parameters` is deliberately **not** defaulted here. Callers gate on
`when: kernel_parameters_new_parameters is defined`, and an imported role's defaults are
visible to a task-level `when` — a default would make that gate never skip.

## Sets

### `kernel_parameters_reboot_required`

**Only on the rpm-ostree path.** `tasks/configure_rpm_ostree.yaml` is the sole assignment in
the role. On the GRUB and systemd-boot paths the fact is never set, so `| default(false)` is
always false and a caller written like the example below never reboots. That is usually what
you want — the command line is staged and takes effect at the next boot, whenever that is —
but do not read the example as a general promise.

```yaml
- name: Set kernel parameters
  ansible.builtin.include_role:
    name: kernel_parameters
  vars:
    kernel_parameters_new_parameters:
      amdgpu.cwsr_enable: "0"

- name: Reboot if kernel parameters were staged
  when: kernel_parameters_reboot_required | default(false)
  ansible.builtin.reboot:
```

## Why the merge is not a dict merge

The obvious implementation — parse the existing command line into a dict, `combine()` the new
parameters over it, render with `dict2items` — is what this role used to do, and it silently
destroys data. A dict cannot hold `console=tty0 console=ttyS0,115200`; parsing it keeps the
last one, and the next run writes a command line with the first `console=` gone.

That is not hypothetical when more than one caller manages the same host. If role A imports
this role with one set of keys and the playbook imports it again with another, A's call runs
first, reparses whatever B wrote last time, and collapses any key B had repeated. The end
state is right only because B's call follows and puts them back; if B's call is ever skipped
or fails, the repeated key is silently down to one entry.

So the merge walks the existing tokens in order:

- a key the caller manages is replaced **in place** by all of its values on first sight, and
  skipped on later sightings, so position is kept and a repeated key does not multiply
- a key the caller never mentions keeps its own occurrences, repeats included
- keys the caller adds that were not already present are appended in the caller's order

`templates/kernel_parameters_string.j2` holds it. **That file must not end with a newline**:
Ansible's template lookup preserves the source's trailing newline, `/etc/kernel/cmdline`
carries none, and a stray one makes the write report `changed` on every run and re-run
`proxmox-boot-tool` each time.

## The loss guard

Before either file is written, `tasks/assert_no_parameters_lost.yaml` asserts that every
token whose key the caller does **not** manage still appears in the string about to be
written. A merge bug then fails the play instead of writing an unbootable command line — on
a Proxmox node that file is copied to every ESP, so there is no older copy left to boot from.

It does not police keys the caller *does* manage: changing or removing those is the caller's
prerogative. Losing one of two *identical* tokens is also not detected, which is harmless —
the same bare flag twice has the same effect as once.

## rpm-ostree hosts

On an image-based OS (Bazzite, Silverblue, Kinoite) the role uses `rpm-ostree kargs`, which
writes a **staged deployment** rather than modifying the running one. Nothing takes effect
until the next boot — hence the fact above.

`--append-if-missing` **never updates an existing value**. Editing a value in
`kernel_parameters_new_parameters` leaves the old one on the command line beside the new one;
removing a key leaves it there entirely. This path adds, it does not reconcile, and that
differs from the two file-writing paths. Pre-existing behaviour, called out here because it
is invisible from the caller.

Under `--check`, the two command tasks that read deployment state are skipped, so their
output is empty. The fact defaults to `false` in that case, and a dry run reports "no reboot
needed" instead of the role erroring on unparseable JSON.

## Tests

`tests/test.yml` — merge cases, loss-guard cases, and all three bootloader paths against a
tempdir with stubbed bootloader commands. See `ansible/tests/README.md` for how to run it.

The dispatch in `tasks/main.yaml` is **not** covered: choosing between GRUB, systemd-boot and
rpm-ostree depends on `proxmox-boot-tool status`, `which rpm-ostree` and the running kernel's
name, none of which a controller-side fixture can honestly reproduce. Verify it on the host.

## Reference

- <https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html>
- <https://pve.proxmox.com/wiki/Host_Bootloader>
