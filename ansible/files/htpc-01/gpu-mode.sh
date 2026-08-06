#!/usr/bin/env bash
#
# gpu-mode — give exactly one consumer the GPU.
#
# The RX 9070 XT has 16 GB and three consumers that each want most of it: ComfyUI,
# llama-server (via llama-swap), and gaming (Steam/gamescope). They cannot share.
# Measured: the same 8k-token prompt took >900 s with ComfyUI resident vs 45 s without,
# with EVICTED_TIME going 772,000 ms -> 52 ms. It is not a throughput problem — the
# amdgpu driver thrashes allocations between VRAM and GTT once free VRAM approaches zero.
#
# This stops the llama-swap CONTAINER rather than just unloading the model, because
# Onyx can trigger a load at any time and would otherwise pull ~10 GiB back onto the
# card mid-game.
#
# Managed by Ansible: ansible/files/htpc-01/gpu-mode.sh
# Background: docs/llama-swap-htpc-01-tuning.md

set -euo pipefail

[ "$(id -u)" -eq 0 ] || exec sudo -- "$0" "$@"

COMFY_UNIT=comfyui.service
LLM_UNIT=llama-swap.service

# Free-VRAM floor to reach before starting the next consumer. The desktop and
# compositor hold ~1.3 GB at idle, so this is "the previous consumer has let go",
# not "the card is empty".
SETTLE_CEILING_MB=2500
SETTLE_TIMEOUT=60

card_path() {
  local d
  for d in /sys/class/drm/card*/device; do
    [ -r "$d/uevent" ] || continue
    if grep -q '^DRIVER=amdgpu$' "$d/uevent" 2>/dev/null && [ -r "$d/mem_info_vram_used" ]; then
      printf '%s' "$d"; return 0
    fi
  done
  echo "gpu-mode: no amdgpu card with mem_info_vram_used found" >&2
  return 1
}

CARD="$(card_path)"
vram_used_mb() { echo $(( $(cat "$CARD/mem_info_vram_used") / 1048576 )); }
vram_total_mb() { echo $(( $(cat "$CARD/mem_info_vram_total") / 1048576 )); }

QUADLET_DIR=/etc/containers/systemd
DROPIN=50-gpu-mode.conf

is_active() { systemctl is-active --quiet "$1"; }
# A unit is "installed" (will start at boot) iff it has a non-empty WantedBy.
boot_enabled() { [ -n "$(systemctl show -p WantedBy --value "$1" 2>/dev/null)" ]; }

# Boot persistence uses a Quadlet [Install] drop-in — the mechanism the manual
# documents for exactly this.
#
# podman-systemd.unit(5), "Enabling unit files": Quadlet services "are considered
# transient by systemd ... it is not possible to `systemctl enable` them"; instead
# "the generator manually applies the [Install] section ... during generation".
# `systemctl disable` is therefore a no-op here (verified: prints nothing,
# UnitFileState stays `generated`), and `systemctl mask` would work but is a generic
# systemd override that leaves the unit un-startable and fails Ansible's
# `state: started`.
#
# The documented idiom: "The Install section can be part of the main file, or it can
# be in a separate drop-in file ... The latter allows you to install an non-enabled
# unit and then later enabling it by installing the drop-in." So comfyui.container and
# llama-swap.container carry NO [Install]; installing this drop-in is what makes a
# container start at boot, and removing it is what stops that.
#
# Verified with the documented dry-run generator rather than by mutating /etc:
#   QUADLET_UNIT_DIRS=<dir> /usr/lib/systemd/system-generators/podman-system-generator --dryrun
# no drop-in -> no WantedBy; drop-in present -> WantedBy=multi-user.target.
#
# Ansible never touches these files: the role templates <name>.container, not
# <name>.container.d/. The role separately declines to start a unit that exists, is
# inactive, and has no WantedBy, so a playbook run does not undo the selected mode.
set_boot() {
  local unit="$1" want="$2" base dir file
  base="${unit%.service}"
  dir="$QUADLET_DIR/${base}.container.d"
  file="$dir/$DROPIN"
  if [ "$want" = "off" ]; then
    [ -f "$file" ] || return 0
    rm -f "$file"
    rmdir "$dir" 2>/dev/null || true
    echo "  boot-start disabled (removed $file)"
  else
    [ -f "$file" ] && return 0
    mkdir -p "$dir"
    printf '# Written by gpu-mode: installs %s so it starts at boot.\n# Removing this file uninstalls it. See podman-systemd.unit(5), "Enabling unit files".\n[Install]\nWantedBy=multi-user.target\n' \
      "$unit" > "$file"
    echo "  boot-start enabled ($file)"
  fi
  systemctl daemon-reload
}

stop_unit() {
  local unit="$1"
  if is_active "$unit"; then
    echo "  stopping $unit"
    systemctl stop "$unit"
  else
    echo "  $unit already stopped"
  fi
  set_boot "$unit" off
}

start_unit() {
  local unit="$1"
  set_boot "$unit" on
  if is_active "$unit"; then
    echo "  $unit already running"
  else
    echo "  starting $unit"
    systemctl start "$unit"
  fi
}

# Starting a new consumer before the previous one's VRAM is actually released
# reproduces the exact contention this script exists to prevent.
wait_for_release() {
  local waited=0 used
  used="$(vram_used_mb)"
  [ "$used" -le "$SETTLE_CEILING_MB" ] && return 0
  echo "  waiting for VRAM to be released (${used} MB in use)..."
  while [ "$waited" -lt "$SETTLE_TIMEOUT" ]; do
    sleep 2; waited=$((waited + 2))
    used="$(vram_used_mb)"
    if [ "$used" -le "$SETTLE_CEILING_MB" ]; then
      echo "  released after ${waited}s (${used} MB in use)"
      return 0
    fi
  done
  echo "  WARNING: ${used} MB still in use after ${SETTLE_TIMEOUT}s (expected <= ${SETTLE_CEILING_MB} MB)." >&2
  echo "           Something outside gpu-mode holds VRAM — check 'gpu-mode status'." >&2
}

status() {
  local used total
  used="$(vram_used_mb)"; total="$(vram_total_mb)"
  echo "GPU:  ${used} MB used / ${total} MB total  ($((total - used)) MB free)"
  # "boot" is the [Install] drop-in state, which is the only thing that decides
  # whether the container comes back after a reboot.
  printf 'ComfyUI:    %-10s boot=%s\n' "$(systemctl is-active $COMFY_UNIT)" \
    "$(boot_enabled $COMFY_UNIT && echo yes || echo no)"
  printf 'llama-swap: %-10s boot=%s\n' "$(systemctl is-active $LLM_UNIT)" \
    "$(boot_enabled $LLM_UNIT && echo yes || echo no)"
  if is_active "$LLM_UNIT"; then
    local running
    running="$(podman exec llama-swap curl -sf --max-time 5 localhost:8080/running 2>/dev/null || true)"
    printf 'models:     %s\n' "${running:-<llama-swap not answering>}"
  fi
  # Name the current mode only when it is unambiguous.
  if is_active "$COMFY_UNIT" && is_active "$LLM_UNIT"; then
    echo "mode:       CONTENDED — both consumers running, expect VRAM thrashing"
  elif is_active "$COMFY_UNIT"; then echo "mode:       comfy"
  elif is_active "$LLM_UNIT"; then  echo "mode:       llm"
  else echo "mode:       game (neither container is running)"
  fi
}

case "${1:-}" in
  game)
    echo "gpu-mode: game — releasing the GPU entirely"
    stop_unit "$LLM_UNIT"
    stop_unit "$COMFY_UNIT"
    wait_for_release
    ;;
  comfy)
    echo "gpu-mode: comfy"
    stop_unit "$LLM_UNIT"
    wait_for_release
    start_unit "$COMFY_UNIT"
    ;;
  llm)
    echo "gpu-mode: llm"
    stop_unit "$COMFY_UNIT"
    wait_for_release
    start_unit "$LLM_UNIT"
    # llama-swap loads a model only on the first request, so the card stays free
    # until something actually asks for one.
    ;;
  status|"")
    status
    exit 0
    ;;
  *)
    cat >&2 <<'USAGE'
Usage: gpu-mode {game|comfy|llm|status}

  game    stop both ComfyUI and llama-swap, leaving the card to Steam/gamescope
  comfy   stop llama-swap, start ComfyUI
  llm     stop ComfyUI, start llama-swap
  status  show VRAM, unit states and any loaded model

While not in 'llm' mode, Onyx cannot generate — retrieval, indexing, web search and
the UI are unaffected, but chat returns a connection error. That is the intended
trade, not a fault.

The selected mode survives reboots: it is stored as a Quadlet [Install] drop-in per
container, which is what decides whether that container starts at boot.

Neither GPU container has an [Install] of its own, so on a freshly provisioned host
neither starts at boot until gpu-mode has been run once.
USAGE
    exit 1
    ;;
esac

echo
status
