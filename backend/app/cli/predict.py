"""Hermes hybrid Stage 3 prediction handoff CLI.

Usage (run from ``backend/`` with ``PYTHONPATH=.``)::

    python -m app.cli.predict list
    python -m app.cli.predict show <match_id>
    python -m app.cli.predict predict <match_id> --outcome home_win \
        --breakdown-json '{"form":65,"h2h":55,"player_condition":60,"home_away":70,"market_odds":50,"contextual":45}' \
        --reasoning-json '["reason 1", "reason 2"]' \
        --predicted-score "2-1" [--apply]

The command previews by default. ``--apply`` is required for writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Match, MatrixAnalysis, PipelineJob, Prediction
from app.services.confidence import CONFIDENCE_FACTORS, calculate_confidence, confidence_label
from app.workers.stage2_worker import make_session_factory

SUPPORTED_SPORTS = {"football", "basketball", "nfl", "mma"}
EVIDENCE_FIELDS = (
    "home_injuries", "away_injuries", "home_suspensions", "away_suspensions",
    "home_form_last5", "away_form_last5", "h2h_results", "lineup_notes",
)
OUTCOMES = {"home_win", "away_win", "draw"}


class PredictionError(ValueError):
    """Raised when a Stage 3 prediction handoff is unsafe."""


def _pretty(value: Any) -> str:
    return json.dumps(value if value is not None else [], indent=2, ensure_ascii=False, default=str)


def _stage2_jobs(session: Session, match_id: str) -> list[PipelineJob]:
    return list(session.execute(
        select(PipelineJob)
        .where(PipelineJob.stage == "stage2", PipelineJob.match_id == match_id)
        .order_by(PipelineJob.created_at.asc(), PipelineJob.id.asc())
    ).scalars())


def _match_context(session: Session, match_id: str) -> tuple[Match, MatrixAnalysis]:
    row = session.execute(
        select(Match, MatrixAnalysis)
        .join(MatrixAnalysis, MatrixAnalysis.match_id == Match.match_id)
        .where(Match.match_id == match_id)
    ).one_or_none()
    if row is None:
        raise PredictionError(f"tidak ada match/matrix_analysis untuk match_id: {match_id}")
    return row


def _existing_prediction(session: Session, match_id: str) -> Prediction | None:
    return session.execute(select(Prediction).where(Prediction.match_id == match_id)).scalar_one_or_none()


def list_ready(session: Session) -> int:
    rows = session.execute(
        select(PipelineJob, Match, Prediction)
        .join(Match, Match.match_id == PipelineJob.match_id)
        .outerjoin(Prediction, Prediction.match_id == PipelineJob.match_id)
        .where(PipelineJob.stage == "stage2", PipelineJob.status == "completed")
        .order_by(PipelineJob.completed_at.asc(), PipelineJob.id.asc())
    ).all()
    ready = [
        (job, match, prediction) for job, match, prediction in rows
        if prediction is None or prediction.pipeline_stage != "stage3" or not prediction.prediction_eligible
    ]
    if not ready:
        print("Tidak ada match yang siap untuk Stage 3.")
        return 0
    print("match_id | sport | team_a | team_b | stage2_completed_at | prediction_state")
    print("---------+-------+--------+--------+---------------------+-----------------")
    for job, match, prediction in ready:
        state = "missing" if prediction is None else f"pipeline_stage={prediction.pipeline_stage or '-'}, eligible={prediction.prediction_eligible}"
        print(f"{match.match_id} | {match.sport} | {match.team_a or '-'} | {match.team_b or '-'} | {job.completed_at or '-'} | {state}")
    return 0


def show_match(session: Session, match_id: str) -> int:
    match, matrix = _match_context(session, match_id)
    prediction = _existing_prediction(session, match_id)
    print(f"match_id: {match.match_id}")
    print(f"sport: {match.sport}")
    print(f"team_a: {match.team_a or '-'}")
    print(f"team_b: {match.team_b or '-'}")
    print("stage2_jobs:")
    for job in _stage2_jobs(session, match_id):
        print(f"  job_id={job.job_id} status={job.status} completed_at={job.completed_at} last_error={job.last_error or '-'}")
    print("prediction:")
    if prediction is None:
        print("  <missing>")
    else:
        print(f"  id={prediction.id} source_record_id={prediction.source_record_id} pipeline_stage={prediction.pipeline_stage or '-'}")
        print(f"  predicted_outcome={prediction.predicted_outcome or '-'} confidence_percent={prediction.confidence_percent or '-'} validation_status={prediction.validation_status or '-'}")
        print(f"  prediction_eligible={prediction.prediction_eligible} no_pick={prediction.no_pick}")
        print(f"  reasoning={_pretty(prediction.reasoning)}")
    print("matrix_analysis:")
    print(f"  data_source_degraded: {matrix.data_source_degraded}")
    print(f"  sources_used: {_pretty(matrix.sources_used)}")
    print(f"  research_completed_at: {matrix.research_completed_at}")
    for field in EVIDENCE_FIELDS:
        print(f"\n{field}:")
        print(_pretty(getattr(matrix, field)))
    print("\ntactical_notes:")
    print(_pretty(matrix.tactical_notes))
    print("\nmotivational:")
    print(matrix.motivational if matrix.motivational is not None else "NULL")
    return 0


def _parse_breakdown(raw: str) -> dict[str, float]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PredictionError(f"--breakdown-json bukan JSON valid: {error.msg}") from error
    if not isinstance(value, dict):
        raise PredictionError("--breakdown-json harus berupa JSON object")
    actual = set(value)
    expected = set(CONFIDENCE_FACTORS)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing: details.append(f"missing keys={missing}")
        if extra: details.append(f"extra keys={extra}")
        raise PredictionError("--breakdown-json harus berisi persis 6 key: " + "; ".join(details))
    result: dict[str, float] = {}
    invalid: list[str] = []
    for key in CONFIDENCE_FACTORS:
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 100:
            invalid.append(f"{key}={item!r}")
        else:
            result[key] = float(item)
    if invalid:
        raise PredictionError("nilai breakdown harus numerik 0-100: " + ", ".join(invalid))
    return result


def _parse_reasoning(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PredictionError(f"--reasoning-json bukan JSON valid: {error.msg}") from error
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise PredictionError("--reasoning-json harus berupa JSON array string yang tidak kosong")
    return value


def _validate_stage2_ready(session: Session, match_id: str) -> PipelineJob:
    jobs = _stage2_jobs(session, match_id)
    completed = [job for job in jobs if job.status == "completed"]
    if len(completed) != 1:
        actual = ", ".join(f"{job.job_id}={job.status}" for job in jobs) or "tidak ada job stage2"
        raise PredictionError(f"match_id {match_id} belum siap Stage 3: status aktual {actual}; wajib persis completed")
    return completed[0]


def predict_match(
    session: Session,
    match_id: str,
    outcome: str,
    breakdown_json: str,
    reasoning_json: str,
    predicted_score: str | None = None,
    *,
    apply: bool = False,
) -> int:
    _validate_stage2_ready(session, match_id)
    match, matrix = _match_context(session, match_id)
    if matrix.sport not in SUPPORTED_SPORTS:
        raise PredictionError(f"sport {matrix.sport} tidak didukung Stage 3")
    existing = _existing_prediction(session, match_id)
    if existing is not None and existing.pipeline_stage == "stage3":
        raise PredictionError(f"match_id {match_id} sudah pernah diproses Stage 3: pipeline_stage=stage3")
    if outcome not in OUTCOMES:
        raise PredictionError(f"--outcome tidak valid: {outcome}; pilih salah satu {sorted(OUTCOMES)}")
    breakdown = _parse_breakdown(breakdown_json)
    reasoning = _parse_reasoning(reasoning_json)
    confidence, weights, penalty = calculate_confidence(session, matrix.sport, breakdown, bool(matrix.data_source_degraded))
    no_pick = confidence < 40
    final_outcome = "NO_PICK" if no_pick else outcome
    no_pick_reason = "confidence_below_40" if no_pick else None
    final_score = predicted_score or "—"
    if no_pick and not predicted_score:
        final_score = "—"
    confidence_breakdown = {**breakdown, "weights_used": weights, "penalty_applied": penalty}

    print("PREVIEW" if not apply else "APPLY")
    print(f"match_id: {match_id}")
    print(f"predicted_outcome: {final_outcome}")
    print(f"predicted_score_or_result: {final_score}")
    print(f"confidence_percent: {confidence}")
    print(f"confidence_label: {confidence_label(confidence)}")
    print(f"confidence_breakdown: {_pretty(confidence_breakdown)}")
    print(f"no_pick: {no_pick}")
    print(f"no_pick_reason: {no_pick_reason or 'NULL'}")
    print(f"data_source_degraded: {bool(matrix.data_source_degraded)}")
    print(f"confidence_penalty_applied: {penalty}")
    print("confidence_model_version: fastapi-hybrid-v1")
    print("validation_status: PENDING")
    print(f"reasoning: {_pretty(reasoning)}")
    print("pipeline_stage: stage3")
    print(f"source_record_id: stage3:{match_id}")

    if not apply:
        return 0

    if existing is None:
        existing = Prediction(match_id=match_id, source_record_id=f"stage3:{match_id}")
        session.add(existing)
    existing.source_record_id = f"stage3:{match_id}"
    existing.predicted_outcome = final_outcome
    existing.predicted_score_or_result = final_score
    existing.confidence_percent = confidence
    existing.confidence_label = confidence_label(confidence)
    existing.confidence_breakdown = confidence_breakdown
    existing.confidence_model_version = "fastapi-hybrid-v1"
    existing.no_pick = no_pick
    existing.no_pick_reason = no_pick_reason
    existing.data_source_degraded = bool(matrix.data_source_degraded)
    existing.confidence_penalty_applied = penalty
    existing.prediction_eligible = not no_pick
    existing.accuracy_excluded = no_pick
    existing.validation_status = "PENDING"
    existing.reasoning = reasoning
    existing.pipeline_stage = "stage3"
    session.commit()
    print(f"Prediction berhasil di-apply; prediction_id={existing.id}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes hybrid Stage 3 prediction CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list matches ready for Stage 3")
    show = sub.add_parser("show", help="show evidence, narrative, and prediction")
    show.add_argument("match_id")
    pred = sub.add_parser("predict", help="preview or apply a Hermes judgment")
    pred.add_argument("match_id")
    pred.add_argument("--outcome", required=True)
    pred.add_argument("--breakdown-json", required=True)
    pred.add_argument("--reasoning-json", required=True)
    pred.add_argument("--predicted-score")
    pred.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        factory = make_session_factory()
        with factory() as session:
            if args.command == "list":
                return list_ready(session)
            if args.command == "show":
                return show_match(session, args.match_id)
            return predict_match(session, args.match_id, args.outcome, args.breakdown_json, args.reasoning_json, args.predicted_score, apply=args.apply)
    except PredictionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
