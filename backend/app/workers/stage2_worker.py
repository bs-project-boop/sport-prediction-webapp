"""Stage 2 polling worker with raw evidence gathering only.

The worker collects source material and persists it as matrix evidence. It does
not synthesize tactical or motivational narratives; those fields remain for the
later Hermes narrative step.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import Match, MatrixAnalysis, PipelineJob
from app.services.sources import searxng

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 60
MAX_JOBS_PER_POLL = 10
RETRY_BACKOFF_MINUTES = (5, 15, 45)
SUPPORTED_SPORTS = {"football", "basketball", "nfl", "mma"}


def get_database_url() -> str:
    """Resolve the database URL using the existing worker convention."""
    url = os.getenv("SPORT_PREDICTION_DATABASE_URL")
    if url:
        return url
    from app.core.settings import Settings

    return Settings().database_url


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    job_id: str
    match_id: str | None
    attempt_count: int
    max_attempts: int


def make_session_factory() -> sessionmaker[Session]:
    """Create a PostgreSQL session factory for this standalone worker."""
    engine = create_engine(get_database_url(), pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def claim_next_job(session: Session) -> ClaimedJob | None:
    """Atomically claim one due Stage 2 job, skipping jobs locked elsewhere."""
    statement = (
        select(PipelineJob)
        .where(
            PipelineJob.stage == "stage2",
            PipelineJob.status == "pending",
            PipelineJob.scheduled_time <= func.now(),
        )
        .order_by(PipelineJob.scheduled_time.asc(), PipelineJob.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    row = session.execute(statement).scalars().first()
    if row is None:
        return None

    attempt_count = row.attempt_count + 1
    session.execute(
        update(PipelineJob)
        .where(PipelineJob.id == row.id)
        .values(status="in_progress", attempt_count=attempt_count, last_attempt_at=func.now())
    )
    session.flush()
    claimed = ClaimedJob(row.id, row.job_id, row.match_id, attempt_count, row.max_attempts)
    session.commit()
    LOGGER.info("stage2_job_claimed job_id=%s match_id=%s attempt=%s/%s", claimed.job_id, claimed.match_id, claimed.attempt_count, claimed.max_attempts)
    return claimed


def _raw_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the raw evidence contract exposed to matrix_analysis."""
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet") or r.get("content", "")}
            for r in results if isinstance(r, dict) and r.get("url")]


def run_evidence_gathering(
    job: ClaimedJob,
    session_factory: sessionmaker[Session],
) -> dict[str, Any]:
    """Gather raw SearXNG evidence for one supported two-party match.

    Six sequential searches can take roughly 150 seconds at the 25-second
    source timeout. That is acceptable for the T-2-hour Stage 2 worker and is
    intentionally not a real-time request path.
    """
    if not job.match_id:
        raise NotImplementedError("evidence gathering membutuhkan match_id")
    with session_factory() as session:
        match = session.execute(select(Match).where(Match.match_id == job.match_id)).scalar_one_or_none()
    if match is None:
        raise NotImplementedError(f"match {job.match_id} tidak ditemukan")
    sport = (match.sport or "").lower()
    if sport not in SUPPORTED_SPORTS:
        raise NotImplementedError(f"evidence gathering untuk sport {sport} belum didukung di scaffold ini")
    if not match.team_a or not match.team_b:
        raise NotImplementedError(f"evidence gathering untuk sport {sport} membutuhkan team_a/team_b")

    home, away = match.team_a, match.team_b
    competition = (match.competition or "").strip()
    search_context = " ".join(part for part in (sport, competition) if part)
    queries = {
        "home_injury": f"{home} {search_context} injury suspension latest",
        "away_injury": f"{away} {search_context} injury suspension latest",
        "home_form_last5": f"{home} {search_context} latest form last 5 matches",
        "away_form_last5": f"{away} {search_context} latest form last 5 matches",
        "h2h_results": f"{home} vs {away} {search_context} head to head",
        "lineup_notes": f"{home} {away} {search_context} lineup team news rotation",
    }
    gathered: dict[str, list[dict[str, Any]]] = {}
    for category, query in queries.items():
        # Deliberately sequential: six calls × 25s worst case is acceptable at T-2h.
        gathered[category] = _raw_results(searxng.search(query))

    home_injuries, away_injuries = gathered["home_injury"], gathered["away_injury"]
    total_results = sum(len(items) for items in gathered.values())
    return {
        "sport": sport,
        "home_injuries": home_injuries,
        "away_injuries": away_injuries,
        "home_suspensions": home_injuries,
        "away_suspensions": away_injuries,
        "home_form_last5": gathered["home_form_last5"],
        "away_form_last5": gathered["away_form_last5"],
        "h2h_results": gathered["h2h_results"],
        "lineup_notes": gathered["lineup_notes"],
        "sources_used": ["SearXNG"],
        "data_source_degraded": total_results < 3,
        "total_results": total_results,
    }


def mark_awaiting_narrative(session: Session, job: ClaimedJob, evidence: dict[str, Any]) -> None:
    """Upsert raw matrix evidence and leave narrative fields untouched."""
    row = session.execute(select(MatrixAnalysis).where(MatrixAnalysis.match_id == job.match_id)).scalar_one_or_none()
    if row is None:
        row = MatrixAnalysis(match_id=job.match_id, sport=evidence["sport"])
        session.add(row)
    for field in ("home_injuries", "away_injuries", "home_suspensions", "away_suspensions", "home_form_last5", "away_form_last5", "h2h_results", "lineup_notes"):
        setattr(row, field, evidence[field])
    row.sport = evidence["sport"]
    row.sources_used = evidence["sources_used"]
    row.data_source_degraded = evidence["data_source_degraded"]
    row.research_completed_at = func.now()
    session.flush()
    session.execute(update(PipelineJob).where(PipelineJob.id == job.id).values(status="awaiting_narrative", last_attempt_at=func.now()))
    session.commit()
    LOGGER.info("stage2_evidence_gathered job_id=%s match_id=%s total_results=%s degraded=%s", job.job_id, job.match_id, evidence["total_results"], evidence["data_source_degraded"])


def mark_failed(session: Session, job: ClaimedJob, error: Exception) -> None:
    """Record terminal failure without terminating the worker loop."""
    session.execute(update(PipelineJob).where(PipelineJob.id == job.id).values(status="failed", last_error=str(error)[:4000], last_attempt_at=func.now()))
    session.commit()
    LOGGER.error("stage2_job_failed job_id=%s match_id=%s error=%s", job.job_id, job.match_id, error)


def requeue_for_retry(session: Session, job: ClaimedJob, error: Exception) -> None:
    """Apply ADR-009 retry backoff for non-terminal transient failures."""
    if job.attempt_count >= job.max_attempts:
        mark_failed(session, job, error)
        return
    index = min(job.attempt_count - 1, len(RETRY_BACKOFF_MINUTES) - 1)
    session.execute(update(PipelineJob).where(PipelineJob.id == job.id).values(status="pending", last_error=str(error)[:4000], last_attempt_at=func.now(), scheduled_time=func.now() + timedelta(minutes=RETRY_BACKOFF_MINUTES[index])))
    session.commit()
    LOGGER.warning("stage2_job_requeued job_id=%s match_id=%s retry_at_plus_minutes=%s error=%s", job.job_id, job.match_id, RETRY_BACKOFF_MINUTES[index], error)


def process_claimed_job(session_factory: sessionmaker[Session], job: ClaimedJob) -> None:
    """Process one claimed job and isolate all per-job failures."""
    try:
        evidence = run_evidence_gathering(job, session_factory)
    except NotImplementedError as error:
        with session_factory() as session:
            mark_failed(session, job, error)
    except Exception as error:  # noqa: BLE001 - worker must survive per-job failures
        with session_factory() as session:
            requeue_for_retry(session, job, error)
    else:
        with session_factory() as session:
            mark_awaiting_narrative(session, job, evidence)


def run_once(session_factory: sessionmaker[Session], *, max_jobs: int = MAX_JOBS_PER_POLL) -> int:
    """Claim and process up to max_jobs due jobs once; return count claimed."""
    factory = session_factory
    claimed_count = 0
    while claimed_count < max_jobs:
        with factory() as session:
            job = claim_next_job(session)
        if job is None:
            break
        claimed_count += 1
        process_claimed_job(factory, job)
    LOGGER.info("stage2_poll_complete claimed_count=%s", claimed_count)
    return claimed_count


def run_forever(session_factory: sessionmaker[Session] | None = None) -> None:
    """Poll due jobs every 60 seconds until the process receives shutdown."""
    factory = session_factory or make_session_factory()
    while True:
        try:
            run_once(factory)
        except Exception:  # noqa: BLE001 - recover loop-level DB failures
            LOGGER.exception("stage2_poll_iteration_failed")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_forever()
