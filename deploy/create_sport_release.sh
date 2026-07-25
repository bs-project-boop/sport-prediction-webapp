#!/bin/bash
# Sport Prediction — Safe Release Creator
# Creates a new release with ALL components (backend + engine + frontend + logs),
# then validates completeness BEFORE switching the 'current' symlink.
#
# Usage:
#   ./create_sport_release.sh [--frontend-only] [--backend-only] [--engine-only]
#   Without flags: copies all components from current release.
#
set -euo pipefail

RELEASES_DIR="/opt/sport-prediction/releases"
CURRENT="${RELEASES_DIR}/current"
TIMESTAMP=$(date +%Y%m%d%H%M%S)
NEW_RELEASE="${RELEASES_DIR}/${TIMESTAMP}"

# ── Parse flags ────────────────────────────────────────────────────────────────
COPY_BACKEND=1
COPY_ENGINE=1
COPY_FRONTEND=1

for arg in "$@"; do
  case $arg in
    --frontend-only)  COPY_BACKEND=0; COPY_ENGINE=0; COPY_FRONTEND=1 ;;
    --backend-only)    COPY_BACKEND=1; COPY_ENGINE=0; COPY_FRONTEND=0 ;;
    --engine-only)    COPY_BACKEND=0; COPY_ENGINE=1; COPY_FRONTEND=0 ;;
    --all)            COPY_BACKEND=1; COPY_ENGINE=1; COPY_FRONTEND=1 ;;
    -h|--help)
      echo "Usage: $0 [--frontend-only|--backend-only|--engine-only|--all]"
      echo "  Default (no flags): copy all components from current release."
      exit 0 ;;
  esac
done

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S')] [release] $*"; }

# ── Require root ───────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  log "ERROR: Must run as root (needed to set ownership)"
  exit 1
fi

# ── Create new release dir ─────────────────────────────────────────────────────
mkdir -p "${NEW_RELEASE}"
log "Created: ${NEW_RELEASE}"

# ── Copy-forward from current (if it exists) ───────────────────────────────────
if [ -d "${CURRENT}" ]; then
  log "Copying forward from ${CURRENT}..."

  if [ $COPY_BACKEND -eq 1 ] && [ -d "${CURRENT}/backend" ]; then
    log "  + backend/"
    cp -a "${CURRENT}/backend" "${NEW_RELEASE}/backend"
  fi

  if [ $COPY_ENGINE -eq 1 ] && [ -d "${CURRENT}/engine" ]; then
    log "  + engine/"
    cp -a "${CURRENT}/engine" "${NEW_RELEASE}/engine"
  fi

  if [ $COPY_FRONTEND -eq 1 ] && [ -d "${CURRENT}/frontend" ]; then
    log "  + frontend/"
    cp -a "${CURRENT}/frontend" "${NEW_RELEASE}/frontend"
  fi

  if [ -d "${CURRENT}/logs" ]; then
    log "  + logs/"
    cp -a "${CURRENT}/logs" "${NEW_RELEASE}/logs"
  fi

  if [ -f "${CURRENT}/run_ingest.sh" ]; then
    log "  + run_ingest.sh"
    cp -a "${CURRENT}/run_ingest.sh" "${NEW_RELEASE}/run_ingest.sh"
  fi
else
  log "WARNING: No current symlink found — creating base release from scratch"
fi

# ── Post-deploy hook: overlay updated components ────────────────────────────────
# After running this script, deploy your changed component:
#   rsync -a /path/to/new/backend/ ${NEW_RELEASE}/backend/
#   rsync -a /path/to/new/engine/  ${NEW_RELEASE}/engine/
#   npm run build && rsync -a ./dist/ ${NEW_RELEASE}/frontend/dist/

# ── Pre-switch validation ──────────────────────────────────────────────────────
log "Running pre-switch validation..."
ERRORS=0

if [ ! -d "${NEW_RELEASE}/backend" ]; then
  log "  ERROR: backend/ missing"
  ERRORS=$((ERRORS + 1))
else
  log "  OK: backend/"
fi

if [ ! -d "${NEW_RELEASE}/frontend" ]; then
  log "  ERROR: frontend/ missing"
  ERRORS=$((ERRORS + 1))
elif [ ! -f "${NEW_RELEASE}/frontend/dist/index.html" ]; then
  log "  ERROR: frontend/dist/index.html missing (run: npm run build)"
  ERRORS=$((ERRORS + 1))
else
  log "  OK: frontend/dist/"
fi

if [ ! -d "${NEW_RELEASE}/engine" ]; then
  log "  ERROR: engine/ missing"
  ERRORS=$((ERRORS + 1))
else
  log "  OK: engine/"
fi

if [ $ERRORS -gt 0 ]; then
  log "VALIDATION FAILED: ${ERRORS} error(s). NOT switching current symlink."
  log "Fix errors above, then manually: ln -sfn ${NEW_RELEASE} ${CURRENT}"
  exit 1
fi

log "Validation passed (${ERRORS} errors)"

# ── Set ownership ──────────────────────────────────────────────────────────────
chown -R sportapp:sportapp "${NEW_RELEASE}"

# ── Atomic switch ──────────────────────────────────────────────────────────────
log "Switching 'current' symlink to ${NEW_RELEASE}"
ln -sfn "${NEW_RELEASE}" "${CURRENT}"
log "Done: ${CURRENT} -> ${NEW_RELEASE}"
