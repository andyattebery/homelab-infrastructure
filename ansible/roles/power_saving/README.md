# power_management

## Status: Production

- CPU: Production
- Hard Drives: Production
- PCIe: WIP
- SATA: WIP

## Dependencies

- Ansible roles
    - kernel_parameters

## CPU

### CPU Performance Scaling Driver and Power Governor Used

| CPU   | Kernel           | Driver                              | Governor  |
|-------|------------------|-------------------------------------|-----------|
| Intel | any              | [intel_pstate=active][intel_pstate] | powersave |
| AMD   | < 6.1            | default (i.e. acpi-cpufreq)         | schedutil |
| AMD   | >= 6.1 and < 6.3 | [amd_pstate=passive][amd_pstate]    | schedutil |
| AMD   | >= 6.3           | [amd_pstate=active][amd_pstate]     | powersave |

[intel_pstate]: https://www.kernel.org/doc/html/latest/admin-guide/pm/intel_pstate.html
[amd_pstate]: https://www.kernel.org/doc/html/latest/admin-guide/pm/amd-pstate.html

### Intel

The intel_pstate driver was added in 3.8 with support for second generation (Sandy Bridge) Intel CPUs with support for later models added in subsequent versions. In version 5.8, the default driver was set to intel_pstate=passive from what I assume was acpi-cpufreq.

For the intel_pstate "full" active mode to be enabled, the CPU must support HWP/Intel Speed Shift Technology and it must be enabled in the BIOS. Otherwise it will fall back to the "active with no_hwp" mode. Additionally, `intel_pstate=passive` will use the intel_cpufreq driver.

### AMD

For the amd_pstate active mode to be enabled, HWP/Intel Speed Shift Technology must be enabled in the BIOS.

### References

- https://vstinner.github.io/intel-cpus.html
- https://www.reddit.com/r/linux/comments/15p4bfs/amd_pstate_and_amd_pstate_epp_scaling_driver/
- https://wiki.archlinux.org/title/CPU_frequency_scaling

## Hard Drives

### openSeaChest

```
openSeaChest_PowerControl --device $drive --deviceInfo
openSeaChest_PowerControl --device $drive --checkPowerMode
openSeaChest_PowerControl --device $drive --showEPCSettings
openSeaChest_PowerControl --device $drive --setAPMLevel <1-254>
openSeaChest_PowerControl --device $drive --disableAPM
openSeaChest_PowerControl --device $drive --EPCfeature <enable|disable>
openSeaChest_PowerControl --device $drive --idle_a <enable|disable|timeout_in_milliseconds>
openSeaChest_PowerControl --device $drive --idle_b <enable|disable|timeout_in_milliseconds>
openSeaChest_PowerControl --device $drive --idle_c <enable|disable|timeout_in_milliseconds>
openSeaChest_PowerControl --device $drive --standby_z <enable|disable|timeout_in_milliseconds>
```

## SSDs

## SATA

Active Link Power Management/Aggressive Link Power Management (ALPM)

`/etc/udev/rules.d/sata_active_link_power_saving.rules`
```
ACTION=="add", SUBSYSTEM=="scsi_host", KERNEL=="host*", ATTR{link_power_saving_policy}="med_power_with_dipm"
```

## PCIe Devices

### Active-State Power Management (ASPM)

### Kernel Parameter
This seems to be removed in at least 6.5+ kernels
```
pcie_aspm.policy=powersave
```

### On Demand
```
echo powersave | sudo tee /sys/module/pcie_aspm/parameters/policy
```

### PCI Runtime Power Management
`/etc/udev/rules.d/pci_runtime_power_saving.rules`
```
SUBSYSTEM=="pci", ATTR{power/control}="auto"
```

## NVMe SSDs

NVMe 1.1: Autonomous Power State Transitions (APST)


## References

### 

- https://wiki.archlinux.org/title/Power_management

### ALPM
- https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/6/html/power_saving_guide/alpm
- https://www.thomas-krenn.com/en/wiki/SATA_Link_Power_Management
- https://www.thomas-krenn.com/en/wiki/AMD_EPYC_Server_with_Ubuntu_-_Enable_SATA_Hot-Swap

### ASPM
- https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/6/html/power_saving_guide/aspm
- http://drvbp1.linux-foundation.org/%7Emcgrof/scripts/enable-aspm
- https://gist.github.com/baybal/b499fc5811a7073df0c03ab8da4be904

### APST
- https://unix.stackexchange.com/questions/612096/clarifying-nvme-apst-problems-for-linux

## VM Passthrough

### Proxmox

- Only q35-based VMs support power management

## Notes

https://forums.servethehome.com/index.php?threads/12gen-n-series-nas-motherboard-topton-cwwk.42432/page-4#post-407589

GRUB_CMDLINE_LINUX_DEFAULT="intel_iommu=on intel_pstate=active cpufreq.default_governor=powersave"

"ansible_cmdline": {
    "amd_pstate": "active",
    "boot": "zfs",
    "cpufreq.default_governor": "powersave",
    "initrd": "\\EFI\\proxmox\\6.5.11-7-pve\\initrd.img-6.5.11-7-pve",
    "root": "ZFS=rpool/ROOT/pve-1",
    "video": "vesa:off"
},

"ansible_kernel": "6.5.11-7-pve",

"ansible_processor": [
    "0",
    "AuthenticAMD",
    "AMD EPYC 7282 16-Core Processor",

"ansible_processor": [
    "0",
    "GenuineIntel",
    "Intel(R) Core(TM) i5-9500T CPU @ 2.20GHz",