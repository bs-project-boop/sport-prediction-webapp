# espn_client.py — ESPN API client for Stage 1 Discovery
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

WIB = timezone(timedelta(hours=7))


def espn_fetch(sport_path: str, dates: str | None = None, timeout: int = 15) -> dict[str, Any]:
    """Fetch ESPN scoreboard for a given sport path and date.

    Returns {"ok": True, "data": ..., "url": ...} on success.
    Returns {"ok": False, "error": ..., "url": ...} on failure.
    NEVER returns fabricated data on failure.
    """
    params = ""
    if dates:
        params = f"?dates={dates}"
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read()), "url": url}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": url}


def utc_to_wib_str(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_wib = dt.astimezone(WIB)
        return dt_wib.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def representative(c: dict) -> str:
    """Extract a team/athlete display name from a competitor dict."""
    if "athlete" in c and isinstance(c["athlete"], dict):
        a = c["athlete"]
        return a.get("displayName") or a.get("shortName") or "?"
    if "team" in c and isinstance(c["team"], dict):
        t = c["team"]
        loc = t.get("location") or ""
        name = t.get("name") or t.get("shortName") or t.get("abbreviation") or "?"
        if loc and not name.startswith(loc):
            return f"{loc} {name}".strip()
        return name
    return "?"


def normalize_event(event: dict, sport_v31: str, competition: str) -> dict | None:
    """Parse an ESPN scoreboard event into our internal match format.

    Returns None if the event doesn't have enough data (no competitors, etc).
    """
    comps = event.get("competitions", [])
    if not comps:
        return None
    comp = comps[0]
    competitors = comp.get("competitors", [])
    if len(competitors) < 2:
        return None
    t1 = representative(competitors[0])
    t2 = representative(competitors[1])
    if not t1 or not t2 or t1 == "?" or t2 == "?":
        return None
    kickoff_utc = event.get("date", "")
    kickoff_wib = utc_to_wib_str(kickoff_utc) if kickoff_utc else ""
    status = comp.get("status", {}).get("type", {}).get("description", "")
    venue = comp.get("venue", {}).get("fullName", "") if comp.get("venue") else ""
    return {
        "sport": sport_v31,
        "competition": competition,
        "event": f"{t1} vs {t2}",
        "team_a": t1,
        "team_b": t2,
        "kickoff_wib": kickoff_wib,
        "kickoff_utc": kickoff_utc,
        "venue": venue,
        "status": status,
        "espn_event_id": event.get("id"),
        "espn_league_slug": event.get("league", {}).get("slug", ""),
        "espn_competition_id": comp.get("id"),
    }
