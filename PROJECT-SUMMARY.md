# Sport Prediction — Project Summary

## URLs

| Service | URL |
|---|---|
| **Frontend** (static) | http://10.10.10.83:8101 |
| **Backend API** | http://10.10.10.83:8100 |
| **API docs** | http://10.10.10.83:8100/docs |
| **LXC container** | ID 108 (Proxmox host: `proxmox`) |

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + TypeScript + Vite + TanStack Query + React Router v6 |
| Backend | FastAPI (Python 3.11) + SQLAlchemy + PostgreSQL |
| Reverse proxy / serving | Python `http.server` (8101) + uvicorn (8100) |
| Infra | Proxmox LXC 108 |

---

## Architecture

### Frontend (`/frontend/src`)
```
App.tsx                 — root: routes PIN → dashboard ↔ settings
lib/api.ts              — ApiClient (fetch-based, auth cookie jar)
features/auth/
  PinLogin.tsx          — 6-digit PIN gate
  Settings.tsx          — change PIN panel
  pin.ts / pin.test.ts  — pure validation helpers
features/matches/       — match list + prediction form
features/metrics/       — accuracy metrics dashboard
```

### Backend (`/backend/app`)
```
main.py                 — FastAPI app, all routes, CORS config
core/
  security.py           — hash_pin(), verify_pin() (PBKDF2-SHA256)
  sessions.py           — in-memory SessionStore (UUID → user_id)
  rate_limit.py         — sliding-window rate limiter
  settings.py           — pydantic Settings (env file + CLI overrides)
models/                 — SQLAlchemy models (Match, Prediction, PredictionResult)
schemas/                 — Pydantic request/response schemas
services/ingestion.py   — scheduled match data ingestion
workers/ingest.py       — APScheduler job (every 2 min)
```

### Database
- **Host**: PostgreSQL on LXC (mapped to `/var/run/postgresql` inside container)
- **Database**: `sport_prediction`
- **Tables**: `matches`, `predictions`, `prediction_results`

---

## Authentication

- PIN-based login: `POST /auth/pin` with `{"pin":"123456"}`
- Session cookie: `sport_session` (HttpOnly, SameSite=lax, 1-hour Max-Age)
- PIN stored as PBKDF2-SHA256 hash in `app.state.pin_hash` (in-memory) + optionally persisted to `/etc/sport-prediction/app.env`
- All `/_management/` and `/_metrics/` routes require authenticated session

### Changing the PIN
- Authenticated endpoint: `PATCH /auth/pin` with `{"current_pin","new_pin"}`
- `new_pin` must be exactly 6 ASCII digits
- On success: updates `app.state.pin_hash` in all running uvicorn workers; optionally writes new hash to `/etc/sport-prediction/app.env` (skipped if file does not exist)
- Returns `{"pin_changed":true}`

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/pin` | No | Login with PIN; sets session cookie |
| POST | `/auth/logout` | Yes | Clear session cookie |
| PATCH | `/auth/pin` | Yes | Change PIN (6 digits) |
| GET | `/matches/` | Yes | List all matches |
| POST | `/matches/` | Yes | Create a match |
| POST | `/matches/{id}/predict` | Yes | Submit prediction |
| GET | `/_metrics/` | Yes | Accuracy + session stats |
| GET | `/health/` | No | Basic health check |
| GET | `/docs` | No | Swagger UI |

---

## Deployment

### Frontend build
```bash
cd frontend
VITE_API_BASE_URL=http://10.10.10.83:8100 npm run build
# output: dist/
```

### Sync to LXC
```bash
# 1. Tar and copy to Proxmox host
tar -C frontend -cvf /tmp/sport-dist.tar dist/
scp /tmp/sport-dist.tar proxmox:/tmp/

# 2. Push into LXC, extract, serve
# (use pct push / script — see start_frontend.sh)
```

### Start/stop frontend
```bash
# inside LXC 108:
pkill -f "http.server 8101"
cd /var/www/sport-prediction
python3 -m http.server 8101 >> /var/log/frontend.log 2>&1 &
```

### Reload backend (no downtime)
```bash
# Backend runs under systemd/svcctl; to reload:
pct exec 108 -- sv reload sport-prediction
# Or restart:
pct exec 108 -- svc -t /service/sport-prediction
```

---

## Known Processes (LXC 108)

| Port | Process | Purpose |
|---|---|---|
| 3000 | Node (dev server) | Old dev frontend (not used for prod) |
| 8000 | uvicorn (test) | Test/dev API instance |
| 8100 | uvicorn (sportapp) | **Production API** |
| 8101 | Python http.server | **Production static frontend** |

---

## Configuration

| Key | Location | Description |
|---|---|---|
| `SPORT_PREDICTION_PIN_HASH` | `app.state.pin_hash` (runtime) | Current PIN hash |
| `ALLOWED_ORIGINS` | `main.py DEFAULT_ALLOWED_ORIGINS` | CORS-allowed origins |
| `DATABASE_URL` | `postgresql+psycopg2:///sport_prediction` | DB connection |
| Env file | `/etc/sport-prediction/app.env` | Persistent PIN hash storage |

---

## Tests

```bash
# Backend
cd backend
python -m pytest -v
# 39 tests: auth, matches, predictions, metrics, ingestion, change PIN

# Frontend
cd frontend
npx vitest run
# 10 tests: pin validation + helpers
```
