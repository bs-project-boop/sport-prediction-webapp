#!/usr/bin/env bash
set -euo pipefail
ENGINE="/opt/sport-prediction/current/engine"
LOCK="/var/run/sport-prematch.lock"
WRAPPER="$ENGINE/scripts/sport-lock-wrapper.py"

python3 "$WRAPPER" "$LOCK"   "$ENGINE/venv/bin/python3" "$ENGINE/scripts/sports_v31_watch.py"   --date "$(TZ=Asia/Jakarta date +%F)" --mode prematch   2>&1 || true
