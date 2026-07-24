from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestionAudit, Match, Prediction, PredictionResult


@dataclass
class IngestResult:
    status: str
    records_seen: int = 0
    records_written: int = 0
    error_message: str | None = None


@dataclass
class IngestSummary:
    files_seen: int = 0
    files_ingested: int = 0
    errors: int = 0
    records_written: int = 0


VALIDATION_STATUS_MAP = {
    "BENAR": "BENAR",
    "SEBAGIAN BENAR": "SEBAGIAN_BENAR",
    "SALAH": "SALAH",
    "NO_PICK": "NO_PICK",
    "NO_PREDICTION": "NO_PREDICTION",
}

# Map 12 chaotic raw status values (found in DB) to 5 canonical values.
# Canonical: SCHEDULED, LIVE, FINISHED, POSTPONED, CANCELLED
MATCH_STATUS_MAP = {
    # SCHEDULED variants
    "scheduled": "SCHEDULED",
    "not started": "SCHEDULED",
    "not_started": "SCHEDULED",
    "not started yet": "SCHEDULED",
    "init": "SCHEDULED",          # "INIT" from legacy raw data
    "k": "SCHEDULED",          # "K" from result capture = Kick-off scheduled
    "b": "SCHEDULED",          # "B" = belum mulai (not started)
    "scheduled": "SCHEDULED",  # keep lowercase for fallback
    "schedul": "SCHEDULED",
    # LIVE variants
    "in progress": "LIVE",
    "first half": "LIVE",
    "half time": "LIVE",
    "second half": "LIVE",
    "third quarter": "LIVE",
    "fourth quarter": "LIVE",
    "q1": "LIVE",
    "q2": "LIVE",
    "q3": "LIVE",
    "q4": "LIVE",
    "over": "LIVE",            # basketball overtime
    "current": "LIVE",
    # FINISHED variants
    "finished": "FINISHED",
    "full time": "FINISHED",
    "final": "FINISHED",
    "post final": "FINISHED",
    "final ft": "FINISHED",
    "ft": "FINISHED",
    "aet": "FINISHED",         # after extra time
    "pens": "FINISHED",        # penalties
    # POSTPONED
    "postponed": "POSTPONED",
    "suspended": "POSTPONED",
    "interrupted": "POSTPONED",
    # CANCELLED
    "cancelled": "CANCELLED",
    "abandoned": "CANCELLED",
    "walkover": "CANCELLED",
    "wo": "CANCELLED",
}


def map_validation_status(raw_value: str | None) -> str | None:
    """Map the v3 top-level validation string to the database enum value."""
    if raw_value is None:
        return None
    try:
        return VALIDATION_STATUS_MAP[raw_value]
    except KeyError as exc:
        raise ValueError(f"Unknown validation status: {raw_value!r}") from exc


def _key(path: Path, document_type: str, payload: bytes) -> str:
    return hashlib.sha256(f"{document_type}:{path}:{hashlib.sha256(payload).hexdigest()}".encode()).hexdigest()


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _audit(db: Session, key: str, path: Path, document_type: str, status: str, seen=0, written=0, error=None):
    row = IngestionAudit(idempotency_key=key, source_file=str(path), document_type=document_type, status=status, records_seen=seen, records_written=written, error_message=error, completed_at=datetime.now(timezone.utc))
    db.add(row)
    db.commit()
    return row


def _normalize_match_status(raw_status: str | None) -> str:
    if not raw_status:
        return "SCHEDULED"  # default for unknown/missing
    lower = str(raw_status).lower().strip()
    return MATCH_STATUS_MAP.get(lower, "SCHEDULED")


def _upsert_match(db: Session, item: dict, date_value):
    match_id = item.get("event_id") or item.get("match_id")
    if not match_id:
        return None
    row = db.scalar(select(Match).where(Match.match_id == match_id))
    if not row:
        row = Match(match_id=match_id, date_wib=date_value, sport=item.get("sport", "unknown"), event_name=item.get("event") or "")
        db.add(row)
    row.date_wib = date_value
    row.sport = item.get("sport", row.sport)
    row.competition = item.get("competition", row.competition or "")
    row.event_name = item.get("event", row.event_name or "")
    row.team_a = item.get("team_a", row.team_a)
    row.team_b = item.get("team_b", row.team_b)
    row.kickoff_wib = _parse_dt(item.get("kickoff_wib"))
    row.venue = item.get("venue", row.venue)
    row.status = _normalize_match_status(item.get("status"))
    row.source_metadata = item.get("data_source") or {}
    row.raw_document = item
    db.flush()
    return row


def _ingest_schedule(db: Session, doc: dict):
    date_value = datetime.strptime(doc["date_wib"], "%Y-%m-%d").date()
    written = 0
    for item in doc.get("events", []):
        if _upsert_match(db, item, date_value):
            written += 1
    db.commit()
    return len(doc.get("events", [])), written


def _ingest_prediction(db: Session, doc: dict):
    """Ingest predictions. Uses match_id as canonical key — one Prediction row per match.

    BEFORE (bug): used source_record_id = "{date}:{match_id}" as lookup key.
    This caused daily-scan's 7-day window to INSERT a new row every cycle for the
    same match (since source_record_id included the scan date, never matched on re-run).
    FIX: look up by match_id (canonical) instead. DB enforces uq_predictions_match_id.
    """
    date_value = datetime.strptime(doc["date_wib"], "%Y-%m-%d").date()
    written = 0
    for item in doc.get("predictions", []):
        match = _upsert_match(db, item, date_value)
        if not match:
            continue
        # Canonical lookup by match_id (not source_record_id which includes scan date)
        row = db.scalar(select(Prediction).where(Prediction.match_id == match.match_id))
        is_new = False
        if not row:
            source_id = f"{doc.get('date_wib')}:{item.get('match_id')}"
            row = Prediction(match_id=match.match_id, source_record_id=source_id)
            db.add(row)
            is_new = True
        for attr, key in (("predicted_outcome", "predicted_outcome"), ("predicted_score_or_result", "predicted_score_or_result"), ("confidence_percent", "confidence_percent"), ("confidence_label", "confidence_label"), ("confidence_breakdown", "confidence_breakdown"), ("confidence_model_version", "confidence_model_version"), ("risk_score", "risk_score_1_to_10"), ("no_pick", "no_pick"), ("data_source_degraded", "DATA_SOURCE_DEGRADED"), ("prediction_eligible", "prediction_eligible"), ("accuracy_excluded", "accuracy_excluded"), ("validation_status", "validation_status")):
            if key in item: setattr(row, attr, item[key])
        row.raw_document = item
        row.evidence = item.get("searxng_evidence", [])
        row.reasoning = item.get("reasoning", [])
        # Always refresh updated_at; created_at stays original (preserve first-seen time)
        row.updated_at = datetime.now(timezone.utc)
        written += 1
    db.commit()
    return len(doc.get("predictions", [])), written


def _normalize_state_match_id(match_id: str) -> str:
    return match_id.replace("_vs_", "_")


def _ingest_state(db: Session, doc: dict):
    date_value = datetime.strptime(doc["date_wib"], "%Y-%m-%d").date()
    written = 0
    warnings: list[str] = []
    for raw_match_id, item in (doc.get("events") or {}).items():
        match_id = _normalize_state_match_id(raw_match_id)
        if not db.scalar(select(Match).where(Match.match_id == match_id)):
            continue
        source_id = f"{doc.get('date_wib')}:{raw_match_id}:result"
        row = db.scalar(select(PredictionResult).where(PredictionResult.source_record_id == source_id))
        if not row:
            row = PredictionResult(match_id=match_id, source_record_id=source_id)
            db.add(row)
        raw_status = item.get("validation")
        try:
            mapped_status = map_validation_status(raw_status)
        except ValueError as exc:
            warnings.append(f"{raw_match_id}: {exc}")
            mapped_status = None
        row.actual_result = item.get("actual_result")
        row.actual_winner = item.get("actual_winner")
        row.actual_score = row.actual_result
        row.validation_status = mapped_status
        row.accuracy_excluded = mapped_status in {"NO_PICK", "NO_PREDICTION"} or bool(item.get("accuracy_excluded", False))
        row.raw_document = item
        written += 1
    db.commit()
    return len(doc.get("events") or {}), written, warnings


def ingest_file(db: Session, path: Path, document_type: str) -> IngestResult:
    payload = path.read_bytes()
    key = _key(path, document_type, payload)
    if db.scalar(select(IngestionAudit).where(IngestionAudit.idempotency_key == key)):
        return IngestResult("already_ingested")
    try:
        warnings: list[str] = []
        if document_type == "audit":
            records = [json.loads(line) for line in payload.decode().splitlines() if line.strip()]
            seen, written = len(records), 0
        else:
            doc = json.loads(payload)
            if document_type == "schedule": seen, written = _ingest_schedule(db, doc)
            elif document_type == "predictions": seen, written = _ingest_prediction(db, doc)
            elif document_type == "state": seen, written, warnings = _ingest_state(db, doc)
            else: raise ValueError(f"unsupported document type: {document_type}")
        status = "warning" if warnings else "ingested"
        message = "; ".join(warnings) if warnings else None
        _audit(db, key, path, document_type, status, seen, written, error=message)
        return IngestResult(status, seen, written, message)
    except Exception as exc:
        db.rollback()
        _audit(db, key, path, document_type, "error", error=str(exc))
        return IngestResult("error", error_message=str(exc))


def ingest_directory(db: Session, root: Path, date_filter: str | None = None) -> IngestSummary:
    summary = IngestSummary()
    if not root.exists():
        return summary
    paths = sorted(list(root.rglob("*.json")) + list(root.rglob("*.jsonl")))
    for path in paths:
        if date_filter and not path.name.startswith(date_filter):
            continue
        name = path.parent.name
        if path.suffix == ".jsonl" or name == "audit":
            document_type = "audit"
        elif name in {"schedules", "predictions", "state"}:
            document_type = {"schedules": "schedule", "predictions": "predictions", "state": "state"}[name]
        else:
            continue  # skip unrelated .json files (e.g. email outbox, tmp scripts)
        result = ingest_file(db, path, document_type)
        summary.files_seen += 1
        if result.status == "error": summary.errors += 1
        elif result.status in {"ingested", "warning"}: summary.files_ingested += 1
        summary.records_written += result.records_written
    return summary
