from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import RateLimiter
from app.core.security import hash_pin, verify_pin
from app.core.sessions import SessionStore
from app.models import Base, Match, Prediction, PredictionResult
from app.schemas import MetricsResponse, PinRequest

SESSION_COOKIE = "sport_session"


def create_app(database_url: str | None = None, pin_hash: str | None = None, testing: bool = False):
    database_url = database_url or os.getenv("SPORT_PREDICTION_DATABASE_URL", "sqlite:///./sport-prediction.db")
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine_kwargs = {"connect_args": connect_args, "pool_pre_ping": True}
    if database_url == "sqlite://":
        engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_kwargs)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = FastAPI(title="Sport Prediction API", version="0.1.0")
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal
    app.state.pin_hash = pin_hash or os.getenv("SPORT_PREDICTION_PIN_HASH")
    app.state.rate_limiter = RateLimiter(max_failures=3 if testing else 5)
    app.state.sessions = SessionStore(ttl_seconds=3600)
    if testing:
        Base.metadata.create_all(engine)

    def db_session():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def current_session(request: Request, db: Session = Depends(db_session)):
        session = app.state.sessions.get(db, request.cookies.get(SESSION_COOKIE))
        if not session:
            raise HTTPException(status_code=401, detail="authentication required")
        return session

    @app.get("/health/live")
    def health_live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready(db: Session = Depends(db_session)):
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ready"}
        except Exception:
            raise HTTPException(status_code=503, detail="service unavailable")

    @app.post("/auth/pin")
    def auth_pin(payload: PinRequest, request: Request, response: Response, db: Session = Depends(db_session)):
        key = request.client.host if request.client else "unknown"
        limiter = app.state.rate_limiter
        if not limiter.allow(key):
            raise HTTPException(status_code=429, detail="temporarily unavailable")
        if not app.state.pin_hash or not verify_pin(payload.pin, app.state.pin_hash):
            limiter.record_failure(key)
            raise HTTPException(status_code=401, detail="invalid credentials")
        limiter.reset(key)
        token = app.state.sessions.create(db, key)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=True, samesite="lax", max_age=3600)
        return {"authenticated": True}

    @app.post("/auth/logout")
    def auth_logout(request: Request, response: Response, db: Session = Depends(db_session)):
        app.state.sessions.revoke(db, request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE)
        return {"logged_out": True}

    @app.get("/matches")
    def list_matches(
        request: Request,
        from_date: date | None = Query(default=None, alias="from"),
        to_date: date | None = Query(default=None, alias="to"),
        sport: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        db: Session = Depends(db_session),
        _: object = Depends(current_session),
    ):
        query = select(Match)
        if from_date:
            query = query.where(Match.date_wib >= from_date)
        if to_date:
            query = query.where(Match.date_wib <= to_date)
        if sport:
            query = query.where(Match.sport == sport)
        rows = db.scalars(query.order_by(Match.date_wib, Match.kickoff_wib).offset(offset).limit(limit)).all()
        total_query = select(Match)
        if from_date: total_query = total_query.where(Match.date_wib >= from_date)
        if to_date: total_query = total_query.where(Match.date_wib <= to_date)
        if sport: total_query = total_query.where(Match.sport == sport)
        total = len(db.scalars(total_query).all())
        return {"items": [{"match_id": x.match_id, "date_wib": x.date_wib.isoformat(), "sport": x.sport, "competition": x.competition, "event": x.event_name, "kickoff_wib": x.kickoff_wib.isoformat() if x.kickoff_wib else None, "team_a": x.team_a, "team_b": x.team_b, "status": x.status} for x in rows], "total": total, "limit": limit, "offset": offset}

    @app.get("/predictions/{match_id}")
    def get_prediction(match_id: str, db: Session = Depends(db_session), _: object = Depends(current_session)):
        row = db.scalar(select(Prediction).where(Prediction.match_id == match_id).order_by(Prediction.updated_at.desc()))
        if not row:
            raise HTTPException(status_code=404, detail="prediction not found")
        return {"match_id": row.match_id, "predicted_outcome": row.predicted_outcome, "predicted_score_or_result": row.predicted_score_or_result, "confidence_percent": row.confidence_percent, "confidence_breakdown": row.confidence_breakdown, "no_pick": row.no_pick, "DATA_SOURCE_DEGRADED": row.data_source_degraded, "accuracy_excluded": row.accuracy_excluded, "validation_status": row.validation_status}

    @app.get("/metrics/accuracy", response_model=MetricsResponse)
    def metrics_accuracy(
        from_date: date | None = Query(default=None, alias="from"),
        to_date: date | None = Query(default=None, alias="to"),
        sport: str | None = None,
        db: Session = Depends(db_session),
        _: object = Depends(current_session),
    ):
        query = select(PredictionResult, Match).join(Match, Match.match_id == PredictionResult.match_id)
        if from_date: query = query.where(Match.date_wib >= from_date)
        if to_date: query = query.where(Match.date_wib <= to_date)
        if sport: query = query.where(Match.sport == sport)
        rows = db.execute(query).all()
        valid = [result for result, _match in rows if result.outcome_correct is not None and not result.accuracy_excluded]
        correct = sum(1 for result, _match in rows if result.outcome_correct is True and not result.accuracy_excluded)
        return {"evaluated_count": len(valid), "correct_count": correct, "accuracy_percent": round(correct * 100 / len(valid), 2) if valid else None}

    return app, engine, SessionLocal


app, _engine, _SessionLocal = create_app()
