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
│  ┌────────────────────┐  ┌────────────────────────────┐  │
│  │ PostgreSQL         │  │ Engine Scripts (systemd)  │  │
│  │ 127.0.0.1 :5432    │  │ 7 timers + services:      │  │
│  │ 1203 matches       │  │ • daily-scan (00:01 WIB)  │  │
│  │ 2209 predictions   │  │ • prematch (*/5 monitoring│  │
│  │                    │  │ • results (*/5 monitoring │  │
│  │                    │  │ • eod-summary (*/30)       │  │
│  │                    │  │ • 10-10 watchdog (*/30)   │  │
│  │                    │  │ • hourly-refresh (hourly) │  │
│  │                    │  │ • cron-alert (*/5)        │  │
│  │                    │  │ All run as sportapp user  │  │
│  │                    │  │ Lock-protected (flock/    │  │
│  │                    │  │ fcntl) — no overlaps      │  │
│  └────────────────────┘  └────────────────────────────┘  │
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

### Data Flow (cutover #2 — Mac decommissioned 2026-07-24)
1. Engine timer fires → v32_daily_quota_safe_fallback.py (as sportapp)
2. Script fetches ESPN API → writes JSON to /opt/sport-prediction/current/engine/data/
3. backend/run_ingest.sh (systemd service) → reads JSON → upserts to PostgreSQL
4. Backend API serves React SPA + REST at :8100

⚠️ Mac is no longer involved. Previously Mac ran rsync daemon (com.hermes.sport-prediction-sync)
pushing to /var/lib/sport-prediction/synced-reports/ — now fully decommissioned.
Root path migrated: /var/lib/sport-prediction/synced-reports/ → /opt/sport-prediction/current/engine/data/
Duplicate ingestion risk eliminated (sport-prediction-ingest.timer/service removed 2026-07-24).

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
| PostgreSQL data ingestion | ✅ Active | APScheduler every 2 min |
| M1–M8 migration complete | ✅ Done | Monorepo, TanStack Query, React 19 |

---

## Deployment

### 1. Build frontend

```bash
cd frontend
npm install
npm run build      # output → dist/
```

### 2. Sync to LXC

```bash
RELEASE_TS=$(date +%Y%m%d%H%M%S)
ssh proxmox "pct exec 108 -- mkdir -p /opt/sport-prediction/releases/${RELEASE_TS}/{backend,frontend}"
tar -C frontend/dist -cf - . | ssh proxmox "pct exec 108 -- tar -xf - -C /opt/sport-prediction/releases/${RELEASE_TS}/frontend/"
# Copy backend from current release base
ssh proxmox "pct exec 108 -- cp -r /opt/sport-prediction/releases/<previous_release>/backend /opt/sport-prediction/releases/${RELEASE_TS}/"
# Update symlink
ssh proxmox "pct exec 108 -- ln -sfn /opt/sport-prediction/releases/${RELEASE_TS} /opt/sport-prediction/current"
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

> Last updated: 2026-07-24 18:00 WIB

**⚠ No active issues** — all known issues resolved. See "Known Issues Resolved" below.

---

## Known Issues Resolved

| Issue | Date Resolved | Root Cause + Fix |
|-------|---------------|-----------------|
| Duplicate predictions growing unchecked (1636 of 2209 rows, ~74%) | 2026-07-24 | Root cause: `_ingest_prediction()` used `source_record_id = "{date}:{match_id}"` as lookup key. Daily scan's 7-day window re-INGESTed the same match every cycle as a NEW row (date in key never matched on re-run). 7 timers × multiple cycles/day accelerated growth. Fix: changed lookup to canonical `match_id`; added DB `UNIQUE constraint uq_predictions_match_id`; cleanup deleted 1007 duplicate rows. DB now: 1202 predictions, 0 duplicates. Backup at `/opt/sport-prediction/backups/predictions-pre-dedup-20260724-111034.sql`. |
| Cron engine paused since Jul 21 20:20 — all 6 jobs disabled | 2026-07-23 | Root cause: `bintangsofyan` issued pause command, then session ended before resume. Fix: `enabled=true, state=active` set for all 7 jobs (6 original + hourly refresh). Jobs resumed Jul 23 16:02 WIB. |
| `run_ingest.sh` missing from LXC | 2026-07-23 | Service `sport-prediction-ingest.service` referenced `run_ingest.sh` which was never deployed to LXC. Created `scripts/run_ingest.sh` (Bash wrapper calling `workers/ingest.py`), deployed to release `20260723153000`. |
| `sport-prediction-ingest.service` failed (exit 126/1) | 2026-07-23 | Permission issues: (1) `run_ingest.sh` missing execute bit for sportapp; (2) log dir `/opt/sport-prediction/logs` missing; (3) `tee` to log file permission denied. Fixed: chmod 755, mkdir logs, chmod 777 logs, sed `tee`→`tee -a "/dev/null"`. |
| Match status chaos (12+ raw variants) | 2026-07-23 | Raw statuses like `P1`, `init`, `b`, `halftime` were stored directly without normalization. Added `MATCH_STATUS_MAP` (12→5 canonical: SCHEDULED/FINISHED/LIVE/POSTPONED/CANCELLED) + `_normalize_match_status()`. DB shows 893 SCHEDULED, 26 FINISHED, 4 LIVE, 1 POSTPONED — all canonical. |
| "ESPN HTTP 404" misdiagnosis | 2026-07-23 | Initial diagnosis of "ESPN API down" was wrong. Root cause was two separate issues: (1) curl used `football/scoreboard` (no league qualifier) which doesn't exist on ESPN — actual league-qualified paths work fine; (2) hourly cron script had 60s timeout for a process needing 3+ min (enrichment bottleneck). Fix: hourly script timeout 60→300s, removed enrich from hourly runs. |
| Hourly refresh script missing `--sport` filter + timeout too short | 2026-07-23 | `sports_v32_hourly_refresh.py` had 60s subprocess timeout, but enrichment takes ~3 min. Also ran without sport filter (all 15 leagues × 8 dates = 120 ESPN calls per sport). Fix: added `--sport football --sport basketball --sport tennis` filter + 300s timeout. |
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
- **CEK SEKURITI** sebelum push — tidak ada secret/password/PIN di git history:
  ```bash
  git log --all -p | grep -iE "password|secret|api[_-]?key|pin.*=.*[0-9]{6}" | head -20
  ```
