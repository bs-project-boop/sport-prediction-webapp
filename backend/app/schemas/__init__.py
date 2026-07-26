from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


class PinRequest(BaseModel):
    pin: str = Field(min_length=6, max_length=6)


class ChangePinRequest(BaseModel):
    current_pin: str = Field(min_length=6, max_length=6)
    new_pin: str = Field(min_length=6, max_length=6)


class MatchResponse(BaseModel):
    match_id: str
    date_wib: str
    sport: str
    competition: str
    event: str
    kickoff_wib: str | None
    team_a: str | None
    team_b: str | None
    status: str


class PredictionResponse(BaseModel):
    match_id: str
    predicted_outcome: str | None
    predicted_score_or_result: str | None
    confidence_percent: int | None
    confidence_breakdown: dict | None
    no_pick: bool
    DATA_SOURCE_DEGRADED: bool
    accuracy_excluded: bool
    validation_status: str | None
    actual_result: str | None
    actual_winner: str | None


class MetricsResponse(BaseModel):
    evaluated_count: int
    correct_count: int
    partial_count: int
    incorrect_count: int
    excluded_count: int
    strict_accuracy_percent: float | None
    lenient_accuracy_percent: float | None


# ── M2: Matrix Analysis ────────────────────────────────────────────────────────

class MatrixAnalysisBase(BaseModel):
    match_id: str
    sport: str
    home_injuries: list[Any] = []
    away_injuries: list[Any] = []
    home_suspensions: list[Any] = []
    away_suspensions: list[Any] = []
    lineup_notes: list[Any] = []
    home_form_last5: list[Any] = []
    away_form_last5: list[Any] = []
    h2h_results: list[Any] = []
    tactical_notes: list[Any] = []
    motivational: str | None = None
    venue_weather: dict[str, Any] | None = None
    schedule_fatigue: dict[str, Any] | None = None
    market_odds: dict[str, Any] | None = None
    polymarket_data: dict[str, Any] | None = None
    evidence_quality_score: int | None = None
    sources_used: list[str] = []
    data_source_degraded: bool = False
    research_completed_at: datetime | None = None


class MatrixAnalysisCreate(MatrixAnalysisBase):
    pass


class MatrixAnalysisResponse(MatrixAnalysisBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── M2: Win Reasoning ─────────────────────────────────────────────────────────

class WinReasoningBase(BaseModel):
    match_id: str
    winner: str
    winning_factors: list[Any] = []
    losing_factors: list[Any] = []
    narrative: str
    key_moment: str | None = None
    tactical_winner: str | None = None
    factors_missed_by_prediction: list[Any] = []
    pattern_tags: list[str] = []


class WinReasoningCreate(WinReasoningBase):
    pass


class WinReasoningResponse(WinReasoningBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── M6: Calibration History ───────────────────────────────────────────────────

class CalibrationHistoryBase(BaseModel):
    run_at_wib: datetime
    sport: str
    bucket: str  # 'HIGH'|'MEDIUM'|'LOW'|'COIN_FLIP'
    matches_in_bucket: int = 0
    mean_confidence_pct: float | None = None
    actual_accuracy_pct: float | None = None
    calibration_error_pp: float | None = None
    direction: str | None = None  # 'over_confident'|'under_confident'
    needs_recalibration: bool = False
    suggested_adjustment: dict[str, Any] | None = None
    bucket_distribution: dict[str, Any] | None = None


class CalibrationHistoryCreate(CalibrationHistoryBase):
    pass


class CalibrationHistoryResponse(CalibrationHistoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── M6: Weight Adjustments ────────────────────────────────────────────────────

class WeightAdjustmentBase(BaseModel):
    sport: str
    factor: str  # 'form'|'h2h'|'player_condition'|etc.
    delta_weight: float
    direction: str  # 'increase'|'decrease'
    triggered_by: str  # 'pattern_tag'|'calibration_suggestion'|'manual'
    trigger_detail: dict[str, Any] | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None  # 'system'|'user:{user_id}'
    status: str = "applied"  # 'applied'|'pending_approval'|'rejected'|'rolled_back'
    expires_at: datetime | None = None  # NULL=permanent


class WeightAdjustmentCreate(WeightAdjustmentBase):
    pass


class WeightAdjustmentResponse(WeightAdjustmentBase):
    id: int
    created_at: datetime
    applied_at: datetime | None = None

    class Config:
        from_attributes = True


# ── M5: Notification Audit ────────────────────────────────────────────────────

class NotificationAuditBase(BaseModel):
    idempotency_key: str
    channel: str  # 'discord'|'email'
    match_id: str | None = None
    subject: str | None = None
    recipient: str | None = None
    status: str  # 'sent'|'deduped'|'failed'
    payload_hash: str | None = None
    error_message: str | None = None


class NotificationAuditCreate(NotificationAuditBase):
    pass


class NotificationAuditResponse(NotificationAuditBase):
    id: int
    sent_at: datetime

    class Config:
        from_attributes = True
