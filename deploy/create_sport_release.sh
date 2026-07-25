#!/bin/bash
# Sport Prediction — Safe Release Creator
# Creates a new release with ALL components (backend + engine + frontend + logs),
# builds frontend natively on LXC, then validates completeness BEFORE switching
# the 'current' symlink.
#
# IMPORTANT: All work is executed INSIDE LXC 108. Mac is ONLY a command dispatcher.
#
# Usage:
#   ./create_sport_release.sh [--frontend-only] [--backend-only] [--engine-only]
#   Without flags: copies all components + builds frontend from LXC source.
#
set -euo pipefail

RELEASES_DIR="/opt/sport-prediction/releases"
CURRENT="${RELEASES_DIR}/current"
FRONTEND_BUILD_WS="/opt/sport-prediction/build-workspace/frontend/frontend"
TIMESTAMP=$(date +%Y%m%d%H%M%S)
NEW_RELEASE="${RELEASES_DIR}/${TIMESTAMP}"

# ── Parse flags ────────────────────────────────────────────────────────────────
COPY_BACKEND=1
COPY_ENGINE=1
COPY_FRONTEND=1
BUILD_FRONTEND=0

for arg in "$@"; do
  case $arg in
    --frontend-only)
      COPY_BACKEND=1   # still need backend/ in the release
      COPY_ENGINE=1   # still need engine/ in the release
      COPY_FRONTEND=0  # will build fresh instead of copying stale one
      BUILD_FRONTEND=1 ;;
    --backend-only)
      COPY_BACKEND=1; COPY_ENGINE=0; COPY_FRONTEND=1; BUILD_FRONTEND=0 ;;
    --engine-only)
      COPY_BACKEND=0; COPY_ENGINE=1; COPY_FRONTEND=1; BUILD_FRONTEND=0 ;;
    --all)
      COPY_BACKEND=1; COPY_ENGINE=1; COPY_FRONTEND=1; BUILD_FRONTEND=1 ;;
    -h|--help)
      echo "Usage: $0 [--frontend-only|--backend-only|--engine-only|--all]"
      echo "  Default (no flags): copy all components + build frontend on LXC."
      echo "  --frontend-only: copy backend+engine, BUILD fresh frontend on LXC."
      exit 0 ;;
  esac
done

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S')] [release] $*"; }

# ── Require root ───────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  log "ERROR: Must run as root"
  exit 1
fi

# ── Load nvm for Node.js ───────────────────────────────────────────────────────
log "Loading Node.js from nvm..."
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  . "$NVM_DIR/nvm.sh"
fi

# Verify node is available
if ! command -v node &>/dev/null; then
  log "ERROR: Node.js not found. Install with: nvm install 22"
  exit 1
fi
log "Node: $(node --version)  npm: $(npm --version)"

# ── Create new release dir ─────────────────────────────────────────────────────
mkdir -p "${NEW_RELEASE}"
log "Created: ${NEW_RELEASE}"

# ── Copy-forward from current ───────────────────────────────────────────────────
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

  if [ $COPY_FRONTEND -eq 1 ] && [ $BUILD_FRONTEND -eq 0 ] && [ -d "${CURRENT}/frontend" ]; then
    log "  + frontend/ (copied from current)"
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
  log "WARNING: No current symlink — creating base release from scratch"
fi

# ── Build frontend on LXC (not on Mac) ────────────────────────────────────────
if [ $BUILD_FRONTEND -eq 1 ]; then
  log "Building frontend on LXC (not Mac)..."

  if [ ! -d "${FRONTEND_BUILD_WS}" ]; then
    log "ERROR: Frontend source not found at ${FRONTEND_BUILD_WS}"
    log "Clone with: git clone https://github.com/bs-project-boop/sport-prediction-webapp.git /opt/sport-prediction/build-workspace/frontend"
    exit 1
  fi

  log "  Pulling latest from GitHub..."
  cd "${FRONTEND_BUILD_WS}"
  git pull origin main

  log "  npm install..."
  npm install --silent

  log "  npm run build..."
  BUILD_OUTPUT=$(npm run build 2>&1)
  log "  Build: $(echo "$BUILD_OUTPUT" | tail -3)"

  # Copy built dist/ into the release's frontend/
  log "  Copying dist/ to release..."
  mkdir -p "${NEW_RELEASE}/frontend"
  rsync -a --delete "${FRONTEND_BUILD_WS}/dist/" "${NEW_RELEASE}/frontend/dist/"
  log "  + frontend/dist/ (built on LXC)"
fi

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
  log "  ERROR: frontend/dist/index.html missing (build may have failed)"
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
