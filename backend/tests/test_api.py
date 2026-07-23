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
        db.add(PredictionResult(match_id="m1", source_record_id="r1", actual_winner="A", actual_score="2-1", validation_status="BENAR", accuracy_excluded=False))
        db.add(PredictionResult(match_id="m2", source_record_id="r2", actual_winner="D", actual_score="0-2", validation_status="NO_PICK", accuracy_excluded=False))
        db.commit()
    return TestClient(app, base_url="https://testserver")


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


# ─── Search ────────────────────────────────────────────────────────────────────

def _search_matches_client(tmp_path):
    """Build a client with extra rows that exercise the search filter."""
    app, engine, SessionLocal = create_app("sqlite://", pin_hash=hash_pin("123456"), testing=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Match(match_id="f1", date_wib=date(2026, 7, 19), sport="football", competition="Premier League",
                     event_name="Manchester United vs Liverpool", kickoff_wib=datetime(2026, 7, 19, 21, 0),
                     team_a="Manchester United", team_b="Liverpool"))
        db.add(Match(match_id="f2", date_wib=date(2026, 7, 19), sport="football", competition="La Liga",
                     event_name="Real Madrid vs Barcelona", kickoff_wib=datetime(2026, 7, 19, 22, 0),
                     team_a="Real Madrid", team_b="Barcelona"))
        db.add(Match(match_id="b1", date_wib=date(2026, 7, 19), sport="basketball", competition="WNBA",
                     event_name="Las Vegas Aces vs New York Liberty", kickoff_wib=datetime(2026, 7, 19, 23, 0),
                     team_a="Las Vegas Aces", team_b="New York Liberty"))
        db.add(Match(match_id="f3", date_wib=date(2026, 7, 20), sport="football", competition="Premier League",
                     event_name="England Friendly: France vs England", kickoff_wib=datetime(2026, 7, 20, 12, 0),
                     team_a="France", team_b="England"))
        db.commit()
    return TestClient(app, base_url="https://testserver")


def test_search_matches_by_team_name_partial_case_insensitive(tmp_path):
    client = _search_matches_client(tmp_path)
    login(client)
    body = client.get("/matches", params={"search": "manchester"}).json()
    assert body["total"] == 1
    assert body["items"][0]["match_id"] == "f1"


def test_search_matches_by_individual_name_via_event_field(tmp_path):
    """Searching 'France' should match event_name even though team_a/b are 'France' too."""
    client = _search_matches_client(tmp_path)
    login(client)
    body = client.get("/matches", params={"search": "france"}).json()
    assert body["total"] == 1
    assert body["items"][0]["match_id"] == "f3"


def test_search_matches_by_competition_name(tmp_path):
    client = _search_matches_client(tmp_path)
    login(client)
    body = client.get("/matches", params={"search": "premier"}).json()
    assert body["total"] == 2  # f1 and f3 both Premier League


def test_search_empty_query_returns_all_matches_in_window(tmp_path):
    client = _search_matches_client(tmp_path)
    login(client)
    body_no_search = client.get("/matches").json()
    body_empty_search = client.get("/matches", params={"search": ""}).json()
    assert body_no_search["total"] == body_empty_search["total"] == 4


def test_search_no_results_returns_empty_list_not_error(tmp_path):
    client = _search_matches_client(tmp_path)
    login(client)
    body = client.get("/matches", params={"search": "atlantis"}).json()
    assert body["items"] == []
    assert body["total"] == 0
    assert isinstance(body["items"], list)


def test_search_combined_with_sport_filter(tmp_path):
    client = _search_matches_client(tmp_path)
    login(client)
    body = client.get("/matches", params={"search": "league", "sport": "football"}).json()
    assert body["total"] == 2  # Premier League × 2 football rows; WNBA is basketball so excluded
    assert all(m["sport"] == "football" for m in body["items"])


def test_prediction_details_and_metrics(tmp_path):
    client = make_client(tmp_path)
    login(client)
    prediction = client.get("/predictions/m1")
    assert prediction.status_code == 200
    assert prediction.json()["confidence_breakdown"] == {"form": 80}
    assert prediction.json()["DATA_SOURCE_DEGRADED"] is True
    assert prediction.json()["validation_status"] == "BENAR"
    assert "outcome_correct" not in prediction.json()
    assert "score_correct" not in prediction.json()
    assert client.get("/predictions/missing").status_code == 404
    metrics = client.get("/metrics/accuracy", params={"from": "2026-07-19", "to": "2026-07-20"})
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["evaluated_count"] == 1
    assert body["correct_count"] == 1
    assert body["partial_count"] == 0
    assert body["incorrect_count"] == 0
    assert body["excluded_count"] == 1
    assert body["strict_accuracy_percent"] == 100.0
    assert body["lenient_accuracy_percent"] == 100.0


def test_metrics_three_category_accuracy(tmp_path):
    client = make_client(tmp_path)
    app = client.app
    with app.state.SessionLocal() as db:
        db.add(Match(match_id="m3", date_wib=date(2026, 7, 19), sport="football", competition="Test", event_name="E vs F", kickoff_wib=datetime(2026, 7, 19, 12, 0), team_a="E", team_b="F"))
        db.add(Match(match_id="m4", date_wib=date(2026, 7, 19), sport="football", competition="Test", event_name="G vs H", kickoff_wib=datetime(2026, 7, 19, 13, 0), team_a="G", team_b="H"))
        db.add(PredictionResult(match_id="m3", source_record_id="r3", validation_status="SEBAGIAN_BENAR"))
        db.add(PredictionResult(match_id="m4", source_record_id="r4", validation_status="SALAH"))
        db.commit()
    login(client)
    body = client.get("/metrics/accuracy", params={"from": "2026-07-19", "to": "2026-07-20"}).json()
    assert body["evaluated_count"] == 3
    assert body["correct_count"] == 1
    assert body["partial_count"] == 1
    assert body["incorrect_count"] == 1
    assert body["excluded_count"] == 1
    assert body["strict_accuracy_percent"] == 33.33
    assert body["lenient_accuracy_percent"] == 66.67


def test_health_live_and_ready(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_direct_http_cors_and_cookie_flags(tmp_path):
    app, engine, _session_local = create_app(
        "sqlite://",
        pin_hash=hash_pin("123456"),
        testing=True,
        allowed_origins=["http://10.10.10.83:8100", "http://localhost:8100"],
        secure_cookies=False,
    )
    Base.metadata.create_all(engine)
    client = TestClient(app, base_url="http://testserver")

    preflight = client.options(
        "/auth/pin",
        headers={
            "Origin": "http://10.10.10.83:8100",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://10.10.10.83:8100"
    assert preflight.headers["access-control-allow-credentials"] == "true"

    login = client.post("/auth/pin", json={"pin": "123456"}, headers={"Origin": "http://10.10.10.83:8100"})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "samesite=lax" in cookie
    assert "secure" not in cookie
