"""
Discovery worker — standalone script that can run on any host with a
PostgreSQL connection. Does NOT import the FastAPI app to avoid pulling in
unnecessary dependencies on the Mac side.

Usage:
    python -m app.workers.discovery                         # today's date (WIB)
    python -m app.workers.discovery --date 2026-07-22       # specific date
    python -m app.workers.discovery --sports football       # filter by sport
    python -m app.workers.discovery --dry-run               # don't write to DB
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.discovery import DiscoveryService


def get_database_url() -> str:
    """
    Resolve the database URL.
    On the Mac: SPORT_PREDICTION_DATABASE_URL is set directly in the shell.
    On the server: falls back to Settings() which reads app.env.
    """
    url = os.getenv("SPORT_PREDICTION_DATABASE_URL")
    if url:
        return url
    # Server-side fallback using app.env
    from app.core.settings import Settings
    return Settings().database_url


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sport Prediction Stage 1 Discovery")
    parser.add_argument(
        "--date",
        default=None,
        help="Target date in WIB (YYYY-MM-DD). Defaults to today in WIB timezone.",
    )
    parser.add_argument(
        "--sports",
        default=None,
        help="Comma-separated sport filter (e.g. football,tennis,motorsport). "
             "Defaults to all supported sports.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery without writing to the database.",
    )
    args = parser.parse_args()

    sports_filter = args.sports.split(",") if args.sports else None

    engine = create_engine(get_database_url(), pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as db:
        svc = DiscoveryService(db)
        summary = svc.run_discovery(
            target_date=args.date,
            sports_filter=sports_filter,
            dry_run=args.dry_run,
        )

    print(
        f"events_discovered={summary['events_discovered']} "
        f"no_event_count={summary.get('no_event_count', '?')} "
        f"failed_count={summary.get('failed_count', '?')} "
        f"sources_with_events={summary.get('sources_with_events', '?')}"
    )
