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
| Backend | FastAPI (Python 3.13) + SQLAlchemy + PostgreSQL |
| Reverse proxy / serving | Python `serve -s` (8101) + uvicorn (8100) |
| Infra | Proxmox LXC 108 |

---

## Architecture

### Frontend (`/frontend/src`)
```
App.tsx                       — root: routes PIN → dashboard ↔ settings
lib/api.ts                    — ApiClient (fetch-based, auth cookie jar)
lib/ThemeProvider.tsx         — dark/light toggle, localStorage persistence
lib/groupMatches.ts           — groupMatchesBySport() utility
features/auth/
  PinLogin.tsx               — 6-digit PIN gate
  Settings.tsx               — change PIN panel + theme toggle
features/matches/
  SportFilterBar.tsx         — dynamic sport pills with counts
  KpiRow.tsx                 — 4 metric cards (evaluated/strict/lenient/excluded)
  MatchGrid.tsx              — auto-fit CSS grid grouped by sport
  MatchCard.tsx              — compact card with color+icon+text badge + expand/collapse
```

### Backend (`/backend/app`)
```
main.py                       — FastAPI app, all routes, CORS config
core/
  security.py                 — hash_pin(), verify_pin() (Argon2id)
  sessions.py                — in-memory SessionStore (UUID → user_id)
  rate_limit.py              — sliding-window rate limiter
  settings.py                — pydantic Settings (env file + CLI overrides)
models/                       — SQLAlchemy models (Match, Prediction, PredictionResult)
schemas/                      — Pydantic request/response schemas
services/ingestion.py         — scheduled match data ingestion
workers/ingest.py            — APScheduler job (every 2 min)
```

### Database
- **Host**: PostgreSQL on LXC 108, TCP `127.0.0.1:5432`
- **Database**: `sport_prediction`
- **Auth**: `scram-sha-256` (TCP) for `sportapp@127.0.0.1`
- **Tables**: `matches`, `predictions`, `prediction_results`

---

## Authentication

- PIN-based login: `POST /auth/pin` with `{"pin":"123456"}`
- Session cookie: `sport_session` (HttpOnly, SameSite=lax, 1-hour Max-Age)
- PIN stored as **Argon2id** hash (never plaintext)
- All `/_management/` and `/_metrics/` routes require authenticated session

### Changing the PIN
- Authenticated endpoint: `PATCH /auth/pin` with `{"current_pin","new_pin"}`
- `new_pin` must be exactly 6 ASCII digits
- On success: updates `app.state.pin_hash` in all running uvicorn workers; optionally writes new hash to `/etc/sport-prediction/app.env`
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
VITE_API_BASE_URL=http://10.10.10.83:8100/api npm run build
# output: dist/
```

### Sync to LXC
```bash
# 1. Tar and copy to Proxmox host
tar -C frontend/dist -cvf - . | ssh proxmox 'pct exec 108 -- tar -C /opt/sport-prediction/releases/<ts>/frontend/ -xf -'
```

### Start/stop via systemd (REQUIRED)
```bash
# inside LXC 108 — ALWAYS use systemd, NEVER manual processes:
systemctl start sport-prediction-backend
systemctl start sport-prediction-frontend
systemctl restart sport-prediction-backend
systemctl restart sport-prediction-frontend
systemctl status sport-prediction-backend sport-prediction-frontend
```

> **⚠️ PENTING**: Selalu gunakan `systemctl` untuk start/restart. JANGAN PERNAH menjalankan `nohup uvicorn ...` atau `nohup python3 -m http.server` atau `nohup serve ...` manual — proses manual tidak akan di-restart oleh systemd saat crash dan tidak ter-track.

---

## Systemd Units (LXC 108)

| Unit | Port | Purpose |
|---|---|---|
| `sport-prediction-backend.service` | 8100 | **Production API** (uvicorn) |
| `sport-prediction-frontend.service` | 8101 | **Production static frontend** (serve -s) |

Both units are `enabled` — they start automatically on boot.

---

## Configuration

| Key | Location | Description |
|---|---|---|
| `SPORT_PREDICTION_PIN_HASH` | `/etc/sport-prediction/app.env` | Argon2id PIN hash |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `/etc/sport-prediction/app.env` | PostgreSQL connection |
| `SECURE_COOKIES`, `session_ttl_seconds` | `/etc/sport-prediction/app.env` | Session config |

> **⚠️ DATABASE AUTHENTICATION**: Koneksi database menggunakan `scram-sha-256` dengan password. JANGAN PERNAH menambahkan rule `trust` di `pg_hba.conf` untuk mengatasi masalah koneksi — jika backend gagal konek ke PostgreSQL, kemungkinan besar `/etc/sport-prediction/app.env` tidak bisa dibaca oleh proses `sportapp`. Cek: `ls -la /etc/sport-prediction/app.env` harus `sportapp:sportapp 600`. Jika permission salah: `chown sportapp:sportapp /etc/sport-prediction/app.env && chmod 600 /etc/sport-prediction/app.env`.

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
# 25 tests: groupMatches, ThemeProvider, validation, api
```

---

## Maintenance Warnings

1. **JANGAN use nohup/manual processes** — selalu `systemctl restart sport-prediction-backend` / `sport-prediction-frontend`
2. **JANGAN add `trust` auth in pg_hba.conf** — jika DB auth gagal, perbaiki permission `app.env` (`sportapp:sportapp 600`), bukan melemahkan PostgreSQL auth
3. **PIN plaintext tidak pernah disimpan** — hanya hash Argon2id di `app.env`
