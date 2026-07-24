#!/usr/bin/env bash
set -euo pipefail
ENGINE="/opt/sport-prediction/current/engine"
LOCK="/var/run/sport-1010.lock"
WRAPPER="$ENGINE/scripts/sport-lock-wrapper.py"

OUT=$(python3 "$WRAPPER" "$LOCK"   "$ENGINE/venv/bin/python3" "$ENGINE/scripts/sports_v31_1010.py" 2>&1 || true)
if printf '%s' "$OUT" | grep -q "'all_pass': true"; then
  printf '🏆 10/10 — sport scanning v3.1 — %s\n' "$(TZ=Asia/Jakarta date +%F)"
fi
