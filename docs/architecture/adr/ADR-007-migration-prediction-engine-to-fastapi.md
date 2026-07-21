# ADR-007 — Migrasi Prediction Engine dari Python Scripts ke FastAPI Backend

**Date:** 2026-07-21 | **Status:** Proposed | **Scope:** Sport Prediction — Backend + Engine Migration

---

## Context

Sistem prediksi olahraga saat ini terdiri dari dua komponen terpisah:

1. **Legacy Engine** (`sports_v3_engine.py` + `sports_v31_espn_ingest.py` + `sports_v31_searxng_scanner.py` + skill cron) — Python stdlib scripts yang berjalan di bawah Hermes/Sports profile, 24/7 via 6 cron jobs. Menulis JSON artifacts ke `/Users/beem/.hermes-shared/reports/sports/v3/`. Trigger: fixed-time systemd timer untuk scan/prematch/result/EOD; polling setiap 5 menit untuk prematch watcher dan result watcher.

2. **Web App Backend** (FastAPI + PostgreSQL) — hanya consumer read-only dari legacy engine. Engine menulis JSON → ingestion service baca → PostgreSQL → API → Frontend.

User telah menyetujui arsitektur baru di mana backend FastAPI menjadi **produsen penuh** logika prediksi, menggantikan peran legacy engine. Enam stage pipeline baru:

| # | Stage | Trigger |
|---|---|---|
| 1 | Discovery | 00:00 WIB, sliding window 24 jam |
| 2 | Matrix Analysis | T-2 jam sebelum kickoff |
| 3 | Prediction Generation | Langsung setelah Stage 2 |
| 4 | Result + Win Reasoning | T+15 menit setelah match selesai |
| 5 | Validation | Bersamaan Stage 4 |
| 6 | Nightly Evaluation | 22:00 WIB (fixed) |

---

## Decision

### 1. Cutover Langsung (Bukan Shadow/Parallel Mode)

Setelah backend baru siap dan divalidasi terhadap data real selama ≥7 hari, engine lama dimatikan dan backend baru diaktifkan penuh.

**Alasan user memilih ini:**
- Tidak mau maintain dua sistem paralel yang conceptually duplicated
- Shadow mode menambah kompleksitas operasional tanpa benefit yang jelas untuk use case personal/non-production
- User menerima risiko yang知情 (lihat Consequences)

### 2. Backend Menjadi Owner Penuh Pipeline Prediksi

- Backend FastAPI di LXC 108 (`10.10.10.83:8100`) menjalankan semua 6 stage
- Tidak ada lagi dual-write: legacy JSON artifacts tidak lagi diperlukan sebagai source of truth
- Ingestion service lama (JSON → PostgreSQL) di-deprecate; data sudah di-database sejak di-generate

### 3. Scheduling dengan systemd timer + Background Worker untuk Relative Triggers

- Stage 1 (Discovery), 3 (Prediction), 6 (Nightly): systemd timer fixed-schedule
- Stage 2 (Matrix Analysis, T-2 jam), Stage 4-5 (Result+Validation, T+15 menit): background worker dengan database polling — polling interval 60 detik
- Mekanisme: setiap backend worker register job di tabel `pipeline_jobs` dengan `target_time`; worker polling memeriksa `WHERE scheduled_time <= NOW() AND status = 'pending'`

### 4. Data Sources yang Diintegrasikan

Semua source data dari engine lama dipindahkan ke backend:

| Source | Engine Lama | Backend Baru |
|---|---|---|
| ESPN API | `sports_v31_espn_ingest.py` — `site.api.espn.com/apis/site/v2/sports/{sport}/scoreboard` | FastAPI service layer |
| SearXNG | `sports_v31_searxng_scanner.py` — `http://10.10.10.5:8888/search` | FastAPI service layer |
| Polymarket | `polymarket.py` — `gamma-api.polymarket.com`, `clob.polymarket.com` | FastAPI service layer |
| MotoGP PulseLive | Built-in di `espn_ingest.py` — `api.motogp.pulselive.com/motogp/v1` | FastAPI service layer |
| EuroLeague API | Built-in di `espn_ingest.py` — `api-live.euroleague.net` | FastAPI service layer |
| FIBA API | Built-in di `espn_ingest.py` — `digital-api.fiba.basketball/hapi` | FastAPI service layer |
| IBL Indonesia | Built-in di `espn_ingest.py` — `iblindonesia.com/games/schedule` | FastAPI service layer |
| Mnemosyne | Lesson learnt storage + retrieval | Backend DB (tabel baru) |
| Discord/Email | `sports_v3_engine.py` — Himalaya CLI + Hermes send | FastAPI notifications |

### 5. Confidence Framework — Bobot per Sport

Canonical source: `sports_v3_engine.py` lines 236-242 + AGENTS.md Sports Profile.

```
FOOTBALL:  form=25%, h2h=15%, player_condition=20%, home_away=15%, market_odds=15%, contextual=10%
TENNIS:    form=20%, h2h=20%, player_condition=25%, home_away=15%, market_odds=10%, contextual=10%
MOTORSPORT:form=15%, h2h=10%, player_condition=20%, home_away=20%, market_odds=20%, contextual=15%
BASKETBALL:form=25%, h2h=15%, player_condition=20%, home_away=15%, market_odds=15%, contextual=10%
NFL:       form=20%, h2h=15%, player_condition=20%, home_away=15%, market_odds=15%, contextual=15%
```

Confidence < 40% → NO_PICK (tidak dipaksa prediksi). Confidence penalty -15 jika DATA_SOURCE_DEGRADED.

### 6. Validation Thresholds per Sport

Canonical source: `sports_v3_engine.py` lines 385-415 + AGENTS.md.

```
FOOTBALL:  BENAR = delta_score <= 1; SEBAGIAN = winner correct but delta > 1
TENNIS:    BENAR = delta_sets <= 1; SEBAGIAN = winner correct but delta_sets > 1
MOTORSPORT: BENAR = predicted in top 3; SEBAGIAN = predicted wins but finishes P2-P3
BASKETBALL: BENAR = delta_score <= 8; SEBAGIAN = winner correct but delta > 8
NFL:       BENAR = delta_score <= 7; SEBAGIAN = winner correct but delta > 7
```

### 7. Safeguards yang Dipertahankan

- **3-bucket UTC scan** — Discovery scan jam 00:00 WIB dengan sliding window -6h hingga +24h UTC untuk mencegah match dini hari WIB terlewat
- **NO_PICK < 40%** — tidak dipaksa prediksi
- **Idempotency guard** — notifikasi tidak double-send: tiap event punya `notif_idempotency_key`
- **"Never fabricate"** — tool gagal = bilang gagal, jangan mengarang
- **Backfill queue** — match telat ditemukan masuk queue, expires saat kickoff
- **ok_zero_events** — liga off-season bukan error, tulis `NO_EVENT` record
- **DATA_SOURCE_DEGRADED** — kalau ESPN/SearXNG gagal, cascade ke fallback sources, apply -15 penalty

---

## Consequences

### Positive

- Single source of truth untuk prediksi (database, bukan filesystem + database)
- Backend API bisa serving both prediction pipeline AND dashboard reads
- Eliminated filesystem coupling — tidak ada lagi path `/Users/beem/.hermes-shared/reports/sports/v3/`
- Scheduling lebih可控 (systemd timer + worker vs cron + scripts)
- Stage 4 baru "win_reasoning" (narasi kenapa tim menang) bisa disimpan secara terstruktur
- Nightly calibration loop (Stage 6) langsung update weights tanpa perlu separate cron job

### Negative / Risks

**Risiko #1 — Cutover Langsung (User-Accepted Risk)**

Tanpa shadow mode, tidak ada "verification against current system" sebelum switch. Jika ada bug di backend baru, prediksi hari itu akan missed. Mitigasi: validasi minimum 7 hari data real sebelum cutover.

**Risiko #2 — Rewriting Stable Logic**

Confidence framework, validation thresholds, dan safeguards sudah stabil di engine lama. Porting ke FastAPI mungkin introducing subtle behavioral differences. Mitigasi: test output persis sama antara engine lama vs backend baru untuk sample data.

**Risiko #3 — LXC 108 Resource**

Backend baru di LXC 108 akan polling database setiap 60 detik (untuk Stage 2/4 relative triggers). Load tambahan: CPU negligible, DB connections perlu di-tune (connection pool). Mitigasi: max 5 concurrent stage workers, connection pool size 10.

**Risiko #4 — Loss of "Never Fabricate" Guarantee**

Engine lama punya explicit guard di multiple scripts. Backend baru harus implementasi ulang di semua stage. Mitigasi: setiap service layer call yang gagal harus raise exception, tidak return fake data.

**Risiko #5 — Notification Dedupe Gap**

Engine lama menggunakan audit log + idempotency marker files. Backend baru pakai database `notification_audit` table.迁移: ada window kecil di mana notifikasi bisa double-send selama migrasi. Mitigasi: stop engine lama DAN flush pending notifikasi sebelum activate backend.

---

## Alternatives Considered

### A. Shadow Mode (Parallel Run)

Jalankan backend baru di samping engine lama, bandingkan output, switch setelah akurasi backend ≥ engine.

Rejected by user. Shadow mode menambah 2x operational complexity dan membiarkan masalah duplikasi logic tidak terselesaikan.

### B. Gradual Sport-by-Sport Migration

Migrate satu sport pada satu waktu (football dulu, lalu tennis, dll).

Rejected. Pipeline 6-stage shared di semua sport; memisahkan per-sport menambah complexity sinkronisasi tanpa benefit.

### C. Tetap di Cron + Extract Library

Extract engine Python jadi library, panggil dari FastAPI route.

Deferred. Ini bisa jadi step setelah M8 (cutover) jika user mau pisahkan logic dari API layer di kemudian hari. Untuk phase ini, logic di-maintain langsung di FastAPI service layer.

### D. gRPC atau Message Queue (RabbitMQ/Kafka)

Gunakan message queue untuk komunikasi antar stage.

Rejected. Overkill untuk skala ini (puluhan-ratusan match/hari). Database polling + simple worker sudah cukup robust dan lebih debuggable.

---

## Rollback Plan

Jika backend baru gagal setelah cutover:

1. **Immediate**: Stop stage workers + disable systemd timers backend
2. **Restore**: Aktifkan kembali engine lama cron jobs (mesin lama masih ada di `/Users/beem/.hermes-shared/scripts/sports_v3_engine.py` dst.)
3. **Resume ingestion**: Re-enable ingestion service JSON → PostgreSQL
4. Backend code tidak di-delete — taruh di branch `rollback-candidate-{date}`

---

## Migration Phases (Summary)

| Phase | Scope | Estimasi |
|---|---|---|
| M1 | Stage 1 — Discovery (port ESPN scan) | Medium |
| M2 | Stage 2 — Matrix Analysis (port data sources) | High |
| M3 | Stage 3 — Prediction Generation (port confidence framework) | Medium |
| M4 | Stage 4-5 — Result + Win Reasoning + Validation | Medium |
| M5 | Notification (Discord + email) | Low |
| M6 | Stage 6 — Nightly Evaluation + ML loop | Medium |
| M7 | Testing terhadap data real ≥7 hari | Medium |
| M8 | Cutover — matikan engine lama, activate backend | High |

Lihat ADR-009 untuk detail scheduling architecture, ADR-008 untuk schema database.
