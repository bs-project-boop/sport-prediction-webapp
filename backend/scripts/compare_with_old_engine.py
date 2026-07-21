"""Side-by-side comparison: old engine (v3.1 JSON) vs new discovery for same target date."""
import json
import sys
from collections import Counter
from pathlib import Path

target_date = sys.argv[1] if len(sys.argv) > 1 else "2026-07-20"
old_path = Path(f"/Users/beem/.hermes-shared/reports/sports/v3/schedules/{target_date}.json")

if not old_path.exists():
    print(f"ERROR: {old_path} not found")
    sys.exit(1)

with old_path.open() as f:
    old_data = json.load(f)
old_events = old_data if isinstance(old_data, list) else old_data.get("events", [])

print(f"=== COMPARISON: target_date = {target_date} ===\n")
print(f"Engine LAMA (v3.1 JSON): {len(old_events)} events")
sport_old = Counter(e.get("sport") for e in old_events)
for s, c in sorted(sport_old.items(), key=lambda x: -x[1]):
    print(f"  {s}: {c}")

print("\n--- 5 sample events from old engine ---")
for e in old_events[:5]:
    print(f"  [{e.get('sport')}] {e.get('competition')}: {e.get('team_a')} vs {e.get('team_b')} @ {e.get('kickoff_wib', e.get('kickoff_utc', '?'))}")

# Now fetch from staging DB
import os
os.environ.setdefault("SPORT_PREDICTION_DATABASE_URL",
    "postgresql+psycopg2://sportapp:PWD@127.0.0.1:5432/sport_prediction_staging")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# We'll re-run discovery to be sure of state, then query
from app.models import Base
engine = create_engine(os.environ["SPORT_PREDICTION_DATABASE_URL"], pool_pre_ping=True)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

with SessionLocal() as db:
    rows = db.execute(text("""
        SELECT match_id, sport, competition, team_a, team_b, kickoff_wib
        FROM matches
        WHERE date_wib = :d
        ORDER BY kickoff_wib
    """), {"d": target_date}).fetchall()

print(f"\nDiscovery BARU (Stage 1): {len(rows)} events")
sport_new = Counter(r.sport for r in rows)
for s, c in sorted(sport_new.items(), key=lambda x: -x[1]):
    print(f"  {s}: {c}")

print("\n--- 5 sample events from new discovery ---")
for r in rows[:5]:
    print(f"  [{r.sport}] {r.competition}: {r.team_a} vs {r.team_b} @ {r.kickoff_wib}")
    print(f"    match_id: {r.match_id}")

print("\n=== SIDE-BY-SIDE TABLE ===")
all_sports = sorted(set(list(sport_old) + list(sport_new)))
print(f"{'Sport':<14} {'Old (v3.1)':<12} {'New (Stage 1)':<14} {'Match?'}")
print(f"{'-'*14} {'-'*12} {'-'*14} {'-'*8}")
for s in all_sports:
    o = sport_old.get(s, 0)
    n = sport_new.get(s, 0)
    match = "✓" if o == n else f"Δ {n-o:+d}"
    print(f"{s:<14} {o:<12} {n:<14} {match}")
print(f"{'TOTAL':<14} {len(old_events):<12} {len(rows):<14}")

print("\n=== 5-MATCH DETAIL COMPARISON ===")
# Match by team_a + team_b + kickoff date (ignoring exact time)
def normalize_match(e):
    if isinstance(e, dict):
        ta = e.get("team_a", "")
        tb = e.get("team_b", "")
        ko = e.get("kickoff_wib", e.get("kickoff_utc", ""))
    else:
        # SQLAlchemy row
        ta = e.team_a or ""
        tb = e.team_b or ""
        ko = str(e.kickoff_wib or "")
    return (ta.lower(), tb.lower(), str(ko)[:10])

old_keys = {normalize_match(e): e for e in old_events}
new_keys = {normalize_match(r): r for r in rows}
shared = set(old_keys) & set(new_keys)
print(f"Shared matches (by team_a + team_b + date): {len(shared)} of {len(old_events)} old, {len(rows)} new")
print()

for i, key in enumerate(sorted(shared)[:5]):
    old = old_keys[key]
    new = new_keys[key]
    def g(o, k, default="N/A"):
        return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)
    print(f"--- Match {i+1}: {g(old,'team_a')} vs {g(old,'team_b')} ---")
    print(f"  match_id old: {g(old, 'match_id', '(no id field)')}")
    print(f"  match_id new: {g(new, 'match_id')}")
    print(f"  sport old:    {g(old,'sport')} | new: {new.sport}")
    print(f"  competition old: {g(old,'competition')} | new: {new.competition}")
    print(f"  team_a old:   {g(old,'team_a')} | new: {new.team_a}")
    print(f"  team_b old:   {g(old,'team_b')} | new: {new.team_b}")
    print(f"  kickoff old:  {g(old,'kickoff_wib') or g(old,'kickoff_utc')} | new: {new.kickoff_wib}")
    print()
