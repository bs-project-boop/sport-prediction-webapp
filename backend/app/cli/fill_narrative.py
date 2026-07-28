"""Hermes narrative handoff CLI for Stage 2 evidence.

Usage (run from ``backend/`` with ``PYTHONPATH=.``)::

    python -m app.cli.fill_narrative list
    python -m app.cli.fill_narrative show <match_id>
    python -m app.cli.fill_narrative fill <match_id> \
        --tactical-notes-json '["note 1", "note 2"]' \
        --motivational "motivational text"
    python -m app.cli.fill_narrative fill <match_id> \
        --tactical-notes-json '["note 1", "note 2"]' \
        --motivational "motivational text" --apply

The ``fill`` command previews by default. ``--apply`` is irreversible through
this CLI: there is no undo command. If the narrative is wrong, reset it
manually with a reviewed SQL UPDATE and restore the job status explicitly.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Match, MatrixAnalysis, PipelineJob
from app.workers.stage2_worker import make_session_factory

EVIDENCE_FIELDS = (
    "home_injuries",
    "away_injuries",
    "home_suspensions",
    "away_suspensions",
    "home_form_last5",
    "away_form_last5",
    "h2h_results",
    "lineup_notes",
)


class NarrativeError(ValueError):
    """Raised when a narrative handoff cannot be safely applied."""


def _pretty(value: Any) -> str:
    return json.dumps(value or [], indent=2, ensure_ascii=False, default=str)


def _related_jobs(session: Session, match_id: str) -> list[PipelineJob]:
    return list(
        session.execute(
            select(PipelineJob)
            .where(PipelineJob.stage == "stage2", PipelineJob.match_id == match_id)
            .order_by(PipelineJob.created_at.asc(), PipelineJob.id.asc())
        ).scalars()
    )


def list_jobs(session: Session) -> int:
    """Print Stage 2 jobs waiting for Hermes narrative completion."""
    rows = session.execute(
        select(PipelineJob, Match, MatrixAnalysis)
        .join(Match, Match.match_id == PipelineJob.match_id)
        .join(MatrixAnalysis, MatrixAnalysis.match_id == PipelineJob.match_id)
        .where(
            PipelineJob.stage == "stage2",
            PipelineJob.status == "awaiting_narrative",
        )
        .order_by(MatrixAnalysis.research_completed_at.asc(), PipelineJob.id.asc())
    ).all()

    if not rows:
        print("Tidak ada job stage2 berstatus awaiting_narrative.")
        return 0

    print("job_id | match_id | sport | team_a | team_b | status | research_completed_at")
    print("-------+----------+-------+--------+--------+--------------------+-----------------------")
    for job, match, matrix in rows:
        print(
            f"{job.job_id} | {job.match_id} | {match.sport} | "
            f"{match.team_a or '-'} | {match.team_b or '-'} | {job.status} | "
            f"{matrix.research_completed_at or '-'}"
        )
    return 0


def show_match(session: Session, match_id: str) -> int:
    """Print all raw evidence and related Stage 2 job statuses."""
    row = session.execute(
        select(MatrixAnalysis).where(MatrixAnalysis.match_id == match_id)
    ).scalar_one_or_none()
    if row is None:
        raise NarrativeError(f"tidak ada evidence untuk match_id ini: {match_id}")

    print(f"match_id: {row.match_id}")
    print(f"sport: {row.sport}")
    print(f"sources_used: {_pretty(row.sources_used)}")
    print(f"data_source_degraded: {row.data_source_degraded}")
    print(f"research_completed_at: {row.research_completed_at}")
    print("pipeline_jobs:")
    for job in _related_jobs(session, match_id):
        print(
            f"  job_id={job.job_id} status={job.status} "
            f"completed_at={job.completed_at} last_error={job.last_error or '-'}"
        )

    for field in EVIDENCE_FIELDS:
        print(f"\n{field}:")
        print(_pretty(getattr(row, field)))
    return 0


def _parse_notes(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise NarrativeError(
            f"--tactical-notes-json bukan JSON valid: {error.msg} "
            f"(line {error.lineno}, column {error.colno})"
        ) from error
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise NarrativeError(
            "--tactical-notes-json harus berupa JSON array yang seluruh elemennya string"
        )
    return parsed


def _awaiting_job(session: Session, match_id: str) -> PipelineJob:
    row = session.execute(
        select(MatrixAnalysis).where(MatrixAnalysis.match_id == match_id)
    ).scalar_one_or_none()
    if row is None:
        raise NarrativeError(f"tidak ada evidence untuk match_id ini: {match_id}")

    jobs = _related_jobs(session, match_id)
    awaiting = [job for job in jobs if job.status == "awaiting_narrative"]
    if len(awaiting) != 1:
        actual = ", ".join(f"{job.job_id}={job.status}" for job in jobs) or "tidak ada job stage2"
        raise NarrativeError(
            f"match_id {match_id} tidak siap diisi: status aktual {actual}; "
            "wajib persis awaiting_narrative"
        )
    return awaiting[0]


def fill_match(
    session: Session,
    match_id: str,
    tactical_notes_json: str,
    motivational: str,
    *,
    apply: bool = False,
) -> int:
    """Preview or apply the narrow narrative handoff."""
    job = _awaiting_job(session, match_id)
    notes = _parse_notes(tactical_notes_json)
    if not motivational.strip():
        raise NarrativeError("--motivational tidak boleh kosong")

    print("PREVIEW" if not apply else "APPLY")
    print(f"match_id: {match_id}")
    print(f"tactical_notes: {_pretty(notes)}")
    print(f"motivational: {motivational}")
    print("status akan berubah ke: completed")

    if not apply:
        return 0

    row = session.execute(
        select(MatrixAnalysis).where(MatrixAnalysis.match_id == match_id)
    ).scalar_one()
    row.tactical_notes = notes
    row.motivational = motivational
    session.execute(
        update(PipelineJob)
        .where(PipelineJob.id == job.id)
        .values(status="completed", completed_at=func.now())
    )
    session.commit()
    print(f"Narrative berhasil di-apply untuk {match_id}; job_id={job.job_id}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes narrative handoff CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list Stage 2 jobs awaiting narrative")

    show_parser = subparsers.add_parser("show", help="show raw evidence")
    show_parser.add_argument("match_id")

    fill_parser = subparsers.add_parser("fill", help="preview or apply narrative")
    fill_parser.add_argument("match_id")
    fill_parser.add_argument("--tactical-notes-json", required=True)
    fill_parser.add_argument("--motivational", required=True)
    fill_parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        factory = make_session_factory()
        with factory() as session:
            if args.command == "list":
                return list_jobs(session)
            if args.command == "show":
                return show_match(session, args.match_id)
            return fill_match(
                session,
                args.match_id,
                args.tactical_notes_json,
                args.motivational,
                apply=args.apply,
            )
    except NarrativeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
