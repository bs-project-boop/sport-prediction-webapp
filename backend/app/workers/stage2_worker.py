"""Stage 2 polling worker scaffold.

This module deliberately contains no evidence-gathering implementation yet.
The worker claims due Stage 2 jobs safely, records the placeholder failure, and
keeps polling without allowing one job error to terminate the process.
"""
from __future__ import annotations

import time
import logging
import os
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import PipelineJob

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 60
MAX_JOBS_PER_POLL = 10
RETRY_BACKOFF_MINUTES = (5, 15, 45)
PLACEHOLDER_ERROR = (
    "Stage 2 evidence gathering belum diimplementasikan — "
    "lihat roadmap M2 step 4"
)

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
        .values(
            status="in_progress",
            attempt_count=attempt_count,
            last_attempt_at=func.now(),
        )
    )
    session.flush()
    claimed = ClaimedJob(
        id=row.id,
        job_id=row.job_id,
        match_id=row.match_id,
        attempt_count=attempt_count,
        max_attempts=row.max_attempts,
    )
    session.commit()
    LOGGER.info(
        "stage2_job_claimed job_id=%s match_id=%s attempt=%s/%s",
        claimed.job_id,
        claimed.match_id,
        claimed.attempt_count,
        claimed.max_attempts,
    )
    return claimed


def run_evidence_gathering(job: ClaimedJob) -> None:
    """Placeholder for the separate per-sport evidence-gathering step."""
    raise NotImplementedError(PLACEHOLDER_ERROR)


def mark_completed(session: Session, job: ClaimedJob) -> None:
    """Mark a successfully processed job as completed."""
    session.execute(
        update(PipelineJob)
        .where(PipelineJob.id == job.id)
        .values(status="completed", completed_at=func.now())
    )
    session.commit()
    LOGGER.info("stage2_job_completed job_id=%s match_id=%s", job.job_id, job.match_id)


def mark_failed(session: Session, job: ClaimedJob, error: Exception) -> None:
    """Record terminal failure without terminating the worker loop."""
    session.execute(
        update(PipelineJob)
        .where(PipelineJob.id == job.id)
        .values(status="failed", last_error=str(error)[:4000], last_attempt_at=func.now())
    )
    session.commit()
    LOGGER.error(
        "stage2_job_failed job_id=%s match_id=%s error=%s",
        job.job_id,
        job.match_id,
        error,
    )


def requeue_for_retry(session: Session, job: ClaimedJob, error: Exception) -> None:
    """Apply ADR-009 retry backoff for non-terminal transient failures."""
    if job.attempt_count >= job.max_attempts:
        mark_failed(session, job, error)
        return
    index = min(job.attempt_count - 1, len(RETRY_BACKOFF_MINUTES) - 1)
    session.execute(
        update(PipelineJob)
        .where(PipelineJob.id == job.id)
        .values(
            status="pending",
            last_error=str(error)[:4000],
            last_attempt_at=func.now(),
            scheduled_time=func.now() + timedelta(minutes=RETRY_BACKOFF_MINUTES[index]),
        )
    )
    session.commit()
    LOGGER.warning(
        "stage2_job_requeued job_id=%s match_id=%s retry_at_plus_minutes=%s error=%s",
        job.job_id,
        job.match_id,
        RETRY_BACKOFF_MINUTES[index],
        error,
    )


def process_claimed_job(session_factory: sessionmaker[Session], job: ClaimedJob) -> None:
    """Process one claimed job and isolate all per-job failures."""
    try:
        run_evidence_gathering(job)
    except NotImplementedError as error:
        with session_factory() as session:
            mark_failed(session, job, error)
    except Exception as error:  # noqa: BLE001 - worker must survive per-job failures
        with session_factory() as session:
            requeue_for_retry(session, job, error)
    else:
        with session_factory() as session:
            mark_completed(session, job)


def run_once(
    session_factory: sessionmaker[Session] | None = None,
    *,
    max_jobs: int = MAX_JOBS_PER_POLL,
) -> int:
    """Claim and process up to ``max_jobs`` due jobs once; return count claimed."""
    factory = session_factory or make_session_factory()
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
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_forever()
