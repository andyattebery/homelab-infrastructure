# media-01 rebuild — NVIDIA driver install method

## Context

media-01 is being rebuilt on Ubuntu 26.04 and reprovisioned from scratch. It's a Proxmox VM with an A4000 (Ampere) passed through. Workloads are Immich-ML, Obico-ML, Plex transcoding — all in containers. No bare-metal CUDA work.

Decision: how to install the NVIDIA driver on the fresh host, and bake that into Ansible going forward.

Inputs locked in:

- CUDA toolkit: **containers only** — host gets driver + `nvidia-container-toolkit` only.
- Kernel modules: **open** (`-open` packages). A4000 is Ampere; NVIDIA's stated default for Turing+ is the open kernel modules, and future branches will be open-only on these GPUs.
- Upgrade cadence: **deliberate, pinned**. Driver branch is a variable in the playbook; upgrades happen when the user changes the variable and re-runs the play. No rolling auto-upgrades.

Existing repo state:

- Galaxy role `nvidia.nvidia_driver` (pinned in [../ansible/requirements.yaml](../ansible/requirements.yaml)).
- Local role [../ansible/roles/nvidia_driver/](../ansible/roles/nvidia_driver/) — trivial wrapper around `ubuntu-drivers install --gpgpu`, unreferenced by any playbook.
- Local role [../ansible/roles/nvidia_container_toolkit/](../ansible/roles/nvidia_container_toolkit/) — adds NVIDIA's `libnvidia-container` apt repo, installs `nvidia-container-toolkit`, runs `nvidia-ctk runtime configure --runtime=docker`. Keep this; it's the only viable source for the container toolkit. **Note:** `nvidia.github.io/libnvidia-container` (used here) is a *different* apt repo from `developer.download.nvidia.com/compute/cuda/...` (the CUDA repo). Using the toolkit doesn't pull us into the CUDA repo for the driver.

---

## What the authoritative sources recommend

Both vendors recommend their own source. Honest disagreement:

- **Canonical** ([Ubuntu Server docs — install nvidia drivers](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/)): recommends `ubuntu-drivers install --gpgpu` against their archive. Calls their `-server`-suffixed packages "Enterprise Ready Drivers (ERD)". Warning: *"NVIDIA drivers installed from sources outside of those listed in this guide could potentially overwrite those provided by ubuntu-drivers and may break Secure Boot."* `ubuntu-drivers` ships only pre-built signed kernel modules.
- **NVIDIA** ([Driver Installation Guide for Ubuntu](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/ubuntu.html)): recommends their CUDA apt repo, with `apt install libnvidia-compute nvidia-dkms-open` for compute-only systems. Doesn't acknowledge Canonical's path.
- **Both agree on one rule**: don't mix sources. Common failure is "default repo + PPA + CUDA repo all enabled → kernel module from one source, userland utilities from another → CUDA breaks."

When each wins:

| Canonical archive (`nvidia-headless-XXX-server-open`) | NVIDIA CUDA repo (`nvidia-headless-XXX-open`) |
|---|---|
| Signed for Secure Boot | Latest patch releases ship faster |
| SRU-tested security backports via `-updates` pocket | Has more branches available (NVIDIA's full set) |
| Canonical's official recommended path | NVIDIA's official recommended path |
| Single-vendor lifecycle (Ubuntu controls kernel + driver together) | Useful if Canonical hasn't packaged the branch you want |
| No third-party apt repo for the driver | — |

---

## Recommendation: Canonical archive, branch-pinned in the playbook

**Install `nvidia-headless-{branch}-server-open` from Canonical's archive via direct `apt` in a rewritten local role.** Branch number is a variable passed from the playbook, not the role default.

Why Canonical archive over NVIDIA's CUDA repo, given pinning:

- The only reason to pick NVIDIA's CUDA repo over Canonical was "latest Recommended/Certified is only there." If we're pinning, "latest" doesn't apply — and Canonical's archive does have current production branches (resolute ships 535, 570, 580, 590, 595 in `-server-open` at release; newer branches arrive via `-updates` over time).
- Pre-signed for Secure Boot — no MOK enrollment dance if/when you flip SB on later.
- One fewer apt source to maintain. We still need `nvidia.github.io/libnvidia-container` for `nvidia-container-toolkit` (separate repo), but the driver itself comes from `archive.ubuntu.com`.
- Matches Canonical's official path verbatim — if anything goes wrong with the driver on Ubuntu, the failure mode lines up with documented troubleshooting.

Why direct `apt` instead of wrapping `ubuntu-drivers install --gpgpu`:

- `ubuntu-drivers` is a non-idempotent `command:` task unless you wrap it carefully; Ansible's `apt` module is idempotent and explicit about the exact package set.
- `ubuntu-drivers` reads from *whatever* apt sources are configured. If a stray CUDA repo gets added later, `ubuntu-drivers` will silently start preferring NVIDIA's packages. Direct `apt install nvidia-headless-595-server-open` is unambiguous.
- The package name is descriptive: `nvidia-headless-{branch}-server-open` says everything (headless, branch, ERD/server, open modules).

### Branch choice for the rebuild

**Pin to `nvidia-headless-595-server-open`** (currently `595.58.03-0ubuntu2` in 26.04 resolute).

Verified by direct probe of `archive.ubuntu.com/ubuntu/dists/resolute/restricted/`:

- Resolute (26.04) release archive ships these `-server-open` branches: **535, 570, 580, 590, 595**.
- 595 is the highest, and it matches NVIDIA's current Recommended/Certified branch for the A4000 (NVIDIA ships 595.71.05; Canonical ships 595.58.03-0ubuntu2 — same branch, one patch release behind; expect Canonical to catch up via `-updates`).

Re-verify on rebuild day in case Canonical has added a newer branch via `resolute-updates`:

```
apt-cache search '^nvidia-headless-[0-9]\+-server-open$' | sort -V
```

Pick the highest number from that output.

---

## Implementation

### Rewritten role

```yaml
# ansible/roles/nvidia_driver/defaults/main.yaml
---
# Override in playbook. Pick the highest available -server-open branch in
# the LTS archive at install time (verify with apt-cache search).
nvidia_driver_branch: "595"
```

```yaml
# ansible/roles/nvidia_driver/tasks/main.yaml
---
- name: Install NVIDIA driver (headless, ERD, open kernel modules)
  ansible.builtin.apt:
    name:
      - "nvidia-headless-{{ nvidia_driver_branch }}-server-open"
      - "nvidia-utils-{{ nvidia_driver_branch }}-server"
    update_cache: true
  notify: reboot host

- name: Enable nvidia-persistenced
  ansible.builtin.systemd:
    name: nvidia-persistenced
    enabled: true
```

```yaml
# ansible/roles/nvidia_driver/handlers/main.yaml
---
- name: reboot host
  ansible.builtin.reboot:
```

Notes on the package set:

- `nvidia-headless-{branch}-server-open` is Canonical's ERD headless meta — pulls `nvidia-dkms-{branch}-server-open` (kernel modules via DKMS, pre-signed), `libnvidia-compute-{branch}-server`, `nvidia-kernel-common-{branch}-server`. No Xorg.
- `nvidia-utils-{branch}-server` — provides `nvidia-smi`. May be transitional on some versions; apt resolves it to whatever actually ships the binary.
- nouveau blacklist is handled by the packaging (`nvidia-kernel-common-{branch}-server` ships the blacklist). No explicit task needed.
- `nvidia-persistenced` is pulled transitively by `libnvidia-compute`; we just enable the systemd unit.

### Playbook delta

Replace the commented `nvidia.nvidia_driver` block in [../ansible/playbook-media-01.yaml](../ansible/playbook-media-01.yaml) with:

```yaml
- role: nvidia_driver
  vars:
    nvidia_driver_branch: "595"   # bump deliberately; verify with `apt-cache search '^nvidia-headless-[0-9]\+-server-open$'` before
```

Order remains: `geerlingguy.docker` → `nvidia_driver` → `nvidia_container_toolkit` → docker-compose workloads. The driver must be installed (and reboot completed, if any) before `nvidia-ctk runtime configure` runs.

### Other repo cleanup tied to this change

- Drop `nvidia.nvidia_driver` from [../ansible/requirements.yaml](../ansible/requirements.yaml). `grep -R "nvidia.nvidia_docker" ansible/` shows zero hits, so remove that too.
- Dedupe the apt sources in [../ansible/roles/nvidia_container_toolkit/tasks/main.yaml](../ansible/roles/nvidia_container_toolkit/tasks/main.yaml) — currently adds both `stable/deb/$(ARCH)` and the legacy `stable/ubuntu18.04/$(ARCH)`. Keep `stable/deb/$(ARCH)` only.
- Make `nvidia-ctk runtime configure` + Docker restart in that role conditional on actual change (compare `/etc/docker/daemon.json`, or convert to a handler) instead of `changed_when: false` + unconditional restart.

### Files modified

- [../ansible/roles/nvidia_driver/defaults/main.yaml](../ansible/roles/nvidia_driver/defaults/main.yaml) (rewrite — just the branch default)
- [../ansible/roles/nvidia_driver/tasks/main.yaml](../ansible/roles/nvidia_driver/tasks/main.yaml) (rewrite)
- [../ansible/roles/nvidia_driver/handlers/main.yaml](../ansible/roles/nvidia_driver/handlers/main.yaml) (new)
- [../ansible/playbook-media-01.yaml](../ansible/playbook-media-01.yaml) (uncomment the GPU stack, switch to local role with `nvidia_driver_branch` var)
- [../ansible/requirements.yaml](../ansible/requirements.yaml) (drop `nvidia.nvidia_driver`, `nvidia.nvidia_docker`)
- [../ansible/roles/nvidia_container_toolkit/tasks/main.yaml](../ansible/roles/nvidia_container_toolkit/tasks/main.yaml) (dedupe sources, fix restart logic)

---

## Verification

After fresh provision on Ubuntu 26.04:

0. **Pre-flight on the new VM**: `apt-cache search '^nvidia-headless-[0-9]\+-server-open$' | sort -V` → confirm the branch you want to pin is present in 26.04's archive. If your pinned `nvidia_driver_branch` isn't there, pick the highest one that is.
1. After play run: `apt-cache policy nvidia-headless-${branch}-server-open` → installed, candidate from `archive.ubuntu.com`. `dpkg -l 'nvidia-*'` shows the consistent versioned set.
2. `nvidia-smi` → reports `${branch}.xx.yy` and lists the A4000.
3. `lsmod | grep nvidia` → shows `nvidia`, `nvidia_uvm`; `lsmod | grep nouveau` is empty.
4. `modinfo nvidia | grep -i license` → confirms open-source licensed modules (MIT/GPL dual).
5. `systemctl is-enabled nvidia-persistenced` → enabled and running.
6. `docker info | grep -i runtimes` → `nvidia` listed.
7. `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi` → succeeds, sees A4000.
8. Spin up Immich-ML container; confirm `/proc/driver/nvidia/version` inside the container matches host and a sample inference job completes.

### Bumping the driver later

1. Check `apt-cache search '^nvidia-headless-[0-9]\+-server-open$' | sort -V` on the host for newly-available branches (Canonical adds them to `-updates` over time).
2. Edit the `nvidia_driver_branch` value in [../ansible/playbook-media-01.yaml](../ansible/playbook-media-01.yaml).
3. Re-run the play — apt swaps to the new versioned package set, `reboot host` handler fires.
4. Re-run the verification block above.
