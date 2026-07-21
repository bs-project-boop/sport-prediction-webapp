# ADR-008 — Schema Data untuk Matrix Analysis, Win Reasoning, dan Calibration History

**Date:** 2026-07-21 | **Status:** Proposed | **Scope:** Sport Prediction Backend — Database Schema

---

## Context

ADR-007 memutuskan bahwa backend FastAPI menjadi owner penuh pipeline prediksi. Schema database yang ada (`matches`, `predictions`, `prediction_results`) didesain untuk ingest dari legacy JSON engine. Sekarang backend akan **menghasilkan** data ini sendiri, plus kolom/tabel baru untuk:

1. **Matrix Analysis** — evidence terstruktur per match (player status, injury, strategy, dll) dari Stage 2
2. **Win Reasoning** — narasi kenapa tim itu menang, field baru sesuai request user
3. **Calibration History** — hasil evaluasi nightly + weight adjustment tracking

Kebutuhan tambahan:
- Pemisahan jelas antara data mentah (evidence/matrix) vs data hasil olahan (reasoning/prediction)
- Schema harus bisa di-query untuk analytics (bukan JSONB tanpa index)
- Migration plan dari schema lama (backward-compatible ADD COLUMN, bukan DROP)

---

## Decision

### Tabel Baru: `matrix_analysis`

Menyimpan evidence per match dari Stage 2 (Matrix Analysis). Data ini adalah input/raw untuk Stage 3 (Prediction Generation).

```sql
CREATE TABLE matrix_analysis (
    id              BIGSERIAL PRIMARY KEY,
    match_id        TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    sport           TEXT NOT NULL,
    
    -- Player/team condition
    home_injuries   JSONB NOT NULL DEFAULT '[]',     -- [{player, injury, severity, returned}]
    away_injuries   JSONB NOT NULL DEFAULT '[]',
    home_suspensions JSONB NOT NULL DEFAULT '[]',
    away_suspensions JSONB NOT NULL DEFAULT '[]',
    lineup_notes    JSONB NOT NULL DEFAULT '[]',      -- [{team, player, role, note}]
    
    -- Form
    home_form_last5 JSONB NOT NULL DEFAULT '[]',      -- ['W','W','D','L','W']
    away_form_last5 JSONB NOT NULL DEFAULT '[]',
    
    -- H2H
    h2h_results     JSONB NOT NULL DEFAULT '[]',     -- [{date, home_score, away_score, competition}]
    
    -- Strategy/Tactics
    tactical_notes  JSONB NOT NULL DEFAULT '[]',     -- [{team, formation, key_tactic}]
    motivational    TEXT,                            -- notes on motivation/importance
    
    -- Contextual
    venue_weather   JSONB,                          -- {temperature, condition, impact_note}
    schedule_fatigue JSONB,                          -- {team, matches_in_7d, travel_km}
    
    -- Market/Odds
    market_odds     JSONB,                           -- {home_win, draw, away_win, source, timestamp}
    polymarket_data JSONB,                           -- {question, yes_price, no_price, volume}
    
    -- Composite quality signal
    evidence_quality_score   INTEGER,                -- 0-100, computed from source_count+recency
    sources_used     TEXT[] NOT NULL DEFAULT '{}',    -- ['ESPN','SearXNG','Polymarket']
    data_source_degraded BOOLEAN NOT NULL DEFAULT FALSE,
    research_completed_at TIMESTAMPTZ,
    
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(match_id)
);

CREATE INDEX ix_matrix_analysis_match_id ON matrix_analysis(match_id);
CREATE INDEX ix_matrix_analysis_sport ON matrix_analysis(sport);
CREATE INDEX ix_matrix_analysis_data_source_degraded ON matrix_analysis(data_source_degraded);
```

### Tabel Baru: `win_reasoning`

Menyimpan narasi kenapa tim itu menang. Ditulis di Stage 4 (Result + Win Reasoning), berbeda dari `reasoning` di `predictions` yang ditulis sebelum match.

```sql
CREATE TABLE win_reasoning (
    id              BIGSERIAL PRIMARY KEY,
    match_id        TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    
    winner          TEXT NOT NULL,                   -- team/player yang menang
    winning_factors JSONB NOT NULL DEFAULT '[]',    -- [{factor, description, weight}]
    losing_factors  JSONB NOT NULL DEFAULT '[]',    -- [{factor, description, weight}]
    
    narrative       TEXT NOT NULL,                   -- prose: "Team X dominated because..."
    key_moment      TEXT,                            -- single most important moment
    tactical_winner TEXT,                            -- 'home' | 'away' | 'neutral'
    
    -- For learning
    factors_missed_by_prediction JSONB DEFAULT '[]', -- factors that predicted model didn't weight enough
    pattern_tags    TEXT[] DEFAULT '{}',
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(match_id)
);

CREATE INDEX ix_win_reasoning_match_id ON win_reasoning(match_id);
CREATE INDEX ix_win_reasoning_pattern_tags ON win_reasoning USING GIN(pattern_tags);
```

### Tabel Baru: `calibration_history`

Hasil evaluasi nightly (Stage 6). Setiap baris = satu evaluasi run.

```sql
CREATE TABLE calibration_history (
    id              BIGSERIAL PRIMARY KEY,
    run_at_wib      TIMESTAMPTZ NOT NULL,
    sport           TEXT NOT NULL,
    
    -- Bucket stats
    bucket          TEXT NOT NULL,                   -- 'HIGH'|'MEDIUM'|'LOW'|'COIN_FLIP'
    matches_in_bucket INTEGER NOT NULL DEFAULT 0,
    mean_confidence_pct  NUMERIC(5,2),
    actual_accuracy_pct  NUMERIC(5,2),
    
    -- Calibration error
    calibration_error_pp NUMERIC(5,2),                -- abs(mean_confidence - actual_accuracy)
    direction         TEXT,                          -- 'over_confident' | 'under_confident'
    needs_recalibration BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Suggested adjustment
    suggested_adjustment JSONB,                       -- {factor, delta_weight, direction}
    
    -- Full distribution (optional, for deep analysis)
    bucket_distribution JSONB,                       -- full per-bucket breakdown
    
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_calibration_history_sport ON calibration_history(sport);
CREATE INDEX ix_calibration_history_run_at ON calibration_history(run_at_wib);
CREATE INDEX ix_calibration_history_needs_recal ON calibration_history(sport) WHERE needs_recalibration = TRUE;
```

### Tabel Baru: `weight_adjustments`

Approved weight adjustments yang sudah applied ke confidence framework.

```sql
CREATE TABLE weight_adjustments (
    id              BIGSERIAL PRIMARY KEY,
    sport           TEXT NOT NULL,
    factor          TEXT NOT NULL,                   -- 'form'|'h2h'|'player_condition'|etc.
    delta_weight    NUMERIC(4,3) NOT NULL,          -- e.g., 0.05
    direction       TEXT NOT NULL,                   -- 'increase'|'decrease'
    
    -- Provenance
    triggered_by    TEXT NOT NULL,                   -- 'pattern_tag'|'calibration_suggestion'|'manual'
    trigger_detail  JSONB,                           -- {pattern_tag, count_14d} or {calibration_error}
    approved_at     TIMESTAMPTZ,
    approved_by     TEXT,                            -- 'system'|'user:{user_id}'
    
    status          TEXT NOT NULL DEFAULT 'applied', -- 'applied'|'pending_approval'|'rejected'|'rolled_back'
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at      TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,                     -- NULL = permanent, else auto-expire
    
    UNIQUE(sport, factor, status) WHERE status = 'applied'
);

CREATE INDEX ix_weight_adjustments_sport ON weight_adjustments(sport);
CREATE INDEX ix_weight_adjustments_status ON weight_adjustments(status);
```

### Tabel Baru: `pipeline_jobs`

Track scheduled jobs untuk relative-trigger stages (Stage 2, 4-5). Workers polling tabel ini.

```sql
CREATE TABLE pipeline_jobs (
    id              BIGSERIAL PRIMARY KEY,
    job_id          TEXT NOT NULL UNIQUE,            -- e.g., 'stage2:{match_id}'
    stage           TEXT NOT NULL,                   -- 'stage2'|'stage4'|'stage5'
    match_id        TEXT REFERENCES matches(match_id) ON DELETE SET NULL,
    scheduled_time  TIMESTAMPTZ NOT NULL,             -- T-2h, T+15m, dll
    status          TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'running'|'completed'|'failed'|'cancelled'
    
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    last_attempt_at TIMESTAMPTZ,
    last_error      TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX ix_pipeline_jobs_pending ON pipeline_jobs(scheduled_time) 
    WHERE status = 'pending' AND scheduled_time <= NOW() + INTERVAL '10 minutes';
CREATE INDEX ix_pipeline_jobs_match_id ON pipeline_jobs(match_id);
CREATE INDEX ix_pipeline_jobs_status ON pipeline_jobs(status);
```

### Tabel Baru: `notification_audit`

Idempotency untuk Discord + email notifications. Pengganti file-based idempotency di engine lama.

```sql
CREATE TABLE notification_audit (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    channel         TEXT NOT NULL,                   -- 'discord'|'email'
    match_id        TEXT REFERENCES matches(match_id) ON DELETE SET NULL,
    
    subject         TEXT,                            -- untuk email
    recipient       TEXT,                            -- channel ID atau email address
    status          TEXT NOT NULL,                   -- 'sent'|'deduped'|'failed'
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Untuk debugging
    payload_hash    TEXT,
    error_message    TEXT
);

CREATE INDEX ix_notification_audit_match_id ON notification_audit(match_id);
CREATE INDEX ix_notification_audit_idempotency ON notification_audit(idempotency_key);
```

### Modifikasi Tabel `predictions` (ADD COLUMN — Tidak DROP)

Kolom baru ditambahkan untuk mengakomodasi win_reasoning reference dan matrix data:

```sql
-- Tambahan di predictions
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS matrix_data JSONB;        -- raw evidence blob (snapshot at prediction time)
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS win_reasoning_id BIGINT  -- FK ke win_reasoning.id, di-set setelah stage 4
  REFERENCES win_reasoning(id) ON DELETE SET NULL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS confidence_weights JSONB;  -- actual weights used (can differ from default via adjustments)
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS confidence_model_version TEXT DEFAULT 'v3.2';
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pipeline_stage TEXT;      -- 'stage3' — untuk tracking
```

### Modifikasi Tabel `matches` (ADD COLUMN)

```sql
ALTER TABLE matches ADD COLUMN IF NOT EXISTS competition_level TEXT DEFAULT 'senior';  -- 'senior'|'junior'
ALTER TABLE matches ADD COLUMN IF NOT EXISTS report_label TEXT;                         -- e.g., '[JUNIOR - NO PREDICTION]'
ALTER TABLE matches ADD COLUMN IF NOT EXISTS matrix_analysis_id BIGINT                  -- FK ke matrix_analysis.id
  REFERENCES matrix_analysis(id) ON DELETE SET NULL;
```

---

## Consequences

### Positive

- **Queriable matrix data**: tidak perlu parse JSONB untuk analytics; kolom specific sudah di-extract
- **Separation of concerns**: matrix (input) ≠ prediction (output) ≠ win_reasoning (post-hoc analysis)
- **Audit trail lengkap**: calibration_history + weight_adjustments track semua perubahan model
- **Backward compatible**: semua ADD COLUMN, tidak ada breaking change ke existing API

### Negative / Risks

- **Schema complexity**: 6 tabel baru vs 3 tabel lama. Pastikan ORM models konsisten.
- **Migration complexity**: perlu backfill matrix_analysis untuk match historical — tidak bisa realtime, doable tapi perlu planning
- **JSONB tetap ada**: `matrix_data` di predictions tetap JSONB (dynamic evidence structure), tapi `matrix_analysis` tabel baru menyediakan queryable projection
- **Stale matrix**: `research_completed_at` perlu di-track untuk detect stale evidence (>6 jam sebelum kickoff = warning)

---

## Migration Plan (Tidak Dieksekusi Sekarang — Desain Saja)

**Phase 0 (Pre-M1):**
```sql
-- Run di existing DB (backward compatible, tidak ada breaking change)
ALTER TABLE matches ADD COLUMN IF NOT EXISTS competition_level TEXT DEFAULT 'senior';
ALTER TABLE matches ADD COLUMN IF NOT EXISTS report_label TEXT;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS matrix_analysis_id BIGINT REFERENCES matrix_analysis(id);
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS matrix_data JSONB;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS win_reasoning_id BIGINT REFERENCES win_reasoning(id);
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS confidence_weights JSONB;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS confidence_model_version TEXT DEFAULT 'v3.2';
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pipeline_stage TEXT;
```

**Phase 1 (Setiap stage run):** Backfill matrix_analysis untuk match baru yang belum punya. Bisa background job pelan-pelan.

**Phase 2 (Post-M7, pre-M8):** Backfill win_reasoning dari existing `lesson_json` di state files untuk match historical yang sudah completed.

**Tidak ada DROP kolom lama** — `raw_document` di matches, `raw_document` di predictions tetap ada untuk backward compatibility dengan existing API responses yang sudah ada di frontend.

---

## Alternatives Considered

### A. Semua Matrix Data JSONB di Predictions Saja

Tidak perlu tabel `matrix_analysis` — simpan semua evidence sebagai JSONB di kolom `predictions.matrix_data`.

Rejected. Analytics query (avg injury count, most common tactical note) akan sangat tidak efisien di JSONB. Perlu tabel terpisah untuk query.

### B. document_versioning dengan Satu Tabel Universal

Track semua versi matrix/prediction/reasoning dalam satu tabel `event_data`.

Rejected. Terlalu generic, lose type safety, FK relationships jadi unclear.

### C. Tidak Ada Calibration History Table

Simpan calibration results sebagai JSONB di file terpisah (pattern lama).

Rejected. Schema ini bagian dari goal ADR — user mau visible calibration tracking. Tabel lebih queryable untuk dashboard.
