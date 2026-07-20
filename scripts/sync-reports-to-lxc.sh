#!/bin/bash
# Sport Prediction — Sync reports from Mac to LXC 108 via rsyncd
set -euo pipefail

REPORTS_ROOT="/Users/beem/.hermes-shared/reports/sports/v3"
LOG_FILE="/Users/beem/sport-prediction-dev/logs/sync.log"

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S')] $*" ;}

log "Sync start"
rsync -avz --delete \
  "$REPORTS_ROOT/" \
  "rsync://sportapp@10.10.10.83/reports/" 2>&1 | tail -3
log "Sync done"
