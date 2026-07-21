# test_discovery.py — Stage 1 Discovery Service Tests
# TDD: Tests are written BEFORE implementation (RED state first).
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Imports from the code under test
from app.services.discovery import (
    WIB,
    classify_endpoint_probe,
    compute_utc_bucket_window,
    slug_key,
)
from app.services.espn_client import (
    normalize_event,
)
from app.services.external_apis.motogp_client import (
    fetch_motogp_pulselive,
)
from app.services.external_apis.euroleague_client import (
    fetch_euroleague_official,
)
from app.services.external_apis.fiba_client import (
    fetch_fiba_official,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def make_wib(dt: datetime) -> datetime:
    """Ensure a datetime is in WIB timezone."""
    return dt.astimezone(WIB)


WIB_TZ = timezone(timedelta(hours=7))


@pytest.fixture
def sample_espn_event():
    """Minimal ESPN scoreboard event structure."""
    return {
        "id": "401123456",
        "date": "2026-07-22T14:00:00Z",
        "name": "Manchester United vs Liverpool",
        "shortName": "MAN UTD vs LIV",
        "competitions": [{
            "id": "401123456",
            "status": {"type": {"description": "Scheduled"}},
            "venue": {"fullName": "Old Trafford"},
            "competitors": [
                {"id": "1", "team": {"name": "Manchester United", "shortName": "Man Utd", "location": "Manchester"}},
                {"id": "2", "team": {"name": "Liverpool", "shortName": "Liverpool", "location": "Liverpool"}},
            ],
        }],
        "league": {"slug": "eng.1"},
    }


@pytest.fixture
def window_bounds():
    """Standard 48h WIB window for 2026-07-22."""
    target = datetime(2026, 7, 22).replace(tzinfo=WIB_TZ)
    start = datetime.combine(target.date(), datetime.min.time(), tzinfo=WIB_TZ)
    end = start + timedelta(hours=48)
    return start, end


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestUtcBucketWindowCalculation:
    """Verifies window -6h s/d +24h UTC dari 00:00 WIB dihitung benar.

    This covers the "dini hari WIB" bug found in audit A.5 where matches
    starting at 01:00-06:00 WIB were missed because the UTC date bucket
    only covered date-1/date/date+1 without the -6h shift.
    """

    def test_window_start_is_midnight_wib(self):
        start, end = compute_utc_bucket_window("2026-07-22")
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0
        # WIB midnight = UTC previous day 17:00
        assert start.utcoffset() == timedelta(hours=7)

    def test_window_covers_late_night_wib_events(self):
        # 01:00 WIB on target day = 18:00 UTC previous day (should be in window)
        start, end = compute_utc_bucket_window("2026-07-22")
        late_night = datetime(2026, 7, 22, 1, 0, tzinfo=WIB_TZ)
        assert start <= late_night < end, "01:00 WIB should be inside window"

    def test_window_covers_early_morning_wib_events(self):
        # 05:30 WIB on target day (should be inside)
        start, end = compute_utc_bucket_window("2026-07-22")
        early_am = datetime(2026, 7, 22, 5, 30, tzinfo=WIB_TZ)
        assert start <= early_am < end, "05:30 WIB should be inside window"

    def test_window_excludes_events_too_far_in_future(self):
        # 48h window: 2026-07-22 00:00 → 2026-07-24 00:00
        # 2026-07-24 00:30 is outside (>= end)
        start, end = compute_utc_bucket_window("2026-07-22")
        too_late = datetime(2026, 7, 24, 0, 30, tzinfo=WIB_TZ)
        assert not (start <= too_late < end), "T+24h30m should be outside window"

    def test_window_48h_duration(self):
        start, end = compute_utc_bucket_window("2026-07-22")
        assert (end - start) == timedelta(hours=48)

    def test_date_today_is_midnight_wib(self):
        # When called with no date (today), start should be today's midnight WIB
        # This is non-deterministic so we check the property, not the value
        start, end = compute_utc_bucket_window()
        assert start.hour == 0
        assert start.minute == 0
        assert (end - start) == timedelta(hours=48)


class TestEspnFetchSuccessParsesFixtures:
    """Mock ESPN response, verify parsing is correct."""

    def test_normalize_event_extracts_all_fields(self, sample_espn_event):
        result = normalize_event(sample_espn_event, "football", "Premier League")
        assert result["sport"] == "football"
        assert result["competition"] == "Premier League"
        assert result["team_a"] == "Manchester United"
        assert result["team_b"] == "Liverpool"
        assert "kickoff_wib" in result
        assert "kickoff_utc" in result
        assert result["status"] == "Scheduled"

    def test_normalize_event_handles_missing_venue(self):
        ev = {
            "id": "1",
            "date": "2026-07-22T14:00:00Z",
            "competitions": [{
                "competitors": [
                    {"team": {"name": "Team A"}},
                    {"team": {"name": "Team B"}},
                ],
            }],
        }
        result = normalize_event(ev, "football", "Test League")
        assert result["venue"] == ""

    def test_normalize_event_returns_none_for_missing_competitors(self):
        ev = {"id": "1", "date": "2026-07-22T14:00:00Z", "competitions": [{"competitors": []}]}
        assert normalize_event(ev, "football", "Test") is None

    def test_slug_key_is_deterministic(self, sample_espn_event):
        result = normalize_event(sample_espn_event, "football", "Premier League")
        key1 = slug_key(result)
        key2 = slug_key(result)
        assert key1 == key2
        # Key should be URL-safe
        assert re.match(r'^[a-z0-9_]+$', key1)


class TestEspnFetchFailureReturnsEmptyNotFabricated:
    """ESPN fails (500/timeout) -> return [] or raise, NEVER return fake data.

    This is the "never fabricate" safeguard from ADR-007.
    """

    def test_espn_fetch_timeout_returns_error_response_not_fabricated_events(self):
        """When ESPN API times out, the client returns {ok: False} — no fabricated events."""
        from app.services.espn_client import espn_fetch
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = espn_fetch("soccer/eng.1", "20260722", timeout=1)
        assert result["ok"] is False
        assert "error" in result
        assert result.get("data") is None

    def test_espn_fetch_500_returns_error_response(self):
        """HTTP 500 should be treated as failure, not a valid empty result."""
        from app.services.espn_client import espn_fetch
        import urllib.error
        from email.message import Message
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(url="", code=500, msg="Server Error", hdrs=Message(), fp=None)):
            result = espn_fetch("soccer/eng.1", "20260722")
        assert result["ok"] is False


class TestOkZeroEventsClassification:
    """Liga off-season, 0 event -> status 'ok_zero_events', NOT an error.

    The distinction: when ok_buckets is populated but events_in_window=0,
    that's off-season (ok_zero_events). When the probe never got any
    buckets (failed to connect), that's invalid/unsupported.
    """

    def test_events_present_is_ok(self):
        probe = {"ok_buckets": ["20260722"], "events_in_window": 5}
        assert classify_endpoint_probe(probe) == "ok"

    def test_degraded_flag_takes_precedence(self):
        probe = {"ok_buckets": ["20260722"], "events_in_window": 5, "DATA_SOURCE_DEGRADED": True}
        assert classify_endpoint_probe(probe) == "DATA_SOURCE_DEGRADED"

    def test_no_buckets_no_degraded_is_invalid(self):
        """No buckets returned = endpoint unreachable/unsupported = invalid."""
        probe = {"ok_buckets": [], "events_in_window": 0}
        assert classify_endpoint_probe(probe) == "endpoint_invalid_or_unsupported"

    def test_buckets_but_zero_events_is_ok_zero_events(self):
        """Got bucket responses but 0 events in window = off-season (not error)."""
        probe = {"ok_buckets": ["20260722", "20260723"], "events_in_window": 0}
        assert classify_endpoint_probe(probe) == "ok_zero_events"


class TestDiscoveryWritesStubMatchesToDb:
    """Match baru ditemukan -> insert ke tabel matches dengan status='scheduled'."""

    def test_discovery_insert_creates_pending_match(self, db_session, sample_espn_event):
        """Insert stub match -> DB row with status='scheduled'."""
        from app.services.discovery import DiscoveryService
        from app.models import Match

        svc = DiscoveryService(db_session)
        results = svc.run_discovery(target_date="2026-07-22")

        # Verify a football match was inserted (real ESPN API)
        match = db_session.query(Match).filter_by(sport="football").first()
        assert match is not None, "No football match found in DB"
        assert match.status == "Scheduled"  # ESPN returns title-case "Scheduled"
        assert match.team_a and match.team_b


class TestDiscoveryRegistersStage2Job:
    """Setiap match stub -> insert row ke pipeline_jobs dengan stage='stage2',
    scheduled_time = kickoff_wib - 2 hours.
    """

    def test_stage2_job_scheduled_T_minus_2_hours(self, db_session, sample_espn_event):
        from app.services.discovery import DiscoveryService
        from app.models import PipelineJob

        svc = DiscoveryService(db_session)
        with patch("app.services.espn_client.espn_fetch") as mock_fetch:
            mock_fetch.return_value = {
                "ok": True,
                "data": {"events": [sample_espn_event]},
                "url": "https://site.api.espn.com",
            }
            with patch("app.services.external_apis.motogp_client.fetch_motogp_pulselive") as mock_moto:
                mock_moto.return_value = ([], {})
                with patch("app.services.external_apis.euroleague_client.fetch_euroleague_official") as mock_el:
                    mock_el.return_value = ([], {})
                    with patch("app.services.external_apis.fiba_client.fetch_fiba_official") as mock_fiba:
                        mock_fiba.return_value = ([], {})
                        with patch("app.services.external_apis.ibl_client.fetch_ibl_official_html") as mock_ibl:
                            mock_ibl.return_value = ([], {})
                            with patch("app.services.external_apis.grand_slam_client.fetch_wimbledon_official") as mock_wim:
                                mock_wim.return_value = ([], {})
                                with patch("app.services.external_apis.grand_slam_client.fetch_us_open_official") as mock_us:
                                    mock_us.return_value = ([], {})
                                    with patch("app.services.external_apis.grand_slam_client.fetch_australian_open_official") as mock_ao:
                                        mock_ao.return_value = ([], {})
                                        with patch("app.services.external_apis.grand_slam_client.fetch_roland_garros_official") as mock_rg:
                                            mock_rg.return_value = ([], {})
                                            results = svc.run_discovery(target_date="2026-07-22")

        # ESPN LEAGUE_CONFIG has 18+ entries, each fetch returns the same mock event.
        # Different competitions / kickoffs across paths → multiple distinct slugs → multiple jobs.
        jobs = db_session.query(PipelineJob).filter_by(stage="stage2").all()
        assert len(jobs) >= 1
        # Regression: each event must produce a distinct pipeline_job. The bug being
        # guarded against was reusing the dedup-loop variable `k` outside its scope,
        # which collapsed all registrations to the same job_id (and made second runs
        # falsely "idempotent" — they'd skip every event).
        job_ids = {j.job_id for j in jobs}
        assert len(job_ids) == len(jobs), (
            f"Duplicate pipeline_job.job_id found — registration loop is reusing "
            f"a single slug: {sorted(job_ids)}"
        )
        # Find the Premier League job (sample_espn_event fixture)
        pl_job = next((j for j in jobs if "premier_league" in j.job_id), None)
        assert pl_job is not None, f"Premier League job not found in {[j.job_id for j in jobs[:3]]}"
        # kickoff: 2026-07-22T14:00:00Z = 2026-07-22T21:00 WIB → T-2h = 2026-07-22T19:00 WIB
        # Compare as naive UTC for SQLite compatibility
        assert pl_job.scheduled_time.replace(tzinfo=None) == datetime(2026, 7, 22, 19, 0)


class TestDiscoverySkipsExistingResearchedMatch:
    """Match yang sudah pernah di-discover (existing row) -> tidak duplicate,
    tidak overwrite data yang sudah ada (idempotent).
    """

    def test_discovery_is_idempotent_on_existing_match(self, db_session, sample_espn_event):
        """Existing researched match -> not duplicated, evidence preserved."""
        from app.services.discovery import DiscoveryService, slug_key
        from app.models import Match

        svc = DiscoveryService(db_session)
        norm = normalize_event(sample_espn_event, "football", "Premier League")
        match_id = slug_key(norm)

        # Pre-seed existing researched match
        existing = Match(
            match_id=match_id,
            date_wib=datetime(2026, 7, 22).date(),
            sport="football",
            event_name=norm["event"],
            competition="Premier League",
            team_a=norm["team_a"],
            team_b=norm["team_b"],
            status="scheduled",
            raw_document={"researched": True, "evidence_url": "http://existing.com"},
        )
        db_session.add(existing)
        db_session.commit()

        results = svc.run_discovery(target_date="2026-07-22")

        # Evidence preserved — discovery is idempotent
        match = db_session.query(Match).filter_by(match_id=match_id).first()
        assert match is not None
        assert match.raw_document.get("evidence_url") == "http://existing.com"
        # No duplicate rows for same match_id
        count = db_session.query(Match).filter_by(match_id=match_id).count()
        assert count == 1, f"Expected 1 row for match_id={match_id}, got {count}"


class TestExternalApiSourceSpecificClient:
    """Test for at least 3 of 5 external API clients (MotoGP, EuroLeague, FIBA)."""

    def test_motogp_fetch_returns_empty_on_api_failure(self):
        from app.services.external_apis.motogp_client import fetch_motogp_pulselive
        with patch("urllib.request.urlopen", side_effect=Exception("network unreachable")):
            start = datetime(2026, 7, 22, 0, 0, tzinfo=WIB_TZ)
            end = start + timedelta(hours=48)
            events, probe = fetch_motogp_pulselive("2026-07-22", start, end)
        assert events == []
        assert len(probe["failed_buckets"]) > 0

    def test_motogp_fetch_returns_events_in_window(self):
        import json
        from app.services.external_apis.motogp_client import fetch_motogp_pulselive

        # Build a minimal MotoGP session JSON response
        def mock_urlopen(req, **kwargs):
            url = req.full_url
            if "seasons" in url:
                body = json.dumps([{"id": "s1", "year": 2026, "current": True}]).encode()
            elif "categories" in url:
                body = json.dumps([{"id": "c1", "name": "MotoGP"}]).encode()
            elif "isFinished" in url:
                body = json.dumps([{
                    "id": "e1", "name": "GP", "sponsored_name": "Dutch TT",
                    "date_start": "2026-06-01", "date_end": "2026-06-30",
                    "circuit": {"name": "Assen"}
                }]).encode()
            elif "sessions" in url:
                body = json.dumps([{
                    "id": "sess1", "type": "RACE", "name": "Race",
                    "date": "2026-07-22T10:00:00Z", "circuit": "Assen"
                }]).encode()
            else:
                body = b"{}"
            # Fake HTTP response that works as context manager
            class FakeResp:
                def __init__(self, b): self._b = b
                def read(self): return self._b
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return FakeResp(body)

        with patch("urllib.request.urlopen", mock_urlopen):
            start = datetime(2026, 7, 22, 0, 0, tzinfo=WIB_TZ)
            end = start + timedelta(hours=48)
            events, probe = fetch_motogp_pulselive("2026-07-22", start, end)
        assert len(events) >= 1
        assert all("sport" in e and "competition" in e for e in events)

    def test_euroleague_fetch_returns_empty_on_failure(self):
        from app.services.external_apis.euroleague_client import fetch_euroleague_official
        with patch("app.services.external_apis.euroleague_client.http_json") as mock_http:
            mock_http.return_value = {"ok": False, "error": "network error"}
            start = datetime(2026, 7, 22, 0, 0, tzinfo=WIB_TZ)
            end = start + timedelta(hours=48)
            events, probe = fetch_euroleague_official("2026-07-22", start, end)
        assert events == []
        assert len(probe["failed_buckets"]) == 1

    def test_fiba_fetch_returns_empty_on_401_degraded(self):
        import urllib.error
        from app.services.external_apis.fiba_client import fetch_fiba_official
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(url="", code=401, msg="Unauthorized", hdrs=__import__("email.message", fromlist=["Message"]).Message(), fp=None)):
            start = datetime(2026, 7, 22, 0, 0, tzinfo=WIB_TZ)
            end = start + timedelta(hours=48)
            events, probe = fetch_fiba_official("2026-07-22", start, end)
        assert events == []
        assert probe.get("DATA_SOURCE_DEGRADED") is True
