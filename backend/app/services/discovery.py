# discovery.py — Stage 1 Discovery Service
# Ported from sports_v31_espn_ingest.py (ADR-007/M1)
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Match, PipelineJob

WIB = timezone(timedelta(hours=7))

# League → (ESPN sport_path, sport_v31, competition_label)
LEAGUE_CONFIG = [
    # Football
    ("soccer/fifa.world",            "football",    "FIFA World Cup 2026"),
    ("soccer/uefa.champions",        "football",    "UEFA Champions League"),
    ("soccer/uefa.euro",             "football",    "UEFA Euro"),
    ("soccer/eng.1",                 "football",    "Premier League"),
    ("soccer/esp.1",                 "football",    "La Liga"),
    ("soccer/ita.1",                 "football",    "Serie A"),
    ("soccer/ger.1",                 "football",    "Bundesliga"),
    ("soccer/fra.1",                 "football",    "Ligue 1"),
    ("soccer/ned.1",                 "football",    "Eredivisie"),
    ("soccer/usa.1",                 "football",    "MLS"),
    ("soccer/idn.1",                 "football",    "Liga 1 Indonesia"),
    ("soccer/conmebol.america",      "football",    "Copa America"),
    # Tennis
    ("tennis/atp",                   "tennis",      "ATP Tour"),
    ("tennis/wta",                   "tennis",      "WTA Tour"),
    # Motorsport
    ("racing/f1",                    "motorsport",  "Formula 1"),
    # Basketball
    ("basketball/nba",               "basketball",  "NBA"),
    ("basketball/wnba",              "basketball",  "WNBA"),
    # NFL
    ("football/nfl",                 "nfl",         "NFL"),
]

# External sources — handled by separate clients
EXTERNAL_SOURCE_CONFIG = [
    ("motogp/pulselive", "motorsport", "MotoGP",              "motogp_pulselive"),
    ("euroleague/official", "basketball", "EuroLeague",        "euroleague_official"),
    ("fiba/official", "basketball",      "FIBA",               "fiba_official"),
    ("ibl/official", "basketball",       "IBL Indonesia",       "ibl_official_html"),
    ("tennis/grand_slam/wimbledon",  "tennis", "Wimbledon",     "grand_slam_wimbledon"),
    ("tennis/grand_slam/us_open",   "tennis", "US Open",        "grand_slam_us_open"),
    ("tennis/grand_slam/australian_open", "tennis", "Australian Open", "grand_slam_australian_open"),
    ("tennis/grand_slam/roland_garros", "tennis", "Roland Garros", "grand_slam_roland_garros"),
]

# Source classification constants
SOURCE_CLASS_OK = "ok"
SOURCE_CLASS_OK_ZERO = "ok_zero_events"
SOURCE_CLASS_INVALID = "endpoint_invalid_or_unsupported"
SOURCE_CLASS_DEGRADED = "DATA_SOURCE_DEGRADED"

STAGE2_LOOKAHEAD_HOURS = 2


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().date().isoformat()


def compute_utc_bucket_window(target_date: str | None = None) -> tuple[datetime, datetime]:
    """Compute 48h WIB window for a target date.

    The window starts at midnight WIB (00:00) of target_date and runs
    for 48 hours. This means it covers:
    - Late-night UTC previous day events (up to 06:00 WIB = UTC 23:00 day-1)
    - All of target_date's events
    - Events up to +24h from midnight WIB

    This is the fix for the "dini hari WIB" bug (audit A.5).
    """
    if target_date is None:
        target_date = today_wib()
    target_day = datetime.fromisoformat(target_date).date()
    window_start = datetime.combine(target_day, datetime.min.time(), tzinfo=WIB)
    window_end = window_start + timedelta(hours=48)
    return window_start, window_end


def utc_to_wib_str(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_wib = dt.astimezone(WIB)
        return dt_wib.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def parse_wib(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
    except Exception:
        return None


def slug_key(ev: dict) -> str:
    base = f"{ev['sport']}|{ev['competition']}|{ev['team_a']}|{ev['team_b']}|{ev['kickoff_wib']}"
    s = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return s[:120]


def classify_endpoint_probe(probe: dict) -> str:
    """Classify an endpoint probe result."""
    if probe.get("DATA_SOURCE_DEGRADED"):
        return SOURCE_CLASS_DEGRADED
    ok_buckets = probe.get("ok_buckets") or []
    if not ok_buckets:
        return SOURCE_CLASS_INVALID
    if int(probe.get("events_in_window") or 0) > 0:
        return SOURCE_CLASS_OK
    return SOURCE_CLASS_OK_ZERO


# ─── Discovery Service ────────────────────────────────────────────────────────


class DiscoveryService:
    """Stage 1 Discovery — finds all fixtures for a target date WIB."""

    def __init__(self, db: Session):
        self.db = db

    def _espn_buckets(self, target_date: str) -> list[str]:
        target_day = datetime.fromisoformat(target_date).date()
        return [
            (target_day + timedelta(days=offset)).strftime("%Y%m%d")
            for offset in (-1, 0, 1)
        ]

    def _register_stage2_job(self, match_id: str, kickoff_wib: datetime) -> None:
        """Register a Stage 2 Matrix Analysis job for T-2h before kickoff."""
        scheduled = kickoff_wib - timedelta(hours=STAGE2_LOOKAHEAD_HOURS)
        job_id = f"stage2:{match_id}"
        # Idempotent: skip if already exists
        existing = self.db.scalar(
            select(PipelineJob).where(PipelineJob.job_id == job_id)
        )
        if existing:
            return
        job = PipelineJob(
            job_id=job_id,
            stage="stage2",
            match_id=match_id,
            scheduled_time=scheduled,
            status="pending",
            attempt_count=0,
            max_attempts=3,
        )
        self.db.add(job)
        self.db.flush()

    def _upsert_match(self, ev: dict, date_wib: date) -> Match | None:
        """Insert or update a match. Returns None if skip (existing researched)."""
        match_id = ev.get("event_id")
        if not match_id:
            return None

        # Idempotency: skip if match already exists with researched=True
        existing = self.db.scalar(select(Match).where(Match.match_id == match_id))
        if existing and existing.raw_document.get("researched"):
            return existing

        row = existing or Match(match_id=match_id, date_wib=date_wib)
        row.sport = ev.get("sport", row.sport or "unknown")
        row.competition = ev.get("competition", row.competition or "")
        row.event_name = ev.get("event", row.event_name or "")
        row.team_a = ev.get("team_a", row.team_a)
        row.team_b = ev.get("team_b", row.team_b)
        row.kickoff_wib = parse_wib(ev.get("kickoff_wib"))
        row.venue = ev.get("venue", row.venue)
        row.status = ev.get("status", row.status or "scheduled")
        # Preserve existing raw_document if already researched
        if not existing or not existing.raw_document.get("researched"):
            row.raw_document = ev
        row.source_metadata = ev.get("data_source") or row.source_metadata or {}
        # competition_level from discovery
        if ev.get("competition_level"):
            row.competition_level = ev.get("competition_level")
        if ev.get("report_label"):
            row.report_label = ev.get("report_label")

        if not existing:
            self.db.add(row)
        self.db.flush()
        return row

    def run_discovery(
        self,
        target_date: str | None = None,
        sports_filter: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run full Stage 1 discovery for target_date WIB.

        Args:
            target_date:  YYYY-MM-DD in WIB. Defaults to today.
            sports_filter: Optional list of sports to limit (e.g. ["football"]).
            dry_run:       If True, fetch and normalize events but don't write
                          anything to the database. Useful for pre-flight checks.

        Returns summary dict with events_discovered, endpoint_probe, etc.
        """
        from app.services.espn_client import espn_fetch
        from app.services.external_apis.motogp_client import fetch_motogp_pulselive
        from app.services.external_apis.euroleague_client import fetch_euroleague_official
        from app.services.external_apis.fiba_client import fetch_fiba_official
        from app.services.external_apis.ibl_client import fetch_ibl_official_html
        from app.services.external_apis.grand_slam_client import (
            fetch_wimbledon_official,
            fetch_us_open_official,
            fetch_australian_open_official,
            fetch_roland_garros_official,
        )

        if target_date is None:
            target_date = today_wib()

        date_wib = datetime.fromisoformat(target_date).date()
        window_start, window_end = compute_utc_bucket_window(target_date)
        espn_buckets = self._espn_buckets(target_date)

        all_events: list[dict] = []
        sport_has_event: dict[str, bool] = {s: False for s in ("football", "tennis", "motorsport", "basketball", "nfl")}
        endpoint_probe: dict[str, dict] = {}

        # ── ESPN sources ──────────────────────────────────────────────────────
        for espn_path, sport_v31, competition in LEAGUE_CONFIG:
            if sports_filter and sport_v31 not in sports_filter:
                continue
            endpoint_probe.setdefault(espn_path, {
                "ok_buckets": [], "failed_buckets": [],
                "events_seen": 0, "events_in_window": 0,
                "source_type": "espn_site_api",
            })
            for espn_date in espn_buckets:
                result = espn_fetch(espn_path, espn_date)
                if not result.get("ok"):
                    endpoint_probe[espn_path]["failed_buckets"].append({
                        "date": espn_date, "error": result.get("error")})
                    continue
                endpoint_probe[espn_path]["ok_buckets"].append(espn_date)
                events = result["data"].get("events", [])
                endpoint_probe[espn_path]["events_seen"] += len(events)
                for ev in events:
                    from app.services.espn_client import normalize_event
                    norm = normalize_event(ev, sport_v31, competition)
                    if not norm:
                        continue
                    kickoff = parse_wib(norm.get("kickoff_wib", ""))
                    if not kickoff or not (window_start <= kickoff < window_end):
                        continue
                    endpoint_probe[espn_path]["events_in_window"] += 1
                    norm["fixture_source_path"] = espn_path
                    norm["fixture_source_competition"] = competition
                    norm["fixture_source_name"] = "ESPN"
                    all_events.append(norm)
                    sport_has_event[sport_v31] = True

        # ── External sources ───────────────────────────────────────────────────
        external_dispatch = {
            "motogp_pulselive":          fetch_motogp_pulselive,
            "euroleague_official":        fetch_euroleague_official,
            "fiba_official":              fetch_fiba_official,
            "ibl_official_html":           fetch_ibl_official_html,
            "grand_slam_wimbledon":        fetch_wimbledon_official,
            "grand_slam_us_open":          fetch_us_open_official,
            "grand_slam_australian_open":  fetch_australian_open_official,
            "grand_slam_roland_garros":    fetch_roland_garros_official,
        }

        for source_path, sport_v31, competition, source_kind in EXTERNAL_SOURCE_CONFIG:
            if sports_filter and sport_v31 not in sports_filter:
                continue
            fetcher = external_dispatch.get(source_kind)
            if not fetcher:
                continue
            events, probe = fetcher(target_date, window_start, window_end)
            probe.setdefault("source_type", "official_api")
            probe["source_kind"] = source_kind
            probe["competition"] = competition
            endpoint_probe[source_path] = probe
            for norm in events:
                all_events.append(norm)
                sport_has_event[sport_v31] = True

        # ── Deduplicate by slug_key ───────────────────────────────────────────
        seen_keys: set[str] = set()
        unique_events: list[dict] = []
        for ev in all_events:
            k = slug_key(ev)
            if k in seen_keys:
                continue
            seen_keys.add(k)
            ev["event_id"] = k
            unique_events.append(ev)

        # ── Write to DB ───────────────────────────────────────────────────────
        if dry_run:
            return {
                "ok": True,
                "target_date": target_date,
                "window_start_wib": window_start.isoformat(),
                "window_end_wib": window_end.isoformat(),
                "events_discovered": len(unique_events),
                "endpoint_probe": endpoint_probe,
                "sports_with_events": [s for s, has in sport_has_event.items() if has],
                "dry_run": True,
            }

        written = 0
        for ev in unique_events:
            ev_slug = slug_key(ev)
            match = self._upsert_match(ev, date_wib)
            if match:
                written += 1
                kickoff = parse_wib(ev.get("kickoff_wib"))
                if kickoff:
                    self._register_stage2_job(ev_slug, kickoff)

        self.db.commit()

        return {
            "ok": True,
            "target_date": target_date,
            "window_start_wib": window_start.isoformat(),
            "window_end_wib": window_end.isoformat(),
            "events_discovered": written,
            "endpoint_probe": endpoint_probe,
            "sports_with_events": [s for s, has in sport_has_event.items() if has],
        }
