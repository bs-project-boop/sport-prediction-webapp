#!/bin/bash
# Sport Engine Results Ingest
# Reads engine state files (schedules, predictions, results) and upserts to DB.
# Idempotent: safe to re-run via systemd timer every 5 min.
set -euo pipefail

ENGINE="/opt/sport-prediction/current/engine"
LOCK="/var/run/sport-ingest.lock"
VENV_PYTHON="/opt/sport-prediction/current/backend/venv/bin/python"

cd /opt/sport-prediction/current/backend
exec "$VENV_PYTHON" -m app.workers.ingest --root "$ENGINE/data" 2>&1
