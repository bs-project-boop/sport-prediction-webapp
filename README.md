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
Browser (LAN direct / Cloudflare Tunnel)
        │
        ▼
┌──────────────────────────────────────┐
│  LXC 108 (Proxmox, 10.10.10.83)     │
│                                      │
│  ┌──────────────────────────────┐   │
│  │ sport-prediction-backend      │   │
│  │ FastAPI / uvicorn :8100      │   │
│  │ • Serves: REST API           │   │
│  │ • Serves: React SPA (/)     │   │
│  │ • CORS: sports.bintangsofyan │   │
│  └──────────────────────────────┘   │
│         │
│         ▼
│  ┌─────────────┐  ┌─────────────────┐
│  │ PostgreSQL  │  │ sport_prediction │
│  │ 127.0.0.1   │  │ 924 matches     │
│  │ :5432       │  │ 1332 predictions│
│  └─────────────┘  └─────────────────┘
└──────────────────────────────────────┘
        │
        │ Cloudflare Tunnel (LXC 104 → host systemd)
        ▼
  sports.bintangsofyan.com (HTTPS)
```

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

> Last updated: 2026-07-23 17:00 WIB

**⚠ ESPN enrichment bottleneck — hourly cron times out** (active since 2026-07-23)
- ESPN API works correctly with league-qualified paths (e.g. `soccer/eng.1/scoreboard`) — returns 200 with live events.
- The previous "HTTP 404 from ESPN" diagnosis was incorrect — curl was using `football/scoreboard` without a league qualifier (path doesn't exist on ESPN's API). Verified via manual curl + Python urllib: all 15 league paths return 200 OK with events.
- **Real issue:** The enrichment phase (`multi_source_research()`) processes each fixture through 5 research sources (SearXNG general, Twitter, Reddit, YouTube, advanced stats) — ~3 minutes per date for 120 events. The hourly refresh script had a 60s timeout, causing silent timeouts.
- **Fix applied:** Hourly refresh script `sports_v32_hourly_refresh.py` updated with 300s timeout. Only `--sport football --sport basketball --sport tennis` filters (no enrich), so re-runs are fast (~3 min for all dates). Manual full ingestion WITH enrich still works (takes ~3 min per date).
- **Root cause of stale data:** Not ESPN failure — most football leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1) are in OFF-SEASON until August. Basketball/NBA also off-season. Only MLS, Leagues Cup, and some friendlies have July matches.

**⚠ TheSportsDB fallback active for football** (mitigation deployed 2026-07-23)
- Fallback adapter for TheSportsDB (free, no API key) added to `sports_v31_espn_ingest.py` — activates when ESPN football endpoints return 0 events despite successful API reach.
- Covers: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, UEFA Champions League, UEFA Europa League, MLS, Liga 1 Indonesia.
- **Limitation:** TheSportsDB `eventsnextleague.php` returns ~15 next events per league (not date-range), so coverage is limited to near-term fixtures.
- Next step: Implement date-range-capable fallback providers (see next section).

**⚠ DB contains stale data (last entry: 2026-07-22)** (active since 2026-07-23)
- Database `matches` table: date range `2026-06-30` to `2026-07-24`, 120 rows added for Jul 24 after fresh ingestion (2026-07-23 16:30 WIB).
- Historical data (924+ matches, 1332+ predictions) is intact.
- Root cause: engine was paused Jul 21 + ESPN off-season + hourly script timeout. Resolved incrementally.

**Coverage gaps — No adapters for MMA, Boxing, Baseball** (documented P3 gap)
- ESPN does not cover these sports. A multi-provider chain (per the spec handbook) would be needed.

---

## Known Issues Resolved

| Issue | Date Resolved | Root Cause + Fix |
|-------|---------------|-----------------|
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
