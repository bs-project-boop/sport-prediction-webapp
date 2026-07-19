from app.core.settings import Settings
from app.main import create_app
from app.services.ingestion import ingest_directory

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from sqlalchemy.orm import sessionmaker

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/Users/beem/.hermes-shared/reports/sports/v3")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    settings = Settings()
    app, engine, SessionLocal = create_app(settings.database_url, settings.sport_prediction_pin_hash or None)
    with SessionLocal() as db:
        root = Path(args.root)
        summary = ingest_directory(db, root)
    print({"files_seen": summary.files_seen, "files_ingested": summary.files_ingested, "errors": summary.errors, "records_written": summary.records_written})
