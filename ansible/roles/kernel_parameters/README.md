# kernel_parameters

Sets Linux kernel command-line parameters, dispatching on how the host boots: GRUB on a
standard server, `rpm-ostree kargs` on an image-based OS.

## Status: Production

## Inputs

### `kernel_parameters_new_parameters`

A dict of parameter name to value. An empty string means a bare flag with no `=value`.

```yaml
kernel_parameters_new_parameters:
  amdgpu.cwsr_enable: "0"     # -> amdgpu.cwsr_enable=0
  pm_debug_messages: ""       # -> pm_debug_messages
```

Values are strings. Quote `"0"` — an unquoted `0` is a YAML integer and renders differently.

The role only ever **adds or updates** the keys given; parameters it was never told about
are left alone.

## Sets

### `kernel_parameters_reboot_required`

`true` when parameters were staged and the running kernel is not yet using them. The caller
decides what to do about it — the role never reboots on its own:

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

## rpm-ostree hosts

On an image-based OS (Bazzite, Silverblue, Kinoite) the role uses `rpm-ostree kargs`, which
writes a **staged deployment** rather than modifying the running one. Nothing takes effect
until the next boot — hence the fact above.

Under `--check`, the two command tasks that read deployment state are skipped, so their
output is empty. The fact defaults to `false` in that case, and a dry run reports "no reboot
needed" instead of the role erroring on unparseable JSON.

## Reference

- <https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html>
- <https://pve.proxmox.com/wiki/Host_Bootloader>
