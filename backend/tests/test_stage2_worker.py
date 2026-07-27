from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Match, MatrixAnalysis, PipelineJob
import app.services.sources.searxng as searxng
import app.workers.stage2_worker as stage2_worker


def make_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_gathering_collects_six_categories_and_marks_aggregate_degraded(monkeypatch):
    factory = make_factory()
    with factory() as session:
        session.add(
            Match(
                match_id="football:test-home-away",
                date_wib=date(2026, 7, 27),
                sport="football",
                team_a="Home FC",
                team_b="Away FC",
            )
        )
        session.commit()
        job = PipelineJob(
            id=1,
            job_id="stage2:test",
            stage="stage2",
            match_id="football:test-home-away",
            scheduled_time=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )

    calls = []

    def fake_search(query, *, max_results=15, timeout=25):
        calls.append(query)
        if len(calls) == 1:
            return [{"title": "result", "url": "https://example/1", "content": "snippet"}]
        return []

    monkeypatch.setattr(searxng, "search", fake_search)

    evidence = stage2_worker.run_evidence_gathering(job, factory)

    assert len(calls) == 6
    assert all("football" in query for query in calls)
    assert evidence["sources_used"] == ["SearXNG"]
    assert evidence["data_source_degraded"] is True
    assert evidence["total_results"] == 1
    assert evidence["home_injuries"] == [{"title": "result", "url": "https://example/1", "snippet": "snippet"}]


def test_unsupported_sport_is_explicit(monkeypatch):
    factory = make_factory()
    with factory() as session:
        session.add(
            Match(
                match_id="tennis:test",
                date_wib=date(2026, 7, 27),
                sport="tennis",
                team_a="Player A",
                team_b="Player B",
            )
        )
        session.commit()
        job = PipelineJob(
            id=1,
            job_id="stage2:tennis-test",
            stage="stage2",
            match_id="tennis:test",
            scheduled_time=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )

    try:
        stage2_worker.run_evidence_gathering(job, factory)
    except NotImplementedError as error:
        assert "evidence gathering untuk sport tennis belum didukung" in str(error)
    else:
        raise AssertionError("unsupported sport must raise NotImplementedError")


def test_mark_awaiting_narrative_upserts_and_leaves_interpretive_fields_empty():
    factory = make_factory()
    with factory() as session:
        job = PipelineJob(
            id=1,
            job_id="stage2:test",
            stage="stage2",
            match_id="football:test-home-away",
            scheduled_time=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )
        session.add(job)
        session.commit()
        evidence = {
            "sport": "football",
            "home_injuries": [{"title": "a", "url": "u", "snippet": "s"}],
            "away_injuries": [],
            "home_suspensions": [],
            "away_suspensions": [],
            "home_form_last5": [],
            "away_form_last5": [],
            "h2h_results": [],
            "lineup_notes": [],
            "sources_used": ["SearXNG"],
            "data_source_degraded": True,
            "total_results": 1,
        }

        stage2_worker.mark_awaiting_narrative(session, job, evidence)
        row = session.query(MatrixAnalysis).one()
        refreshed_job = session.get(PipelineJob, job.id)

        assert row.home_injuries == evidence["home_injuries"]
        assert row.tactical_notes == []
        assert row.motivational is None
        assert row.venue_weather is None
        assert row.schedule_fatigue is None
        assert row.market_odds is None
        assert row.polymarket_data is None
        assert row.evidence_quality_score is None
        assert row.sources_used == ["SearXNG"]
        assert refreshed_job.status == "awaiting_narrative"
