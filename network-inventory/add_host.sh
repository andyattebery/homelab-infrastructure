#!/usr/bin/env bash
set -euo pipefail

# Add or update a host's MAC address in 1Password and the inventory file.
#
# 1Password:
#   - If item exists: adds hardware/mac address field
#   - If item doesn't exist: creates new Server item
#
# Inventory (network_hosts_inventory.yaml.tpl):
#   - If host exists without mac: adds mac line after ip line
#   - If host exists with mac: updates the mac line
#   - If host doesn't exist: adds new entry with ip and mac
#
# Usage: ./add_host.sh <hostname> <ip> <mac> [--dry-run]
#
# Requires: OP_SERVICE_ACCOUNT_TOKEN in environment

VAULT="Home Lab"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INVENTORY="$SCRIPT_DIR/network_hosts_inventory.yaml.tpl"

if [[ $# -lt 3 ]]; then
    echo "Usage: $0 <hostname> <ip> <mac> [--dry-run]" >&2
    exit 1
fi

HOSTNAME="$1"
IP="$2"
MAC="$3"
DRY_RUN=""

if [[ "${4:-}" == "--dry-run" ]]; then
    DRY_RUN="--dry-run"
fi

OP_REF="{{ op://$VAULT/$HOSTNAME/hardware/mac address }}"

# --- 1Password ---
echo "=== 1Password ==="
if op item get "$HOSTNAME" --vault "$VAULT" < /dev/null > /dev/null 2>&1; then
    echo "Item '$HOSTNAME' exists, adding hardware/mac address"
    op item edit "$HOSTNAME" --vault "$VAULT" $DRY_RUN -- "hardware.mac address=$MAC" < /dev/null
else
    echo "Item '$HOSTNAME' does not exist, creating new Server item"
    op item create --category Server --title "$HOSTNAME" --vault "$VAULT" $DRY_RUN -- "hardware.mac address=$MAC" < /dev/null
fi

# --- Inventory file ---
echo ""
echo "=== Inventory ==="

if [[ ! -f "$INVENTORY" ]]; then
    echo "Error: inventory file not found at $INVENTORY" >&2
    exit 1
fi

if grep -q "^  ${HOSTNAME}:" "$INVENTORY"; then
    # host exists — check if it has a mac line (look at all indented lines under it)
    has_mac=false
    while IFS= read -r line; do
        if [[ "$line" =~ ^[[:space:]]+mac: ]]; then
            has_mac=true
            break
        fi
    done < <(sed -n "/^  ${HOSTNAME}:/,/^  [^ ]/p" "$INVENTORY" | tail -n +2)

    if $has_mac; then
        if [[ -n "$DRY_RUN" ]]; then
            echo "Would update mac for existing host '$HOSTNAME'"
        else
            sed -i '' "/^  ${HOSTNAME}:/,/^  [^ ]/{s|^    mac:.*|    mac: $OP_REF|;}" "$INVENTORY"
            echo "Updated mac for '$HOSTNAME'"
        fi
    else
        if [[ -n "$DRY_RUN" ]]; then
            echo "Would add mac to existing host '$HOSTNAME'"
        else
            sed -i '' "/^  ${HOSTNAME}:/{n;s|$|\n    mac: $OP_REF|;}" "$INVENTORY"
            echo "Added mac to '$HOSTNAME'"
        fi
    fi

    # update ip if different
    CURRENT_IP=$(sed -n "/^  ${HOSTNAME}:/,/^  [^ ]/p" "$INVENTORY" | grep "ip:" | sed 's/.*ip: //')
    if [[ "$CURRENT_IP" != "$IP" ]]; then
        if [[ -n "$DRY_RUN" ]]; then
            echo "Would update ip for '$HOSTNAME': $CURRENT_IP → $IP"
        else
            sed -i '' "/^  ${HOSTNAME}:/,/^  [^ ]/{s|^    ip:.*|    ip: $IP|;}" "$INVENTORY"
            echo "Updated ip for '$HOSTNAME': $CURRENT_IP → $IP"
        fi
    fi
else
    # host doesn't exist — add before other_hosts section
    if [[ -n "$DRY_RUN" ]]; then
        echo "Would add new host '$HOSTNAME' (ip: $IP)"
    else
        sed -i '' "/^# Hosts on a different domain/i\\
\\
  $HOSTNAME:\\
    ip: $IP\\
    mac: $OP_REF
" "$INVENTORY"
        echo "Added new host '$HOSTNAME' (ip: $IP)"
    fi
fi
