#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/sport-prediction/current/engine/venv/bin:$PATH"
ENGINE_DIR="/opt/sport-prediction/current/engine"
out=$(TZ=Asia/Jakarta "$ENGINE_DIR/venv/bin/python3" "$ENGINE_DIR/scripts/sports_v31_1010.py" 2>&1 || true)
if printf '%s' "$out" | grep -q '"'"'all_pass'"'"': true'; then
  printf '🏆 10/10 — sport scanning v3.1 — %s\n' "$(TZ=Asia/Jakarta date +%F)"
fi
