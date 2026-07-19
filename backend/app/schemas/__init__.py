from pydantic import BaseModel, Field


class PinRequest(BaseModel):
    pin: str = Field(min_length=6, max_length=6)


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


class MetricsResponse(BaseModel):
    evaluated_count: int
    correct_count: int
    accuracy_percent: float | None
