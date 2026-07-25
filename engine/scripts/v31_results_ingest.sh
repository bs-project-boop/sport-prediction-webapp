#!/bin/bash
# Sport Engine Results Ingest
# Runs ingestion on current engine state files (schedules, predictions, state)
# Idempotent: safe to re-run via systemd timer every 5 min
set -euo pipefail

ENGINE="/opt/sport-prediction/current/engine"
LOCK="/var/run/sport-ingest.lock"
WRAPPER="$ENGINE/scripts/sport-lock-wrapper.py"
VENV="$ENGINE/backend/venv"

if [ -f "$WRAPPER" ]; then
    exec python3 "$WRAPPER" "$LOCK" "$VENV/bin/python" "$VENV/bin/python" -m app.workers.ingest \
        --root "$ENGINE/data" 2>&1
else
    exec "$VENV/bin/python" -m app.workers.ingest \
        --root "$ENGINE/data" 2>&1
fi
