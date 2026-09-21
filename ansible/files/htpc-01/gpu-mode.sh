#!/usr/bin/env bash
#
# gpu-mode — give exactly one consumer the GPU.
#
# The RX 9070 XT has 16 GB and five consumers that each want most of it: ComfyUI,
# llama-server (via llama-swap), the Tdarr transcode node, the gpu-encoder-sweep agent, and
# gaming (Steam/gamescope). They cannot share. Measured: the same 8k-token prompt took >900 s
# with ComfyUI resident vs 45 s without, with EVICTED_TIME going 772,000 ms -> 52 ms. It is not
# a throughput problem — the amdgpu driver thrashes allocations between VRAM and GTT once free
# VRAM approaches zero.
#
# This stops the llama-swap CONTAINER rather than just unloading the model, because
# Onyx can trigger a load at any time and would otherwise pull ~10 GiB back onto the
# card mid-game.
#
# Tdarr and the sweep agent are the two consumers whose work is LOST rather than deferred
# when they are stopped. An in-flight Tdarr transcode dies and its partial output in /temp is
# wasted; the server re-queues the file, so nothing is corrupted, but a mode switch mid-batch
# throws away however far that one file had got.
#
# The sweep agent is worse in one respect and better in another: the run it was executing fails
# at the hub's 90 s heartbeat TTL and the queue entry waits for the agent to come back, so
# nothing needs re-planning — but a sweep measures TIMINGS, so a cell interrupted by a mode
# switch would be a wrong number rather than a missing one if it were ever counted. It is not:
# the hub fails the whole run. Prefer wrapping a campaign in `sleep-inhibit run`, and switching
# modes between campaigns rather than inside one.
#
# Managed by Ansible: ansible/files/htpc-01/gpu-mode.sh
# Background: research/local-llm/docs/llm-tuning.md

set -euo pipefail

# `card` only reads world-readable sysfs, so it does not need root — which is what makes
# the card selector testable against a fixture tree (see GPU_MODE_SYSFS_DRM below).
# `status` still re-execs: its model line runs `podman exec` against ROOTFUL podman.
[ "${1:-}" = card ] || [ "$(id -u)" -eq 0 ] || exec sudo -- "$0" "$@"

COMFY_UNIT=comfyui.service
LLM_UNIT=llama-swap.service
TDARR_UNIT=tdarr-node.service
SWEEP_UNIT=gpu-encoder-sweep-node.service

# Free-VRAM floor to reach before starting the next consumer. The desktop and
# compositor hold ~1.3 GB at idle, so this is "the previous consumer has let go",
# not "the card is empty".
SETTLE_CEILING_MB=2500
SETTLE_TIMEOUT=60

# The card is PINNED by PCI ID, not discovered as "the first amdgpu device that has VRAM
# counters". htpc-01 has TWO amdgpu devices — this dGPU and the Cezanne iGPU — and both
# satisfy that test, so lexical glob order decided it and the iGPU (card0) won. Measured
# 2026-09-10: `status` reported the iGPU's 2048 MB UMA carve-out as "the GPU", and because
# 2048 < SETTLE_CEILING_MB and used <= total always, wait_for_release's early return was
# unconditional. The settle wait had never once waited.
#
# Ranking by largest mem_info_vram_total was rejected: it is the same failure class — a
# heuristic that yields a plausible number when it is wrong and stays wrong silently. A pin
# either matches or the script refuses to start. A replaced card therefore needs a
# deliberate edit here, which is correct — SETTLE_CEILING_MB and the whole "16 GB, exactly
# one consumer" premise are properties of this specific card, not of "the GPU".
GPU_PCI_ID=1002:7550   # ASRock Steel Legend Radeon RX 9070 XT (gfx1201)

# Overridable ONLY so the selector has a positive and a negative control off-hardware:
# point it at a fixture tree and run `gpu-mode card`. Nothing in production sets it.
SYSFS_DRM="${GPU_MODE_SYSFS_DRM:-/sys/class/drm}"

# card[0-9] rather than card*, which is cosmetic and not the fix: the eight connector
# directories (card1-DP-1, card0-HDMI-A-2, card1-Writeback-1, ...) are already excluded
# on their own merits. Their `device` symlink resolves to the DRM *minor*, not the PCI
# device, so their uevent holds only MAJOR/MINOR/DEVNAME/DEVTYPE=drm_minor — no DRIVER=
# line and no mem_info_*. Narrowing the glob just stops the loop stat-ing directories that
# can never match.
card_path() {
  local d found="" pci mb
  for d in "$SYSFS_DRM"/card[0-9]/device; do
    [ -r "$d/uevent" ] || continue
    grep -qx 'DRIVER=amdgpu' "$d/uevent" 2>/dev/null || continue
    [ -r "$d/mem_info_vram_used" ] || continue
    [ -r "$d/mem_info_vram_total" ] || continue
    if grep -qx "PCI_ID=$GPU_PCI_ID" "$d/uevent" 2>/dev/null; then
      printf '%s' "$d"; return 0
    fi
    pci="$(sed -n 's/^PCI_ID=//p' "$d/uevent" | head -1)"
    mb=$(( $(cat "$d/mem_info_vram_total") / 1048576 ))
    found="${found}    $(basename "$(dirname "$d")")  ${pci:-unknown}  ${mb} MB"$'\n'
  done
  {
    echo "gpu-mode: no amdgpu card with PCI_ID=$GPU_PCI_ID under $SYSFS_DRM"
    if [ -n "$found" ]; then
      echo "  amdgpu cards that are present:"
      printf '%s' "$found"
      echo "  If the GPU was replaced, set GPU_PCI_ID in this script to the right one — and"
      echo "  re-check SETTLE_CEILING_MB, which assumes a 16 GB card idling at ~1.3 GB."
    else
      echo "  no amdgpu cards found at all"
    fi
  } >&2
  return 1
}

# Deliberately at top level, so every subcommand fails on a card that is not there rather
# than each one rediscovering it.
CARD="$(card_path)" || exit 1
CARD_NAME="$(basename "$(dirname "$CARD")")"
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
  # The device is named on this line on purpose. The wrong-card bug went unnoticed because
  # the figure looked like a number rather than a number *about a device*.
  echo "GPU:  ${used} MB used / ${total} MB total  ($((total - used)) MB free)  [${CARD_NAME} ${GPU_PCI_ID}]"
  # "boot" is the [Install] drop-in state, which is the only thing that decides
  # whether the container comes back after a reboot.
  printf 'ComfyUI:    %-10s boot=%s\n' "$(systemctl is-active $COMFY_UNIT)" \
    "$(boot_enabled $COMFY_UNIT && echo yes || echo no)"
  printf 'llama-swap: %-10s boot=%s\n' "$(systemctl is-active $LLM_UNIT)" \
    "$(boot_enabled $LLM_UNIT && echo yes || echo no)"
  printf 'Tdarr:      %-10s boot=%s\n' "$(systemctl is-active $TDARR_UNIT)" \
    "$(boot_enabled $TDARR_UNIT && echo yes || echo no)"
  printf 'Sweep:      %-10s boot=%s\n' "$(systemctl is-active $SWEEP_UNIT)" \
    "$(boot_enabled $SWEEP_UNIT && echo yes || echo no)"
  if is_active "$LLM_UNIT"; then
    local running
    running="$(podman exec llama-swap curl -sf --max-time 5 localhost:8080/running 2>/dev/null || true)"
    printf 'models:     %s\n' "${running:-<llama-swap not answering>}"
  fi
  # Name the current mode only when it is unambiguous. Counted rather than nested, so
  # adding a fifth consumer does not need a new branch. if/then rather than `cmd && n=$((n+1))`
  # because the latter's exit status under `set -e` is not portable.
  local active=0
  if is_active "$COMFY_UNIT"; then active=$((active + 1)); fi
  if is_active "$LLM_UNIT";   then active=$((active + 1)); fi
  if is_active "$TDARR_UNIT"; then active=$((active + 1)); fi
  if is_active "$SWEEP_UNIT"; then active=$((active + 1)); fi
  if [ "$active" -gt 1 ]; then
    echo "mode:       CONTENDED — $active consumers running, expect VRAM thrashing"
  elif is_active "$COMFY_UNIT"; then echo "mode:       comfy"
  elif is_active "$LLM_UNIT"; then   echo "mode:       llm"
  elif is_active "$TDARR_UNIT"; then echo "mode:       tdarr"
  elif is_active "$SWEEP_UNIT"; then echo "mode:       sweep"
  else echo "mode:       game (no container is running)"
  fi
}

case "${1:-}" in
  game)
    echo "gpu-mode: game — releasing the GPU entirely"
    stop_unit "$SWEEP_UNIT"
    stop_unit "$TDARR_UNIT"
    stop_unit "$LLM_UNIT"
    stop_unit "$COMFY_UNIT"
    wait_for_release
    ;;
  comfy)
    echo "gpu-mode: comfy"
    stop_unit "$SWEEP_UNIT"
    stop_unit "$TDARR_UNIT"
    stop_unit "$LLM_UNIT"
    wait_for_release
    start_unit "$COMFY_UNIT"
    ;;
  llm)
    echo "gpu-mode: llm"
    stop_unit "$SWEEP_UNIT"
    stop_unit "$TDARR_UNIT"
    stop_unit "$COMFY_UNIT"
    wait_for_release
    start_unit "$LLM_UNIT"
    # llama-swap loads a model only on the first request, so the card stays free
    # until something actually asks for one.
    ;;
  tdarr)
    echo "gpu-mode: tdarr"
    stop_unit "$SWEEP_UNIT"
    stop_unit "$COMFY_UNIT"
    stop_unit "$LLM_UNIT"
    wait_for_release
    start_unit "$TDARR_UNIT"
    # Unlike ComfyUI and llama-swap this starts working immediately, as soon as the server has
    # a queued file to hand it.
    ;;
  sweep)
    echo "gpu-mode: sweep"
    stop_unit "$TDARR_UNIT"
    stop_unit "$COMFY_UNIT"
    stop_unit "$LLM_UNIT"
    wait_for_release
    start_unit "$SWEEP_UNIT"
    # Starts claiming as soon as the hub has a queued entry for this host — and a claimed cell
    # is a timed measurement, so leave the card to it until the campaign is done.
    ;;
  card)
    # Selection only, no unit state: this is the one subcommand that needs neither root nor
    # systemd, which is what lets the selector be tested against a fixture tree.
    printf '%s  %s  %s MB total\n' "$CARD_NAME" "$GPU_PCI_ID" "$(vram_total_mb)"
    exit 0
    ;;
  status|"")
    status
    exit 0
    ;;
  *)
    cat >&2 <<'USAGE'
Usage: gpu-mode {game|comfy|llm|tdarr|sweep|status|card}

  game    stop all four containers, leaving the card to Steam/gamescope
  comfy   stop llama-swap, Tdarr and the sweep agent, start ComfyUI
  llm     stop ComfyUI, Tdarr and the sweep agent, start llama-swap
  tdarr   stop ComfyUI, llama-swap and the sweep agent, start the Tdarr transcode node
  sweep   stop the other three, start the gpu-encoder-sweep encode agent
  status  show VRAM, unit states and any loaded model
  card    print which GPU this script is driving, and nothing else

This host has two amdgpu devices — the RX 9070 XT and the Cezanne iGPU. The card is pinned
by PCI ID rather than discovered, so 'card' should always name the 16 GB one. If it names
the iGPU, or the script refuses to start, the pin no longer matches the hardware.

While not in 'llm' mode, Onyx cannot generate — retrieval, indexing, web search and
the UI are unaffected, but chat returns a connection error. That is the intended
trade, not a fault.

Switching away from 'tdarr' kills any in-flight transcode. The server re-queues the
file, so nothing is lost permanently, but the partial output in /temp is wasted work.
Prefer switching between batches.

Switching away from 'sweep' fails whatever run the agent was executing — the hub notices at
the 90 s heartbeat TTL and the queue entry waits for the agent to return, so nothing needs
re-planning. But a sweep measures timings, so switch between campaigns, not inside one.

The selected mode survives reboots: it is stored as a Quadlet [Install] drop-in per
container, which is what decides whether that container starts at boot.

None of the four GPU containers has an [Install] of its own, so on a freshly
provisioned host none starts at boot until gpu-mode has been run once.
USAGE
    exit 1
    ;;
esac

echo
status
