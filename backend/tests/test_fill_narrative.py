from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Match, MatrixAnalysis, PipelineJob
from app.cli import fill_narrative


def make_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def seed_awaiting(factory):
    with factory() as session:
        session.add(
            Match(
                match_id="football:narrative-test",
                date_wib=date(2026, 7, 27),
                sport="football",
                team_a="Home FC",
                team_b="Away FC",
            )
        )
        session.add(
            PipelineJob(
                id=1,
                job_id="stage2:narrative-test",
                stage="stage2",
                match_id="football:narrative-test",
                status="awaiting_narrative",
                scheduled_time=datetime(2026, 7, 27, tzinfo=timezone.utc),
            )
        )
        session.add(
            MatrixAnalysis(
                match_id="football:narrative-test",
                sport="football",
                home_injuries=[{"title": "Home injury", "url": "https://example/home", "snippet": "home raw"}],
                away_injuries=[{"title": "Away injury", "url": "https://example/away", "snippet": "away raw"}],
                home_form_last5=[{"title": "Home form", "url": "https://example/form", "snippet": "form raw"}],
                h2h_results=[{"title": "H2H", "url": "https://example/h2h", "snippet": "h2h raw"}],
                lineup_notes=[{"title": "Lineup", "url": "https://example/lineup", "snippet": "lineup raw"}],
                sources_used=["SearXNG"],
                data_source_degraded=False,
            )
        )
        session.commit()


def test_list_returns_awaiting_job(capsys):
    factory = make_factory()
    seed_awaiting(factory)
    with factory() as session:
        assert fill_narrative.list_jobs(session) == 0
    output = capsys.readouterr().out
    assert "stage2:narrative-test" in output
    assert "Home FC" in output
    assert "Away FC" in output
    assert "awaiting_narrative" in output


def test_show_prints_all_evidence(capsys):
    factory = make_factory()
    seed_awaiting(factory)
    with factory() as session:
        assert fill_narrative.show_match(session, "football:narrative-test") == 0
    output = capsys.readouterr().out
    assert "home_injuries" in output
    assert "away_suspensions" in output
    assert "home_form_last5" in output
    assert "away_form_last5" in output
    assert "h2h_results" in output
    assert "lineup_notes" in output
    assert "https://example/h2h" in output
    assert "awaiting_narrative" in output


def test_fill_preview_does_not_change_database(capsys):
    factory = make_factory()
    seed_awaiting(factory)
    notes = '["note one", "note two"]'
    with factory() as session:
        assert fill_narrative.fill_match(session, "football:narrative-test", notes, "motivation", apply=False) == 0
        row = session.query(MatrixAnalysis).one()
        job = session.query(PipelineJob).one()
        assert row.tactical_notes == []
        assert row.motivational is None
        assert job.status == "awaiting_narrative"
    output = capsys.readouterr().out
    assert "PREVIEW" in output
    assert "completed" in output


def test_fill_apply_changes_only_narrative_and_status():
    factory = make_factory()
    seed_awaiting(factory)
    with factory() as session:
        before = session.query(MatrixAnalysis).one()
        evidence_before = {
            field: getattr(before, field)
            for field in fill_narrative.EVIDENCE_FIELDS
        }
        assert fill_narrative.fill_match(
            session,
            "football:narrative-test",
            json.dumps(["note one", "note two"]),
            "motivation",
            apply=True,
        ) == 0
        session.expire_all()
        after = session.query(MatrixAnalysis).one()
        job = session.query(PipelineJob).one()
        assert after.tactical_notes == ["note one", "note two"]
        assert after.motivational == "motivation"
        assert job.status == "completed"
        assert job.completed_at is not None
        assert {field: getattr(after, field) for field in fill_narrative.EVIDENCE_FIELDS} == evidence_before


def test_fill_rejects_non_awaiting_status(capsys):
    factory = make_factory()
    seed_awaiting(factory)
    with factory() as session:
        session.query(PipelineJob).one().status = "completed"
        session.commit()
        with pytest.raises(fill_narrative.NarrativeError, match="completed"):
            fill_narrative.fill_match(
                session,
                "football:narrative-test",
                '["note"]',
                "motivation",
                apply=True,
            )
    assert capsys.readouterr().out == ""
