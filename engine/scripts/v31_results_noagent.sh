#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/sport-prediction/current/engine/venv/bin:$PATH"
ENGINE_DIR="/opt/sport-prediction/current/engine"
out=$(TZ=Asia/Jakarta "$ENGINE_DIR/venv/bin/python3" "$ENGINE_DIR/scripts/sports_v31_watch.py" --date "$(TZ=Asia/Jakarta date +%F)" --mode results 2>&1 || true)
if [ "$out" = "[SILENT]" ] || [ -z "$out" ]; then
  exit 0
fi
printf '%s\n' "$out"
