#!/bin/bash
# Sport Prediction Ingestion Scheduler — runs on Mac, connects to LXC 108 PostgreSQL
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/backend/venv"
REPORTS_ROOT="${REPORTS_ROOT:-/Users/beem/.hermes-shared/reports/sports/v3}"

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S')] $*" ;}
log "=== Ingestion start ==="

# Activate venv
if [ ! -f "$VENV_DIR/bin/python" ]; then
    log "ERROR: venv not found at $VENV_DIR — run scripts/setup-mac-ingestion.sh first"
    exit 1
fi
source "$VENV_DIR/bin/activate"

# Database credentials from macOS Keychain
DB_PASSWORD=$(security find-generic-password -a sportapp -s sport-prediction-db -w 2>/dev/null || true)
if [ -z "$DB_PASSWORD" ]; then
    log "ERROR: DB_PASSWORD not found in macOS Keychain (sportapp/sport-prediction-db)"
    log "Run: scripts/setup-mac-ingestion.sh first"
    exit 1
fi

# Override settings for Mac-side execution
export SPORT_PREDICTION_DATABASE_URL="postgresql://sportapp:${DB_PASSWORD}@10.10.10.83:5432/sport_prediction"
export SPORT_PREDICTION_PIN_HASH=""
export SECURE_COOKIES=false

# Ingest today's reports (cd to backend so app/ module is importable)
cd "$PROJECT_DIR/backend"
python -m app.workers.ingest \
    --root "$REPORTS_ROOT" \
    --date "$(date +%Y-%m-%d)"

log "=== Ingestion done ==="
