"""
Compare old discovery (v31_espn_ingest / sports_v31_watch) vs new Stage 1 Discovery.

Usage on server (with staging DB):
    SPORT_PREDICTION_DATABASE_URL=postgresql://... python compare_discovery.py --date 2026-07-22

This script:
1. Reads staging DB to find what OLD engine discovered for a given date
   (matches that have source_metadata['engine'] = 'v3.1' or 'v31')
2. Runs new DiscoveryService against the same date
3. Shows side-by-side comparison: new-only, old-only, shared
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.discovery import DiscoveryService
from app.models import Base, Match


def get_database_url() -> str:
    url = os.getenv("SPORT_PREDICTION_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "SPORT_PREDICTION_DATABASE_URL not set. "
            "Run on server with: SPORT_PREDICTION_DATABASE_URL=postgresql://... python compare_discovery.py"
        )
    return url


def old_engine_matches(db, target_date: str) -> list[dict]:
    """
    Query staging DB for matches discovered by the old v3.1 engine.
    The old engine set raw_document['source'] = 'espn' and did not have
    competition_level / report_label fields.
    """
    result = db.execute(
        text("""
            SELECT match_id, sport, competition, event_name,
                   team_a, team_b, kickoff_wib, status,
                   raw_document
            FROM matches
            WHERE date_wib = :date
              AND raw_document IS NOT NULL
            ORDER BY competition, kickoff_wib
        """),
        {"date": target_date}
    )
    matches = []
    for row in result:
        raw = row._mapping
        raw_doc = raw.get("raw_document") or {}
        matches.append({
            "match_id": raw["match_id"],
            "sport": raw["sport"],
            "competition": raw["competition"],
            "event_name": raw["event_name"],
            "team_a": raw["team_a"],
            "team_b": raw["team_b"],
            "kickoff_wib": str(raw["kickoff_wib"]) if raw["kickoff_wib"] else None,
            "status": raw["status"],
            "source": raw_doc.get("source", raw_doc.get("fixture_source_name", "unknown")),
            "engine": raw_doc.get("engine", "v31" if raw_doc.get("source") == "espn" else "unknown"),
        })
    return matches


def new_engine_matches(db, target_date: str) -> list[dict]:
    """Run new DiscoveryService for target_date and return all discovered matches."""
    svc = DiscoveryService(db)
    summary = svc.run_discovery(target_date=target_date, dry_run=False)

    # Fetch written matches from DB
    date_obj = datetime.fromisoformat(target_date).date()
    rows = db.execute(
        text("""
            SELECT match_id, sport, competition, event_name,
                   team_a, team_b, kickoff_wib, status,
                   source_metadata
            FROM matches
            WHERE date_wib = :date
            ORDER BY competition, kickoff_wib
        """),
        {"date": str(date_obj)}
    )
    matches = []
    for row in rows:
        raw = row._mapping
        sm = raw.get("source_metadata") or {}
        matches.append({
            "match_id": raw["match_id"],
            "sport": raw["sport"],
            "competition": raw["competition"],
            "event_name": raw["event_name"],
            "team_a": raw["team_a"],
            "team_b": raw["team_b"],
            "kickoff_wib": str(raw["kickoff_wib"]) if raw["kickoff_wib"] else None,
            "status": raw["status"],
            "source": sm.get("fixture_source_name", sm.get("source", "unknown")),
            "engine": "v3.2-discovery",
        })
    return matches


def compare(old: list[dict], new: list[dict]) -> dict:
    """Compare two match lists and categorize differences."""
    old_keys = {m["match_id"] for m in old}
    new_keys = {m["match_id"] for m in new}
    shared = old_keys & new_keys
    old_only = old_keys - new_keys
    new_only = new_keys - old_keys

    return {
        "total_old": len(old),
        "total_new": len(new),
        "shared": len(shared),
        "old_only": old_only,
        "new_only": new_only,
    }


def format_match(m: dict) -> str:
    return (f"  [{m['sport']}] {m['competition']}: "
            f"{m['team_a']} vs {m['team_b']} "
            f"({m['kickoff_wib'] or '?'})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare old vs new discovery engine")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (WIB). Defaults to today.")
    args = parser.parse_args()

    target_date = args.date or datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
    print(f"\n=== Discovery Comparison for {target_date} WIB ===\n")

    db_url = get_database_url()
    engine = create_engine(db_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as db:
        print("Fetching old engine (v3.1) matches from staging DB...")
        old_matches = old_engine_matches(db, target_date)
        print(f"  -> {len(old_matches)} matches found\n")

        print("Running new discovery engine (v3.2)...")
        new_matches = new_engine_matches(db, target_date)
        print(f"  -> {len(new_matches)} matches found\n")

    result = compare(old_matches, new_matches)

    print(f"{'─'*60}")
    print(f"OLD engine (v3.1): {result['total_old']} matches")
    print(f"NEW engine (v3.2): {result['total_new']} matches")
    print(f"SHARED:            {result['shared']} matches")
    print(f"{'─'*60}")

    if result["old_only"]:
        print(f"\nIn OLD only ({len(result['old_only'])}) — new engine MISSED these:")
        old_map = {m["match_id"]: m for m in old_matches}
        for k in sorted(result["old_only"]):
            print(format_match(old_map[k]))

    if result["new_only"]:
        print(f"\nIn NEW only ({len(result['new_only'])}) — old engine MISSED these:")
        new_map = {m["match_id"]: m for m in new_matches}
        for k in sorted(result["new_only"]):
            print(format_match(new_map[k]))

    print(f"\n{'─'*60}")
    if result["total_new"] > result["total_old"]:
        print(f"✅ New engine found {result['total_new'] - result['total_old']} MORE events")
    elif result["total_new"] < result["total_old"]:
        print(f"⚠️  New engine missed {result['total_old'] - result['total_new']} events from old engine")
    else:
        print(f"✅ Both engines found same number of events")

    print()
