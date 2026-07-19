# Sport Prediction Web App Architecture

## Scope

This document describes the new Software Engineering profile application. The existing Sports profile engine and cron jobs remain unchanged and continue to write the legacy JSON/JSONL artifacts.

## Runtime boundary

```text
Legacy Sports engine
  -> /Users/beem/.hermes-shared/reports/sports/v3/{schedules,predictions,state,audit}
  -> read-only ingestion service
  -> PostgreSQL sport_prediction
  -> FastAPI API
  -> React dashboard
```

The backend will listen on `127.0.0.1:8100`. Caddy will provide the external homelab listener on port `8080`.

## PostgreSQL schema

### `matches`

Canonical fixture identity and schedule metadata. `match_id` is the stable legacy event identifier. `source_metadata` and `raw_document` preserve source-specific fields and the original normalized document.

Important indexes: `(date_wib, sport)`, `kickoff_wib`, and unique `match_id`.

### `predictions`

One current/source-derived prediction row per source record. Stores outcome, score/result, confidence, confidence breakdown, risk, NO_PICK state, degraded-source state, eligibility, accuracy exclusion, evidence, and raw JSON. `source_record_id` is unique for ingestion idempotency.

### `prediction_results`

Actual result and validation projection. `outcome_correct` and `score_correct` are nullable because an unvalidated or backfilled record is not the same as false. `accuracy_excluded` preserves the legacy denominator behavior.

### `ingestion_audit`

Append-only ingestion attempt record. `idempotency_key` is unique and must be derived from source file identity, source hash/version, document type, and logical date/event scope. Errors are recorded and skipped rather than crashing a full scan.

### `auth_sessions`

Server-side opaque session records. Store only a hash of the random browser token. Tracks client key, failed attempts, temporary lockout, idle/absolute expiry, and revocation.

### `accuracy_metrics` view

Aggregates evaluated, correct, and percentage accuracy by sport/date. It excludes rows with null validation and rows marked `accuracy_excluded`.

## Migration policy

- The initial migration is `20260719_0001`.
- The legacy engine is not imported as a runtime dependency of the API.
- The migration must run using `/etc/sport-prediction/app.env` in LXC 108 or an explicitly provided `SPORT_PREDICTION_DATABASE_URL`; credentials are never committed.
- Schema changes require a new Alembic revision and a rollback plan.
- The first ingestion release must test the migration against sample JSON before enabling a periodic job.
