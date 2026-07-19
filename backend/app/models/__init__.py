from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(Text, unique=True, index=True)
    date_wib: Mapped[date] = mapped_column(Date)
    sport: Mapped[str] = mapped_column(Text, index=True)
    competition: Mapped[str] = mapped_column(Text, default="")
    event_name: Mapped[str] = mapped_column(Text, default="")
    team_a: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_b: Mapped[str | None] = mapped_column(Text, nullable=True)
    kickoff_wib: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="scheduled")
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_document: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id", ondelete="CASCADE"), index=True)
    source_record_id: Mapped[str] = mapped_column(Text, unique=True)
    predicted_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    predicted_score_or_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_pick: Mapped[bool] = mapped_column(Boolean, default=False)
    no_pick_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_source_degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence_penalty_applied: Mapped[int] = mapped_column(Integer, default=0)
    prediction_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    accuracy_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    raw_document: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class PredictionResult(Base):
    __tablename__ = "prediction_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id", ondelete="CASCADE"), index=True)
    source_record_id: Mapped[str] = mapped_column(Text, unique=True)
    actual_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_winner: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_score: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score_diff: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    accuracy_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_document: Mapped[dict] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionAudit(Base):
    __tablename__ = "ingestion_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    source_file: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str] = mapped_column(Text)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    client_key: Mapped[str] = mapped_column(Text, index=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["Base", "Match", "Prediction", "PredictionResult", "IngestionAudit", "AuthSession"]
