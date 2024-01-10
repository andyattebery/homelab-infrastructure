# kernel_parameters

## Reference
- https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html
- https://pve.proxmox.com/wiki/Host_Bootloader

## Notes

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