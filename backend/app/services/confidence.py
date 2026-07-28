"""Deterministic confidence calculation shared by Stage 3."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WeightAdjustment

CONFIDENCE_WEIGHTS = {
    "football": {"form": 0.25, "h2h": 0.15, "player_condition": 0.20, "home_away": 0.15, "market_odds": 0.15, "contextual": 0.10},
    "tennis": {"form": 0.20, "h2h": 0.20, "player_condition": 0.25, "home_away": 0.15, "market_odds": 0.10, "contextual": 0.10},
    "motorsport": {"form": 0.15, "h2h": 0.10, "player_condition": 0.20, "home_away": 0.20, "market_odds": 0.20, "contextual": 0.15},
    "basketball": {"form": 0.25, "h2h": 0.15, "player_condition": 0.20, "home_away": 0.15, "market_odds": 0.15, "contextual": 0.10},
    "nfl": {"form": 0.20, "h2h": 0.15, "player_condition": 0.20, "home_away": 0.15, "market_odds": 0.15, "contextual": 0.15},
}
CONFIDENCE_FACTORS = ["form", "h2h", "player_condition", "home_away", "market_odds", "contextual"]


def adjusted_weights(session: Session, sport: str) -> dict[str, float]:
    """Apply active DB adjustments and normalize weights exactly like legacy."""
    sport = (sport or "unknown").lower()
    weights = dict(CONFIDENCE_WEIGHTS.get(sport, CONFIDENCE_WEIGHTS["football"]))
    rows = session.execute(
        select(WeightAdjustment).where(
            WeightAdjustment.sport == sport,
            WeightAdjustment.status == "applied",
        )
    ).scalars()
    for adjustment in rows:
        if adjustment.factor in weights:
            weights[adjustment.factor] = max(
                0.0,
                weights[adjustment.factor] + float(adjustment.delta_weight or 0),
            )
    total = sum(weights.values()) or 1.0
    return {key: value / total for key, value in weights.items()}


def calculate_confidence(
    session: Session,
    sport: str,
    breakdown: dict[str, float],
    degraded: bool = False,
) -> tuple[int, dict[str, float], int]:
    """Return rounded confidence, weights used, and applied penalty."""
    weights = adjusted_weights(session, sport)
    score = 0.0
    for factor in CONFIDENCE_FACTORS:
        try:
            value = float((breakdown or {}).get(factor, 50))
        except Exception:
            value = 50.0
        value = max(0.0, min(100.0, value))
        score += value * weights.get(factor, 0.0)
    penalty = -15 if degraded else 0
    score = max(0.0, min(100.0, score + penalty))
    return int(round(score)), weights, penalty


def confidence_label(value: Any) -> str:
    try:
        v = float(value)
    except Exception:
        return "UNKNOWN"
    if v >= 75:
        return "HIGH"
    if v >= 55:
        return "MEDIUM"
    if v >= 40:
        return "LOW"
    return "COIN FLIP"
