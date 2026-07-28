from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, WeightAdjustment
from app.services.confidence import CONFIDENCE_WEIGHTS, calculate_confidence, confidence_label


def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_complete_breakdown_matches_manual_weighted_sum():
    make = factory()
    breakdown = {"form": 65, "h2h": 55, "player_condition": 60, "home_away": 70, "market_odds": 50, "contextual": 45}
    expected = round(65*.25 + 55*.15 + 60*.20 + 70*.15 + 50*.15 + 45*.10)
    with make() as session:
        score, weights, penalty = calculate_confidence(session, "football", breakdown, False)
    assert score == expected == 59
    assert weights == CONFIDENCE_WEIGHTS["football"]
    assert penalty == 0


def test_missing_factor_defaults_to_50():
    make = factory()
    with make() as session:
        score, _, _ = calculate_confidence(session, "football", {"form": 100}, False)
    assert score == round(100*.25 + 50*.75)


def test_degraded_penalty_is_minus_15():
    make = factory()
    with make() as session:
        score, _, penalty = calculate_confidence(session, "football", {factor: 70 for factor in ["form", "h2h", "player_condition", "home_away", "market_odds", "contextual"]}, True)
    assert score == 55
    assert penalty == -15


def test_score_is_clamped_before_rounding():
    make = factory()
    with make() as session:
        high, _, _ = calculate_confidence(session, "football", {factor: 200 for factor in ["form", "h2h", "player_condition", "home_away", "market_odds", "contextual"]}, False)
        low, _, _ = calculate_confidence(session, "football", {factor: -200 for factor in ["form", "h2h", "player_condition", "home_away", "market_odds", "contextual"]}, True)
    assert high == 100
    assert low == 0


def test_empty_adjustments_are_noop():
    make = factory()
    with make() as session:
        score, weights, _ = calculate_confidence(session, "football", {factor: 50 for factor in ["form", "h2h", "player_condition", "home_away", "market_odds", "contextual"]}, False)
    assert score == 50
    assert weights == CONFIDENCE_WEIGHTS["football"]


def test_applied_adjustment_changes_and_normalizes_weight():
    make = factory()
    with make() as session:
        session.add(WeightAdjustment(sport="football", factor="form", delta_weight=0.10, direction="increase", triggered_by="manual", status="applied"))
        session.add(WeightAdjustment(sport="football", factor="h2h", delta_weight=0.10, direction="increase", triggered_by="manual", status="pending_approval"))
        session.commit()
        _, weights, _ = calculate_confidence(session, "football", {factor: 50 for factor in ["form", "h2h", "player_condition", "home_away", "market_odds", "contextual"]}, False)
    assert round(sum(weights.values()), 10) == 1.0
    assert weights["form"] == 0.35 / 1.10
    assert weights["h2h"] == 0.15 / 1.10


def test_confidence_labels_match_legacy_buckets():
    assert confidence_label(75) == "HIGH"
    assert confidence_label(55) == "MEDIUM"
    assert confidence_label(40) == "LOW"
    assert confidence_label(39) == "COIN FLIP"
    assert confidence_label("bad") == "UNKNOWN"
