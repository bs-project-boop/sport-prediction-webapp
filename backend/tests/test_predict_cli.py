from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.cli import predict
from app.models import Base, Match, MatrixAnalysis, PipelineJob, Prediction

FACTORS = {"form": 65, "h2h": 55, "player_condition": 60, "home_away": 70, "market_odds": 50, "contextual": 45}
REASONING = ["reason one", "reason two"]


def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def seed(factory, status="completed", prediction=None):
    with factory() as session:
        session.add(Match(match_id="football:predict-test", date_wib=date(2026, 7, 27), sport="football", team_a="Home FC", team_b="Away FC"))
        session.add(PipelineJob(id=1, job_id="stage2:predict-test", stage="stage2", match_id="football:predict-test", status=status, scheduled_time=datetime(2026, 7, 27, tzinfo=timezone.utc), completed_at=datetime(2026, 7, 27, tzinfo=timezone.utc) if status == "completed" else None))
        session.add(MatrixAnalysis(match_id="football:predict-test", sport="football", home_form_last5=[{"url": "u"}], tactical_notes=["tactic"], motivational="motivation", data_source_degraded=False))
        if prediction:
            session.add(Prediction(match_id="football:predict-test", source_record_id="2026-07-27:football:predict-test", **prediction))
        session.commit()


def args_json():
    return json.dumps(FACTORS), json.dumps(REASONING)


def test_list_finds_stage2_completed_ready_match(capsys):
    make = factory(); seed(make)
    with make() as session:
        assert predict.list_ready(session) == 0
    output = capsys.readouterr().out
    assert "football:predict-test" in output
    assert "Home FC" in output
    assert "completed" in output


def test_show_includes_evidence_narrative_and_prediction(capsys):
    make = factory(); seed(make)
    with make() as session:
        assert predict.show_match(session, "football:predict-test") == 0
    output = capsys.readouterr().out
    assert "home_form_last5" in output
    assert "tactical_notes" in output
    assert "motivation" in output
    assert "<missing>" in output


def test_predict_rejects_non_completed_stage2():
    make = factory(); seed(make, status="awaiting_narrative")
    b, r = args_json()
    with make() as session:
        with pytest.raises(predict.PredictionError, match="awaiting_narrative"):
            predict.predict_match(session, "football:predict-test", "home_win", b, r)


def test_preview_does_not_write(capsys):
    make = factory(); seed(make)
    b, r = args_json()
    with make() as session:
        assert predict.predict_match(session, "football:predict-test", "home_win", b, r, "2-1") == 0
        assert session.query(Prediction).count() == 0
    assert "PREVIEW" in capsys.readouterr().out


def test_apply_high_confidence_keeps_outcome():
    make = factory(); seed(make)
    b, r = args_json()
    with make() as session:
        predict.predict_match(session, "football:predict-test", "away_win", b, r, "1-2", apply=True)
        row = session.query(Prediction).one()
        assert row.predicted_outcome == "away_win"
        assert row.pipeline_stage == "stage3"
        assert row.validation_status == "PENDING"
        assert row.source_record_id == "stage3:football:predict-test"
        assert row.raw_document == {}
        assert row.evidence == []


def test_apply_low_confidence_overrides_no_pick():
    make = factory(); seed(make)
    b = json.dumps({key: 20 for key in FACTORS}); r = json.dumps(REASONING)
    with make() as session:
        predict.predict_match(session, "football:predict-test", "home_win", b, r, apply=True)
        row = session.query(Prediction).one()
        assert row.predicted_outcome == "NO_PICK"
        assert row.no_pick is True
        assert row.no_pick_reason == "confidence_below_40"
        assert row.prediction_eligible is False
        assert row.accuracy_excluded is True


def test_apply_updates_existing_stub_without_duplicate():
    make = factory(); seed(make, prediction={"predicted_outcome": None, "prediction_eligible": True, "no_pick": False, "accuracy_excluded": False})
    b, r = args_json()
    with make() as session:
        original = session.query(Prediction).one()
        original_id = original.id
        predict.predict_match(session, "football:predict-test", "home_win", b, r, apply=True)
        session.expire_all()
        row = session.query(Prediction).one()
        assert row.id == original_id
        assert session.query(Prediction).count() == 1
        assert row.pipeline_stage == "stage3"


def test_double_predict_is_rejected():
    make = factory(); seed(make, prediction={"pipeline_stage": "stage3", "predicted_outcome": "home_win", "prediction_eligible": True, "no_pick": False, "accuracy_excluded": False})
    b, r = args_json()
    with make() as session:
        with pytest.raises(predict.PredictionError, match="sudah pernah"):
            predict.predict_match(session, "football:predict-test", "home_win", b, r)


def test_breakdown_and_reasoning_validation():
    make = factory(); seed(make)
    with make() as session:
        with pytest.raises(predict.PredictionError, match="persis 6 key"):
            predict.predict_match(session, "football:predict-test", "home_win", json.dumps({"form": 50}), json.dumps(REASONING))
        with pytest.raises(predict.PredictionError, match="0-100"):
            predict.predict_match(session, "football:predict-test", "home_win", json.dumps({**FACTORS, "form": 101}), json.dumps(REASONING))
        with pytest.raises(predict.PredictionError, match="tidak kosong"):
            predict.predict_match(session, "football:predict-test", "home_win", json.dumps(FACTORS), "[]")
