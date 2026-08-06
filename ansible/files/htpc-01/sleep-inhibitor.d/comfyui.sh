#!/usr/bin/env bash
set -euo pipefail
response=$(curl -sf --max-time 5 "http://127.0.0.1:8188/queue") || exit 1
printf '%s' "$response" | python3 -c "
import json, sys
q = json.load(sys.stdin)
active = len(q.get('queue_running', [])) + len(q.get('queue_pending', []))
sys.exit(0 if active > 0 else 1)
"
