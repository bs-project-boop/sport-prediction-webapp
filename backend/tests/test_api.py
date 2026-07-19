from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.security import hash_pin
from app.main import create_app
from app.models import Base, Match, Prediction, PredictionResult


def make_client(tmp_path):
    app, engine, SessionLocal = create_app("sqlite://", pin_hash=hash_pin("123456"), testing=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Match(match_id="m1", date_wib=date(2026, 7, 19), sport="football", competition="Test", event_name="A vs B", kickoff_wib=datetime(2026, 7, 19, 10, 0), team_a="A", team_b="B"))
        db.add(Match(match_id="m2", date_wib=date(2026, 7, 20), sport="tennis", competition="Test", event_name="C vs D", kickoff_wib=datetime(2026, 7, 20, 11, 0), team_a="C", team_b="D"))
        db.add(Prediction(match_id="m1", source_record_id="p1", predicted_outcome="A_win", confidence_percent=72, confidence_breakdown={"form": 80}, no_pick=False, data_source_degraded=True, accuracy_excluded=False))
        db.add(Prediction(match_id="m2", source_record_id="p2", predicted_outcome="C_win", confidence_percent=35, confidence_breakdown={}, no_pick=True, data_source_degraded=False, accuracy_excluded=True))
        db.add(PredictionResult(match_id="m1", source_record_id="r1", actual_winner="A", actual_score="2-1", outcome_correct=True, score_correct=True, accuracy_excluded=False))
        db.add(PredictionResult(match_id="m2", source_record_id="r2", actual_winner="D", actual_score="0-2", outcome_correct=False, score_correct=False, accuracy_excluded=True))
        db.commit()
    return TestClient(app)


def login(client):
    response = client.post("/auth/pin", json={"pin": "123456"})
    assert response.status_code == 200
    assert response.cookies.get("sport_session")


def test_auth_success_wrong_pin_and_lockout(tmp_path):
    client = make_client(tmp_path)
    good = client.post("/auth/pin", json={"pin": "123456"})
    assert good.status_code == 200
    assert "sport_session" in good.cookies
    assert "password" not in good.text.lower()

    bad = client.post("/auth/pin", json={"pin": "000000"})
    assert bad.status_code == 401
    assert bad.json() == {"detail": "invalid credentials"}


def test_logout_is_idempotent_and_protected_endpoints_need_session(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/matches").status_code == 401
    assert client.post("/auth/logout").status_code == 200
    login(client)
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/matches").status_code == 401


def test_matches_filters_and_pagination(tmp_path):
    client = make_client(tmp_path)
    login(client)
    response = client.get("/matches", params={"from": "2026-07-19", "to": "2026-07-19", "sport": "football", "limit": 1, "offset": 0})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["match_id"] == "m1"
    assert client.get("/matches", params={"sport": "basketball"}).json()["items"] == []


def test_prediction_details_and_metrics(tmp_path):
    client = make_client(tmp_path)
    login(client)
    prediction = client.get("/predictions/m1")
    assert prediction.status_code == 200
    assert prediction.json()["confidence_breakdown"] == {"form": 80}
    assert prediction.json()["DATA_SOURCE_DEGRADED"] is True
    assert client.get("/predictions/missing").status_code == 404
    metrics = client.get("/metrics/accuracy", params={"from": "2026-07-19", "to": "2026-07-20"})
    assert metrics.status_code == 200
    assert metrics.json()["evaluated_count"] == 1
    assert metrics.json()["correct_count"] == 1
    assert metrics.json()["accuracy_percent"] == 100.0


def test_health_live_and_ready(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
