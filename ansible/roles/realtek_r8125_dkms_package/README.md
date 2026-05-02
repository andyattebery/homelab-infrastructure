# realtek_r8125_dkms_package

Installs the Realtek R8125 driver via the Debian `r8125-dkms` package, deploys a udev rule that swaps matching cards from the kernel's `r8169` to `r8125`, reboots if DKMS built against a newer-than-running kernel, and re-triggers udev for any matching device still on `r8169` so the swap takes effect without a manual reboot in the common case.

Distinct from the `realtek_r8125_dkms` role, which builds from GitHub source via DKMS manually.

## Status: Production
