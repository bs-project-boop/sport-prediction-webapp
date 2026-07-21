# fiba_client.py — FIBA Digital API client for Stage 1 Discovery
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any

WIB = timezone(timedelta(hours=7))
FIBA_API_BASE = "https://digital-api.fiba.basketball/hapi"
FIBA_FRONTEND_SUBSCRIPTION_KEY = "898cd5e7389140028ecb42943c47eb74"


def http_json_with_headers(url: str, headers: dict[str, str], timeout: int = 15) -> dict[str, Any]:
    import json, urllib.request, urllib.error
    try:
        merged = {"User-Agent": "Hermes-SportScanner/3.2", "Accept": "application/json,*/*", **headers}
        req = urllib.request.Request(url, headers=merged)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read()), "url": url, "status_code": getattr(r, "status", None)}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            body = ""
        return {"ok": False, "error": str(exc)[:200], "url": url, "status_code": exc.code, "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": url}


def _fiba_api_headers() -> dict[str, str]:
    return {"Ocp-Apim-Subscription-Key": FIBA_FRONTEND_SUBSCRIPTION_KEY}


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


def parse_wib(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
    except Exception:
        return None


def _fiba_game_to_event(game: dict, path: str) -> dict | None:
    dt_wib = parse_iso_to_wib(str(game.get("gameDateTimeUTC") or ""))
    if not dt_wib:
        return None
    team_a = (game.get("teamA") or {}).get("officialName") or (game.get("teamA") or {}).get("shortName") or "Team A"
    team_b = (game.get("teamB") or {}).get("officialName") or (game.get("teamB") or {}).get("shortName") or "Team B"
    competition = (game.get("competition") or {}).get("officialName") or "FIBA"
    level = "junior" if re.search(
        r"\bU\s*-?\s*(?:16|17|18|19|20|21)\b|Under\s*-?\s*(?:16|17|18|19|20|21)\b",
        competition, re.I
    ) else "senior"
    status_code = str(game.get("statusCode") or "")
    live_game_status = game.get("liveGameStatus")
    status = "Final" if live_game_status == 999 or status_code in {"VALID", "COMPL"} else (status_code or "scheduled")
    return {
        "sport": "basketball",
        "competition": competition,
        "event": f"{team_a} vs {team_b}",
        "team_a": team_a,
        "team_b": team_b,
        "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
        "kickoff_utc": game.get("gameDateTimeUTC"),
        "venue": game.get("venueName") or game.get("hostCity") or "",
        "status": status,
        "fixture_source_path": path,
        "fixture_source_competition": competition,
        "fixture_source_name": "FIBA Digital API",
        "fiba_game_id": game.get("gameId"),
        "fiba_game_name": game.get("gameName"),
        "fiba_competition_id": (game.get("competition") or {}).get("competitionId"),
        "fiba_competition_code": (game.get("competition") or {}).get("competitionCode"),
        "fiba_round_name": (game.get("round") or {}).get("roundName"),
        "competition_level": level,
        "prediction_eligible": level != "junior",
        "validation": "NO_PREDICTION" if level == "junior" else None,
        "accuracy_excluded": level == "junior",
        "report_label": "[JUNIOR - NO PREDICTION]" if level == "junior" else None,
        "source_event_shape": "fiba_gdap_game",
    }


def _fiba_espn_worldcup_fallback(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    """Fallback to ESPN basketball/fiba when FIBA API is unavailable."""
    from app.services.espn_client import espn_fetch, normalize_event as espn_normalize
    probe: dict[str, Any] = {
        "ok_buckets": [], "failed_buckets": [],
        "events_seen": 0, "events_in_window": 0,
        "source_type": "espn_site_api", "scope": "FIBA World Cup only"
    }
    target_day = datetime.fromisoformat(date_str).date()
    buckets = [(target_day + timedelta(days=offset)).strftime("%Y%m%d") for offset in (-1, 0, 1)]
    out: list[dict] = []
    for bucket in buckets:
        res = espn_fetch("basketball/fiba", bucket)
        if not res.get("ok"):
            probe["failed_buckets"].append({"date": bucket, "error": res.get("error")})
            continue
        probe["ok_buckets"].append(bucket)
        events = (res.get("data") or {}).get("events") or []
        probe["events_seen"] += len(events)
        for ev in events:
            norm = espn_normalize(ev, "basketball", "FIBA World Cup")
            if not norm:
                continue
            kickoff = parse_wib(norm.get("kickoff_wib", ""))
            if not kickoff or not (window_start <= kickoff < window_end):
                continue
            norm["fixture_source_path"] = "basketball/fiba"
            norm["fixture_source_competition"] = "FIBA World Cup"
            norm["fixture_source_name"] = "ESPN FIBA fallback"
            norm["source_event_shape"] = "espn_fiba_worldcup_fallback"
            out.append(norm)
            probe["events_in_window"] += 1
    return out, probe


def fetch_fiba_official(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    path = "fiba/official"
    date_from = urllib.parse.quote(
        window_start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        safe=""
    )
    date_to = urllib.parse.quote(
        window_end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        safe=""
    )
    url = f"{FIBA_API_BASE}/getgdapgamesbetweentwodates?dateFrom={date_from}&dateTo={date_to}"
    probe: dict[str, Any] = {
        "ok_buckets": [],
        "failed_buckets": [],
        "events_seen": 0,
        "events_in_window": 0,
        "source_type": "official_api",
        "api_base": FIBA_API_BASE,
        "endpoint": "getgdapgamesbetweentwodates",
        "fallback": "ESPN basketball/fiba (World Cup only)",
    }
    res = http_json_with_headers(url, _fiba_api_headers())
    if not res.get("ok"):
        status_code = res.get("status_code")
        degraded = status_code == 401
        probe["DATA_SOURCE_DEGRADED"] = bool(degraded)
        probe["degraded_reason"] = "fiba_subscription_key_unauthorized" if degraded else "fiba_api_fetch_failed"
        probe["failed_buckets"].append({
            "step": "getgdapgamesbetweentwodates",
            "status_code": status_code,
            "error": res.get("error"),
            "body": res.get("body"),
        })
        fallback_events, fallback_probe = _fiba_espn_worldcup_fallback(date_str, window_start, window_end)
        probe["fallback_probe"] = fallback_probe
        probe["fallback_events_in_window"] = fallback_probe.get("events_in_window", 0)
        return fallback_events, probe

    probe["ok_buckets"].append("getgdapgamesbetweentwodates")
    games = res.get("data") or []
    if not isinstance(games, list):
        probe["failed_buckets"].append({"step": "response_shape", "error": "expected list"})
        return [], probe
    probe["events_seen"] = len(games)

    out: list[dict] = []
    for game in games:
        norm = _fiba_game_to_event(game, path)
        if not norm:
            continue
        kickoff = parse_wib(norm.get("kickoff_wib", ""))
        if not kickoff or not (window_start <= kickoff < window_end):
            continue
        out.append(norm)
        probe["events_in_window"] += 1
    return out, probe
