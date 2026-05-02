#!/usr/bin/env bash
# Pre-wipe backup for a Proxmox VE node, run FROM another host.
#
# Connects to the target as a non-root user with passwordless sudo and
# pulls config + a state snapshot off it via rsync (with --rsync-path=
# "sudo rsync") and ssh sudo. Preserves the source file structure under
# the output directory (so /etc/pve on the remote becomes <out>/etc/pve
# locally).
#
# THE OUTPUT TARBALL CONTAINS SENSITIVE DATA — cluster auth keys, root's
# SSH private keys, ACME tokens (via /etc/pve). Treat it like a
# credentials dump: store on a trusted host, don't share, delete after
# the reinstall is verified.
#
# Note: file ownership (uid/gid) is NOT preserved on the local copy
# because the local rsync runs as a non-root user and can't chown.
# Modes, symlinks, ACLs, xattrs are preserved.
#
# Usage:
#   ./pve-pre-wipe-backup.sh <remote-host> [output-dir]
#
# Example:
#   ./pve-pre-wipe-backup.sh vm-host-02
#   ./pve-pre-wipe-backup.sh vm-host-02 ./vm-host-02-backup
#
# Defaults:
#   SSH_USER  — unset; SSH connects with whatever user your ssh config
#               resolves for the host. Override via env var if needed.
#   output-dir — ./<remote-host>-backup-YYYYMMDD-HHMMSS
#
# Requirements on the remote:
#   - SSH access (root SSH is typically disabled by geerlingguy.security;
#     use a regular user with passwordless sudo)
#   - passwordless sudo for the connecting user (configured by
#     geerlingguy.security via security_sudoers_passwordless)
#   - rsync installed (Proxmox installs it by default)

set -euo pipefail

REMOTE_HOST="${1:?usage: $0 <remote-host> [output-dir]}"
OUT_DIR="${2:-./${REMOTE_HOST}-backup-$(date +%Y%m%d-%H%M%S)}"
# If SSH_USER is set, prepend "user@" — otherwise let ssh config resolve.
SSH_TARGET="${SSH_USER:+${SSH_USER}@}${REMOTE_HOST}"

umask 077
mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

echo "==> Backing up ${SSH_TARGET} to $OUT_DIR"

# Sanity-check passwordless sudo before we go further. Fails fast with a
# clear message if sudo would prompt or be denied.
if ! ssh -o BatchMode=yes "${SSH_TARGET}" sudo -n true 2>/dev/null; then
    echo "Error: ${SSH_TARGET} cannot run sudo without a password." >&2
    echo "       Configure passwordless sudo for this user before retrying." >&2
    exit 1
fi

# --- Configs (rsync with sudo on the remote, preserve structure) ---

REMOTE_PATHS=(
    /etc/ssh
    /root/.ssh
    /etc/network
    /etc/hosts
    /etc/hostname
    /etc/resolv.conf
    /etc/apt/sources.list.d
    /etc/apt/sources.list
    /etc/pve
)

RSYNC_OPTS=(
    --archive          # -rlptgoD
    --relative         # preserve full source path under destination
    --hard-links
    --acls
    --xattrs
    --ignore-missing-args  # don't fail if a path doesn't exist on the remote
    --rsync-path="sudo rsync"
    --rsh=ssh
)

for path in "${REMOTE_PATHS[@]}"; do
    echo "==> rsync ${path}"
    rsync "${RSYNC_OPTS[@]}" \
        "${SSH_TARGET}:${path}" \
        "$OUT_DIR/" \
        || echo "    Warning: rsync of ${path} failed (continuing)"
done

# --- State snapshot (read-only commands, run via ssh+sudo) ---

echo "==> Capturing state snapshot"
ssh -o BatchMode=yes "${SSH_TARGET}" "sudo bash -s" > "$OUT_DIR/state-snapshot.txt" 2>&1 <<'EOSH' || true
set +e
echo "==== uname -a ===="
uname -a
echo
echo "==== pveversion -v ===="
pveversion -v
echo
echo "==== ip a ===="
ip a
echo
echo "==== ip r ===="
ip r
echo
echo "==== lsblk -f ===="
lsblk -f
echo
echo "==== blkid ===="
blkid
echo
echo "==== smartctl -a /dev/sda ===="
smartctl -a /dev/sda
echo
echo "==== smartctl -a /dev/nvme0n1 ===="
smartctl -a /dev/nvme0n1
echo
echo "==== pvecm status ===="
pvecm status
echo
echo "==== pvecm nodes ===="
pvecm nodes
echo
echo "==== pvesm status ===="
pvesm status
echo
echo "==== ceph -s ===="
ceph -s
echo
echo "==== ceph mon dump ===="
ceph mon dump
echo
echo "==== ceph osd tree ===="
ceph osd tree
echo
echo "==== ceph fs status ===="
ceph fs status
echo
echo "==== ceph-volume lvm list ===="
ceph-volume lvm list
EOSH

# --- Package selections ---

echo "==> Capturing package selections"
ssh -o BatchMode=yes "${SSH_TARGET}" "sudo dpkg --get-selections" \
    > "$OUT_DIR/dpkg-selections.txt" 2>&1 || true
ssh -o BatchMode=yes "${SSH_TARGET}" "sudo apt-mark showmanual" \
    > "$OUT_DIR/apt-mark-manual.txt" 2>&1 || true

# --- Tarball (optional convenience; the unpacked tree is right there too) ---

TARBALL="${OUT_DIR}.tar.gz"
tar czf "$TARBALL" -C "$(dirname "$OUT_DIR")" "$(basename "$OUT_DIR")"
chmod 600 "$TARBALL"

echo
echo "==> Backup directory: $OUT_DIR"
echo "==> Tarball:          $TARBALL"
echo "    Size: $(du -h "$TARBALL" | cut -f1)"
echo
echo "WARNING: backup contains private SSH keys and cluster credentials."
echo "         Store on a trusted host; delete after reinstall is verified."
