# Kubernetes on the Turing Pi's vendor OSes: what reaches a pod

Researched 2026-10-07. **[I]** marks inference. Nothing here was run on the boards. It comes from source, kernel configs, published packages, docs and issue reports, at the versions named. The source keys are listed at the end.

**The question:** if the Turing Pi boards run Kubernetes, can pods use each board's hardware? [hardware-support.md](hardware-support.md) answered that for Talos on 2026-09-26. This doc answers it for the OSes the boards run now ([turingpi/nodes.md](../../turingpi/nodes.md)):
- **RK1 ×2:** Debian 13 on Rockchip's vendor kernel 6.1.172 ([rk1-armbian-minimal](https://github.com/andyattebery/rk1-armbian-minimal)). On 2026-10-03 the host itself ran libmali OpenCL and Vulkan, RKNN 2.3.2, RKLLM 1.3.1, MPP encode and decode, and RGA.
- **Orin Nano:** L4T R39.2.1 (JetPack 7.2.1, kernel 6.8.12), NVIDIA's minimal rootfs plus the BSP's debs ([turingpi/jetson/](../../turingpi/jetson/README.md)). No container runtime yet.
- **CM4:** Armbian `rpi4b` (6.18.42) today. [cm4-os.md](cm4-os.md) records the decision to run Ubuntu 26.04 on it, and recommends Canonical's image (`linux-raspi` 7.0, from the Pi tree).
  - This doc's CM4 section describes Raspberry Pi OS (kernel 6.18.50) and Talos 1.14.1.
  - On Canonical's 7.0 kernel the codec devices are the same (H.264 and the `rpi-hevc-dec` HEVC decoder). Armbian's kernel is the Pi tree built without any HEVC decoder.

## Bottom line

**Under Kubernetes on these OSes, the Orin's GPU and the CM4's H.264 blocks reach pods the standard way. The RK1's reach them only partly: its full video codecs and most of its NPU front ends need privileged pods.**

| Board | Feature | From a pod | Privileged? | Through |
|---|---|---|---|---|
| Orin | GPU: CUDA, TensorRT | **yes** | no | NVIDIA's toolkit 1.19.1 (Tegra CSV → CDI) and `k8s-device-plugin` in Tegra mode. Reported working on AGX Orin R39.2.1 with k3s 1.36.3 (KDP2061) |
| Orin | NVDEC, NVJPG, VIC | **partly**, unverified | no | Part of the one GPU device; needs NVIDIA's ffmpeg or GStreamer plugins in the image. No JetPack 7.2 container report |
| Orin | NVENC, DLA, PVA, MIG, NVML telemetry | no | — | Not on the module, or not supported on Orin |
| RK1 | GPU: OpenCL, Vulkan (kbase + libmali) | **yes** [I] | no | `/dev/mali0`, plus a g29p1 libmali in the image |
| RK1 | NPU: C runtimes (`librknnrt`, `librkllmrt`) | **partly** [I, untested] | no | The rknpu DRM `cardN` + `renderDN` and `/dev/dma_heap/system` |
| RK1 | NPU: Python `rknn-toolkit-lite2`, Frigate, Immich | **partly** | **yes** | They read `/proc/device-tree/compatible`, which Kubernetes masks |
| RK1 | Video: MPP decode and encode | **partly**; H.264 only unprivileged [I] | **yes** for HEVC, VP9 and AV1 decode and HEVC encode | MPP identifies the SoC from `/proc/device-tree/compatible` |
| RK1 | RGA 2D | **yes** [I] | no | `/dev/rga` |
| CM4, RPi OS | H.264 decode, H.264 encode, ISP | **yes** [I] | no | `/dev/video10`, `11`, `12` |
| CM4, RPi OS | HEVC decode | **partly** | no | A stateless decoder at `/dev/video19`, plus its media node. Needs a v4l2-request FFmpeg or GStreamer; Frigate's preset probably misses it [I] |
| CM4, RPi OS | GPU (V3D) | **yes** [I] | no | `/dev/dri/renderD128` + Mesa |
| CM4, Talos | codecs / GPU | no / only through the `vc4` extension | — | The codecs aren't in mainline |

The other findings:
- **No maintained device plugin exists for the Rockchip or Pi blocks.** The generic route is [squat/generic-device-plugin](https://github.com/squat/generic-device-plugin). The Orin uses NVIDIA's plugin, but NVIDIA calls Kubernetes on Jetson community support, and its GPU Operator excludes Jetson.
- **Every kernel runs k3s's defaults** (Flannel VXLAN, iptables kube-proxy).
  - The Orin's stock kernel can't run nftables or IPVS kube-proxy, Cilium or WireGuard, and Calico needs a rebuild.
  - It also has no iSCSI, so it can't hold Longhorn volumes.
  - The RK1's kernel has everything, Cilium included.
- **The boards shouldn't join the Super6C Talos cluster.** Sidero won't support mixed clusters, and the Orin's kernel can't run that cluster's nftables kube-proxy [I].
- **Kubernetes would make the workload layer consistent, not the OS layer.** Each board's kernel and firmware come from its own vendor, and those upgrades stay three separate jobs either way.
- **Recommendation: Docker hosts managed by Ansible.** Choose k3s for its operating model, or to keep RK1 services up through RK1 upgrades, not to reduce OS maintenance. See [Decision](#decision-kubernetes-on-the-turing-pi-or-not).

## How a device node reaches a pod

These mechanics apply to every board.

**A hostPath mount of `/dev/x` doesn't work.**
- On cgroup v2, device access is checked by a BPF program when the device is opened ([Linux v6.1 `cgroup-v2.rst:2312-2317`](https://github.com/torvalds/linux/blob/v6.1/Documentation/admin-guide/cgroup-v2.rst)).
- containerd starts every container from deny-all (k3s-io/containerd `v2.3.4-k3s1.36` `pkg/oci/spec.go:210-216`).
- It adds allow rules only for devices from a device plugin, CDI devices, or privileged pods (`container_create.go:860-866`).
- Pod Security "baseline" forbids hostPath anyway.

**The ways in, as of Kubernetes 1.36:**

| Route | State | Fit here |
|---|---|---|
| `privileged: true` | always works | Grants every device and a writable `/sys`. It is what the RK1 video and Python NPU need. |
| [squat/generic-device-plugin](https://github.com/squat/generic-device-plugin) | 0.2.0 (2026-04-14); last commit 2026-05-15; arm64 images | The practical route for the RK1 and CM4. Groups of paths (globs allowed) become a resource such as `squat.ai/npu: 1`; the RK1's NPU needs `card1` and `renderD129` grouped explicitly. Its DaemonSet is privileged; the workload pods are not. Symlinks such as `/dev/dri/by-path` don't work. |
| Akri | v0.14.0 (2026-09-01), after a 22-month gap; CNCF Sandbox | udev-rule discovery, with a controller, an agent, a webhook and CRDs. Heavy for four nodes. |
| ARM smarter-device-manager | last real commit 2022 | Dormant [I]. |
| A static CDI spec | containerd 2.x enables CDI by default (`internal/cri/config/config_unix.go:107-108`); k3s doesn't change it | A pod can't ask for a CDI device directly. It gets one through a device plugin's `cdi_devices` or a DRA driver. The deprecated `cdi.k8s.io/` annotations are read only from container annotations, so setting them on the Pod does nothing [I]. |
| containerd NRI `device-injector` (v0.12.3) | a sample plugin | Injects devices named in pod annotations. Without an admission policy, any pod author could take any host device [I]. |
| DRA | GA since 1.34; 1.36's release blog calls it "a robust production-ready alternative to the legacy device plugin system" (K136) | No DRA driver exists for these devices, except two that don't fit. gclawes/rockchip-dra-driver covers only the mainline `rocket` NPU: "does not support the proprietary Rockchip `rknpu`". NVIDIA's DRA driver is NVML-based, has no Tegra path, and "some GPU allocation features can be tried out, they are not yet officially supported". |

**Supporting pieces:**
- **Node Feature Discovery v0.19.0** has no device-tree source, so it labels none of the RK3588's or BCM2711's blocks on its own. A `NodeFeatureRule` on `kernel.loadedmodule` or `kernel.enabledmodule` would do it [I]. Examples: `rknpu`, `valhall_kbase` and `rk_vcodec`, all built in on the RK1; `bcm2835_codec` and `rpi_hevc_dec` on the CM4.
- **Non-root pods** need the host's numeric `video` and `render` GIDs in `supplementalGroups`, because device nodes keep their host owner.
  - The RK1 image sets `mali0`, `mpp_service` and `rga` to `root:video 0660`, and the dma_heap `system*` nodes to 0666 (rk1-armbian-minimal `userpatches/overlay/*.rules`).
  - Alternatively, k3s `--nonroot-devices` hands devices to the pod's user, but only devices from a device plugin.
- **Pod Security:** k3s enforces nothing by default. The Talos cluster enforces baseline, which forbids privileged pods outside a namespace opened for them.

**Why a pod can't read `/proc/device-tree`.** This is what makes the RK1's video and Python NPU privileged.
- `/proc/device-tree` is a symlink to `/sys/firmware/devicetree/base` (Linux `drivers/of/base.c:188`).
- The kubelet masks `/sys/firmware` by default (kubernetes v1.36.5 `pkg/securitycontext/util.go:208`).
- containerd's AppArmor profile also denies reads there, when `apparmor_parser` is installed (`deny /sys/firmware/** rwklx`, containerd v2.3.4 `contrib/apparmor/template.go:88`).
- **Unmasking doesn't work on this kernel.**
  - `procMount: Unmasked` requires `hostUsers: false` (user namespaces). In practice those need Linux 6.3 or later for idmapped tmpfs (Kubernetes 1.36 docs, "User namespaces").
  - The RK1's vendor 6.1 tmpfs lacks `FS_ALLOW_IDMAP` (`mm/shmem.c:4068`), and immich#25057 hit exactly this.
  - The Orin's 6.8 and the CM4's 6.18 aren't affected, but nothing on them needs the device tree either.

## Turing RK1: Debian 13, vendor kernel 6.1.172

### Kernel readiness

**Config source.** Values come from the resolved config `/boot/config-6.1.172-vendor-rk35xx` in Armbian's beta `linux-image-vendor-rk35xx` 26.11.0-trunk.75 (AKD). It is built from `02600c6fba83`, six commits after the image's pin `44bbd021d780`. None of those six touch a Kconfig, so the values apply to the image [I]. To confirm on a node: `zcat /proc/config.gz`.

**What it has:**
- Namespaces, cgroups (every controller), seccomp, `NF_NAT`, and the `XT` masquerade, mark and NAT targets.
- `XT_MATCH_SOCKET`, `XT_TARGET_TPROXY` and `DEBUG_INFO_BTF=y`.
- `ISCSI_TCP=m`, `DM_CRYPT=m`, and NFS 4.1 and 4.2.

**What that means:**
- **k3s:** every "Generally Necessary" flag in `check-config.sh` (k3s v1.36.5+k3s1, `:461-470`) is present. So is every optional flag except `INET_XFRM_MODE_TRANSPORT`, which doesn't exist in this tree, so that warning means nothing.
- **Cilium v1.20.2:** its requirements are all met except NETKIT, which needs kernel 6.8+ and is used only by an optional mode.
- **Longhorn v1:** the kernel side is all there.

**People run k3s on the RK1 already** (k3s#13974, on 6.1.0-1025-rockchip with v1.35.4; ubuntu-rockchip#664). Searches of the k3s, Armbian and ubuntu-rockchip trackers found no RK3588-specific k3s bug.

**Traps on this image:**
- **`/var/log` is a 50 MB RAM disk** (armbian-ramlog, `ENABLED=true, SIZE=50M`).
  - The kubelet keeps pod logs in `/var/log/pods/`, up to 10 Mi × 5 files per container.
  - k3s#10126 is this failure on an Armbian RK3588: ramlog filled and k3s exited with 255.
  - The image doesn't change ramlog.
- **zram swap is on.**
  - k3s sets `FailSwapOn: false` (`pkg/daemons/agent/agent.go:180`), so it starts anyway.
  - A plain kubelet defaults to `failSwapOn: true`.
- **AppArmor is in the kernel's LSM list.** check-config fails, and containerd applies no profile, if `apparmor_parser` is missing. Whether the minimal image has it is unverified.
- **Debian 13's containerd is 1.7.24, which Kubernetes 1.36 doesn't support** ("v1.35 as the last release to support the containerd v1.X series"). Ubuntu 26.04, the RK1s' decided release, ships containerd 2.2.2. k3s bundles containerd v2.3.4, so this matters only for a plain kubelet.
- **iptables:**
  - k3s's Flannel is hard-wired to iptables (k3s#12849, open).
  - Its network-policy controller is iptables-only, and nft rules added by other software can crash it (k3s#11415, open).

### NPU (rknpu 0.9.8, RKNN 2.3.2, RKLLM 1.3.1)

**The kernel side.** All from armbian/linux-rockchip `44bbd021d780` `drivers/rknpu/`:
- The driver registers as a DRM device with `DRIVER_GEM | DRIVER_RENDER` (`rknpu_drv.c:735`). So it gets both a `cardN` and a `renderDN` node.
- Every ioctl is `DRM_RENDER_ALLOW` (`:703-712`).
- `/dev/rknpu` exists only with `ROCKCHIP_RKNPU_DMA_HEAP` (`:1439-1448`), which is off.

**What the runtimes open** (from `strings` of the v2.3.2 `librknnrt.so`):
- `/dev/rknpu` first.
- Then the `/dev/dri` `card%d`/`renderD%d` nodes whose driver is `rknpu`.
- `/dev/dma_heap/system`.
- `/sys/kernel/debug/rknpu/freq`, with a "take %dMHz as default" fallback, so not fatal [I].
- No device-tree, `/sys/firmware` or `cpuinfo` path.
- `librkllmrt` 1.3.1 adds `/proc/rk_dmabuf/dev` and CPU-topology reads under `/sys`.

**So the C runtimes should work in an unprivileged pod given the NPU's `cardN` and `renderDN` plus `/dev/dma_heap/system` [I, untested].**
- The display controller probes first, so the NPU is probably `card1`/`renderD129` [I]. Check on a node with `strace -e openat` on any RKNN program, and map both nodes.
- **Trap: `/dev/rknpu` must not exist in the container.** A symlink `/dev/rknpu → renderD129` sent the library down the old ioctl path, giving `hw_version = -1`. invisiofficial/rk-llama.cpp#19 is this exact stack: RK1, Armbian vendor 6.1, rknpu 0.9.8, librknnrt 2.3.2, k3s.

**What needs privileged.** The front ends above the C library read `/proc/device-tree/compatible`:
- `rknn-toolkit-lite2` 2.3.2 (Python): "Please specify the target in init_runtime!", rknn-toolkit2#153. Whether passing `target='rk3588'` skips the read is unverified.
- Frigate's RKNN detector (`frigate/detectors/plugins/rknn.py:88-100`: "Make sure to run docker in privileged mode").
- Immich's `rknnpool.py` `get_soc`.

On 6.1 these need `privileged: true` (see "Why a pod can't read `/proc/device-tree`"). Every public RKNN-in-a-pod setup found runs privileged; no unprivileged report turned up.

**Device plugins.** None is maintained and fits:

| Repo | Last change | What it does |
|---|---|---|
| elct9620/rknpu-device-plugin | real code 2024-03 | Hard-codes `renderD129` |
| tylertitsworth/ai-cluster `npu-device-plugin` | 2026-08-10 | Still privileged |
| gjing1st/rk3588-device-plugin | 2026-09-18 | Returns mounts, no devices; untested by its author |
| schwankner/talos-rk3588-npu | 2026-05 | Mainline `rocket`, `/dev/rknpu` |
| gclawes/rockchip-dra-driver | 0.7.0, 2026-09-29 | Mainline `rocket` only |

**Sharing.** Whether several pods can use the NPU's `cardN` at once, given DRM master rules, is unverified.

### GPU (kbase g29p1 + libmali)

**What a pod needs.**
- The OpenCL-only libmali g29p1 blob opens only `/dev/mali*`.
- The full blob also opens `/dev/dri/card0` and `/dev/dma_heap/{system-uncached,protected}` [I: for GBM/EGL].
- Neither reads the device tree. The CSF firmware is compiled into the kernel (`MALI_CSF_INCLUDE_FW=y`).
- So `/dev/mali0`, plus `/dev/dma_heap` and `card0` for the full blob, should work unprivileged [I].

**libmali in the image must suit the g29p1 kernel driver:**
- kbase negotiates an older same-major userspace down to its minor version (`valhall/mali_kbase_core_linux.c:357-390`) [I: so older libmali works].
- Jellyfin's docs say versions must match "otherwise OpenCL will not work properly" (`rockchip.md:155`). Its official image ships g24p0, which is unverified against g29p1.
- Safe choices:
  - the g29p1 libmali in the image (ginkage/JeffyCN `libmali-next`, as the host has);
  - or bind-mount the host's `libmali.so.1` and `/etc/OpenCL`, as Immich's `hwaccel.transcoding.yml:41-42` does.

**Field reports.** An unprivileged LXC container ran Jellyfin with `mali0` (discuss.linuxcontainers.org t/27133). No Kubernetes report of OpenCL or Vulkan on kbase turned up.

**Panthor instead.** The `panthor-gpu` overlay swaps the driver at boot.
- A pod then needs `/dev/dri/renderD*` and Mesa in the image.
- Debian 13's Mesa 25.0.7 gives only Vulkan 1.1 on this GPU; trixie-backports has 26.1.6.
- Not worth it while kbase works.

### Video (MPP) and RGA

**MPP decides which codecs exist from `/proc/device-tree/compatible`.**
- The read is `osal/mpp_soc.c:1098` at jellyfin-ffmpeg 8.1.3's MPP pin (nyanmisaka/rk-mirrors `a9380ef3`), and `:1122` upstream.
- If the read fails, it falls back to an "unknown" SoC with only the old VDPU/VEPU 1 and 2 blocks (`:1083-1089, 1171-1175`).
- `mpp/mpp.c:147-152` then refuses any codec that SoC doesn't list.
- Unprivileged, therefore:
  - HEVC, VP9 and AV1 decode and HEVC encode fail.
  - H.264 passes the check, probably on the legacy cores rather than the RK3588's main decoder and encoder [I].

**What Jellyfin and Frigate document.**
- Jellyfin's Rockchip page passes devices `dri dma_heap mali0 rga mpp_service …` with `--security-opt systempaths=unconfined --security-opt apparmor=unconfined` (`rockchip.md:196-213`).
- Frigate documents the same `security_opt`, with `/dev/dri`, `/dev/dma_heap`, `/dev/rga` and `/dev/mpp_service`.
- `systempaths=unconfined` is Docker's switch for the masked paths. Kubernetes' equivalent is the unmasking that doesn't work on 6.1, so a pod needs `privileged: true`.
- Every Jellyfin and Frigate RK3588 manifest found runs privileged, including a Turing Pi cluster (willianpaixao/homelab).

**RGA works unprivileged.** librga opens only `/dev/rga` and identifies the hardware by ioctl (rk-mirrors `1d330cc` `im2d_api/src/im2d_context.cpp:133-150`) [I].

### Host-only

These are not available to pods:
- Writing NPU, GPU or DDR governors and the rknpu debugfs controls (`/sys` is read-only in an unprivileged container).
- Switching between kbase and panthor (an overlay plus a reboot).

## Jetson Orin Nano: L4T R39.2.1

### GPU

**The container stack.** On Orin, JetPack 7.2.1 uses the Tegra CSV path, not the NVML path:
- `nvidia-l4t-init` 39.2.1: "tegra23x chips use nvgpu-l4t; tegra264 and later use openrm-l4t" (`nv-load-display-modules-choose-variant.sh:37,52-56`).
- At boot `nv-load-gpu-libs.sh` writes Orin's `libcuda` into the container CSV and restarts `nvidia-cdi-refresh.service` (`:31-34, 81-123, 67-72`).
- The toolkit picks CSV mode for a GPU named "(nvgpu)" (go-nvlib `d0f42ba016dd` `property-extractor.go:154-165`; toolkit `internal/info/auto.go:132-133`).
- `nvidia-cdi-refresh` writes the spec to `/var/run/cdi/nvidia.yaml`. On an Orin Nano it is one device (`0`/`all`) carrying every node in `devices.csv` that exists on the host.

**What to install.**
- JetPack's apt repo carries `nvidia-container` 7.2.1-b49, which pins toolkit **1.19.1** (upstream is at 1.20.1).
- The minimal rootfs has no containerd or runc; NVIDIA's "basic" flavor adds them.
- k3s bundles its own containerd and "will automatically detect alternative container runtimes"; pods use `runtimeClassName: nvidia`.

**Host side vs image.**
- The BSP debs provide the driver side: `libcuda` (`nvidia-l4t-cuda-nvgpu`), NVML (`nvidia-l4t-nvml`), the nvrm/host1x libraries, the multimedia core and the CSVs.
- The CSV mounts no CUDA runtime or TensorRT, so the image brings its own.
- 38 `drivers.csv` rows, mostly the GStreamer plugins, belong to apt packages that aren't installed. Those are skipped with a warning (toolkit `internal/discover/mounts.go:66-72`).

**Scheduling.**
- k8s-device-plugin with `--device-discovery-strategy=tegra`.
- **Reported working:** AGX Orin, JetPack 7 / L4T R39.2.1, CUDA driver 13.2, k3s v1.36.3+k3s1, device plugin and GFD v0.18.2, using the CUDA resource manager (KDP2061, 2026-09-24).
  - In that report GFD labels every Jetson `nvidia.com/gpu.memory=4095`: "Scheduling through the `nvidia.com/gpu` extended resource is unaffected — only the label is wrong."
  - The fix is on `main`, not in v0.20.1.
- No report covers v0.20.x on an Orin Nano with R39.
- The chart's node affinity wants `pci-10de.present`, CPU vendor `NVIDIA`, or `nvidia.com/gpu.present=true`. Expect to set the last label by hand [I].
- **Time-slicing** applies to Tegra devices (`internal/rm/tegra_manager.go:32`), as advertisement only, with no isolation [I]. Not reported on R39.

**Support status.**
- NVIDIA staff on JetPack 6.2.1: "By default Kubernetes is not supported on default Jetpack release. This would need community support." Nothing newer says otherwise.
- GPU Operator v26.7: "NVIDIA Jetson, or other embedded products with integrated GPUs, are not supported."
- MIG: "not supported … on the Jetson Orin Series" (r39.2.1 release notes, p.13).

**Images.**
- CUDA 13.2 uses the SBSA toolkit on every Arm target, Orin included. NVIDIA: "This release also supports NVIDIA Jetson Orin devices on the same CUDA SBSA toolkit".
- The Jetson repo's `libcudart.so.13.2.86` is byte-identical to the SBSA repo's.
- NVIDIA's Orin Nano guide for JetPack 7.2.1 uses `nvcr.io/nvidia/cuda:13.0.0-devel-ubuntu24.04` and `nvcr.io/nvidia/pytorch:25.08-py3`. So pods use generic arm64 CUDA 13.2 images.
- NGC's `l4t-*` images stop at r36.
- dusty-nv/jetson-containers targets JetPack 7.2 but is "in a very unstable state currently" for Orin (issue #1736).
- The owner's `immich-machine-learning-jetson-docker` project (Immich ML, Wyoming whisper and piper) targets JetPack 6.2 / CUDA 12.6, and would need rebuilding for CUDA 13 [I].

**Memory.**
- The 8 GB is shared with the CPU.
- Release-note issue 5699079: an oversized CUDA allocation can reboot the device. Set pod memory limits.

### Video and image engines

**How they reach the pod.**
- NVDEC, NVJPG and VIC have no device of their own. They come with the GPU allocation, through `/dev/dri/*`, `/dev/nvmap`, `/dev/host1x-fence` and `/dev/v4l2-nvdec`.
- `/dev/v4l2-nvdec` is a placeholder: udev creates it as char 1:3, which is `/dev/null` (`99-tegra-devices.rules:34`). Real decoding goes through NVIDIA's libv4l2 plugin chain, which the CSV mounts.

**What the image needs.**
- NVIDIA's `ffmpeg 7:8.0.1-nvidia1` (repo `jetson/ffmpeg r39.2`, with `h264/hevc/vp9_nvv4l2dec`), or `nvidia-l4t-gstreamer`.
- Stock Ubuntu libv4l2 fails.

**No report shows hardware decode inside a container on JetPack 7.2.** Unverified.

### What a pod can't use

- **NVENC:** "The NVIDIA® Jetson™ Orin Nano does not have the NVENC engine", although the device tree has an `nvenc` node with status okay.
- **DLA:** none.
- **PVA:** none [I].
- **MIG:** not supported on Orin.
- **NVML telemetry:** utilization, memory, clocks and power return NotSupported on an Orin Nano with JetPack 7.2.1, so `dcgm-exporter` gets nothing.
- **nvpmodel, fan control and `jetson_clocks`:** host only.

### Kernel readiness

**Config source.** The shipped config is in `nvidia-l4t-kernel-headers` 6.8.12-tegra-39.2.1: a full resolved `.config` for `6.8.12-1021-tegra`, which matches the IKCONFIG in `/boot/Image`. Line numbers below are in that file (LJ).

**What k3s needs is there:**
- `VXLAN` (2722), `BRIDGE_NETFILTER` (1155), and the `XT` masquerade, mark, comment and multiport modules.
- `NFT_COMPAT=m` (1212). R36.5 lacked it, which broke iptables-nft containers on JetPack 6.
- `IP_SET`, `VETH`, `OVERLAY_FS=y`, and every cgroup controller.
- NVIDIA's own `nvidia-l4t-configs` loads `br_netfilter` and sets `bridge-nf-call-iptables`.
- k3s v1.37.1's `check-config.sh` passes every required flag.

**What's missing:**

| Missing | Config line | Breaks |
|---|---|---|
| `NFT_CT`; `NFT_FIB_IPV4`/`IPV6` | 1202; 1384, 1417 | kube-proxy **nftables** mode, which uses `ct state` and `fib daddr type local` (kubernetes v1.34.1 `pkg/proxy/nftables/proxier.go:420-433,693`; v1.36.5 uses the same expressions, `:373,481,672,1793`) |
| `IP_VS_PROTO_TCP`/`UDP`, `IP_VS_RR` | 1337, 1338, 1346 | kube-proxy **IPVS** mode |
| `DEBUG_INFO_BTF` (blocked by `DEBUG_INFO_REDUCED=y`, 10939); `XT_TARGET_TPROXY`, `XT_TARGET_CT`, `XT_MATCH_SOCKET` | 10939; 1256, 1239, 1302 | **Cilium** |
| `WIREGUARD`; `XFRM_USER`, `INET_ESP` | 2714; 1090, 1116 | WireGuard and IPsec backends, Tailscale kernel mode |
| `ISCSI_TCP` | 2486 | **Longhorn v1** volumes on this node |
| `XT_TARGET_CT`, `NETFILTER_NETLINK_LOG`, `IP6_NF_MATCH_RPFILTER` | 1239, 1170, 1429 | **Calico** without a kernel rebuild |
| `BLK_DEV_RBD`, `CEPH_FS` | 2353, 10263 | the Ceph kernel client |
| `PSI` | 133 | kubelet PSI metrics |

So the Orin runs **k3s's defaults: Flannel VXLAN and iptables kube-proxy.** `NVME_TCP`, `NBD` and NFS are present.

## Raspberry Pi CM4

### On Raspberry Pi OS (kernel 6.18.50)

All from raspberrypi/linux at `cff533a`, the 2026-10-06 image's kernel.

**Codec device nodes:**
- `bcm2835-codec` creates `/dev/video10` (decode), `video11` (encode), `video12` (ISP), `video18` (deinterlace) and `video31` (JPEG encode) (`bcm2835-v4l2-codec.c:52-68`).
  - Decode inputs: H.264, MJPEG, MPEG-4, H.263, MPEG-2, VC-1. No HEVC.
- **The H.264 encoder is still there on BCM2711.** Only the Pi 5 lost it ("Raspberry Pi 5 uses software video encoders").
- HEVC is a separate **stateless** decoder, `rpi-hevc-dec`: `/dev/video19` plus its own `/dev/mediaN` (`hevc_d.c:37,270,278`).
  - It needs a request-API client: GStreamer, or an FFmpeg with v4l2-request.
  - Frigate's `preset-rpi-64-h265` uses the stateful `hevc_v4l2m2m` (`frigate/ffmpeg_presets.py:86`), so it probably runs in software [I].
  - Jellyfin has deprecated V4L2 on the Pi: "it's unlikely that we'll address any resulting issues".

**How these reach a pod.**
- Frigate's docs: "`/dev/video11` is the correct device (on Raspberry Pi 4B)… Or map in all the `/dev/video*` devices."
- One generic-device-plugin group covering `video10`–`12`, `video19` and the media nodes gives a pod the codecs unprivileged [I].
- The GPU is `/dev/dri/renderD128` (v3d) with Mesa in the image.

**k3s on this CM4:**
- **cgroups.** The CM4's device tree passes `cgroup_disable=memory` (`bcm2711-rpi-ds.dtsi:6`). k3s's docs still say to add `cgroup_memory=1 cgroup_enable=memory` to `cmdline.txt`.
- **etcd.** "SD cards and eMMC cannot handle the IO load" of etcd (k3s requirements). This CM4 has only its 32 GB eMMC.

### Under Talos 1.14.1

**What it loses.**
- No codecs: `bcm2835-codec` and the HEVC decoder aren't in mainline, and `STAGING` is off.
- The GPU works only through the `vc4` extension, with config.txt changes and more CMA than the default 16 MB.

**Turing Pi 2 slot 3.** The v2.5 board fixes the "unconnected #clkreq signal (mostly a case with Talos running on Raspberry Pi CM4)", and U-Boot (since 2024.01) and Linux 6.18 carry matching fixes. No field report confirms a Talos CM4 in a v2.5 slot 3.

## Where Kubernetes could run

### Joining the Super6C Talos cluster

**Sidero's position:**
- "Sorry, this is not supported (mixed clusters), and not going to be supported." (talos#11974, 2025-10-06)
- A newer issue, talos#13371 (opened 2026-05-17, still open), hits the same `talosctl upgrade-k8s` failure on non-Talos nodes.
- Talos 1.12–1.14 and Omni add nothing for outside nodes.

**What a join would need on each vendor node:**
- a kubelet 1.35 or 1.36, no newer than 1.36.5;
- containerd 2.x, which Debian 13 doesn't ship;
- swap off;
- Flannel's CNI binaries preinstalled, since Talos's DaemonSet copies only its config;
- either KubePrism disabled or an HAProxy on 127.0.0.1:7445;
- the bootstrap kubeconfig and CA copied by hand (talos#3990).

**What rules it out:**
- **The Orin's kernel can't run the cluster's kube-proxy nftables mode** (above) [I].
- The cluster enforces baseline Pod Security, so the RK1's privileged pods need a namespace opened for them.

**The CM4 alone could join as an ordinary Talos node**, like the Super6C's own six, at the cost of its codecs and with no data disk.

### A separate k3s cluster on the Turing Pi

**Version and networking.** k3s v1.36.5+k3s1, the current stable, bundles containerd v2.3.4, etcd v3.6.14 and Flannel v0.28.4. Its defaults work on all three kernels.

**Which OSes k3s supports.**
- **SUSE's k3s support matrix** validates v1.36 on Ubuntu 26.04, 24.04 and 22.04, and v1.37 on Ubuntu 26.04 and 24.04, for x86_64 and arm64 (suse.com/suse-k3s/support-matrix). Debian is not on it at all.
- **k3s's own tests:** its end-to-end tests default to `bento/ubuntu-24.04` (`tests/e2e/scripts/run_tests.sh:3`). Ubuntu 26.04 passed k3s's formal OS validation for v1.34.11, v1.35.8 and v1.36.4 on amd64 and arm64 (k3s#14576, closed 2026-09-02).
- **What validation doesn't cover:** it is done on Ubuntu's own kernels, and these boards run their vendors' kernels. So the Ubuntu release contributes only the userspace k3s touches: systemd, AppArmor, iptables. An example of a userspace-and-kernel interaction it wouldn't catch is k3s#13625, an AppArmor signal denial on Ubuntu 25.10's raspi kernel, closed 2026-02.

**Servers.**
- Embedded-etcd HA needs three servers on SSDs. That means both RK1s and the Orin, each with its data dir on NVMe. The Orin shares its 8 GB with the GPU.
- The CM4's eMMC is advised against.
- The alternative is one SQLite server on an RK1: "SQLite cannot be used on clusters with multiple servers".

**Longhorn v1** could place replicas on the RK1s' NVMe. It can't on the Orin, which has no iSCSI. The CM4 has nothing but its eMMC.

### No Kubernetes on the boards

Each board runs its services under Docker Compose, deployed by Ansible like every other host here.
- **What works:** every accelerator, including the RK1's full MPP codec set and Python RKNN. They use the Docker device lists and `security_opt` that Frigate and Jellyfin document.
- **Reaching them from Talos:** pods call these services through a Service with no selector, backed by EndpointSlices (option E in [os-alternatives.md](os-alternatives.md)).

## Decision: Kubernetes on the Turing Pi, or not

**The question:** should the four boards form a Kubernetes cluster, join the Super6C cluster, or run as Docker hosts?

**The goal (owner, 2026-10-08):** the board is self-contained. Its primary data is local, except data that lives only on nas-01, and it may serve other systems, such as the Wyoming whisper stack for Home Assistant.
- A separate k3s cluster meets that goal, and so do Docker hosts.
- Joining the Talos cluster makes the board part of another system.
- How the nodes store their data is in [node-storage.md](node-storage.md).

**Join the Talos cluster as hand-built workers.**
- **For:** one cluster, with the accelerators next to the workloads that already run there.
- **Against:**
  - Sidero won't support it, and the `upgrade-k8s` failure (talos#13371) is open.
  - The kubelet, containerd 2.x, the CNI binaries and a KubePrism stand-in would be kept by hand on three OSes.
  - The Orin's kernel can't run the cluster's kube-proxy mode [I].
  - The RK1's video and Python NPU would need privileged pods in a baseline cluster.
  - It turns a supported stack into an unsupported one.

  It isn't a real option.

### What Kubernetes makes consistent, and what it doesn't

The owner's concern (2026-10-08): three OSes running Docker Compose means "three different sets of problems when upgrading the os and different docker issues". Kubernetes was meant to be "a consistent layer on top of this", but "that might be a fallacy". **Partly. Kubernetes makes the workload layer consistent. It does not touch the OS layer, and the OS layer is where those upgrade problems live.**

**Below Kubernetes, each node has its own update channel, set by its hardware vendor:**

| Node | Kernel and firmware come from | Userspace | How it updates today |
|---|---|---|---|
| RK1 ×2 | Rockchip's vendor kernel, through the homelab's own Armbian build (`rk1-armbian-minimal`) | Debian 13 today; Ubuntu 26.04 decided | Userspace through apt. The kernel needs a new image and a reflash: no in-place path yet (open since 2026-10-01) |
| Orin | NVIDIA L4T, through the homelab's private repo with the fixed QSPI capsule | Ubuntu 24.04 | `apt upgrade` and a reboot; new releases publish themselves ([turingpi/jetson/](../../turingpi/jetson/README.md)) |
| CM4 | Canonical's `linux-raspi` (from the Pi tree, `rpi-7.0.y`) ([cm4-os.md](cm4-os.md)) | Ubuntu 26.04 (decided; Armbian trixie today) | `apt upgrade`. `piboot-try` tries each new kernel once and falls back if it fails to boot |

- **Every accelerator here needs its vendor's kernel.** So three kernel and firmware channels is the floor for as long as all four boards run. Kubernetes sits above every row and changes none of them.
- **The userspace can be one distro, but only Ubuntu.** NVIDIA's L4T root filesystem is Ubuntu, so the Jetson can't change. The owner's decision is Ubuntu 26.04 on the RK1s and the CM4 and 24.04 on the Jetson: one distro, two releases ([cm4-os.md](cm4-os.md)).
- **Only three things shrink the OS work:**
  - one distro across the nodes;
  - fewer channels: the CM4 adds the least hardware and costs a whole channel [I];
  - automating each channel: the Jetson's is automated; the RK1 kernel is the manual one.

**"Different Docker issues" mostly don't arise.**
- The repo installs Docker CE from Docker's own repository (`geerlingguy.docker`). That repository ships the same `docker-ce` (5:29.8.2) and `containerd.io` (2.3.6) for Debian 13, Ubuntu 24.04 and Ubuntu 26.04 on arm64.
- What does differ per node is the accelerator plumbing: NVIDIA's container toolkit on the Orin, device lists or privileged mode on the RK1 and CM4. That sits below Docker, and below k3s just the same.
- k3s goes one step further: it bundles its own containerd and runc, so the runtime doesn't come from the distro at all.

**What Kubernetes does make consistent:**
- One runtime version.
- One way to deploy, upgrade, roll back, health-check and restart every service, with the config in one place.
- The same tooling as the Super6C cluster.
- k3s can upgrade itself node by node with Rancher's system-upgrade-controller, which the k3s docs describe.

**What it adds or can't do:**
- **A layer of its own to upgrade:** k3s, the NVIDIA device plugin (tied to the JetPack release), a generic device plugin.
- **Help during maintenance only for the RK1 pair.** The two RK1s are identical, so their pods can move to the other one while one is upgraded. That holds if they're stateless, or if Longhorn replicates their volumes between the two NVMe drives. The Orin and the CM4 are single nodes, so their services stop during their own upgrades either way.
- **Limits from the Orin's kernel:** Flannel with iptables kube-proxy only.
- **Rewrites:** the repo's existing Compose roles, such as `docker_compose_wyoming_faster_whisper`, would become manifests.

**A correction to the first version of this decision.** It recommended Docker hosts because "every accelerator works" there, the RK1's full video and Python NPU included. That is no advantage over k3s:
- k3s enforces no Pod Security by default, so a privileged pod gets what Docker's `systempaths=unconfined` gets.
- On capability the two options are equal. What separates them is moving parts and the operating model.

**A separate k3s cluster.**
- **For:**
  - One runtime (k3s's bundled containerd) and one deploy, health and rollout model on every node.
  - Self-upgrading through system-upgrade-controller.
  - The same operating model as the Super6C cluster.
  - Every accelerator reaches pods: most unprivileged, the RK1's full video and Python NPU through privileged pods, which k3s allows by default.
  - It exercises the accelerator mechanics a production cluster uses: a vendor device plugin with CDI and a RuntimeClass on the Orin, extended resources, NFD labels, taints, and the generic-device-plugin pattern.
  - k3s's defaults work on every kernel.
- **Against:**
  - Changes nothing about the OS update channels (above).
  - Adds k3s and the device plugins to maintain. The device plugins are the parts most exposed to vendor updates: NVIDIA's plugin and toolkit move with the JetPack release, and an RK1 kernel change can renumber the DRM nodes a generic-plugin config names [I].
  - Rolling upgrades work only for the RK1 pair. The Orin's and the CM4's services stop during their upgrades.
  - NVIDIA calls Kubernetes on Jetson community support. What enterprises use, the GPU Operator, excludes Jetson, so the Orin teaches the layer under the Operator, not the Operator itself [I].
  - The Orin can't hold Longhorn volumes.
  - HA would put etcd on the Orin, next to its GPU's memory.
  - The Orin path rests on one AGX Orin report.
  - The existing Compose roles are rewritten as manifests.
  - The Immich ML image needs rebuilding for CUDA 13 [I], on either option.

**Docker hosts managed by Ansible.**
- **For:**
  - The fewest moving parts.
  - The same Docker CE version on every node.
  - The same tooling and roles as every other host in the repo. The whisper stack already has a role, and the Orin's Immich ML and Wyoming project is already a Compose project.
  - Every accelerator works, using the device lists the apps document for Docker.
- **Against:**
  - No health-driven restarts beyond Docker's restart policy, no rollouts, and no shared ingress or monitoring model unless built.
  - Each service is pinned to a host by hand. An RK1 upgrade stops that RK1's services, where k3s could move them to the other RK1.
  - Changes nothing about the OS update channels either.
  - Nothing to learn about accelerator scheduling.

**The CM4, separately.** It could become a seventh Talos node, losing its codecs, with no data disk and no field report for slot 3. Or it could stay a plain host on its recommended OS ([cm4-os.md](cm4-os.md)) for H.264. Or it could leave the board's service roles, which removes one OS channel.

**Measured against OS upgrades, the concern the owner raised, k3s buys one thing: RK1 services that stay up while an RK1 is upgraded.**
- It does nothing for the Orin or the CM4, whose services stop during their upgrades on either option.
- It does nothing for "Docker issues", which Docker CE already makes uniform.
- In exchange, it adds k3s, the device plugins and the CNI as things that can break after a vendor update. It also replaces Compose roles the repo already has.
- The consistency that does cut OS-upgrade work comes from below Kubernetes:
  - **one distro on every node.** The Jetson can only run Ubuntu, so that means Ubuntu: 26.04 on the RK1s and the CM4, 24.04 on the Jetson ([cm4-os.md](cm4-os.md));
  - **automated RK1 kernel updates.**

**Recommendation: Docker hosts managed by Ansible.**
- The only OS-upgrade benefit k3s offers is RK1 services staying up during RK1 upgrades.
- Nothing planned so far needs that. Whisper and piper, the service named for Home Assistant, run on the Orin, which k3s can't cover.

**What would change it:**
- **If RK1-hosted services must stay up through RK1 upgrades,** choose k3s. That means services such as LLMs on the NPU, or Immich ML on RKNN. Make them stateless, or replicate their volumes with Longhorn between the two RK1s.
- **If the operating model itself is wanted,** also choose k3s: health-driven restarts, rollouts, one ingress and monitoring stack, the same tooling as the Super6C, or learning accelerator scheduling. The Orin is the board that teaches the enterprise-shaped part: NVIDIA's device plugin, CDI and RuntimeClass.
- **Either way the OS channels stay as they are.**

## Open

**Everything here was read, not run.** On the nodes:
- **RK1:**
  - Which DRM node librknnrt opens, and whether several pods can share the NPU.
  - Whether H.264 under MPP's fallback uses the main or the legacy cores.
  - Whether the image has `apparmor_parser`.
  - Whether `init_runtime(target='rk3588')` avoids the device-tree read.
  - Whether g24p0 libmali works on the g29p1 kernel driver.
- **Orin:**
  - Whether `nvidia-cdi-refresh` writes a valid spec.
  - Whether device plugin v0.20.x works on an Orin Nano with R39.
  - Hardware decode inside a container, and time-slicing.
  - Whether the node boots with cgroup v2.
- **CM4:**
  - Its actual device nodes.
  - A Talos CM4 in a v2.5 slot 3.

## Sources

**RK1**
- **AKD:** Armbian beta `linux-image-vendor-rk35xx_26.11.0-trunk.75` (6.1.172), `./boot/config-6.1.172-vendor-rk35xx`, from beta.armbian.com `pool/main/l/linux-6.1.172/`.
- armbian/linux-rockchip `44bbd021d780`: `drivers/rknpu/rknpu_drv.c`, `drivers/gpu/arm/valhall/`, `mm/shmem.c`, `init/Kconfig`.
- armbian/build `8eb7e43e`: `lib/functions/compilation/armbian-kernel.sh`, `packages/bsp/common/etc/default/armbian-ramlog.dpkg-dist`, `armbian-zram-config.dpkg-dist`.
- airockchip/rknn-toolkit2 v2.3.2 (`librknnrt.so`); airockchip/rknn-llm release-v1.3.1.
- nyanmisaka/rk-mirrors `a9380ef3` (`osal/mpp_soc.c`, `mpp/mpp.c`) and `1d330cc` (librga); rockchip-linux/mpp `develop` `osal/mpp_soc.c:1122`.
- JeffyCN/mirrors `bf621d15f009` (libmali g29p1).
- Jellyfin docs, Rockchip hardware acceleration (`rockchip.md`); Frigate docs (`installation.md`, `hardware_acceleration_video.md`), `frigate/detectors/plugins/rknn.py`.
- Issues: invisiofficial/rk-llama.cpp#19, airockchip/rknn-toolkit2#153, immich#25057, k3s#10126, #11415, #12849, #13974, Joshua-Riek/ubuntu-rockchip#664.
- Device plugins: elct9620/rknpu-device-plugin, tylertitsworth/ai-cluster, gjing1st/rk3588-device-plugin, schwankner/talos-rk3588-npu, gclawes/rockchip-dra-driver.

**Orin**
- **LJ:** `nvidia-l4t-kernel-headers_6.8.12-tegra-39.2.1-20260806224157_arm64.deb`, `…/3rdparty/canonical/linux-noble/.config`.
- NVIDIA apt repos `repo.download.nvidia.com/jetson/{common,som,ffmpeg}/dists/r39.2/`; the BSP `Jetson_Linux_R39.2.1_aarch64.tbz2` (`nvidia-l4t-init`, `nvidia-l4t-cuda-nvgpu`, `nvidia-l4t-nvml`, `nvidia-l4t-configs`).
- [r39.2.1 Developer Guide](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/) (Package Manifest, Root File System, Software Encode in Orin Nano, Accelerated Decode with ffmpeg); [r39.2.1 release notes](https://docs.nvidia.com/jetson/archives/r39.2.1/ReleaseNotes/Jetson_Linux_Release_Notes_r39.2.1.pdf); [Orin Nano devkit user guide](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/).
- NVIDIA/nvidia-container-toolkit v1.19.1; NVIDIA/go-nvlib `d0f42ba016dd`.
- **KDP2061:** [NVIDIA/k8s-device-plugin#2061](https://github.com/NVIDIA/k8s-device-plugin/issues/2061); also #1963; v0.20.1 `internal/rm/tegra_manager.go`, `deployments/helm/.../values.yaml`.
- [GPU Operator platform support](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html); [kubernetes-sigs/dra-driver-nvidia-gpu](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu).
- [CUDA 13.2 blog](https://developer.nvidia.com/blog/cuda-13-2-introduces-enhanced-cuda-tile-support-and-new-python-features/); NGC registry tags for `l4t-jetpack`, `l4t-base`, `l4t-cuda`; dusty-nv/jetson-containers #1736.
- NVIDIA forum: "Kubernetes is not supported on default Jetpack release" (2025-07-29); thread 358833 (Calico kernel rebuild).

**CM4**
- raspberrypi/linux `cff533a` (`arch/arm64/configs/bcm2711_defconfig`, `drivers/staging/vc04_services/bcm2835-codec/bcm2835-v4l2-codec.c`, `drivers/media/platform/raspberrypi/hevc_dec/`, `arch/arm/boot/dts/broadcom/bcm2711-rpi-ds.dtsi`); [Raspberry Pi OS release notes](https://downloads.raspberrypi.com/raspios_lite_arm64/release_notes.txt).
- raspberrypi/documentation `processors/bcm2711.adoc`, `camera/rpicam_vid.adoc`.
- Frigate `frigate/ffmpeg_presets.py`; Jellyfin `hardware-acceleration/index.md:172-176`.
- siderolabs/pkgs `release-1.14` `kernel/build/config-arm64`; siderolabs/extensions v1.14.1 `drm/vc4`; [Talos rpi_generic v1.14](https://docs.siderolabs.com/talos/v1.14/platform-specific-installations/single-board-computers/rpi_generic); [Turing Pi 2.5 changelog](https://docs.turingpi.com/changelog/turing-pi2-v25-list-of-improvements).

**Kubernetes, k3s, containerd**
- kubernetes v1.36.5 `pkg/securitycontext/util.go:196-210`; v1.34.1 and v1.36.5 `pkg/proxy/nftables/proxier.go`; [version skew policy](https://kubernetes.io/releases/version-skew-policy/); Kubernetes 1.35 release blog (containerd 1.x); [1.36 release blog](https://kubernetes.io/blog/) (**K136**, DRA); "User namespaces" (release-1.36).
- k3s v1.36.5+k3s1: `contrib/util/check-config.sh`, `pkg/daemons/agent/agent.go:180`; [k3s requirements](https://docs.k3s.io/installation/requirements), [HA embedded etcd](https://docs.k3s.io/datastore/ha-embedded), [NVIDIA runtime support](https://docs.k3s.io/advanced#nvidia-container-runtime-support).
- containerd v2.3.4 (`pkg/oci/spec.go`, `contrib/apparmor/template.go`, `internal/cri/config/config_unix.go`, `container_create.go`); runc v1.4.2.
- [squat/generic-device-plugin](https://github.com/squat/generic-device-plugin); Akri; ARM smarter-device-manager; containerd/nri `device-injector`; [Node Feature Discovery](https://github.com/kubernetes-sigs/node-feature-discovery) v0.19.0.
- Talos: [#11974](https://github.com/siderolabs/talos/issues/11974), [#13371](https://github.com/siderolabs/talos/issues/13371), [#3990](https://github.com/siderolabs/talos/issues/3990); v1.14.1 `internal/app/machined/pkg/controllers/k8s/internal/k8stemplates/flannel.go`.
- Cilium v1.20.2 `Documentation/operations/system_requirements.rst`.
