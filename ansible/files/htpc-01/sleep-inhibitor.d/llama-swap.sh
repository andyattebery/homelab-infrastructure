#!/usr/bin/env bash
set -euo pipefail

# Busy while llama-swap has a model resident. Suspending a process that holds ~10 GiB
# of VRAM across a ROCm context does not reliably survive resume, so block sleep until
# llama-swap's own ttl unloads the model.
#
# Nothing is published to the host (Caddy reaches the container over caddy.network),
# so unlike comfyui.sh this cannot curl 127.0.0.1 and goes through the container.
#
# Exit 0 = busy (hold the inhibitor), exit 1 = idle.

# Unreachable or not running means nothing is on the GPU: idle, same as comfyui.sh.
response=$(podman exec llama-swap curl -sf --max-time 5 http://localhost:8080/running) || exit 1

printf '%s' "$response" | python3 -c "
import json, sys

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    # Reachable but unparseable: assume something is loaded rather than risk
    # suspending mid-inference.
    sys.exit(0)

# The /running schema is not documented, so accept the plausible shapes rather than
# guessing one: a bare list, or an object wrapping the list under a known key.
if isinstance(data, list):
    running = data
elif isinstance(data, dict):
    for key in ('running', 'models', 'processes'):
        if isinstance(data.get(key), list):
            running = data[key]
            break
    else:
        # An object we do not recognise. Treat non-empty as busy.
        sys.exit(0 if data else 1)
else:
    sys.exit(0)

sys.exit(0 if len(running) > 0 else 1)
"
