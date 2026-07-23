from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import RateLimiter
from app.core.security import hash_pin, verify_pin
from app.core.sessions import SessionStore
from app.core.settings import Settings
from app.models import Base, Match, Prediction, PredictionResult
from app.schemas import ChangePinRequest, MetricsResponse, PinRequest

SESSION_COOKIE = "sport_session"
DEFAULT_ALLOWED_ORIGINS = [
    "http://10.10.10.83:8101",
    "https://sports.bintangsofyan.com",
]
ENV_FILE = "/etc/sport-prediction/app.env"


def _write_pin_hash_to_env(new_hash: str, env_file: str | None = None) -> None:
    """
    Atomically update SPORT_PREDICTION_PIN_HASH in app.env.

    If env_file is None or the path does not exist (testing/local machine),
    the write is skipped — app.state.pin_hash is updated in-memory instead.
    """
    if env_file is None:
        return
    env_path = Path(env_file)
    if not env_path.exists():
        return  # testing or non-server environment
    import tempfile

    line = f"SPORT_PREDICTION_PIN_HASH={new_hash}\n"
    with tempfile.NamedTemporaryFile(
        mode="w", dir=env_path.parent, prefix=".app.env.tmp.", suffix=".tmp", delete=False
    ) as tmp:
        tmp.write(line)
        tmp_name = tmp.name
    os.replace(tmp_name, env_path)


def create_app(
    database_url: str | None = None,
    pin_hash: str | None = None,
    testing: bool = False,
    allowed_origins: list[str] | None = None,
    secure_cookies: bool = True,
):
    database_url = database_url or os.getenv("SPORT_PREDICTION_DATABASE_URL", "sqlite:///./sport-prediction.db")
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine_kwargs = {"connect_args": connect_args, "pool_pre_ping": True}
    if database_url == "sqlite://":
        engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_kwargs)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app = FastAPI(title="Sport Prediction API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins or DEFAULT_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
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
        response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure_cookies, samesite="lax", max_age=3600)
        return {"authenticated": True}

    @app.patch("/auth/pin")
    def change_pin(
        payload: ChangePinRequest,
        request: Request,
        response: Response,
        db: Session = Depends(db_session),
        _session=Depends(current_session),
    ):
        key = request.client.host if request.client else "unknown"
        limiter = app.state.rate_limiter
        if not limiter.allow(key):
            raise HTTPException(status_code=429, detail="temporarily unavailable")
        if not verify_pin(payload.current_pin, app.state.pin_hash):
            limiter.record_failure(key)
            raise HTTPException(status_code=403, detail="current PIN is incorrect")
        limiter.reset(key)
        try:
            new_hash = hash_pin(payload.new_pin)
        except ValueError:
            raise HTTPException(status_code=422, detail="new PIN must be exactly six ASCII digits")
        app.state.pin_hash = new_hash
        _write_pin_hash_to_env(new_hash, ENV_FILE)
        token = app.state.sessions.create(db, key)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure_cookies, samesite="lax", max_age=3600)
        return {"pin_changed": True}

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
        search: str | None = Query(default=None, description="Case-insensitive partial match on team_a, team_b, event_name, or competition. Supports individual names (e.g. driver/pilot/player) when present in those fields."),
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
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Match.team_a.ilike(term),
                    Match.team_b.ilike(term),
                    Match.event_name.ilike(term),
                    Match.competition.ilike(term),
                )
            )
        rows = db.scalars(query.order_by(Match.date_wib, Match.kickoff_wib).offset(offset).limit(limit)).all()
        total_query = select(Match)
        if from_date: total_query = total_query.where(Match.date_wib >= from_date)
        if to_date: total_query = total_query.where(Match.date_wib <= to_date)
        if sport: total_query = total_query.where(Match.sport == sport)
        if search:
            term = f"%{search.strip()}%"
            total_query = total_query.where(
                or_(
                    Match.team_a.ilike(term),
                    Match.team_b.ilike(term),
                    Match.event_name.ilike(term),
                    Match.competition.ilike(term),
                )
            )
        total = len(db.scalars(total_query).all())
        return {"items": [{"match_id": x.match_id, "date_wib": x.date_wib.isoformat(), "sport": x.sport, "competition": x.competition, "event": x.event_name, "kickoff_wib": x.kickoff_wib.isoformat() if x.kickoff_wib else None, "team_a": x.team_a, "team_b": x.team_b, "status": x.status} for x in rows], "total": total, "limit": limit, "offset": offset}

    @app.get("/predictions/{match_id}")
    def get_prediction(match_id: str, db: Session = Depends(db_session), _: object = Depends(current_session)):
        row = db.scalar(select(Prediction).where(Prediction.match_id == match_id).order_by(Prediction.updated_at.desc()))
        if not row:
            raise HTTPException(status_code=404, detail="prediction not found")
        result = db.scalar(select(PredictionResult).where(PredictionResult.match_id == match_id).order_by(PredictionResult.captured_at.desc()))
        match_row = db.scalar(select(Match).where(Match.match_id == match_id))
        lesson_learnt = None
        if match_row and match_row.raw_document:
            lesson_learnt = match_row.raw_document.get("lesson_learnt")
        return {
            "match_id": row.match_id,
            "predicted_outcome": row.predicted_outcome,
            "predicted_score_or_result": row.predicted_score_or_result,
            "confidence_percent": row.confidence_percent,
            "confidence_breakdown": row.confidence_breakdown,
            "no_pick": row.no_pick,
            "DATA_SOURCE_DEGRADED": row.data_source_degraded,
            "accuracy_excluded": row.accuracy_excluded,
            "validation_status": result.validation_status if result else row.validation_status,
            "actual_result": result.actual_result if result else None,
            "actual_winner": result.actual_winner if result else None,
            "reasoning": row.reasoning,
            "lesson_learnt": lesson_learnt,
        }

    @app.get("/metrics/accuracy", response_model=MetricsResponse)
    def metrics_accuracy(
        from_date: date | None = Query(default=None, alias="from"),
        to_date: date | None = Query(default=None, alias="to"),
        sport: str | None = None,
        db: Session = Depends(db_session),
        _: object = Depends(current_session),
    ):
        query = select(PredictionResult, Match).join(Match, Match.match_id == PredictionResult.match_id)
        if from_date: query = query.where(func.date(Match.kickoff_wib) >= from_date)
        if to_date: query = query.where(func.date(Match.kickoff_wib) <= to_date)
        if sport: query = query.where(Match.sport == sport)
        rows = db.execute(query).all()
        evaluated_statuses = {"BENAR", "SEBAGIAN_BENAR", "SALAH"}
        excluded_statuses = {"NO_PICK", "NO_PREDICTION"}
        statuses = [result.validation_status for result, _match in rows]
        evaluated_count = sum(status in evaluated_statuses for status in statuses)
        correct_count = sum(status == "BENAR" for status in statuses)
        partial_count = sum(status == "SEBAGIAN_BENAR" for status in statuses)
        incorrect_count = sum(status == "SALAH" for status in statuses)
        excluded_count = sum(status in excluded_statuses for status in statuses)
        return {"evaluated_count": evaluated_count, "correct_count": correct_count, "partial_count": partial_count, "incorrect_count": incorrect_count, "excluded_count": excluded_count, "strict_accuracy_percent": round(correct_count * 100 / evaluated_count, 2) if evaluated_count else None, "lenient_accuracy_percent": round((correct_count + partial_count) * 100 / evaluated_count, 2) if evaluated_count else None}

    return app, engine, SessionLocal


_runtime_settings = Settings()
app, _engine, _SessionLocal = create_app(
    _runtime_settings.database_url,
    _runtime_settings.sport_prediction_pin_hash or None,
    allowed_origins=["http://10.10.10.83:8101", "http://localhost:8101", "https://sports.bintangsofyan.com"],
    secure_cookies=_runtime_settings.secure_cookies,
)

# ── Backend serves its own frontend for external/cloudflare access ────────────
# This lets Cloudflare tunnel target ONE port (8100) for both API + frontend,
# eliminating the need for Caddy or any other reverse proxy.
_FRONTEND_DIST = "/opt/sport-prediction/current/frontend"
if os.path.isdir(_FRONTEND_DIST):
    # StaticFiles for /assets/* — no explicit Cache-Control so ETag/Last-Modified
    # negotiation works naturally. These files have content-hash names so safe to
    # cache long-term.
    app.mount("/assets", StaticFiles(directory=f"{_FRONTEND_DIST}/assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # StaticFiles at /assets handles JS/CSS; this catches SPA routes
        # (matches, settings, etc.) and serves index.html for client-side routing.
        # index.html carries Cache-Control: no-cache so Cloudflare never caches it,
        # preventing the stale-bundle problem from recurring on future deploys.
        index = f"{_FRONTEND_DIST}/index.html"
        response = FileResponse(index)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
