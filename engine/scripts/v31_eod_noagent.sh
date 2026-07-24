#!/usr/bin/env bash
set -euo pipefail
ENGINE="/opt/sport-prediction/current/engine"
LOCK="/var/run/sport-eod.lock"
WRAPPER="$ENGINE/scripts/sport-lock-wrapper.py"
DATE="$(TZ=Asia/Jakarta date +%F)"

python3 "$WRAPPER" "$LOCK"   "$ENGINE/venv/bin/python3" "$ENGINE/scripts/sports_v31_watch.py"   --date "$DATE" --mode eod 2>&1 || true

python3 "$WRAPPER" "$LOCK-eodcal"   "$ENGINE/venv/bin/python3" "$ENGINE/scripts/sports_calibration_evaluator.py"   --date "$DATE" 2>&1 || true
