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
    row.status = item.get("status", row.status or "scheduled")
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
    date_value = datetime.strptime(doc["date_wib"], "%Y-%m-%d").date()
    written = 0
    for item in doc.get("predictions", []):
        match = _upsert_match(db, item, date_value)
        if not match:
            continue
        source_id = f"{doc.get('date_wib')}:{item.get('match_id')}"
        row = db.scalar(select(Prediction).where(Prediction.source_record_id == source_id))
        if not row:
            row = Prediction(match_id=match.match_id, source_record_id=source_id)
            db.add(row)
        for attr, key in (("predicted_outcome", "predicted_outcome"), ("predicted_score_or_result", "predicted_score_or_result"), ("confidence_percent", "confidence_percent"), ("confidence_label", "confidence_label"), ("confidence_breakdown", "confidence_breakdown"), ("confidence_model_version", "confidence_model_version"), ("risk_score", "risk_score_1_to_10"), ("no_pick", "no_pick"), ("data_source_degraded", "DATA_SOURCE_DEGRADED"), ("prediction_eligible", "prediction_eligible"), ("accuracy_excluded", "accuracy_excluded"), ("validation_status", "validation_status")):
            if key in item: setattr(row, attr, item[key])
        row.raw_document = item
        row.evidence = item.get("searxng_evidence", [])
        row.reasoning = item.get("reasoning", [])
        written += 1
    db.commit()
    return len(doc.get("predictions", [])), written


def _normalize_state_match_id(match_id: str) -> str:
    return match_id.replace("_vs_", "_")


def _ingest_state(db: Session, doc: dict):
    date_value = datetime.strptime(doc["date_wib"], "%Y-%m-%d").date()
    written = 0
    for raw_match_id, item in (doc.get("events") or {}).items():
        match_id = _normalize_state_match_id(raw_match_id)
        if not db.scalar(select(Match).where(Match.match_id == match_id)):
            continue
        phases = item.get("phases") or {}
        validation = phases.get("validation") or {}
        source_id = f"{doc.get('date_wib')}:{raw_match_id}:result"
        row = db.scalar(select(PredictionResult).where(PredictionResult.source_record_id == source_id))
        if not row:
            row = PredictionResult(match_id=match_id, source_record_id=source_id)
            db.add(row)
        row.actual_result = item.get("actual_result") or (phases.get("result") or {}).get("actual_score")
        row.actual_winner = item.get("actual_winner") or (phases.get("result") or {}).get("winner")
        row.actual_score = row.actual_result
        row.validation_status = item.get("validation") or item.get("validation_status")
        row.outcome_correct = validation.get("outcome_correct")
        row.score_correct = validation.get("score_correct")
        row.accuracy_excluded = bool(item.get("accuracy_excluded", False))
        row.raw_document = item
        written += 1
    db.commit()
    return len(doc.get("events") or {}), written


def ingest_file(db: Session, path: Path, document_type: str) -> IngestResult:
    payload = path.read_bytes()
    key = _key(path, document_type, payload)
    if db.scalar(select(IngestionAudit).where(IngestionAudit.idempotency_key == key)):
        return IngestResult("already_ingested")
    try:
        if document_type == "audit":
            records = [json.loads(line) for line in payload.decode().splitlines() if line.strip()]
            seen, written = len(records), 0
        else:
            doc = json.loads(payload)
            if document_type == "schedule": seen, written = _ingest_schedule(db, doc)
            elif document_type == "predictions": seen, written = _ingest_prediction(db, doc)
            elif document_type == "state": seen, written = _ingest_state(db, doc)
            else: raise ValueError(f"unsupported document type: {document_type}")
        _audit(db, key, path, document_type, "ingested", seen, written)
        return IngestResult("ingested", seen, written)
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
        else:
            document_type = {"schedules": "schedule", "predictions": "predictions", "state": "state"}.get(name, "predictions")
        result = ingest_file(db, path, document_type)
        summary.files_seen += 1
        if result.status == "error": summary.errors += 1
        elif result.status == "ingested": summary.files_ingested += 1
        summary.records_written += result.records_written
    return summary
