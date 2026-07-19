# ADR-001 — Migrate Web-App Persistence from JSON Files to PostgreSQL

**Date:** 2026-07-19 | **Status:** Accepted | **Scope:** Sport Prediction Web App

## Context

The existing Sport Prediction engine writes daily JSON and JSONL artifacts under `/Users/beem/.hermes-shared/reports/sports/v3`. Those files are the current operational source of truth and are used by active Sports profile automation. The new web app needs durable querying, filtering, pagination, aggregates, and concurrent read access without changing the running engine.

## Problem

Directly changing the legacy engine to write PostgreSQL would increase production risk, couple the existing scheduler to the new application schema, and make rollback harder. A migration must preserve the current JSON behavior while establishing a queryable relational projection.

## Decision

Use PostgreSQL as the web application's durable read model, populated by a separate idempotent ingestion service.

The legacy engine remains unchanged and continues to write JSON/JSONL. The ingestion service watches or periodically scans the shared report directories, parses new or changed files, validates their shape, and upserts normalized records into PostgreSQL. Original source file path, source hash, event ID, and raw source fragments are retained for auditability.

The first release uses **read-only ingestion from the legacy report tree**. It does not dual-write from the engine and does not write back to legacy JSON. A later ADR is required before any engine write path is changed.

Ingestion requirements:

- Idempotency key per source file and logical event.
- Transactional upsert of a source artifact and its derived rows.
- Corrupt files are logged in `ingestion_audit` and skipped without aborting the whole scan.
- `NO_PICK`, `NO_PREDICTION`, `accuracy_excluded`, and null validation states remain distinct.
- Unknown/source-specific fields are preserved in JSONB during initial migration.
- Reprocessing the same file must not create duplicate matches, predictions, or results.

## Alternatives Considered

### A. Modify the legacy engine to write PostgreSQL directly

Rejected for the initial release. It changes production behavior, expands the rollback surface, and couples the old engine to new migrations and database availability.

### B. Dual-write JSON and PostgreSQL from the legacy engine

Rejected for the initial release. Dual-write introduces partial-failure consistency problems and requires modifying the engine that must remain untouched.

### C. One-time import only

Rejected. It would make the dashboard stale and would not support ongoing prediction/result history.

### D. Read-through cache without durable ingestion

Rejected. It would move parsing and schema instability into request handlers and provide poor query/pagination behavior.

## Consequences

### Positive

- Existing production automation remains unchanged.
- PostgreSQL supports indexed filters, pagination, aggregates, and concurrent dashboard reads.
- Ingestion can be replayed and audited independently.
- Rollback is straightforward: stop ingestion and keep the legacy JSON flow operating.

### Negative

- There are temporarily two representations of the data.
- Ingestion lag and partial-file handling must be observable.
- The schema must accommodate both v3.2 daily JSON and older monthly phase documents.

### Risks and Mitigations

- **Schema drift:** preserve raw JSONB and versioned parsers.
- **Duplicate ingestion:** enforce unique idempotency keys.
- **Partial writes:** only ingest complete/parseable documents and record failures.
- **Stale dashboard:** expose ingestion freshness and readiness metrics.

## Rollback Plan

Disable the ingestion service and leave the legacy engine, JSON files, and Sports cron jobs unchanged. Database projection data may remain for forensic review; no legacy source data is deleted.

## Review Trigger

Revisit after the first production-like ingestion cycle and before any proposal to modify legacy engine write behavior.
