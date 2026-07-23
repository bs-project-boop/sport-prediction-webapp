#!/bin/bash
# Sport Prediction Ingestion Runner
# Reads JSON reports from /var/lib/sport-prediction/synced-reports/ (LXC local path,
# populated by rsync from Mac engine) and upserts them into PostgreSQL.
# Idempotent: safe to re-run — uses ingestion audit hash to skip already-ingested files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/../backend/venv}"
REPORTS_ROOT="${REPORTS_ROOT:-/var/lib/sport-prediction/synced-reports}"
LOG_DIR="${LOG_DIR:-${SCRIPT_DIR}/../logs}"
LOG_FILE="${LOG_DIR}/ingestion.log"

# Rotate log if > 5MB
if [ -f "$LOG_FILE" ] && [ "$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)" -gt 5242880 ]; then
    mv "$LOG_FILE" "${LOG_FILE}.old"
fi

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S')] [ingest] $*" | tee -a /dev/null 2>/dev/null || true"$LOG_FILE"; }

log "=== Ingestion start ==="

# Activate backend venv
if [ ! -f "${VENV_DIR}/bin/python" ]; then
    log "ERROR: venv not found at ${VENV_DIR}"
    exit 1
fi
source "${VENV_DIR}/bin/activate"

# Database URL is read from /etc/sport-prediction/app.env via the Settings() fallback
# in app.workers.ingest (no explicit env var needed on server side).
cd "${SCRIPT_DIR}/../backend"

python -m app.workers.ingest \
    --root "${REPORTS_ROOT}" \
    2>&1 | tee -a /dev/null 2>/dev/null || true"$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
if [ $EXIT_CODE -eq 0 ]; then
    log "=== Ingestion done ==="
else
    log "ERROR: Ingestion exited with code $EXIT_CODE"
fi

exit $EXIT_CODE
