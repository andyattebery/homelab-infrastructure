#!/bin/bash
# Armbian's image-customization hook for the RK1 image (armbian/README.md). Armbian copies it into
# the image and runs it there as root (lib/functions/rootfs/customize.sh:24-34) with the arguments
#   RELEASE LINUXFAMILY BOARD BUILD_DESKTOP ARCH
# after its own packages are installed and before its apt repo is enabled: Debian's repos are
# reachable here, Armbian's are not. userpatches/overlay/ is bind-mounted read-only at
# /tmp/overlay. Any non-zero exit fails the build.
set -euo pipefail

RELEASE="$1"
BOARD="$3"
# Everything below is written for one target: Debian 13 package names, Jellyfin's trixie suite,
# and the RK1's GPU and NPU.
if [[ "$RELEASE" != trixie || "$BOARD" != turing-rk1 ]]; then
    echo "customize-image.sh: written for trixie on turing-rk1, called for $RELEASE on $BOARD" >&2
    exit 1
fi

OVERLAY=/tmp/overlay
# shellcheck source=SCRIPTDIR/../versions.env
source "$OVERLAY/versions.env"
export DEBIAN_FRONTEND=noninteractive

# Downloads land here and are deleted on exit, so none of them ships in the image. Readable by
# apt's _apt user, which fetches the local libmali deb.
WORK="$(mktemp -d)"
chmod 755 "$WORK"
trap 'rm -rf "$WORK"' EXIT

# fetch_verified URL SHA256 DEST: download, then fail unless the file matches its pin.
fetch_verified() {
    curl -fsSL --retry 3 -o "$3" "$1"
    echo "$2  $3" | sha256sum -c -
}

apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl locales fish sudo clinfo vulkan-tools ocl-icd-libopencl1 libgomp1

# GPU: Mali G610 userspace (OpenCL 3.0, Vulkan 1.3, GLES 3.2), DDK g29p1 to match the vendor
# kernel's kbase driver. It installs the OpenCL and Vulkan ICD files clinfo and vulkaninfo read.
fetch_verified "$LIBMALI_URL" "$LIBMALI_SHA256" "$WORK/libmali.deb"
apt-get install -y --no-install-recommends "$WORK/libmali.deb"

# NPU: the RKNN and RKLLM runtimes, which Rockchip ships as bare .so files.
fetch_verified "$RKNNRT_URL" "$RKNNRT_SHA256" "$WORK/librknnrt.so"
fetch_verified "$RKLLMRT_URL" "$RKLLMRT_SHA256" "$WORK/librkllmrt.so"
install -m 0644 "$WORK/librknnrt.so" "$WORK/librkllmrt.so" /usr/lib/
ldconfig

# RKNN Toolkit Lite2's newest wheel is cp312 and trixie's python3 is 3.13, so uv installs CPython
# 3.12 into /opt/python and a venv on it at /opt/rknn-lite2. Dependencies come from the
# hash-locked rknn-requirements.txt, wheels only; the toolkit wheel is checked against its pin.
# Bytecode is compiled now because the venv is root-owned and its users can't write __pycache__.
fetch_verified "$UV_URL" "$UV_SHA256" "$WORK/uv.tar.gz"
tar -xzf "$WORK/uv.tar.gz" -C "$WORK"
install -m 0755 "$WORK/uv-aarch64-unknown-linux-gnu/uv" /usr/local/bin/uv
export UV_PYTHON_INSTALL_DIR=/opt/python UV_MANAGED_PYTHON=1 UV_NO_CACHE=1 UV_COMPILE_BYTECODE=1
uv python install --no-bin 3.12
uv venv --python 3.12 /opt/rknn-lite2
uv pip install --python /opt/rknn-lite2/bin/python --require-hashes --only-binary :all: \
    -r "$OVERLAY/rknn-requirements.txt"
WHEEL="$WORK/${RKNN_LITE_WHEEL_URL##*/}"
fetch_verified "$RKNN_LITE_WHEEL_URL" "$RKNN_LITE_WHEEL_SHA256" "$WHEEL"
uv pip install --python /opt/rknn-lite2/bin/python --no-deps "$WHEEL"

# Video: jellyfin-ffmpeg8, which bundles its own MPP and RGA, from Jellyfin's repo. The pin file
# lets nothing else come from there.
install -d -m 0755 /etc/apt/keyrings
fetch_verified "$JELLYFIN_KEY_URL" "$JELLYFIN_KEY_SHA256" /etc/apt/keyrings/jellyfin.asc
chmod 0644 /etc/apt/keyrings/jellyfin.asc
cat > /etc/apt/sources.list.d/jellyfin.sources <<'EOF'
Types: deb
URIs: https://repo.jellyfin.org/debian
Suites: trixie
Components: main
Architectures: arm64
Signed-By: /etc/apt/keyrings/jellyfin.asc
EOF
install -m 0644 "$OVERLAY/jellyfin.pref" /etc/apt/preferences.d/jellyfin
apt-get update
apt-get install -y --no-install-recommends "jellyfin-ffmpeg8=$JELLYFIN_FFMPEG_VERSION"

# Device permissions: the GPU (Armbian's own rule from packages/bsp/rk3399, which its RK3588
# family no longer installs: rockchip-rk3588.conf makes family_tweaks_bsp a no-op), and MPP, RGA
# and the DMA heaps (Jellyfin's rules). Then the SSH policy.
install -m 0644 "$OVERLAY/50-mali.rules" /etc/udev/rules.d/
install -m 0644 "$OVERLAY/99-rk-device-permissions.rules" /etc/udev/rules.d/
install -m 0644 "$OVERLAY/10-rk1.conf" /etc/ssh/sshd_config.d/

# Access, as on the NixOS hosts (nix/modules/base.nix): user services with uid and gid 1000,
# fish, passwordless sudo that keeps SSH_AUTH_SOCK, keys from nix/modules/ssh-keys.nix.
# build-image.sh writes the two generated/ files inside the build machine only. The password
# reaches chpasswd on stdin, never in argv, and is hashed with Debian's default method.
groupadd -g 1000 services
useradd -m -u 1000 -g services -G sudo,video,render -s /usr/bin/fish services
{ printf 'services:'; tr -d '\n' < "$OVERLAY/generated/services-password"; printf '\n'; } | chpasswd
install -d -m 0700 -o services -g services /home/services/.ssh
install -m 0600 -o services -g services "$OVERLAY/generated/authorized_keys" /home/services/.ssh/
cat > "$WORK/90-services" <<'EOF'
services ALL=(ALL) NOPASSWD:ALL
Defaults env_keep += "SSH_AUTH_SOCK"
EOF
visudo -cf "$WORK/90-services"
install -m 0440 "$WORK/90-services" /etc/sudoers.d/90-services

# No root password and no first-login wizard. Armbian sets root's password to 1234 and runs the
# wizard on the first root login, where it asks for a new root password and a second user.
usermod -p '!' root
rm -f /root/.not_logged_in_yet

# Time zone and locale, which the wizard would otherwise set. The zone file is checked first
# because ln -sf to a missing target succeeds and leaves the node on UTC.
test -f /usr/share/zoneinfo/America/Chicago
ln -sf /usr/share/zoneinfo/America/Chicago /etc/localtime
echo America/Chicago > /etc/timezone
sed -i 's/^# *\(en_US.UTF-8 UTF-8\)$/\1/' /etc/locale.gen
grep -q '^en_US.UTF-8 UTF-8$' /etc/locale.gen
locale-gen
update-locale LANG=en_US.UTF-8

apt-get clean
