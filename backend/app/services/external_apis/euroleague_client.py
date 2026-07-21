# euroleague_client.py — EuroLeague Official API client for Stage 1 Discovery
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

WIB = timezone(timedelta(hours=7))
EUROLEAGUE_API_BASE = "https://api-live.euroleague.net"


def http_json(url: str, timeout: int = 15) -> dict[str, Any]:
    import json, urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-SportScanner/3.2", "Accept": "application/json,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read()), "url": url}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": url}


def parse_iso_to_wib(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(WIB)
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(WIB)
    except Exception:
        return None


def euroleague_season_code(target_day) -> str:
    """EuroLeague season code starts in July: Sep 2025–Jun 2026 => E2025."""
    year = target_day.year if target_day.month >= 7 else target_day.year - 1
    return f"E{year}"


def fetch_euroleague_official(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    path = "euroleague/official"
    target_day = datetime.fromisoformat(date_str).date()
    season_code = euroleague_season_code(target_day)
    url = f"{EUROLEAGUE_API_BASE}/v2/competitions/E/seasons/{season_code}/games"
    probe: dict[str, Any] = {
        "ok_buckets": [],
        "failed_buckets": [],
        "events_seen": 0,
        "events_in_window": 0,
        "source_type": "official_api",
        "api_base": EUROLEAGUE_API_BASE,
        "season_code": season_code,
    }
    res = http_json(url)
    if not res.get("ok"):
        probe["failed_buckets"].append({
            "step": "games", "season_code": season_code, "error": res.get("error")})
        return [], probe
    probe["ok_buckets"].append(f"games_{season_code}")
    games = (res.get("data") or {}).get("data") if isinstance(res.get("data"), dict) else res.get("data")
    games = games or []
    probe["events_seen"] = len(games)

    out: list[dict] = []
    for g in games:
        dt_wib = parse_iso_to_wib(str(g.get("utcDate") or g.get("date") or ""))
        if not dt_wib or not (window_start <= dt_wib < window_end):
            continue
        home = (
            ((g.get("local") or {}).get("club") or {}).get("name")
            or ((g.get("local") or {}).get("club") or {}).get("abbreviatedName")
            or "Home"
        )
        away = (
            ((g.get("road") or {}).get("club") or {}).get("name")
            or ((g.get("road") or {}).get("club") or {}).get("abbreviatedName")
            or "Away"
        )
        venue = ((g.get("venue") or {}).get("name") or "")
        status = "Final" if g.get("played") else (g.get("gameStatus") or "scheduled")
        out.append({
            "sport": "basketball",
            "competition": "EuroLeague",
            "event": f"{home} vs {away}",
            "team_a": home,
            "team_b": away,
            "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
            "kickoff_utc": g.get("utcDate") or g.get("date"),
            "venue": venue,
            "status": status,
            "fixture_source_path": path,
            "fixture_source_competition": "EuroLeague",
            "fixture_source_name": "EuroLeague Official API",
            "euroleague_game_code": g.get("gameCode"),
            "euroleague_identifier": g.get("identifier"),
            "euroleague_season_code": season_code,
            "source_event_shape": "euroleague_game",
        })
        probe["events_in_window"] += 1
    return out, probe
