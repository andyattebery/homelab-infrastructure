# Istio's mesh on this Talos cluster

Researched 2026-09-30. Quotes are verbatim. **[I]** marks inference.

The front door doesn't need a mesh ([README.md](README.md), decision 2). This doc answers the follow-up question: if Istio is the controller, can its mesh run on this cluster later? It covers Talos 1.14.1, Flannel, nftables kube-proxy, arm64 CM4s, and Pod Security at baseline.

## Bottom line

- **Probably, but nobody has reported it on this setup.**
  - Ambient mode, Istio's sidecar-free mesh, has community success reports on Talos, all with Cilium; two name Istio 1.27 or newer.
  - None of them use Flannel, which is Talos's default CNI and this cluster's.
  - One report is an unexplained failure.
- **The kernel isn't the obstacle.** Everything ambient's traffic redirection uses is built in. That matters because Talos won't let workloads load kernel modules, the suspected cause of a 2023 failure.
- **One Talos-specific setting:** Talos 1.14's kernel leaves out legacy iptables. Run Istio's rules in its native nftables mode (`global.nativeNftables=true`, for ambient since Istio 1.28) rather than let it detect a backend [I].
- **Two costs:**
  - Istio's CNI agent and ztunnel need a privileged namespace.
  - Together they reserve about 600 MiB on each node by default.
- **A test install settles it.** Run it after the rebuild on 1.36, before anything depends on the mesh. The steps are at the end.

## How ambient mode works

- It adds two DaemonSets to istiod: the istio-cni node agent and ztunnel, a per-node proxy.
- "The `istio-cni` node agent enters the pod's network namespace and establishes network redirection rules inside the pod network namespace, such that packets entering and leaving the pod are intercepted and transparently redirected to the node-local ztunnel proxy." (Istio blog, "Maturing Istio Ambient", 2024)
- The rules use TPROXY, REDIRECT and CONNMARK in the mangle and nat tables. They send ingress "to port 15008 for HBONE-encrypted traffic or port 15006 for plaintext, and egress traffic to port 15001" (Istio docs, "Traffic redirection").
- This in-pod design was built to make ambient independent of the cluster's CNI. Istio cites "GKE, AKS, and EKS and all the CNI implementations they offer, as well as with 3rd-party CNIs like Calico and Cilium, as well as platforms like OpenShift."

## Checked against this cluster

### Kernel

Talos 1.14.1 builds its kernel from `siderolabs/pkgs` v1.14.0-25-gf694e1b (`kernel/build/config-arm64`).

- **Built in (`=y`):**
  - TPROXY: `NETFILTER_XT_TARGET_TPROXY`, `NF_TPROXY_IPV4`, `NF_TPROXY_IPV6`, `NFT_TPROXY`
  - socket matching: `NETFILTER_XT_MATCH_SOCKET`, `NFT_SOCKET`
  - marks: `NETFILTER_XT_MARK`, `NETFILTER_XT_CONNMARK`, `NF_CONNTRACK_MARK`, `NFT_CT`
  - redirect and NAT: `NETFILTER_XT_TARGET_REDIRECT`, `NFT_REDIR`, `NFT_NAT`
  - iptables over nf_tables: `NFT_COMPAT`
- **Nothing has to be loaded as a module.**
  - siderolabs/talos#7380 (2023, Istio 1.18) reported that ambient failed on Talos. That was before in-pod redirection existed.
  - A Talos maintainer replied: "I think it could be ztunnel tried to load a module? Talos doesn;t allow loading modules by K8s workloads."
  - The issue closed as stale without an answer.
- **`# CONFIG_NETFILTER_XTABLES_LEGACY is not set`:** legacy iptables is compiled out, and iptables works only through nf_tables. That's consistent with kube-proxy running in nftables mode here.

### Which backend Istio uses for its rules

- Istio 1.28 change notes:
  - "Added support for native nftables when using Istio ambient mode. … To enable the nftables mode, use `--set values.global.nativeNftables=true` when installing Istio."
  - Also: "Added support for the environment variable `FORCE_IPTABLES_BINARY` to override iptables backend detection and use a specific binary."
- The 1.31.1 `cni` chart defaults to `nativeNftables: false`, so by default it detects an iptables backend.
- With legacy iptables missing from the kernel, set `nativeNftables: true` rather than depend on detection [I]. Every nftables feature that mode needs is built in (above).

### CNI paths

- The `cni` chart's defaults are `cniBinDir: /opt/cni/bin`, `cniConfDir: /etc/cni/net.d`, `cniNetnsDir: "/var/run/netns"` and `chained: true`. That is, it adds itself to the existing CNI configuration.
- On Talos: "/opt/cni/bin is actually an overlay mount, so it's writeable, and you can do an init container which drops any plugins you might want" (Talos maintainer, siderolabs/talos discussion #10524, 2025-03-13).
- Istio's platform prerequisites list environments that need extra settings. K3s and k3d need a `global.platform` value for their nonstandard CNI paths, and GKE, EKS, OpenShift and others have quirks of their own. Talos isn't listed, and its paths match the defaults [I: no platform value needed].
- A third-party guide adds kubelet `extraMounts` for both CNI paths on Talos, for sidecar mode. The maintainer's statement above suggests they aren't needed [I].

### Flannel

- Istio documents ambient with Flannel only through k3d ("When using k3d with the default Flannel CNI, you must append the correct `platform` value…") and K3s. Both need path overrides only, "as K3s uses nonstandard locations for CNI configuration and binaries".
- No report found of ambient on Talos with Flannel.
- The Talos reports found are from an October 2025 forum thread:
  - three successes, all with Cilium. Two set Cilium's `cni.exclusive=false`, and two name Istio "1.27 or newer" (one 1.27.2).
  - one failure ("my entire cluster became unresponsive"), with no detail

### Pod Security and SELinux

- **istio-cni** adds `NET_ADMIN`, `NET_RAW`, `SYS_PTRACE`, `SYS_ADMIN` and `DAC_OVERRIDE`. It mounts host paths: `/opt/cni/bin`, `/etc/cni/net.d`, `/proc`, `/var/run/netns`, `/var/run/ztunnel`, `/var/run/istio-cni`.
- **ztunnel** adds `NET_ADMIN` ("Required for TPROXY and setsockopt"), `SYS_ADMIN` ("Required for `setns`") and `NET_RAW`. Both are `privileged: false`.
- Baseline forbids `NET_ADMIN`, `NET_RAW`, `SYS_PTRACE` and `SYS_ADMIN` (only `DAC_OVERRIDE` is on its allowed list), and it forbids host paths. So `istio-system` needs the privileged labels, as `metallb-system` and `longhorn-system` have.
- The CNI DaemonSet runs as `system-node-critical`. GKE restricts that class to certain namespaces (Istio docs); Talos isn't documented to [I].
- SELinux on Talos is permissive by default. Enforcing needs `enforcing=1` on the kernel command line, which `talos/schematic.yaml` doesn't set.

### Images and resources

- `istio/ztunnel:1.31.1` and `istio/install-cni:1.31.1` are published for amd64 and arm64.
- Default requests per node, from the 1.31.1 charts: ztunnel 200m CPU and 512 MiB; istio-cni 100m and 100 MiB.
  - That's about 612 MiB per node, or 3.6 GiB across six, before istiod's 2 GiB (tunable).
  - Each node has 6.2–6.8 GiB available.

### Sidecar mode, the other mesh mode

- Without the CNI agent, sidecar injection needs "the `NET_ADMIN` and `NET_RAW` capabilities" in every meshed pod, which baseline forbids.
- "The `istio-cni` node agent is effectively a replacement for the `istio-init` container".
- So on Talos, either mesh mode needs the same CNI agent and the same privileged namespace [I].

## The test that would settle it

Run it on the rebuilt 1.36 cluster, before anything depends on the mesh. The steps get written out and approved before anything runs.

1. Label `istio-system` with the privileged Pod Security labels.
2. Install `base`, `istiod`, `cni` and `ztunnel` 1.31.1 from `oci://ghcr.io/istio/release/charts`, with `profile=ambient` and `global.nativeNftables=true`.
3. Label a test namespace `istio.io/dataplane-mode=ambient` and run two pods in it. Check their traffic goes through ztunnel with mutual TLS: `istioctl` shows the workloads using HBONE [I: confirm the exact command then].
4. Check the rollback: `helm uninstall` the `ztunnel` and `cni` releases. Then confirm each node's CNI configuration no longer lists istio-cni, and that new pods still start.

## Sources

- Istio blog, "Maturing Istio Ambient: Compatibility Across Various Kubernetes Providers and CNIs" (2024): istio.io/latest/blog/2024/inpod-traffic-redirection-ambient/
- Istio docs, "Traffic redirection": istio.io/latest/docs/ambient/architecture/traffic-redirection/
- Istio docs, "Platform-Specific Prerequisites": istio.io/latest/docs/ambient/install/platform-prerequisites/
- Istio docs, "Install the Istio CNI node agent": istio.io/latest/docs/setup/additional-setup/cni/
- Istio 1.28.0 change notes: istio.io/latest/news/releases/1.28.x/announcing-1.28/change-notes/
- Talos kernel configuration: github.com/siderolabs/pkgs, `kernel/build/config-arm64` at v1.14.0-25-gf694e1b (the `PKGS` pin in Talos v1.14.1's Makefile)
- siderolabs/talos#7380 and discussion #10524 on GitHub
- Talos docs, "SELinux": docs.siderolabs.com/talos/v1.13/security/selinux
- Forum thread "Has Anyone Deployed Istio in Ambient Mode on a Talos Cluster?" (October 2025): yomotherboard.com
- Istio 1.31.1 `cni` and `ztunnel` charts (`helm show values`, `helm template`) and Docker Hub tags
