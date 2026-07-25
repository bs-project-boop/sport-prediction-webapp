# Sport Intelligence

Prediction desk for football, basketball, tennis, motorsport, and NFL — covering FIFA World Cup, IBL, MotoGP, FIBA, Grand Slam, and more.

## Access URLs

| Service | URL | Notes |
|---------|-----|-------|
| **LAN + External** | http://10.10.10.83:8100 | FastAPI — single port for API + SPA |
| **External via Cloudflare Tunnel** | https://sports.bintangsofyan.com/ | Routes to backend port 8100 |

- API docs: http://10.10.10.83:8100/docs
- PIN: 6-digit, ask the operator

> ⚠️ Port 8101 (`serve -s` static frontend) was **decommissioned on 2026-07-23**. All access now goes through port 8100.

---

## Architecture

```
Browser (LAN / Cloudflare Tunnel)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│  LXC 108 (Proxmox, 10.10.10.83)                         │
│                                                          │
│  ┌──────────────────────────────┐                        │
│  │ sport-prediction-backend     │                        │
│  │ FastAPI / uvicorn :8100     │                        │
│  │ • REST API                  │                        │
│  │ • React SPA (/)             │                        │
│  └──────────────────────────────┘                        │
│         │                                                │
│         ▼                                                │
│  ┌────────────────────┐  ┌────────────────────────────┐ │
│  │ PostgreSQL         │  │ Engine Scripts (systemd)  │ │
│  │ 127.0.0.1 :5432   │  │ 8 timers + services:     │ │
│  │ 1203 matches       │  │ • daily-scan (00:01 WIB) │ │
│  │ 1202 predictions   │  │ • prematch (*/5)          │ │
│  │                    │  │ • results (*/5)           │ │
│  │                    │  │ • results-ingest (*/5)    │ │
│  │                    │  │ • eod-summary (*/30)      │ │
│  │                    │  │ • 10-10 watchdog (*/30)   │ │
│  │                    │  │ • hourly-refresh (hourly) │ │
│  │                    │  │ • cron-alert (*/5)        │ │
│  │                    │  │ All run as sportapp user  │ │
│  │                    │  │ Lock-protected (flock/    │ │
│  │                    │  │ fcntl) — no overlaps      │ │
│  └────────────────────┘  └────────────────────────────┘ │
│                            │                             │
│                            ▼                             │
│                   /opt/sport-prediction/                  │
│                   current/engine/data/                     │
│                   (predictions, schedules, state, audit)   │
└──────────────────────────────────────────────────────────┘
        │
        │ Cloudflare Tunnel (LXC 104 → host systemd)
        ▼
  sports.bintangsofyan.com (HTTPS)
```

### Two-Writer Pipeline Architecture

The system has **2 writers** with **strictly separate scopes** — no double-write risk:

| Writer | Trigger | Scope |
|--------|---------|-------|
| `v32_daily_quota_safe_fallback.py` (daily-scan) | `daily-scan.timer` (00:01 WIB) | **Discovery/scheduling** — fetches ESPN → writes new matches + predictions to DB (INSERT new rows only) |
| `run_ingest.sh` (results-ingest) | `sport-engine-results-ingest.timer` (every 5 min) | **Results/validation** — reads `state.json` → updates existing matches with final scores + evaluates predictions (UPDATE existing rows only) |

> ⚠️ **Historical note:** The `sport-prediction-ingest.timer/service` was removed 2026-07-24 because it was thought to be fully redundant with daily-scan. That was incorrect — daily-scan handles *discovery* (new matches), while ingestion handles *results* (existing matches with final scores). The two tasks never overlapped. The results-ingest timer restores this separate responsibility.

### Ports

| Port | Service | Purpose |
|------|---------|---------|
| 8100 | `sport-prediction-backend` | **FastAPI — API + embedded SPA (single port for all access)** |

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | React 19 + TypeScript + Vite + TanStack Query |
| Backend | FastAPI (Python 3.13) + SQLAlchemy + Pydantic |
| Database | PostgreSQL (`sport_prediction`) |
| Auth | PIN + Argon2id hash + HttpOnly session cookie |
| Serving | `uvicorn` (port 8100 only) |
| Infra | Proxmox LXC 108 |
| Deployment | systemd units — **always use `systemctl`** |

---

## Repository Structure

```
sport-prediction-webapp/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, all routes, CORS, session config
│   │   ├── core/
│   │   │   ├── security.py      # Argon2id PIN hash/verify
│   │   │   ├── sessions.py      # In-memory UUID session store
│   │   │   ├── rate_limit.py    # Sliding-window rate limiter
│   │   │   └── settings.py      # Pydantic Settings (env + CLI)
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   └── services/ingestion.py
│   ├── tests/                  # pytest — auth, matches, predictions, metrics
│   └── .venv/                  # Python 3.13 virtualenv
├── frontend/
│   ├── src/
│   │   ├── App.tsx             # Root: PIN gate → dashboard ↔ settings
│   │   ├── lib/api.ts          # ApiClient (fetch, cookie jar, base URL smart-resolve)
│   │   ├── lib/ThemeProvider.tsx
│   │   ├── lib/groupMatches.ts
│   │   └── features/
│   │       ├── auth/           # PinLogin, Settings
│   │       └── matches/        # SportFilterBar, KpiRow, MatchGrid, MatchCard
│   ├── dist/                   # Built output (rsync'd to LXC)
│   └── tests/                  # vitest — groupMatches, ThemeProvider, validation
├── docs/                       # ADRs and technical decisions
├── PROJECT-SUMMARY.md          # Detailed technical reference
└── README.md                  # This file
```

---

## Feature Status

| Feature | Status | Notes |
|---------|--------|-------|
| PIN authentication | ✅ Active | 6-digit PIN, Argon2id hash |
| Session management | ✅ Active | UUID cookie, 1-hour TTL, rate-limited |
| Match listing + filtering | ✅ Active | Sport pills, date range (optional), search |
| Prediction cards | ✅ Active | BENAR/SEBAGIAN_BENAR/SALAH badges, confidence breakdown |
| Accuracy metrics (KPI row) | ✅ Active | Strict & lenient accuracy % |
| Date filter | ✅ Active | Optional — defaults to no filter (shows all matches) |
| Dark/light theme | ✅ Active | localStorage persistence |
| Change PIN (authenticated) | ✅ Active | PATCH /auth/pin |
| Swagger docs | ✅ Active | /docs |
| Cloudflare Tunnel external access | ✅ Active | sports.bintangsofyan.com → 8100 |
| Two-writer ingestion pipeline | ✅ Active | Discovery (daily-scan) + results (results-ingest) separate scopes |
| M1–M8 migration complete | ✅ Done | Monorepo, TanStack Query, React 19 |

---

## Deployment

> **Mac is ONLY a command dispatcher** — all build, compile, and deploy work happens inside LXC 108.

### Frontend: Build + Release (LXC-native)

```bash
# Option A — Recommended: use the safe release script (copies forward all
# components from current release, builds frontend on LXC, validates before switch)
ssh lxc-108 'bash /opt/sport-prediction/create_sport_release.sh --frontend-only'
# This script: git pull + npm install + npm run build + copy dist to new release
# + pre-switch validation (checks backend/, frontend/dist/, engine/ exist)
# + atomic symlink switch to new release

# Option B — Full stack release (all components)
ssh lxc-108 'bash /opt/sport-prediction/create_sport_release.sh --all'
```

Frontend source workspace on LXC: `/opt/sport-prediction/build-workspace/frontend/frontend`
(Cloned from GitHub, Node.js v22.22.3 managed via nvm in LXC)

### Backend: Deploy migration/file change

```bash
ssh lxc-108 'bash /opt/sport-prediction/create_sport_release.sh --backend-only'
```

### Engine: Deploy script changes

```bash
ssh lxc-108 'bash /opt/sport-prediction/create_sport_release.sh --engine-only'
```

### Manual fallback (if script unavailable)

```bash
# Create release dir + copy forward all components from current release
ssh lxc-108 bash << 'EOF'
RELEASE_TS=$(date +%Y%m%d%H%M%S)
mkdir -p /opt/sport-prediction/releases/${RELEASE_TS}
cp -a /opt/sport-prediction/current/backend  /opt/sport-prediction/releases/${RELEASE_TS}/
cp -a /opt/sport-prediction/current/engine  /opt/sport-prediction/releases/${RELEASE_TS}/
cp -a /opt/sport-prediction/current/frontend /opt/sport-prediction/releases/${RELEASE_TS}/
ln -sfn /opt/sport-prediction/releases/${RELEASE_TS} /opt/sport-prediction/current
EOF
```

### 3. Restart backend (REQUIRED — always use systemd)

```bash
ssh proxmox "pct exec 108 -- systemctl restart sport-prediction-backend"
```

### 4. Verify

```bash
# Backend health
curl http://10.10.10.83:8100/health/

# Login
curl -s -X POST http://10.10.10.83:8100/auth/pin \
  -H "Content-Type: application/json" \
  -d '{"pin":"123456"}'

# Dashboard loads (no date filter)
curl -s -b /tmp/cookies.txt http://10.10.10.83:8100/matches?limit=3
```

> **⚠️ NEVER use `nohup`, `&`, or manual `uvicorn`/`python -m http.server`** — systemd is the only way to ensure processes restart after crashes.

---

## Systemd Units

The backend unit is `enabled` (starts on boot); the frontend unit is `disabled` (decommissioned 2026-07-23).

| Unit | Status | WorkingDirectory | ExecStart |
|------|--------|----------------|-----------|
| `sport-prediction-backend.service` | **enabled** | `/opt/sport-prediction/current/backend` | `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100` |
| `sport-prediction-frontend.service` | **disabled** | — | Decommissioned 2026-07-23 — all access via 8100 |
| `sport-engine-results-ingest.timer` | **enabled** | `/opt/sport-prediction/current/engine` | Runs `v31_results_ingest.sh` every 5 min |
| `sport-engine-results-ingest.service` | **static** | `/opt/sport-prediction/current/engine` | Calls `run_ingest.sh` (results-ingest scope only) |

---

## Environment Configuration

Config file: `/etc/sport-prediction/app.env` (owned by `sportapp:sportapp`, mode `600`)

| Variable | Description |
|----------|-------------|
| `SPORT_PREDICTION_PIN_HASH` | Argon2id hash of current PIN |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection |
| `SECURE_COOKIES` | Set `false` for HTTP-only access; `true` requires HTTPS |

---

## Facing Issues

> Last updated: 2026-07-25 17:35 WIB

**⚠ Active limitation:** ~764 overdue matches (FIBA youth/qualifier leagues) will NEVER auto-resolve — ESPN doesn't cover these competitions. See "Data Coverage Limitations" below for details.

---

## Data Coverage Limitations

> ⚠️ **Realistic expectations for overdue match resolution**

Of 911 past matches stuck at `SCHEDULED`, the breakdown by ESPN coverage is:

| Category | Competitions | Count | Will Auto-Resolve? |
|----------|-------------|-------|-------------------|
| **ESPN-covered** | Wimbledon (tennis), MLS (football), FIFA World Cup 2026, MotoGP | **147** | ✅ YES — pipeline works |
| **Not ESPN-covered** | FIBA U18/U20/U17 youth qualifiers, AmeriCup/EuroBasket pre-quals, eFIBA, FIBA Africa/Asia/Americas/WABA qualifiers | **764** | ❌ NO — provider doesn't cover these |

**147 matches (16.1%)** will resolve automatically when those competitions are active and ESPN provides scores.

**764 matches (83.9%) are permanently stuck** — the system cannot capture results for competitions not covered by ESPN. These require either:
- A second data provider for youth/qualifier leagues, or
- Manual result entry, or
- Acceptance they will remain as historical records

This is a **known limitation** (not a bug). The 30 matches that already have `actual_result` in DB (FIFA World Cup 2026 matches from July 8–20) prove the pipeline works correctly for ESPN-covered sports.

---

## Known Issues Resolved

| Issue | Date Resolved | Root Cause + Fix |
|-------|---------------|------------------|
| Ingestion results pipeline gap — 933 past matches stuck at SCHEDULED despite actual_result in `prediction_results` | 2026-07-25 | Root cause: `sport-engine-results-ingest.timer` was mistakenly deleted 2026-07-24 (thought to be redundant with daily-scan). Actually, daily-scan handles *discovery* (new matches/predictions INSERT), while results-ingest handles *results* (existing matches UPDATE with final scores + prediction evaluation). Separate scopes, no double-write risk. Fix: (1) Restored `sport-engine-results-ingest.timer` (every 5 min) + `sport-engine-results-ingest.service`; (2) Fixed `app/services/ingestion.py` to also update `matches.status` from state file; (3) Backfill updated 22 matches.status from SCHEDULED to FINISHED; (4) `run_ingest.sh` correctly reads from `/opt/sport-prediction/current/engine/data/` and `/var/lib/sport-prediction/synced-reports/state/` (historical). |
| Silent failure masking — engine scripts silenced errors with `|| true` | 2026-07-25 | 5 instances across 4 scripts: `v31_results_noagent.sh` (line 9), `v31_prematch_noagent.sh` (line 9), `v31_eod_noagent.sh` (lines 8+10), `v31_1010_noagent.sh` (line 7 inside `OUT=$(...)` subshell — masks only the assignment, not script exit). Fix: removed all top-level `|| true` instances; fixed `run_ingest.sh` log redirection (`LOGFILE="..." 2>&1` → `>> $LOGFILE 2>&1`); added `set -euo pipefail`. All scripts verified with proper exit codes. |
| `v31_results_ingest.sh` wrong venv path — timer silently failed | 2026-07-25 | Timer `sport-engine-results-ingest.timer` was firing every 5 min but producing NO data because the script had wrong path (`$ENGINE/backend/venv` → `/opt/sport-prediction/current/engine/backend/venv` which doesn't exist) AND used lock wrapper with duplicate python args AND didn't `cd` to backend directory. Fix: hardcoded `VENV_PYTHON="/opt/sport-prediction/current/backend/venv/bin/python"`, `cd /opt/sport-prediction/current/backend`, `exec "$VENV_PYTHON"`. Timer now verified working with journalctl output showing `files_seen=23 files_ingested=1 records_written=0`. |
| `eod.timer` and `watchdog.timer` missing boot-time trigger | 2026-07-25 | Both timers only had `OnUnitActiveSec=1800` (fires 30 min after service last-active), but no `OnBootSec` — meaning after host reboot, timers would not fire until 30 min after first service run. Fix: added `OnBootSec=60` to both timers. Removed stale `[Install]` section from `eod.timer`. Timers now fire at boot + recurring. |
| Production DOWN — frontend returning `{"detail":"Not Found"}` (sports.bintangsofyan.com) | 2026-07-24 | Root cause: `current/frontend` symlink pointed to `/opt/sport-prediction/releases/sport-prediction-frontend-20250724/frontend` but no release ever contained a `frontend/` directory — `os.path.isdir()` was always False → the entire frontend-serving block was bypassed → FastAPI returned default 404. Also: `serve -s .` in `sport-prediction-frontend.service` served directory listing, not SPA. Fix: (1) `_FRONTEND_DIST` updated to `/opt/sport-prediction/current/frontend/dist` (correct path); (2) added explicit `@app.get("/")` route (empty path doesn't match `{full_path:path}`); (3) frontend built on Mac + deployed to LXC new release; (4) frontend service decommissioned (backend now serves SPA directly). Deploy script `/opt/sport-prediction/create_sport_release.sh` created to enforce complete releases. |
| sed text-edit corrupted 2 Python scripts silently (SyntaxError in cron-alert + hourly-refresh) | 2026-07-24 | During cutover migration, `sed -i` replaced `/var/run/sportapp/` paths without preserving Python string quotes — `LOCK_FILE = /path` (no quotes) → `SyntaxError`. Both services failed for ~20h (cron-alert) and ~11h (hourly-refresh). Fix: Python script applied quotes restoration, duplicate imports removed. Prevention: `python3 -m py_compile` must run after every automated text edit to Python files. All 9 scripts verified clean. |
| Release folder missing `frontend/dist` — production DOWN | 2026-07-24 | Pattern: every release was created by selectively rsyncing only the changed component, with no copy-forward of other components. `frontend/dist` was never included in any release. Fix: `/opt/sport-prediction/create_sport_release.sh` enforces copy-forward of ALL components from current release + pre-switch validation (checks `backend/`, `frontend/dist/index.html`, `engine/scripts/` exist). |
| `run_ingest.sh` missing from LXC releases | 2026-07-23 | Same pattern as `frontend/dist` — only the changed component was rsynced; `run_ingest.sh` (not modified) was never included. Created and deployed. Now covered by copy-forward script. |
| Duplicate predictions growing unchecked (1636 of 2209 rows, ~74%) | 2026-07-24 | Root cause: `_ingest_prediction()` used `source_record_id = "{date}:{match_id}"` as lookup key. Daily scan's 7-day window re-INGESTed the same match every cycle as a NEW row. Fix: canonical `match_id` lookup; DB `UNIQUE constraint uq_predictions_match_id`; cleanup deleted 1007 rows. DB now: 1202 predictions, 0 duplicates. Backup at `/opt/sport-prediction/backups/predictions-pre-dedup-20260724-111034.sql`. |
| Cron engine paused since Jul 21 20:20 — all 6 jobs disabled | 2026-07-23 | Root cause: `bintangsofyan` issued pause command, then session ended before resume. Fix: `enabled=true, state=active` set for all 7 jobs (6 original + hourly refresh). Jobs resumed Jul 23 16:02 WIB. |
| `run_ingest.sh` missing from LXC | 2026-07-23 | Service `sport-prediction-ingest.service` referenced `run_ingest.sh` which was never deployed to LXC. Created `scripts/run_ingest.sh` (Bash wrapper calling `workers/ingest.py`), deployed to release `20260723153000`. |
| `sport-prediction-ingest.service` failed (exit 126/1) | 2026-07-23 | Permission issues: (1) `run_ingest.sh` missing execute bit for sportapp; (2) log dir `/opt/sport-prediction/logs` missing; (3) `tee` to log file permission denied. Fixed: chmod 755, mkdir logs, chmod 777 logs, sed `tee`→`tee -a "/dev/null"`. |
| Match status chaos (12+ raw variants) | 2026-07-23 | Raw statuses like `P1`, `init`, `b`, `halftime` were stored directly without normalization. Added `MATCH_STATUS_MAP` (12→5 canonical: SCHEDULED/FINISHED/LIVE/POSTPONED/CANCELLED) + `_normalize_match_status()`. DB shows 893 SCHEDULED, 26 FINISHED, 4 LIVE, 1 POSTPONED — all canonical. |
| "ESPN HTTP 404" misdiagnosis | 2026-07-23 | Initial diagnosis of "ESPN API down" was wrong. Root cause was two separate issues: (1) curl used `football/scoreboard` (no league qualifier) which doesn't exist on ESPN — actual league-qualified paths work fine; (2) hourly cron script had 60s timeout for a process needing 3+ min (enrichment bottleneck). Fix: hourly script timeout 60→300s, removed enrich from hourly runs. |
| Hourly refresh script missing `--sport` filter + timeout too short | 2026-07-23 | `sports_v32_hourly_refresh.py` had 60s subprocess timeout, but enrichment takes ~3 min. Also ran without sport filter (all 15 leagues × 8 dates = 120 ESPN calls per sport). Also ran without sport filter (all 15 leagues × 8 dates = 120 ESPN calls per sport). Fix: added `--sport football --sport basketball --sport tennis` filter + 300s timeout. |
| Window scan only 48h instead of 7 days | 2026-07-23 | `sports_v31_espn_ingest.py` line 1231 had `window_end = window_start + timedelta(hours=48)`. Fixed to `timedelta(days=7)` to match spec. |
| No hourly refresh job existed | 2026-07-23 | Spec requires refresh every hour. Created `sports_v32_hourly_refresh.py` — calls ingest for today+7days across 8× windows (12z-20z WIB). Registered as job `5e9a1c3f8b2d` with cron `0 * * * *`. |
| Port 8101 decommissioned | 2026-07-23 | Two-service architecture (`serve -s` on 8101 + FastAPI on 8100) caused repeated out-of-sync bugs (bundle mismatch, restart forgotten). Consolidated to single port 8100. Cloudflare Tunnel and LAN access now both route to backend directly. |
| Port 8101 served old bundle (`index-CokD2ddX.js`) causing PIN to fail | 2026-07-23 | `sport-prediction-frontend` service had not been restarted after `current` symlink was updated to release `20260722052000`. Fixed by running `systemctl restart sport-prediction-frontend`. Lesson: always restart services after updating the `current` symlink. |
| `/api/auth/pin` 405 on Cloudflare Tunnel | 2026-07-22 | Frontend bundle had `VITE_API_BASE_URL=/api` baked in, causing API calls to go to `/api/auth/pin` (FastAPI returns 405 on that route). Fixed by removing `VITE_API_BASE_URL` from `.env.production`, letting the bundle use relative URLs. |
| Cache busting — old JS bundle served after deploy | 2026-07-22 | Cloudflare was caching `index-*.js` assets indefinitely. Fixed by adding Cache Rule to bypass cache on root `/` and setting `Cache-Control: no-cache` on `index.html` via FastAPI response header. |
| `sport_prediction` database not found | 2026-07-22 | Database name uses underscores (`sport_prediction`), not dashes. Correct `DATABASE_URL` in env. |
| Caddy reverse proxy rejected by user | 2026-07-21 | User explicitly does not want Caddy. Architecture switched to Cloudflare Tunnel only with FastAPI serving SPA directly. |

---

## Git Commit Conventions

- Format: `git commit -m "scope: short description (#ticket)"`
- **WAJIB** — setiap push ke `main` harus update bagian "Facing Issues" di README.md
- **WAJIB** — test files (`test_*.py`, `test-*.js`) harus di-clean sebelum commit
- **WAJIB** — setiap automated text-edit ke file Python (sed/str_replace/patch) WAJIB langsung diikuti `python3 -m py_compile <file>` — jika gagal compile: STOP, perbaiki dulu sebelum restart service. (Contoh: sed yang tidak escape quotes bisa membuat `LOCK_FILE = /path` tanpa quotes → SyntaxError.)
- **WAJIB** — setiap release baru DI LXC WAJIB dibuat pakai `/opt/sport-prediction/create_sport_release.sh` (copy-forward semua komponen + validasi kelengkapan sebelum symlink switch)
- **CEK SEKURITI** sebelum push — tidak ada secret/password/PIN di git history:
  ```bash
  git log --all -p | grep -iE "password|secret|api[_-]?key|pin.*=.*[0-9]{6}" | head -20
  ```
