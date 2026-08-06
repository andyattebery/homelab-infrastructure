#!/usr/bin/env bash
set -euo pipefail

# Cold boot: no suspend cycle in dmesg yet, always turn on TV
if ! dmesg | grep -q "PM: suspend exit"; then
    exec /usr/bin/cec-control onboot
fi

# Resume: check if the MOST RECENT suspend cycle had a wakeup IRQ trigger.
# With pm_debug_messages enabled, the kernel logs "PM: Triggering wakeup from IRQ"
# only for USB/input wakes, not for WoL wakes.
# Awk resets on each "suspend entry" so only the latest cycle is evaluated.
if dmesg | awk '/PM: suspend entry/{f=0} /PM: Triggering wakeup from IRQ/{f=1} END{exit !f}'; then
    exec /usr/bin/cec-control onboot
fi

echo "WoL wake detected, skipping CEC"
