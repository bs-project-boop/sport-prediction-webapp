# Sport Intelligence

Prediction desk for football, basketball, tennis, motorsport, and NFL — covering FIFA World Cup, IBL, MotoGP, FIBA, Grand Slam, and more.

## Access URLs

| Service | URL | Notes |
|---------|-----|-------|
| LAN — Frontend (static) | http://10.10.10.83:8101 | `serve -s` static build |
| LAN — Backend (API + SPA) | http://10.10.10.83:8100 | FastAPI + React SPA served together |
| **External (Cloudflare Tunnel)** | https://sports.bintangsofyan.com/ | Routes to backend port 8100 |

- API docs: http://10.10.10.83:8100/docs
- PIN: 6-digit, ask the operator

---

## Architecture

```
Browser (LAN / Cloudflare Tunnel)
        │
        ▼
┌──────────────────────────────────────┐
│  LXC 108 (Proxmox, 10.10.10.83)     │
│                                      │
│  ┌──────────────────────────────┐    │
│  │ sport-prediction-backend     │    │
│  │ FastAPI / uvicorn :8100      │    │
│  │ Serves: API + React SPA       │    │
│  │ Serves: /assets/* static     │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ sport-prediction-frontend    │    │
│  │ serve -s dist :8101          │    │
│  │ (LAN static-only)            │    │
│  └──────────────────────────────┘    │
│         │                  │         │
│         ▼                  ▼         │
│  ┌─────────────┐  ┌─────────────────┐ │
│  │ PostgreSQL  │  │ sport_prediction │ │
│  │ 127.0.0.1   │  │ 924 matches     │ │
│  │ :5432       │  │ 1332 predictions│ │
│  └─────────────┘  └─────────────────┘ │
└──────────────────────────────────────┘
        │
        │ Cloudflare Tunnel (LXC 104 → host systemd)
        ▼
  sports.bintangsofyan.com (HTTPS)
```

### Ports

| Port | Service | Purpose |
|------|---------|---------|
| 8100 | `sport-prediction-backend` | FastAPI — API + embedded SPA for external access |
| 8101 | `sport-prediction-frontend` | `serve -s dist` — static build, LAN access only |

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | React 19 + TypeScript + Vite + TanStack Query |
| Backend | FastAPI (Python 3.13) + SQLAlchemy + Pydantic |
| Database | PostgreSQL (`sport_prediction`) |
| Auth | PIN + Argon2id hash + HttpOnly session cookie |
| Serving | `uvicorn` (8100) + `serve -s` (8101) |
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
| Match listing + filtering | ✅ Active | Sport pills, date range, search |
| Prediction cards | ✅ Active | BENAR/SEBAGIAN_BENAR/SALAH badges, confidence breakdown |
| Accuracy metrics (KPI row) | ✅ Active | Strict & lenient accuracy % |
| Auto-date range (last 3 days) | ✅ Active | Defaults to today ± 1 day WIB |
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
# Update symlink
ssh proxmox "pct exec 108 -- ln -sfn /opt/sport-prediction/releases/${RELEASE_TS} /opt/sport-prediction/current"
```

### 3. Restart services (REQUIRED — always use systemd)

```bash
ssh proxmox "pct exec 108 -- systemctl restart sport-prediction-backend"
ssh proxmox "pct exec 108 -- systemctl restart sport-prediction-frontend"
```

### 4. Verify

```bash
# Backend health
curl http://10.10.10.83:8100/health/

# Frontend bundle check
curl -s http://10.10.10.83:8101/ | grep 'index-.*\.js'

# Login
curl -s -X POST http://10.10.10.83:8100/auth/pin \
  -H "Content-Type: application/json" \
  -d '{"pin":"123456"}'
```

> **⚠️ NEVER use `nohup`, `&`, or manual `uvicorn`/`python -m http.server`** — systemd is the only way to ensure processes restart after crashes.

---

## Systemd Units

Both units are `enabled` (start on boot):

| Unit | WorkingDirectory | ExecStart |
|------|----------------|-----------|
| `sport-prediction-backend.service` | `/opt/sport-prediction/current/backend` | `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100` |
| `sport-prediction-frontend.service` | `/opt/sport-prediction/current/frontend` | `/usr/local/bin/serve -s . -l 8101` |

---

## Environment Configuration

Config file: `/etc/sport-prediction/app.env` (owned by `sportapp:sportapp`, mode `600`)

| Variable | Description |
|----------|-------------|
| `SPORT_PREDICTION_PIN_HASH` | Argon2id hash of current PIN |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection |
| `SECURE_COOKIES` | Set `false` for HTTP-only access; `true` (default) requires HTTPS |

---

## Facing Issues

> Last updated: 2026-07-23

- **Dashboard shows 0 matches in browser** — Default date filter `from=today-1, to=today+1` (WIB timezone) does not capture historical matches (FIFA World Cup 2026, IBL, MotoGP are all in the past). The `/matches?from=...&to=...` query returns empty even though 924 matches exist in the database. Fix in progress: extend default date range or adjust filter behavior.

- **`secure_cookies=True` hardcoded as default** — FastAPI backend has `secure_cookies: bool = True` hardcoded in `main.py:59` with no environment variable override. This prevents session cookies from being stored when accessing via HTTP (LAN). Currently works around it because `secure_cookies=False` is implicitly used when `SPORT_PREDICTION_SECURE_COOKIES` env var is not set, but the code needs a proper env-var-driven setting.

---

## Known Issues Resolved

| Issue | Date Resolved | Notes |
|-------|---------------|-------|
| Port 8101 served old bundle (`index-CokD2ddX.js` instead of `index-BSsGzJEe.js`) causing PIN to fail on LAN access | 2026-07-23 | `sport-prediction-frontend` service had not been restarted after `current` symlink was updated to release `20260722052000`. Fixed by running `systemctl restart sport-prediction-frontend`. Lesson: always restart services after updating the `current` symlink. |
| `/api/auth/pin` 405 on Cloudflare Tunnel | 2026-07-22 | Frontend bundle had `VITE_API_BASE_URL=/api` baked in, causing API calls to go to `/api/auth/pin` (FastAPI returns 405 on that route). Fixed by removing `VITE_API_BASE_URL` from `.env.production`, letting the bundle use relative URLs. |
| Cache busting — old JS bundle served after deploy | 2026-07-22 | Cloudflare was caching `index-*.js` assets indefinitely. Fixed by adding Cache Rule to bypass cache on root `/` and setting `Cache-Control: no-cache` on `index.html` via FastAPI response header. |
| `sport_prediction` database not found | 2026-07-22 | Database name uses underscores (`sport_prediction`), not dashes. Correct `DATABASE_URL` in env. |
| Caddy reverse proxy rejected by user | 2026-07-21 | User explicitly does not want Caddy. Architecture switched to Cloudflare Tunnel only with FastAPI serving SPA directly. |
