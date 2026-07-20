from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_pin, verify_pin
from app.main import create_app
from app.models import Base, Match, Prediction


def make_client(tmp_path, pin: str = "123456"):
    """Create a test client with in-memory SQLite and a known PIN hash."""
    h = hash_pin(pin)
    app, engine, SessionLocal = create_app(
        "sqlite://",
        pin_hash=h,
        testing=True,
        secure_cookies=False,
    )
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Match(
            match_id="m1", date_wib=date(2026, 7, 19), sport="football",
            competition="Test", event_name="A vs B",
            kickoff_wib=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
            team_a="A", team_b="B",
        ))
        db.add(Prediction(
            match_id="m1", source_record_id="p1",
            predicted_outcome="A_win", confidence_percent=72,
            confidence_breakdown={"form": 80}, no_pick=False,
            data_source_degraded=False, accuracy_excluded=False,
        ))
        db.commit()
    return TestClient(app, base_url="http://testserver"), app, h


def login(client: TestClient, pin: str = "123456") -> None:
    r = client.post("/auth/pin", json={"pin": pin})
    assert r.status_code == 200, f"login failed: {r.text}"
    assert "sport_session" in r.cookies


class TestChangePinRequiresSession:
    def test_unauthenticated_returns_401(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        r = client.patch(
            "/auth/pin",
            json={"current_pin": "123456", "new_pin": "654321"},
        )
        assert r.status_code == 401


class TestChangePinVerification:
    def test_wrong_current_pin_returns_403(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        login(client)
        r = client.patch(
            "/auth/pin",
            json={"current_pin": "000000", "new_pin": "654321"},
        )
        assert r.status_code == 403
        assert "incorrect" in r.json()["detail"].lower()


class TestChangePinSuccess:
    def test_correct_current_pin_updates_hash(self, tmp_path):
        client, app, original_hash = make_client(tmp_path, pin="123456")
        login(client)

        r = client.patch(
            "/auth/pin",
            json={"current_pin": "123456", "new_pin": "654321"},
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"

        # Hash must have changed in app state
        assert app.state.pin_hash != original_hash

        # New PIN must verify against the new hash
        assert verify_pin("654321", app.state.pin_hash)

        # Old PIN must no longer verify
        assert not verify_pin("123456", app.state.pin_hash)

    def test_new_session_cookie_set_after_pin_change(self, tmp_path):
        client, app, _ = make_client(tmp_path)
        login(client)
        old_cookie = client.cookies.get("sport_session")

        r = client.patch(
            "/auth/pin",
            json={"current_pin": "123456", "new_pin": "654321"},
        )
        assert r.status_code == 200
        # Session token is rotated; new cookie must differ
        new_cookie = r.cookies.get("sport_session") or client.cookies.get("sport_session")
        assert new_cookie != old_cookie, "session should be rotated after PIN change"

    def test_can_login_with_new_pin_after_change(self, tmp_path):
        client, app, _ = make_client(tmp_path, pin="123456")
        login(client)
        client.patch(
            "/auth/pin",
            json={"current_pin": "123456", "new_pin": "654321"},
        )

        # Old PIN no longer works
        r_old = client.post("/auth/pin", json={"pin": "123456"})
        assert r_old.status_code == 401

        # New PIN works
        r_new = client.post("/auth/pin", json={"pin": "654321"})
        assert r_new.status_code == 200
        assert "sport_session" in r_new.cookies


class TestChangePinValidation:
    @pytest.mark.parametrize("bad_pin", ["12345", "1234567", "abcdef", "12345a", "12 456", ""])
    def test_rejects_invalid_pin_format(self, tmp_path, bad_pin: str):
        client, _, _ = make_client(tmp_path)
        login(client)
        r = client.patch(
            "/auth/pin",
            json={"current_pin": "123456", "new_pin": bad_pin},
        )
        assert r.status_code == 422, f"expected 422 for {bad_pin!r}, got {r.status_code}"

    def test_missing_current_pin_returns_422(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        login(client)
        r = client.patch(
            "/auth/pin",
            json={"new_pin": "654321"},
        )
        assert r.status_code == 422

    def test_missing_new_pin_returns_422(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        login(client)
        r = client.patch(
            "/auth/pin",
            json={"current_pin": "123456"},
        )
        assert r.status_code == 422


class TestChangePinRateLimit:
    def test_rate_limited_after_too_many_bad_attempts(self, tmp_path):
        """
        The existing rate limiter on auth/pin also applies to PATCH /auth/pin.
        After 3 failed attempts, the key is blocked and further requests return 429.
        """
        client, app, _ = make_client(tmp_path)
        login(client)

        # Use a helper to reach into app state for testing purposes
        # First exhaust the limiter on PATCH /auth/pin itself (different key = same limiter)
        # We simulate by directly manipulating rate limiter to near-limit
        limiter = app.state.rate_limiter
        key = "testclient"
        # Set near limit
        for _ in range(limiter.max_failures):
            limiter.record_failure(key)
        r = client.patch(
            "/auth/pin",
            json={"current_pin": "000000", "new_pin": "111111"},
        )
        assert r.status_code == 429, f"expected 429 after exhausted attempts, got {r.status_code}"
