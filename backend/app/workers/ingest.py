"""
Ingestion worker — standalone script that can run on any host with a
PostgreSQL connection. Does NOT import the FastAPI app to avoid pulling in
unnecessary dependencies on the Mac side.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.ingestion import ingest_directory


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

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/var/lib/sport-prediction/synced-reports")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    engine = create_engine(get_database_url(), pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as db:
        root = Path(args.root)
        summary = ingest_directory(db, root, args.date)
    print(
        f"files_seen={summary.files_seen} "
        f"files_ingested={summary.files_ingested} "
        f"errors={summary.errors} "
        f"records_written={summary.records_written}"
    )
