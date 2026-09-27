# Alternatives to Talos, and the Orin's GPU

Researched 2026-09-26. **[I]** marks inference.

The question: which ways of building this cluster let Kubernetes pods use the Orin's GPU, and what does each cost?

## Why the Orin's GPU needs NVIDIA's stack

- **No mainline driver.** nouveau's Tegra list in v6.18 is `"nvidia,gk20a"`, `"nvidia,gm20b"`, `"nvidia,gp10b"`, unchanged at 7.3-rc4 ([`nouveau_platform.c`](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/nouveau/nouveau_platform.c)). nova-core lists Turing, GA100–GA107, Hopper, Ada and Blackwell, but not GA10B ([`gpu.rs`](https://github.com/torvalds/linux/blob/master/drivers/gpu/nova-core/gpu.rs)).
- **No firmware.** linux-firmware's `nvidia/` folder has gk20a, gm20b and gp10b, but no ga10b ([tree](https://gitlab.com/kernel-firmware/linux-firmware/-/tree/main/nvidia)).
- **NVIDIA's current release still uses out-of-tree nvgpu.** The r39.2 docs (JetPack 7.2): "Jetson Orin devices use the NVGPU driver, `nvgpu.ko`"; "`Tegra23x` selects `nvgpu-l4t`" ([r39.2](https://docs.nvidia.com/jetson/archives/r39.2/DeveloperGuide/SD/Kernel/DisplayConfigurationAndBringUp/NvLoadDisplayModulesService.html)).
- **Talos packaging is stalled.**
  - [siderolabs/pkgs#1518](https://github.com/siderolabs/pkgs/pull/1518), opened 2026-04-22, is on hold. Its author: "linux-firmware does not carry the GA10B blobs" (2026-09-10).
  - A Sidero maintainer: "the nvidia extensions are not supporting jetson modules due to the differences in kernel modules" ([sbc-jetson#23](https://github.com/siderolabs/sbc-jetson/pull/23)).

### JetPack releases for the Orin Nano

| JetPack | L4T | Date | Notes |
|---|---|---|---|
| 6.2 | 36.4.3 | Jan 2025 | introduces Super mode ([notes](https://docs.nvidia.com/jetson/archives/jetpack-archived/jetpack-62/release-notes/index.html)) |
| 6.2.1 | 36.4.4 | Jun 2025 | |
| 6.2.2 | 36.5 | 2026-02-04 | "Linux Kernel 5.15 and Ubuntu 22.04" |
| 6.2.3 | 36.5.2 | Aug 2026 | |
| 7.0, 7.1 | — | — | Thor only: "Orin AGX and Jetson Orin NX modules stayed on JetPack 6" |
| 7.2 | 39.2 | 2026-06-02 | Kernel 6.8, CUDA 13.2.1, "Jetson Orin Family". Needs "JetPack 6.x-generation Jetson UEFI/QSPI firmware"; "SD Card images are no longer supported" |
| 7.2.1 | 39.2.1 | 2026-08-12 | "ISO now flashes the Jetson Orin Nano Developer Kit with Super Mode flashing configuration by default" |

## Kubernetes GPU on Jetson

- **Device plugin** ([k8s-device-plugin](https://github.com/NVIDIA/k8s-device-plugin)).
  - NVIDIA's plugin supports Tegra iGPUs: "(>= 1.11.0 to use integrated GPUs on Tegra-based systems)". Discovery is `'auto', 'nvml', or 'tegra'`.
  - v0.19.1 fixed "CDI spec generation … for Tegra CSV files". The latest is v0.20.1 (2026-09-22).
- **Container toolkit.** v1.20.1 (2026-09-19); CDI via `nvidia-ctk cdi generate … --mode=csv`. JetPack 7.2 ships toolkit 1.19.
  - NVIDIA staff: "nvidia-container-cli is no longer supported on Jetson that uses iGPUs" (2024-06-27).
- **Support status.**
  - NVIDIA staff, on JetPack 6.2.1: "By default Kubernetes is not supported on default Jetpack release. This would need community support." (2025-07-29)
  - GPU Operator 26.7.x: "NVIDIA Jetson … are not supported". The feature request [gpu-operator#1453](https://github.com/NVIDIA/gpu-operator/issues/1453) was closed 2026-09-11 as "not currently on our priority roadmap".
- **A working recipe** (from the #1453 reporter, 2025-05-22): Orin Nano dev kit 8 GB, JetPack 6.1, k3s v1.31.5+k3s1, device plugin v0.17.1 "without any issue", toolkit 1.17.7-1 with CDI, and a separately installed containerd passed via `--container-runtime-endpoint`.
  - k3s "will automatically detect alternative container runtimes", and pods use `runtimeClassName: nvidia` ([k3s](https://docs.k3s.io/advanced#nvidia-container-runtime-support)).
- **Caveats.** A PREEMPT_RT kernel broke pod cgroups. One NVIDIA reply suggested `--docker` for a cgroup failure on JetPack 6.0.
- **Longhorn on the Orin.** L4T R36.5.2's kernel is built from a `defconfig` with no `CONFIG_ISCSI_TCP`, and R38.4 is the same. So the Orin can't attach Longhorn volumes without a kernel rebuild [I]. jetpack-nixos builds the same defconfig with `autoModules = false`.

## The options

### A. Talos control plane, Orin as a JetPack worker

- **Sidero's position.**
  - 2024-10-04: "workers can be set up e.g. using `kubeadm`. Some features of Talos might not work … (e.g. KubeSpan)" ([#9435](https://github.com/siderolabs/talos/discussions/9435)).
  - 2025-10-06: "Sorry, this is not supported (mixed clusters), and not going to be supported." ([#11974](https://github.com/siderolabs/talos/issues/11974))
  - There is no documentation for it.
- **#11974 in detail.** Talos 1.11.2 with an Orin NX on Ubuntu 22.04. `talosctl upgrade-k8s` aborts with "dial tcp …:50000: connect: connection refused". It was closed the same day and pointed at the manual upgrade docs.
- **Joining the node** ([#3990](https://github.com/siderolabs/talos/issues/3990)).
  - `kubeadm join` doesn't work ("the cluster was not created with Kubeadm").
  - Instead: copy `bootstrap-kubeconfig`, `kubeconfig-kubelet` and `pki/ca.crt` with `talosctl cat`, rewrite `server:`, and hand-write a KubeletConfiguration from `talosctl get kubeletconfig`.
  - KubePrism: the CNI points at 127.0.0.1:7445, so either disable KubePrism or run HAProxy on the node bound to localhost:7445.
- **Version skew.** The kubelet "must not be newer than kube-apiserver".
- The Orin can stay on its dev-kit carrier [I].

### B. k3s on vendor OSes, managed by Ansible

- **RK1 OS options:**
  - [ubuntu-rockchip](https://github.com/Joshua-Riek/ubuntu-rockchip) is archived; the last release was v2.4.0 (2024-10-23).
  - Turing's image is "Ubuntu 22.04 LTS Server based on the BSP Linux 5.10"; the directory was last modified 2024-02-16.
  - Armbian's `turing-rk1.csc` has `BOARD_MAINTAINER=""`, with "Community" rolling images on "vendor 6.1.172". Community boards are "untested and Armbian team won't respond on troubles or apply any fixes".
  - Armbian's vendor, current and edge kernels all set `CONFIG_ISCSI_TCP=m`.
- **Mainline on the RK1.** The device tree has been in since v6.7. "Fix Turing RK1 PCIe3 hang" landed in v6.13 and is absent from 6.12.60, so the NVMe needs kernel 6.13 or later.
- **CM4.** The RPi rpi-6.18.y kernel has `CONFIG_ISCSI_TCP=m`. k3s: "Standard Raspberry Pi OS installations do not start with `cgroups` enabled"; "SD cards and eMMC cannot handle the IO load" of etcd ([k3s requirements](https://docs.k3s.io/installation/requirements)).
- **Cost.** Three OS families to patch, with the RK1 as the weak link [I].

### C. NixOS + k3s everywhere

- **[jetpack-nixos](https://github.com/anduril/jetpack-nixos)** (825dfea, 2026-09-23):
  - Orin Nano on JetPack 5, 6 and 7, pinning 6.2.3/36.5.2 and 7.2.1/39.2.1.
  - `super`: "enable 'super mode' for Jetson Orin NX and Nano".
  - Initial flash "On an x86_64 machine" (`tegrarcm_v2` is x86_64-only); UEFI capsule updates after that.
  - `hardware.nvidia-container-toolkit.enable` yields a CDI device `nvidia.com/gpu=all`. The CDI generator is ordered only for docker and podman ("TODO: This should be upstreamed").
  - No k3s issues in the repo.
- **k3s and CDI.** k3s v1.37.0+k3s1 bundles containerd v2.3.4-k3s1, and containerd 2.0 defaults to `enable_cdi = true`.
- **RK1 on NixOS:**
  - no nixos-hardware entry
  - nixpkgs has `ubootTuringRK1` (since 2024-04-11, in 25.11 and 26.05)
  - default kernel: 6.12 in 25.11, which lacks the NVMe fix; 6.18 in 26.05
  - community flakes: [GiyoMoon/nixos-turing-rk1](https://github.com/GiyoMoon/nixos-turing-rk1) (pushed 2026-09-01; needs an aarch64 builder) and mcgilly17/nixos-rk1; ryan4yin/nixos-rk3588 is archived
- **Longhorn on NixOS.**
  - [longhorn#2166](https://github.com/longhorn/longhorn/issues/2166) ("NixOS support") has been open since 2021, in the Backlog milestone. The 1.12.1 docs have no NixOS page.
  - Workarounds:
    - a `/usr/local/bin` symlink tmpfiles rule plus `services.openiscsi` (2023-12-20)
    - an iscsid `BindPaths = "/run/current-system/sw/bin:/bin"` (2025-06-22)
    - a Kyverno PATH policy (nixpkgs k3s `STORAGE.md`), which needs rewriting in CEL form since Kyverno 1.17 (2026-03-15)
  - RWX NFS mounts still fail for some users ("exit status 127", 2025-07-15).
- **Unknowns [I].** GPU access in k3s pods is plausible but undocumented. The Mac can build aarch64 in Docker but can't run the x86-only flasher.

### D. Kairos and other immutable distros

- **Kairos** v4.3.0 (2026-09-08):
  - Board models: "generic, rpi3, rpi4, nvidia-jetson-agx-orin, nvidia-jetson-orin-nx, nvidia-jetson-thor, nvidia-dgx-spark". No RK3588, no Orin Nano, and CM4 is not named.
  - Kubernetes GPU access is documented only "on Thor".
  - The Orin models use L4T r36.x, flashed from "A Linux host".
- **SUSE Linux Micro 6.2:** Orin is supported, with the GPU via SUSE kernel-module packages and JetPack 6.2.2; firmware needs an x86 host. Kubernetes GPU is not covered. RK3588: not found.
- **Ubuntu Core 24:** "the entire range of NVIDIA Jetson Orin devices". MicroK8s's GPU add-on uses the GPU Operator, which doesn't support Jetson. RK3588: not found.
- **balenaOS:** has a `jetson-orin-nano-devkit-nvme` device type, but no RK1, and it is not Kubernetes.

### E. Talos on RK1, RK1, CM4, with the Orin standalone

- A Service without a selector, backed by EndpointSlices, "can abstract other kinds of backends, including ones that run outside the cluster". `ExternalName` returns "a CNAME record" ([Service](https://kubernetes.io/docs/concepts/services-networking/service/)).
- Pods call the Orin's services over the network. No GPU scheduling, no reflash, no Longhorn on the Orin [I].

## Comparison

| Option | Orin GPU in pods | RK1 | CM4 | Longhorn | Model | Upkeep | Orin reflash (only if moved into a slot) |
|---|---|---|---|---|---|---|---|
| A: Talos + JetPack worker | yes (community path) | Talos, official | Talos, official | yes, except on the Orin | immutable + mutable | high: manual k8s upgrades, hand-kept kubelet and HAProxy, unsupported | yes |
| B: k3s + Ansible | yes | Armbian community, or mainline ≥ 6.13 | Pi OS | yes, except on the Orin | mutable | high: three distros; unmaintained RK1 OS | yes |
| C: NixOS + k3s | plausible, undocumented | community flakes | nixos-hardware | with workarounds; Orin needs a kernel option | declarative | medium-high | yes (x86_64 flasher) |
| D: Kairos | not documented for the Orin | no | rpi4 model | not researched | immutable | doesn't cover the RK1 | yes |
| E: Talos + standalone Orin | no (network calls) | Talos | Talos | yes | immutable; Orin as today | low | no |
