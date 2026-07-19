import json
from datetime import date

from app.models import Base, Match, Prediction, PredictionResult
from app.services.ingestion import ingest_file


def make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def schedule_doc():
    return {"date_wib": "2026-07-19", "events": [{"event_id": "m1", "sport": "football", "competition": "Test", "event": "A vs B", "team_a": "A", "team_b": "B", "kickoff_wib": "2026-07-19 10:00", "DATA_SOURCE_DEGRADED": True, "data_source": {"fixture_source": "fixture"}}]}


def prediction_doc():
    return {"date_wib": "2026-07-19", "predictions": [{"match_id": "m1", "sport": "football", "competition": "Test", "event": "A vs B", "kickoff_wib": "2026-07-19 10:00", "team_a": "A", "team_b": "B", "predicted_outcome": "A_win", "predicted_score_or_result": "2-1", "confidence_percent": 72, "confidence_breakdown": {"form": 80}, "no_pick": False, "DATA_SOURCE_DEGRADED": True, "accuracy_excluded": False}]}


def state_doc_with_validation():
    return {"date_wib": "2026-07-19", "events": {"m1": {"actual_result": "2-1", "actual_winner": "A", "validation": "BENAR", "phases": {"result": {"outcome_correct": False}, "validation": {"outcome_correct": True, "score_correct": True}}}}}


def test_ingestion_idempotency_and_field_mapping(tmp_path):
    SessionLocal = make_db()
    path = tmp_path / "predictions-2026-07-19.json"
    path.write_text(json.dumps(prediction_doc()))
    with SessionLocal() as db:
        first = ingest_file(db, path, "predictions")
        second = ingest_file(db, path, "predictions")
        assert first.status == "ingested"
        assert second.status == "already_ingested"
        assert db.query(Prediction).count() == 1
        row = db.query(Prediction).one()
        assert row.confidence_breakdown == {"form": 80}
        assert row.data_source_degraded is True


def test_corrupt_json_is_error_not_exception(tmp_path):
    SessionLocal = make_db()
    path = tmp_path / "bad.json"
    path.write_text("{bad")
    with SessionLocal() as db:
        result = ingest_file(db, path, "predictions")
        assert result.status == "error"
        assert "JSON" in result.error_message or "Expecting" in result.error_message


def test_validation_comes_from_phases_validation(tmp_path):
    SessionLocal = make_db()
    schedule = tmp_path / "schedule.json"
    predictions = tmp_path / "predictions.json"
    state = tmp_path / "state.json"
    schedule.write_text(json.dumps(schedule_doc()))
    predictions.write_text(json.dumps(prediction_doc()))
    state.write_text(json.dumps(state_doc_with_validation()))
    with SessionLocal() as db:
        ingest_file(db, schedule, "schedule")
        ingest_file(db, predictions, "predictions")
        ingest_file(db, state, "state")
        from app.models import PredictionResult
        result = db.query(PredictionResult).one()
        assert result.outcome_correct is True


def test_missing_directory_is_noop(tmp_path):
    SessionLocal = make_db()
    with SessionLocal() as db:
        from app.services.ingestion import ingest_directory
        summary = ingest_directory(db, tmp_path / "missing")
        assert summary.files_seen == 0
        assert summary.errors == 0


def test_state_vs_alias_maps_to_schedule_match(tmp_path):
    SessionLocal = make_db()
    schedule = tmp_path / "schedule.json"
    state = tmp_path / "state.json"
    schedule.write_text(json.dumps({"date_wib": "2026-07-19", "events": [{**schedule_doc()["events"][0], "event_id": "m_1"}]}))
    aliased_state = {"date_wib": "2026-07-19", "events": {"m_vs_1": {"actual_result": "2-1", "phases": {"validation": {"outcome_correct": True}}}}}
    state.write_text(json.dumps(aliased_state))
    with SessionLocal() as db:
        ingest_file(db, schedule, "schedule")
        result = ingest_file(db, state, "state")
        assert result.records_written == 1
        assert db.query(PredictionResult).count() == 1
