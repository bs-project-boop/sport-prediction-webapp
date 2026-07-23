#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/sport-prediction/current/engine/venv/bin:$PATH"
ENGINE_DIR="/opt/sport-prediction/current/engine"
date_wib="$(TZ=Asia/Jakarta date +%F)"
out=$(TZ=Asia/Jakarta "$ENGINE_DIR/venv/bin/python3" "$ENGINE_DIR/scripts/sports_v31_watch.py" --date "$date_wib" --mode eod 2>&1 || true)
cal=$(TZ=Asia/Jakarta "$ENGINE_DIR/venv/bin/python3" "$ENGINE_DIR/scripts/sports_calibration_evaluator.py" --date "$date_wib" 2>&1 || true)
printed=0
if [ "$out" != "[SILENT]" ] && [ -n "$out" ]; then
  printf '%s\n' "$out"
  printed=1
fi
if [ "$cal" != "[SILENT]" ] && [ -n "$cal" ]; then
  if [ "$printed" -eq 1 ]; then
    printf '\n'
  fi
  printf '%s\n' "$cal"
  printed=1
fi
if [ "$printed" -eq 0 ]; then
  exit 0
fi
