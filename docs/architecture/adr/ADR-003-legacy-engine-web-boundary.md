# ADR-003 — Keep the Legacy Prediction Engine Outside the Web-App Boundary

**Date:** 2026-07-19 | **Status:** Accepted | **Scope:** Sport Prediction Web App and Sports automation boundary

## Context

The existing deterministic engine and its watcher/ingestion scripts run under the Sports profile and write operational JSON, reports, email state, and audit logs. The new application is being developed by the Software Engineering profile and must not disrupt those jobs.

## Problem

Duplicating prediction logic in API handlers would create divergent behavior, while importing or modifying the legacy engine directly would couple web requests to filesystem paths, email side effects, and scheduler state.

## Decision

The legacy engine remains an external producer. The web app is a read-only consumer initially, with a separate ingestion adapter that translates legacy artifacts into PostgreSQL records.

Boundaries:

- Legacy engine owns fixture discovery, prediction generation, confidence calculation, NO_PICK behavior, result capture, validation, reports, and legacy audit files.
- Ingestion owns file discovery, parsing, idempotency, normalization, PostgreSQL upserts, and ingestion audit records.
- Backend API owns authentication, query/filter/pagination behavior, readiness, and dashboard-specific response schemas.
- Frontend owns presentation and client-side interaction only.
- No request handler invokes the legacy engine, sends Discord/email, or mutates legacy report files.
- No new code is added to the Sports profile or existing Sports cron jobs in this phase.

The adapter must preserve raw source references and expose the engine's semantic states, including degraded source status, NO_PICK, NO_PREDICTION, and accuracy exclusion.

## Alternatives Considered

### A. Copy prediction algorithms into the web app

Rejected. This would create two prediction implementations and make future model behavior inconsistent.

### B. Import and call the legacy engine from API routes

Rejected. The engine performs filesystem writes and can trigger email/report side effects; request latency and side effects are incompatible with API handlers.

### C. Modify the legacy engine to become a library immediately

Deferred. A future refactor may extract pure functions behind a tested interface, but it is outside the safe initial boundary and would require separate approval.

### D. Let the web app write back to legacy JSON

Rejected. It would make the web app a competing source of truth and risk corrupting scheduler state.

## Consequences

### Positive

- Existing Sports automation remains operational and independently rollbackable.
- Web development can proceed with stable API/database contracts.
- Prediction semantics remain centralized in the engine.
- Ingestion failures do not block the legacy prediction pipeline.

### Negative

- Dashboard data is eventually consistent.
- The adapter must handle multiple legacy schema variants.
- Operational ownership spans two profiles and requires clear evidence/monitoring.

## Rollback Plan

Stop or disable only the new ingestion/backend services. Do not alter the existing Sports cron jobs, engine scripts, or JSON artifacts. The legacy pipeline continues independently.

## Review Trigger

Revisit after ingestion and dashboard behavior are stable, before extracting engine code or changing any Sports profile automation.
