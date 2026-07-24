#!/usr/bin/env python3
"""Sport Scanning AI v3.2 — ESPN API ingester (real fixtures, replaces stubs).

Reads ESPN scoreboard APIs for the 5 v3.1 sports and writes deterministic
fixture data into the same `schedules/YYYY-MM-DD.json` the v3.0 engine
already consumes. This is the PRIMARY data source for matches.

Why ESPN API, not just SearXNG: ESPN's scoreboard returns scheduled fixtures
with kickoff times + teams/athletes. SearXNG returns aggregator URLs that we'd
then need to scrape anyway. ESPN is one HTTP GET = one structured fixture.

SearXNG is used for: deep research (SearXNG + scrapling) — Step 2 deep research.
ESPN is used for: match discovery + identification — Step 1 fixture list.

Sport → ESPN path mapping follows site.api.espn.com conventions.
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SEARXNG_URL = "http://10.10.10.5:8888"

WIB = timezone(timedelta(hours=7))
ROOT = Path("/opt/sport-prediction/current/engine/data")
SCHEDULE_DIR = ROOT / "schedules"
PRED_DIR = ROOT / "predictions"
SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
PRED_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DIR = ROOT / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().date().isoformat()


def utc_to_wib_str(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_wib = dt.astimezone(WIB)
        return dt_wib.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def parse_wib(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
    except Exception:
        return None


def audit(action: str, status: str, details: Dict[str, Any]) -> None:
    rec = {
        "ts_wib": now_wib().isoformat(timespec="seconds"),
        "module": "v31_espn_ingest",
        "action": action,
        "status": status,
        "details": details,
    }
    path = AUDIT_DIR / f"{today_wib()}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# League → (ESPN sport_path, sport_v31, competition_label)
LEAGUE_CONFIG: List[Tuple[str, str, str]] = [
    # Football (soccer)
    ("soccer/fifa.world",            "football", "FIFA World Cup 2026"),
    ("soccer/uefa.champions",        "football", "UEFA Champions League"),
    ("soccer/uefa.euro",             "football", "UEFA Euro"),
    ("soccer/eng.1",                 "football", "Premier League"),
    ("soccer/esp.1",                 "football", "La Liga"),
    ("soccer/ita.1",                 "football", "Serie A"),
    ("soccer/ger.1",                 "football", "Bundesliga"),
    ("soccer/fra.1",                 "football", "Ligue 1"),
    ("soccer/ned.1",                 "football", "Eredivisie"),
    ("soccer/usa.1",                 "football", "MLS"),
    ("soccer/idn.1",                 "football", "Liga 1 Indonesia"),
    ("soccer/conmebol.america",      "football", "Copa America"),
    # Tennis
    ("tennis/atp",                   "tennis",   "ATP Tour"),
    ("tennis/wta",                   "tennis",   "WTA Tour"),
    # Motorsport
    ("racing/f1",                    "motorsport", "Formula 1"),
    # Basketball
    ("basketball/nba",               "basketball", "NBA"),
    ("basketball/wnba",              "basketball", "WNBA"),
    # NFL
    ("football/nfl",                 "nfl", "NFL"),
]


SOURCE_CLASS_OK = "ok"
SOURCE_CLASS_OK_ZERO = "ok_zero_events"
SOURCE_CLASS_INVALID = "endpoint_invalid_or_unsupported"
SOURCE_CLASS_DEGRADED = "DATA_SOURCE_DEGRADED"
KNOWN_GAP_PENDING_FALLBACK = "known_gap_pending_fallback_source"
KNOWN_GAP_ENDPOINTS: Dict[str, str] = {}

# Non-ESPN official fixture sources approved by beem.
# path, sport_v31, competition_label, source_kind
EXTERNAL_SOURCE_CONFIG: List[Tuple[str, str, str, str]] = [
    ("motogp/pulselive", "motorsport", "MotoGP", "motogp_pulselive"),
    ("euroleague/official", "basketball", "EuroLeague", "euroleague_official"),
    ("fiba/official", "basketball", "FIBA", "fiba_official"),
    ("ibl/official", "basketball", "IBL Indonesia", "ibl_official_html"),
    ("tennis/grand_slam/wimbledon", "tennis", "Wimbledon", "grand_slam_wimbledon"),
    ("tennis/grand_slam/us_open", "tennis", "US Open", "grand_slam_us_open"),
    ("tennis/grand_slam/australian_open", "tennis", "Australian Open", "grand_slam_australian_open"),
    ("tennis/grand_slam/roland_garros", "tennis", "Roland Garros", "grand_slam_roland_garros"),
]

MOTOGP_API_BASE = "https://api.motogp.pulselive.com/motogp/v1"
EUROLEAGUE_API_BASE = "https://api-live.euroleague.net"
FIBA_API_BASE = "https://digital-api.fiba.basketball/hapi"
FIBA_FRONTEND_SUBSCRIPTION_KEY = "898cd5e7389140028ecb42943c47eb74"
IBL_SCHEDULE_URL = "https://iblindonesia.com/games/schedule"
WIMBLEDON_CONFIG_URL = "https://www.wimbledon.com/en_GB/json/gen/config_web.json"
US_OPEN_CONFIG_URL = "https://www.usopen.org/en_US/json/gen/config_web.json"
AUSTRALIAN_OPEN_API_TEMPLATE = "https://prod-scores-api.ausopen.com/year/{year}/period/{period}/day/{day}/schedule"
ROLAND_GARROS_MATCHES_URL = "https://www.rolandgarros.com/en-us/matches"
THESPORTSDB_API = "https://www.thesportsdb.com/api/v1/json/3"

# TheSportsDB league ID → (league_id_str, sport_v31, competition_label)
# Used as fallback when ESPN returns 0 events for football leagues.
THESPORTSDB_LEAGUES: List[Tuple[str, str, str]] = [
    ("4328", "football", "Premier League"),
    ("4346", "football", "La Liga"),
    ("4339", "football", "Serie A"),
    ("4335", "football", "Bundesliga"),
    ("4331", "football", "Ligue 1"),
    ("4332", "football", "UEFA Champions League"),
    ("4334", "football", "UEFA Europa League"),
    ("4396", "football", "MLS"),
    ("4564", "football", "Liga 1 Indonesia"),
]

# TheSportsDB free API — fallback for football when ESPN returns 0 events.
# eventsnextleague.php returns ~15 next events per league (not date-range query).
# Called only as fallback after ESPN probe confirms zero football events in window.
def fetch_thesportsdb_events(window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetch football events from TheSportsDB (free, no API key).
    Returns (events_list, probe_dict) in the same shape as fetch_external_source.
    Only called as fallback when ESPN football endpoints all return 0 events.
    """
    all_events: List[Dict[str, Any]] = []
    probe = {"ok_buckets": [], "failed_buckets": [], "events_seen": 0, "events_in_window": 0, "source_type": "thesportsdb_free"}

    for league_id, sport_v31, competition in THESPORTSDB_LEAGUES:
        url = f"{THESPORTSDB_API}/eventsnextleague.php?id={league_id}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as exc:
            probe["failed_buckets"].append({"league_id": league_id, "error": str(exc)[:200]})
            continue

        events = data.get("events") or []
        if not events:
            continue
        probe["ok_buckets"].append(league_id)
        probe["events_seen"] += len(events)

        for ev in events:
            date_str = ev.get("dateEvent", "")
            time_str = ev.get("strTime", "")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(
                    f"{date_str} {time_str}" if time_str else date_str,
                    "%Y-%m-%d %H:%M:%S" if time_str else "%Y-%m-%d"
                )
            except ValueError:
                continue

            try:
                dt_wib = dt.replace(tzinfo=WIB)
            except Exception:
                continue
            if not (window_start <= dt_wib < window_end):
                continue

            probe["events_in_window"] += 1
            match: Dict[str, Any] = {
                "sport": sport_v31,
                "competition": competition,
                "team_a": ev.get("strHomeTeam", ""),
                "team_b": ev.get("strAwayTeam", ""),
                "kickoff_wib": dt_wib.isoformat(),
                "venue": ev.get("strVenue", ""),
                "status": "SCHEDULED",
                "event_name": ev.get("strEvent", f"{ev.get('strHomeTeam','')} vs {ev.get('strAwayTeam','')}"),
                "source_id": ev.get("idAPIfootball") or ev.get("idEvent", ""),
                "raw_source": "thesportsdb",
            }
            all_events.append(match)

    return all_events, probe


def classify_endpoint_probe(probe: Dict[str, Any]) -> str:
    if probe.get("DATA_SOURCE_DEGRADED"):
        return SOURCE_CLASS_DEGRADED
    ok_buckets = probe.get("ok_buckets") or []
    if not ok_buckets:
        return SOURCE_CLASS_INVALID
    if int(probe.get("events_in_window") or 0) > 0:
        return SOURCE_CLASS_OK
    return SOURCE_CLASS_OK_ZERO


def annotate_endpoint_probe(path: str, probe: Dict[str, Any]) -> Dict[str, Any]:
    info = {**probe, "classification": classify_endpoint_probe(probe)}
    if path in KNOWN_GAP_ENDPOINTS and info["classification"] == SOURCE_CLASS_INVALID:
        info["gap_status"] = KNOWN_GAP_PENDING_FALLBACK
        info["known_gap"] = True
        info["known_gap_reason"] = KNOWN_GAP_ENDPOINTS[path]
        info["fallback_status"] = "pending"
    return info


def espn_fetch(sport_path: str, dates: Optional[str] = None, timeout: int = 10) -> Dict[str, Any]:
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


def http_json(url: str, timeout: int = 15) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-SportScanner/3.2", "Accept": "application/json,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read()), "url": url, "status_code": getattr(r, "status", None)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": url}


def http_json_with_headers(url: str, headers: Dict[str, str], timeout: int = 15) -> Dict[str, Any]:
    try:
        merged_headers = {"User-Agent": "Hermes-SportScanner/3.2", "Accept": "application/json,*/*", **headers}
        req = urllib.request.Request(url, headers=merged_headers)
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


def http_text(url: str, timeout: int = 15) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-SportScanner/3.2", "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "text": r.read().decode("utf-8", errors="replace"), "url": url, "status_code": getattr(r, "status", None)}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            body = ""
        return {"ok": False, "error": str(exc)[:200], "url": url, "status_code": exc.code, "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": url}


def parse_iso_to_wib(value: str) -> Optional[datetime]:
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
    # EuroLeague season code starts in July: Sep 2025–Jun 2026 => E2025.
    year = target_day.year if target_day.month >= 7 else target_day.year - 1
    return f"E{year}"


def fetch_motogp_pulselive(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    path = "motogp/pulselive"
    probe: Dict[str, Any] = {
        "ok_buckets": [],
        "failed_buckets": [],
        "events_seen": 0,
        "events_in_window": 0,
        "source_type": "official_api",
        "api_base": MOTOGP_API_BASE,
        "session_handling": "MotoGP category only; session events for Race/Sprint/Qualifying, weekend fallback if sessions unavailable",
    }
    target_year = datetime.fromisoformat(date_str).year
    seasons_res = http_json(f"{MOTOGP_API_BASE}/results/seasons")
    if not seasons_res.get("ok"):
        probe["failed_buckets"].append({"step": "seasons", "error": seasons_res.get("error")})
        return [], probe
    seasons = seasons_res.get("data") or []
    season = next((x for x in seasons if int(x.get("year") or 0) == target_year), None) or next((x for x in seasons if x.get("current")), None)
    if not season or not season.get("id"):
        probe["failed_buckets"].append({"step": "season_select", "error": f"no season for {target_year}"})
        return [], probe
    season_uuid = season["id"]
    probe["season_uuid"] = season_uuid
    probe["season_year"] = season.get("year")

    cats_res = http_json(f"{MOTOGP_API_BASE}/results/categories?seasonUuid={urllib.parse.quote(season_uuid)}")
    if not cats_res.get("ok"):
        probe["failed_buckets"].append({"step": "categories", "error": cats_res.get("error")})
        return [], probe
    cats = cats_res.get("data") or []
    category = next((c for c in cats if "motogp" in str(c.get("name", "")).lower()), None)
    if not category or not category.get("id"):
        probe["failed_buckets"].append({"step": "category_select", "error": "MotoGP category not found"})
        return [], probe
    category_uuid = category["id"]
    probe["category_uuid"] = category_uuid
    probe["category_name"] = category.get("name")

    events_raw: List[Dict[str, Any]] = []
    for finished in ("false", "true"):
        url = f"{MOTOGP_API_BASE}/results/events?seasonUuid={urllib.parse.quote(season_uuid)}&isFinished={finished}"
        res = http_json(url)
        if not res.get("ok"):
            probe["failed_buckets"].append({"step": f"events_finished_{finished}", "error": res.get("error")})
            continue
        probe["ok_buckets"].append(f"events_finished_{finished}")
        events_raw.extend(res.get("data") or [])
    probe["events_seen"] = len(events_raw)

    allowed_session_types = {"RAC", "RACE", "SPR", "SPRINT", "Q1", "Q2", "QP", "Q"}
    out: List[Dict[str, Any]] = []
    for ev in events_raw:
        event_id = ev.get("id")
        if not event_id:
            continue
        sessions: List[Dict[str, Any]] = []
        sess_url = f"{MOTOGP_API_BASE}/results/sessions?eventUuid={urllib.parse.quote(event_id)}&categoryUuid={urllib.parse.quote(category_uuid)}"
        sess_res = http_json(sess_url)
        if sess_res.get("ok"):
            sessions = sess_res.get("data") or []
        else:
            probe.setdefault("session_fetch_errors", []).append({"event_id": event_id, "error": sess_res.get("error")})
        session_added = False
        for sess in sessions:
            typ = str(sess.get("type") or sess.get("session_type") or "").upper()
            name = str(sess.get("name") or sess.get("session_name") or typ).strip()
            label_blob = f"{typ} {name}".lower()
            if typ not in allowed_session_types and not any(x in label_blob for x in ("race", "sprint", "qualifying")):
                continue
            dt_wib = parse_iso_to_wib(str(sess.get("date") or ""))
            if not dt_wib or not (window_start <= dt_wib < window_end):
                continue
            session_added = True
            gp_name = (ev.get("sponsored_name") or ev.get("name") or "MotoGP Grand Prix").strip()
            session_label = name if name and name != typ else typ
            circuit = (ev.get("circuit") or {}).get("name") or sess.get("circuit") or ""
            out.append({
                "sport": "motorsport",
                "competition": "MotoGP",
                "event": f"{gp_name} — MotoGP {session_label}",
                "team_a": "MotoGP Field",
                "team_b": session_label,
                "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
                "kickoff_utc": sess.get("date"),
                "venue": circuit,
                "status": sess.get("status") or ev.get("status") or "scheduled",
                "fixture_source_path": path,
                "fixture_source_competition": "MotoGP",
                "fixture_source_name": "MotoGP PulseLive",
                "motogp_event_id": event_id,
                "motogp_session_id": sess.get("id"),
                "motogp_category_uuid": category_uuid,
                "motogp_category_name": category.get("name"),
                "motogp_session_type": typ,
                "motogp_weekend_start": ev.get("date_start"),
                "motogp_weekend_end": ev.get("date_end"),
                "source_event_shape": "motogp_session",
            })
            probe["events_in_window"] += 1
        # Weekend fallback: if qualifying/sprint/race sessions are not published yet, keep the race weekend discoverable.
        if not session_added:
            try:
                start = datetime.fromisoformat(str(ev.get("date_start"))).replace(tzinfo=WIB)
                end = datetime.fromisoformat(str(ev.get("date_end"))).replace(hour=23, minute=59, tzinfo=WIB)
            except Exception:
                continue
            if start < window_end and end >= window_start:
                gp_name = (ev.get("sponsored_name") or ev.get("name") or "MotoGP Grand Prix").strip()
                circuit = (ev.get("circuit") or {}).get("name") or ""
                out.append({
                    "sport": "motorsport",
                    "competition": "MotoGP",
                    "event": f"{gp_name} — MotoGP Race Weekend",
                    "team_a": "MotoGP Field",
                    "team_b": "Race Weekend",
                    "kickoff_wib": start.strftime("%Y-%m-%d %H:%M"),
                    "kickoff_utc": start.astimezone(timezone.utc).isoformat(),
                    "venue": circuit,
                    "status": ev.get("status") or "scheduled",
                    "fixture_source_path": path,
                    "fixture_source_competition": "MotoGP",
                    "fixture_source_name": "MotoGP PulseLive",
                    "motogp_event_id": event_id,
                    "motogp_category_uuid": category_uuid,
                    "motogp_category_name": category.get("name"),
                    "motogp_weekend_start": ev.get("date_start"),
                    "motogp_weekend_end": ev.get("date_end"),
                    "source_event_shape": "motogp_weekend",
                })
                probe["events_in_window"] += 1
    return out, probe


def fetch_euroleague_official(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    path = "euroleague/official"
    target_day = datetime.fromisoformat(date_str).date()
    season_code = euroleague_season_code(target_day)
    url = f"{EUROLEAGUE_API_BASE}/v2/competitions/E/seasons/{season_code}/games"
    probe: Dict[str, Any] = {
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
        probe["failed_buckets"].append({"step": "games", "season_code": season_code, "error": res.get("error")})
        return [], probe
    probe["ok_buckets"].append(f"games_{season_code}")
    games = (res.get("data") or {}).get("data") if isinstance(res.get("data"), dict) else res.get("data")
    games = games or []
    probe["events_seen"] = len(games)
    out: List[Dict[str, Any]] = []
    for g in games:
        dt_wib = parse_iso_to_wib(str(g.get("utcDate") or g.get("date") or ""))
        if not dt_wib or not (window_start <= dt_wib < window_end):
            continue
        home = ((g.get("local") or {}).get("club") or {}).get("name") or ((g.get("local") or {}).get("club") or {}).get("abbreviatedName") or "Home"
        away = ((g.get("road") or {}).get("club") or {}).get("name") or ((g.get("road") or {}).get("club") or {}).get("abbreviatedName") or "Away"
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


def _fiba_api_headers() -> Dict[str, str]:
    return {"Ocp-Apim-Subscription-Key": FIBA_FRONTEND_SUBSCRIPTION_KEY}


def _fiba_game_to_event(game: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
    dt_wib = parse_iso_to_wib(str(game.get("gameDateTimeUTC") or ""))
    if not dt_wib:
        return None
    team_a = (game.get("teamA") or {}).get("officialName") or (game.get("teamA") or {}).get("shortName") or "Team A"
    team_b = (game.get("teamB") or {}).get("officialName") or (game.get("teamB") or {}).get("shortName") or "Team B"
    competition = (game.get("competition") or {}).get("officialName") or "FIBA"
    level = "junior" if re.search(r"\bU\s*-?\s*(?:16|17|18|19|20|21)\b|Under\s*-?\s*(?:16|17|18|19|20|21)", competition, re.I) else "senior"
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
        "fiba_group_pairing_code": game.get("groupPairingCode"),
        "competition_level": level,
        "prediction_eligible": level != "junior",
        "validation": "NO_PREDICTION" if level == "junior" else None,
        "accuracy_excluded": level == "junior",
        "report_label": "[JUNIOR - NO PREDICTION]" if level == "junior" else None,
        "source_event_shape": "fiba_gdap_game",
    }


def _fiba_espn_worldcup_fallback(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    probe: Dict[str, Any] = {"ok_buckets": [], "failed_buckets": [], "events_seen": 0, "events_in_window": 0, "source_type": "espn_site_api", "scope": "FIBA World Cup only"}
    target_day = datetime.fromisoformat(date_str).date()
    buckets = [(target_day + timedelta(days=offset)).strftime("%Y%m%d") for offset in (-1, 0, 1)]
    out: List[Dict[str, Any]] = []
    for bucket in buckets:
        res = espn_fetch("basketball/fiba", bucket)
        if not res.get("ok"):
            probe["failed_buckets"].append({"date": bucket, "error": res.get("error")})
            continue
        probe["ok_buckets"].append(bucket)
        events = (res.get("data") or {}).get("events") or []
        probe["events_seen"] += len(events)
        for ev in events:
            norm = normalize_event(ev, "basketball", "FIBA World Cup")
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


def fetch_fiba_official(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    path = "fiba/official"
    date_from = urllib.parse.quote(window_start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), safe="")
    date_to = urllib.parse.quote(window_end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), safe="")
    url = f"{FIBA_API_BASE}/getgdapgamesbetweentwodates?dateFrom={date_from}&dateTo={date_to}"
    probe: Dict[str, Any] = {
        "ok_buckets": [],
        "failed_buckets": [],
        "events_seen": 0,
        "events_in_window": 0,
        "source_type": "official_api",
        "api_base": FIBA_API_BASE,
        "endpoint": "getgdapgamesbetweentwodates",
        "coverage": "all FIBA competitions returned by date-window GDAP endpoint",
        "fallback": "ESPN basketball/fiba (World Cup only)",
    }
    res = http_json_with_headers(url, _fiba_api_headers())
    if not res.get("ok"):
        status_code = res.get("status_code")
        degraded = status_code == 401
        probe["DATA_SOURCE_DEGRADED"] = bool(degraded)
        probe["degraded_reason"] = "fiba_subscription_key_unauthorized" if degraded else "fiba_api_fetch_failed"
        probe["failed_buckets"].append({"step": "getgdapgamesbetweentwodates", "status_code": status_code, "error": res.get("error"), "body": res.get("body")})
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
    out: List[Dict[str, Any]] = []
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


IBL_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _html_to_plain_text(raw_html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", raw_html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _parse_ibl_datetime(month: str, day: str, year: str, hm: str) -> Optional[datetime]:
    try:
        return datetime(int(year), IBL_MONTHS[month], int(day), int(hm[:2]), int(hm[3:5]), tzinfo=WIB)
    except Exception:
        return None


def parse_ibl_schedule_html(raw_html: str, path: str = "ibl/official") -> List[Dict[str, Any]]:
    text = _html_to_plain_text(raw_html)
    events: List[Dict[str, Any]] = []
    chunks = re.split(r"\bDATE/TIME\s*:\s*", text)
    for chunk in chunks[1:]:
        # Limit each block before the next record's residue or footer noise.
        chunk = re.split(r"\s+\*Last update\b|\s+Copyright\b|\s+CONTACT US\b", chunk, maxsplit=1)[0].strip()
        m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})\s*\|\s*(\d{2}:\d{2})\s+VENUE\s*:\s*(.+?)\s+(.+?)\s+(\d{1,3})\s+FINAL\s+(\d{1,3})\s+(.+)$", chunk)
        if not m:
            continue
        month, day, year, hm, venue, team_a, score_a, score_b, team_b = m.groups()
        dt = _parse_ibl_datetime(month, day, year, hm)
        if not dt:
            continue
        team_b = re.sub(r"\s+DATE/TIME\s*:.*$", "", team_b).strip()
        events.append({
            "sport": "basketball",
            "competition": "IBL Indonesia",
            "event": f"{team_a.strip()} vs {team_b.strip()}",
            "team_a": team_a.strip(),
            "team_b": team_b.strip(),
            "kickoff_wib": dt.strftime("%Y-%m-%d %H:%M"),
            "kickoff_utc": dt.astimezone(timezone.utc).isoformat(),
            "venue": venue.strip(),
            "status": "Final",
            "fixture_source_path": path,
            "fixture_source_competition": "IBL Indonesia",
            "fixture_source_name": "IBL Official HTML Schedule",
            "ibl_score_a": int(score_a),
            "ibl_score_b": int(score_b),
            "source_event_shape": "ibl_official_html_final_score",
        })
    return events


def fetch_ibl_official_html(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    path = "ibl/official"
    probe: Dict[str, Any] = {
        "ok_buckets": [],
        "failed_buckets": [],
        "events_seen": 0,
        "events_in_window": 0,
        "source_type": "official_html",
        "url": IBL_SCHEDULE_URL,
        "parser": "DATE/TIME + VENUE + team-score-FINAL-score-team deterministic regex",
        "offseason_policy": "ok_zero_events when official page has no parsed match inside 48h WIB window",
    }
    res = http_text(IBL_SCHEDULE_URL, timeout=20)
    if not res.get("ok"):
        probe["failed_buckets"].append({"step": "schedule_html", "status_code": res.get("status_code"), "error": res.get("error"), "body": res.get("body")})
        return [], probe
    probe["ok_buckets"].append("schedule_html")
    events = parse_ibl_schedule_html(res.get("text") or "", path=path)
    probe["events_seen"] = len(events)
    out: List[Dict[str, Any]] = []
    for ev in events:
        kickoff = parse_wib(ev.get("kickoff_wib", ""))
        if not kickoff or not (window_start <= kickoff < window_end):
            continue
        out.append(ev)
        probe["events_in_window"] += 1
    probe["season_window_status"] = "active" if probe["events_in_window"] else "offseason_or_no_matches_in_48h_window"
    return out, probe


def _team_name_from_slam_team(team: Any) -> str:
    if isinstance(team, list):
        players = team
    elif isinstance(team, dict):
        players = team.get("players") or [team]
    else:
        players = []
    names = []
    for p in players:
        if not isinstance(p, dict):
            continue
        first = str(p.get("firstNameA") or p.get("first_name") or p.get("firstName") or "").strip()
        last = str(p.get("lastNameA") or p.get("last_name") or p.get("lastName") or "").strip()
        display = str(p.get("displayNameA") or p.get("shortName") or p.get("short_name") or p.get("full_name") or "").strip()
        names.append((f"{first} {last}".strip() or display or "TBD"))
    return " / ".join([n for n in names if n and n != "TBD"]) or "TBD"


def _scoreline_from_sets(scores: Any) -> Optional[str]:
    if not isinstance(scores, dict):
        return None
    sets = scores.get("sets") or []
    parts = []
    for s in sets:
        if isinstance(s, list) and len(s) >= 2:
            a = s[0].get("scoreDisplay", s[0].get("score")) if isinstance(s[0], dict) else None
            b = s[1].get("scoreDisplay", s[1].get("score")) if isinstance(s[1], dict) else None
            if a is not None and b is not None:
                parts.append(f"{a}-{b}")
    return " ".join(parts) or None


def _slam_status(raw: Any, code: Any = None) -> str:
    s = str(raw or code or "scheduled")
    low = s.lower()
    if low in {"completed", "complete", "finished"} or str(code or "").upper() in {"D", "C", "CMP"}:
        return "completed"
    if "live" in low or "progress" in low:
        return "live"
    return s


def _date_from_epoch(epoch: Any) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(epoch), timezone.utc).astimezone(WIB)
    except Exception:
        return None


def _slam_ibm_match_to_event(match: Dict[str, Any], court: Dict[str, Any], competition: str, path: str, feed_url: str) -> Optional[Dict[str, Any]]:
    team_a = _team_name_from_slam_team(match.get("team1"))
    team_b = _team_name_from_slam_team(match.get("team2"))
    if team_a == "TBD" or team_b == "TBD":
        return None
    dt_wib = _date_from_epoch(court.get("startEpoch"))
    if not dt_wib:
        return None
    status = _slam_status(match.get("status"), match.get("statusCode"))
    ev = {
        "sport": "tennis",
        "competition": competition,
        "event": f"{team_a} vs {team_b}",
        "team_a": team_a,
        "team_b": team_b,
        "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
        "kickoff_utc": dt_wib.astimezone(timezone.utc).isoformat(),
        "venue": match.get("courtName") or court.get("courtName") or "",
        "status": status,
        "fixture_source_path": path,
        "fixture_source_competition": competition,
        "fixture_source_name": f"{competition} Official Feed",
        "grand_slam_match_id": match.get("match_id"),
        "grand_slam_event_name": match.get("eventName"),
        "grand_slam_round": match.get("roundName"),
        "scoreline": _scoreline_from_sets(match.get("scores")),
        "source_feed_url": feed_url,
        "source_event_shape": "grand_slam_ibm_schedule_match",
    }
    return ev


def _config_schedule_candidates(config_url: str, config: Dict[str, Any], target_year: int) -> List[str]:
    scoring = config.get("scoring") or {}
    sd = config.get("scoringData") or {}
    schedule_days = sd.get("scheduleDays") or ""
    candidates: List[str] = []
    def add(u: str) -> None:
        if u and u not in candidates:
            candidates.append(u)
    if schedule_days:
        absolute = urllib.parse.urljoin(config_url, schedule_days)
        add(re.sub(r"/20\d{2}/", f"/{target_year}/", absolute))
        add(absolute)
        origin = urllib.parse.urljoin(config_url, "/")[:-1]
        parsed = urllib.parse.urlparse(absolute)
        target_path = re.sub(r"/20\d{2}/", f"/{target_year}/", parsed.path)
        add(origin + target_path)
    base_host = config.get("baseHost") or scoring.get("jsonServer") or ""
    if base_host and schedule_days:
        add(urllib.parse.urljoin(base_host, re.sub(r"/20\d{2}/", f"/{target_year}/", schedule_days)))
        add(urllib.parse.urljoin(base_host, schedule_days))
    return candidates


def _fetch_ibm_grand_slam_from_config(config_url: str, competition: str, path: str, date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    target_year = datetime.fromisoformat(date_str).year
    probe: Dict[str, Any] = {"ok_buckets": [], "failed_buckets": [], "events_seen": 0, "events_in_window": 0, "source_type": "official_json_feed", "config_url": config_url, "auto_discovery": "config_web.json scoringData.scheduleDays + eventDays.feedUrl"}
    cfg = http_json(config_url, timeout=20)
    if not cfg.get("ok"):
        probe["failed_buckets"].append({"step": "config", "error": cfg.get("error")})
        return [], probe
    config = cfg.get("data") or {}
    probe["ok_buckets"].append("config_web.json")
    candidates = _config_schedule_candidates(config_url, config, target_year)
    probe["schedule_days_candidates"] = candidates[:6]
    days_data = None
    schedule_days_url = None
    for u in candidates:
        res = http_json(u, timeout=20)
        if res.get("ok"):
            days_data = res.get("data") or {}
            schedule_days_url = u
            probe["ok_buckets"].append("scheduleDays.json")
            break
        probe["failed_buckets"].append({"step": "scheduleDays", "url": u, "error": res.get("error")})
    if not days_data:
        return [], probe
    event_days = days_data.get("eventDays") or []
    probe["schedule_days_url"] = schedule_days_url
    probe["schedule_days_seen"] = len(event_days)
    out: List[Dict[str, Any]] = []
    for day in event_days:
        if day.get("practice"):
            continue
        day_dt = _date_from_epoch(day.get("epoch"))
        if not day_dt or not (window_start.date() <= day_dt.date() <= (window_end - timedelta(minutes=1)).date()):
            continue
        feed_url = day.get("feedUrl")
        if not feed_url:
            continue
        feed_url = re.sub(r"/20\d{2}/", f"/{target_year}/", urllib.parse.urljoin(schedule_days_url, feed_url))
        sched = http_json(feed_url, timeout=25)
        if not sched.get("ok"):
            probe["failed_buckets"].append({"step": "schedule", "url": feed_url, "error": sched.get("error")})
            continue
        probe["ok_buckets"].append(f"schedule_day_{day.get('tournDay') or day.get('displayDay')}")
        for court in (sched.get("data") or {}).get("courts") or []:
            for match in court.get("matches") or []:
                probe["events_seen"] += 1
                ev = _slam_ibm_match_to_event(match, court, competition, path, feed_url)
                if not ev:
                    continue
                kickoff = parse_wib(ev.get("kickoff_wib", ""))
                if not kickoff or not (window_start <= kickoff < window_end):
                    continue
                out.append(ev)
                probe["events_in_window"] += 1
    return out, probe


def fetch_wimbledon_official(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    events, probe = _fetch_ibm_grand_slam_from_config(WIMBLEDON_CONFIG_URL, "Wimbledon", "tennis/grand_slam/wimbledon", date_str, window_start, window_end)
    probe["espn_coarse_presence"] = _espn_tennis_presence(date_str, "Wimbledon")
    return events, probe


def fetch_us_open_official(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    events, probe = _fetch_ibm_grand_slam_from_config(US_OPEN_CONFIG_URL, "US Open", "tennis/grand_slam/us_open", date_str, window_start, window_end)
    probe["espn_coarse_presence"] = _espn_tennis_presence(date_str, "US Open")
    return events, probe


def _espn_tennis_presence(date_str: str, needle: str) -> Dict[str, Any]:
    target_day = datetime.fromisoformat(date_str).date()
    buckets = [(target_day + timedelta(days=o)).strftime("%Y%m%d") for o in (-1, 0, 1)]
    out = {"needle": needle, "ok_buckets": [], "failed_buckets": [], "events_seen": 0, "matching_events": []}
    for tour in ("tennis/atp", "tennis/wta"):
        for b in buckets:
            res = espn_fetch(tour, b)
            if not res.get("ok"):
                out["failed_buckets"].append({"tour": tour, "date": b, "error": res.get("error")})
                continue
            out["ok_buckets"].append(f"{tour}:{b}")
            events = (res.get("data") or {}).get("events") or []
            out["events_seen"] += len(events)
            for ev in events:
                name = str(ev.get("name") or ev.get("shortName") or "")
                if needle.lower().replace(" ", "") in name.lower().replace(" ", ""):
                    out["matching_events"].append({"tour": tour, "date": b, "event_id": ev.get("id"), "name": name, "event_date": ev.get("date")})
    return out


def _ao_team_name(team_ref: Dict[str, Any], teams_by_id: Dict[str, Any], players_by_id: Dict[str, Any]) -> str:
    team = teams_by_id.get(str(team_ref.get("team_id"))) or {}
    names = []
    for pid in team.get("players") or []:
        p = players_by_id.get(str(pid)) or {}
        names.append(p.get("full_name") or p.get("short_name") or "TBD")
    return " / ".join([n for n in names if n and n != "TBD"]) or "TBD"


def fetch_australian_open_official(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    year = datetime.fromisoformat(date_str).year
    path = "tennis/grand_slam/australian_open"
    periods = ["MD", "QD", "PT", "CH", "JR", "WC", "D"]
    probe: Dict[str, Any] = {"ok_buckets": [], "failed_buckets": [], "events_seen": 0, "events_in_window": 0, "source_type": "official_api", "api_template": AUSTRALIAN_OPEN_API_TEMPLATE, "period_codes_probed": periods, "valid_period_codes": []}
    out: List[Dict[str, Any]] = []
    for period in periods:
        for day in range(1, 23):
            url = AUSTRALIAN_OPEN_API_TEMPLATE.format(year=year, period=period, day=day)
            res = http_json(url, timeout=20)
            if not res.get("ok"):
                if day == 1:
                    probe["failed_buckets"].append({"period": period, "day": day, "error": res.get("error")})
                break
            data = res.get("data") or {}
            if "schedule" not in data:
                if day == 1 and str(data.get("heading")) == "No Schedules":
                    probe["ok_buckets"].append(f"{period}:no_schedules")
                break
            if period not in probe["valid_period_codes"]:
                probe["valid_period_codes"].append(period)
            probe["ok_buckets"].append(f"{period}:day_{day}")
            players_by_id = {str(p.get("uuid")): p for p in data.get("players") or [] if isinstance(p, dict)}
            teams_by_id = {str(t.get("uuid")): t for t in data.get("teams") or [] if isinstance(t, dict)}
            events_by_id = {str(e.get("uuid")): e for e in data.get("events") or [] if isinstance(e, dict)}
            rounds_by_id = {str(r.get("uuid")): r for r in data.get("rounds") or [] if isinstance(r, dict)}
            court_names = {str(c.get("uuid") or c.get("id")): c.get("name") for c in data.get("courts") or [] if isinstance(c, dict)}
            for court in (data.get("schedule") or {}).get("courts") or []:
                court_name = court_names.get(str(court.get("court_id"))) or str(court.get("court_id") or "")
                for sess in court.get("sessions") or []:
                    session_ts = sess.get("session_start_time_timestamp")
                    for act in sess.get("activities") or []:
                        probe["events_seen"] += 1
                        teams = act.get("teams") or []
                        if len(teams) < 2:
                            continue
                        team_a = _ao_team_name(teams[0], teams_by_id, players_by_id)
                        team_b = _ao_team_name(teams[1], teams_by_id, players_by_id)
                        dt_wib = _date_from_epoch(session_ts)
                        if not dt_wib:
                            continue
                        status = _slam_status(act.get("match_state"), (act.get("match_status") or {}).get("abbr"))
                        ev = {
                            "sport": "tennis", "competition": "Australian Open", "event": f"{team_a} vs {team_b}", "team_a": team_a, "team_b": team_b,
                            "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"), "kickoff_utc": dt_wib.astimezone(timezone.utc).isoformat(), "venue": court_name,
                            "status": status, "fixture_source_path": path, "fixture_source_competition": "Australian Open", "fixture_source_name": "Australian Open Official API",
                            "grand_slam_match_id": act.get("match_id") or act.get("uuid"), "grand_slam_event_name": (events_by_id.get(str(act.get("event_uuid"))) or {}).get("name"),
                            "grand_slam_round": (rounds_by_id.get(str(act.get("round_id"))) or {}).get("name"), "source_feed_url": url, "source_event_shape": "australian_open_schedule_activity",
                        }
                        kickoff = parse_wib(ev["kickoff_wib"])
                        if kickoff and window_start <= kickoff < window_end:
                            out.append(ev); probe["events_in_window"] += 1
    probe["espn_coarse_presence"] = _espn_tennis_presence(date_str, "Australian Open")
    return out, probe


def fetch_roland_garros_official(date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    path = "tennis/grand_slam/roland_garros"
    probe: Dict[str, Any] = {"ok_buckets": [], "failed_buckets": [], "events_seen": 0, "events_in_window": 0, "source_type": "official_ssr", "url": ROLAND_GARROS_MATCHES_URL, "parser": "window.__NUXT__ SSR regex"}
    res = http_text(ROLAND_GARROS_MATCHES_URL, timeout=25)
    if not res.get("ok"):
        probe["failed_buckets"].append({"step": "matches_page", "error": res.get("error")})
        return [], probe
    raw = res.get("text") or ""
    out: List[Dict[str, Any]] = []
    probe["ok_buckets"].append("matches_page")
    margs = re.search(r"window\.__NUXT__=\(function\(([^)]*)\).*?\}\((.*)\)\);</script>", raw, re.S)
    varmap: Dict[str, str] = {}
    if margs:
        names = [x.strip() for x in margs.group(1).split(",")]
        vals = re.findall(r'"((?:\\.|[^"\\])*)"|\b(null|false|true|\d+)\b', margs.group(2))
        flat = [(a or b) for a, b in vals]
        for n, v in zip(names, flat):
            varmap[n] = v.encode().decode("unicode_escape") if isinstance(v, str) else str(v)
    default_date = varmap.get("p") or ""
    for block in re.findall(r'\{id:"([A-Z]{1,3}\d{3})"(.*?)(?=\},\{id:"[A-Z]{1,3}\d{3}"|\]\}\],fetch)', raw, flags=re.S):
        match_id, body = block
        probe["events_seen"] += 1
        type_m = re.search(r'typeLabel:"([^"]+)"', body)
        court_m = re.search(r'courtName:(?:"([^"]+)"|([a-zA-Z_$][\w$]*))', body)
        date_m = re.search(r'dateSchedule:(?:"(\d{8})"|([a-zA-Z_$][\w$]*))', body)
        status_m = re.search(r'statusLabel:"([^"]+)"', body)
        team_a_body = re.search(r'teamA:\{players:\[(.*?)\],sets:', body, flags=re.S)
        team_b_body = re.search(r'teamB:\{players:\[(.*?)\],sets:', body, flags=re.S)
        def names_from_rg(s: str) -> str:
            names = []
            for first, last in re.findall(r'firstName:"([^"]+)",lastName:"([^"]+)"', s or ""):
                names.append(f"{first} {last}".title())
            return " / ".join(names) or "TBD"
        team_a = names_from_rg(team_a_body.group(1) if team_a_body else "")
        team_b = names_from_rg(team_b_body.group(1) if team_b_body else "")
        date_token = (date_m.group(1) or varmap.get(date_m.group(2), "")) if date_m else default_date
        try:
            dt_wib = datetime.strptime(date_token, "%Y%m%d").replace(tzinfo=WIB)
        except Exception:
            continue
        if team_a == "TBD" or team_b == "TBD":
            continue
        ev = {"sport": "tennis", "competition": "Roland Garros", "event": f"{team_a} vs {team_b}", "team_a": team_a, "team_b": team_b, "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"), "kickoff_utc": dt_wib.astimezone(timezone.utc).isoformat(), "venue": (court_m.group(1) or varmap.get(court_m.group(2), "")) if court_m else "", "status": _slam_status(status_m.group(1) if status_m else "scheduled"), "fixture_source_path": path, "fixture_source_competition": "Roland Garros", "fixture_source_name": "Roland Garros Official SSR", "grand_slam_match_id": match_id, "grand_slam_event_name": type_m.group(1) if type_m else None, "source_feed_url": ROLAND_GARROS_MATCHES_URL, "source_event_shape": "roland_garros_nuxt_match"}
        kickoff = parse_wib(ev["kickoff_wib"])
        if kickoff and window_start <= kickoff < window_end:
            out.append(ev); probe["events_in_window"] += 1
    probe["espn_coarse_presence"] = _espn_tennis_presence(date_str, "French Open")
    return out, probe


def fetch_external_source(path: str, kind: str, date_str: str, window_start: datetime, window_end: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if kind == "motogp_pulselive":
        return fetch_motogp_pulselive(date_str, window_start, window_end)
    if kind == "euroleague_official":
        return fetch_euroleague_official(date_str, window_start, window_end)
    if kind == "fiba_official":
        return fetch_fiba_official(date_str, window_start, window_end)
    if kind == "ibl_official_html":
        return fetch_ibl_official_html(date_str, window_start, window_end)
    if kind == "grand_slam_wimbledon":
        return fetch_wimbledon_official(date_str, window_start, window_end)
    if kind == "grand_slam_us_open":
        return fetch_us_open_official(date_str, window_start, window_end)
    if kind == "grand_slam_australian_open":
        return fetch_australian_open_official(date_str, window_start, window_end)
    if kind == "grand_slam_roland_garros":
        return fetch_roland_garros_official(date_str, window_start, window_end)
    return [], {"ok_buckets": [], "failed_buckets": [{"step": "unknown_source", "error": kind}], "events_seen": 0, "events_in_window": 0}


def searxng_search(query: str, limit: int = 5, timeout: int = 15) -> List[Dict[str, Any]]:
    """SearXNG evidence search used alongside ESPN structured fixtures.

    ESPN identifies real fixtures; SearXNG supplies corroborating/open-web evidence.
    This keeps v3.1 compliant with SearXNG search while preserving structured dates.
    """
    params = {"q": query, "format": "json", "language": "en", "safesearch": 0}
    url = f"{SEARXNG_URL}/search?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-SportScanner/3.2"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        out = []
        seen = set()
        for item in data.get("results", []) or []:
            u = item.get("url")
            if not u or u in seen:
                continue
            seen.add(u)
            out.append({
                "title": item.get("title"),
                "url": u,
                "snippet": item.get("content"),
                "engine": item.get("engine"),
                "score": item.get("score"),
            })
            if len(out) >= limit:
                break
        return out
    except Exception as exc:
        audit("searxng_event_enrich_failed", "error", {"query": query, "error": str(exc)[:200]})
        return []


    # Five-source research matrix per v3.1 deep-research spec.
# Each source has a SearXNG query template (with site: filters) and a per-source hit cap.
# Sports applicability is encoded per source so we skip irrelevant queries for tennis/motorsport/NFL.
SOURCE_MATRIX: Dict[str, Dict[str, Any]] = {
    "general": {
        "label": "General web preview",
        "query": "{event} {competition} preview lineup injury odds",
        "limit": 4,
        "applies_to": ["football", "tennis", "motorsport", "basketball", "nfl"],
    },
    "twitter": {
        "label": "Twitter/X official accounts",
        "query": "(site:x.com OR site:twitter.com) {team_a} {team_b} (injury OR lineup OR roster)",
        "limit": 3,
        "applies_to": ["football", "tennis", "motorsport", "basketball", "nfl"],
    },
    "reddit": {
        "label": "Reddit fan sentiment / match thread",
        "query": "site:reddit.com {event} prediction OR preview OR thread",
        "limit": 3,
        "applies_to": ["football", "basketball", "nfl", "motorsport"],
    },
    "youtube": {
        "label": "YouTube press conference / tactical preview",
        "query": "site:youtube.com {team_a} {team_b} (press conference OR preview OR tactical)",
        "limit": 2,
        "applies_to": ["football", "basketball", "nfl", "motorsport"],
        "note": "Depends on SearXNG YouTube coverage; transcript extracted when video found.",
    },
    "advanced_stats": {
        "label": "Advanced stats (Whoscored/FBref/Understat)",
        "query": "(site:whoscored.com OR site:fbref.com OR site:understat.com) {team_a} {team_b} stats preview",
        "limit": 3,
        "applies_to": ["football"],
    },
}


def _extract_youtube_id(url: str) -> Optional[str]:
    """Extract 11-char YouTube video ID from a watch / shorts / youtu.be URL."""
    if not url:
        return None
    import re as _re
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = _re.search(p, url)
        if m:
            return m.group(1)
    return None


def _yt_transcript_snippet(video_id: str, max_chars: int = 1200) -> Optional[Dict[str, Any]]:
    """Best-effort YouTube transcript fetch via yt-dlp. Returns None on any failure.

    Does not require cookies — relies on YouTube's auto-generated captions.
    Handles both plain VTT and YouTube's JSON3 caption formats.
    """
    if not video_id:
        return None
    try:
        import subprocess as _sp
        url = f"https://www.youtube.com/watch?v={video_id}"
        # Step 1: get video metadata including subtitle URLs
        proc2 = _sp.run(
            ["yt-dlp", "--skip-download", "--dump-json", url],
            capture_output=True, text=True, timeout=30,
        )
        if proc2.returncode != 0:
            return None
        meta = json.loads(proc2.stdout)
        # Step 2: pick first English subtitle URL (manual or auto)
        subs = (meta.get("subtitles") or {}).get("en") or (meta.get("automatic_captions") or {}).get("en") or []
        if not subs:
            return None
        # Prefer srv1/srv2/srv3 (timed text JSON) over plain VTT for resilience.
        sub_url = None
        sub_format = None
        for s in subs:
            ext = (s.get("ext") or "").lower()
            if ext in ("json3", "srv1", "srv2", "srv3"):
                sub_url = s.get("url")
                sub_format = ext
                break
        if not sub_url:
            sub_url = subs[0].get("url")
            sub_format = (subs[0].get("ext") or "").lower()
        if not sub_url:
            return None
        # Step 3: download caption payload
        with urllib.request.urlopen(sub_url, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="replace")
        # Step 4: parse — supports JSON3 and plain VTT
        import re as _re
        text_lines: List[str] = []
        if sub_format in ("json3", "srv1", "srv2", "srv3") or raw.lstrip().startswith("{"):
            try:
                payload = json.loads(raw)
                events = payload.get("events") or []
                for ev in events:
                    for seg in ev.get("segs") or []:
                        u = seg.get("utf8") or ""
                        if u and u != "\n":
                            cleaned = _re.sub(r"<[^>]+>", "", u).strip()
                            if cleaned:
                                text_lines.append(cleaned)
            except Exception:
                # Fall back to treating as vtt
                for line in raw.splitlines():
                    if "-->" in line or line.startswith("WEBVTT") or not line.strip():
                        continue
                    text_lines.append(_re.sub(r"<[^>]+>", "", line).strip())
        else:
            # Plain VTT
            for line in raw.splitlines():
                if "-->" in line or line.startswith("WEBVTT") or not line.strip():
                    continue
                text_lines.append(_re.sub(r"<[^>]+>", "", line).strip())
        snippet = " ".join(t for t in text_lines if t)[:max_chars]
        return {
            "video_id": video_id,
            "title": meta.get("title"),
            "transcript_snippet": snippet,
            "url": url,
            "format": sub_format or "vtt",
        }
    except Exception:
        return None


def multi_source_research(ev: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    """Run the v3.1 5-source research matrix for a single event.

    Returns a dict keyed by source name; each value contains SearXNG hits and
    (for YouTube) an optional transcript snippet. Empty/missing sources are
    represented as empty lists so the LLM sees the full picture.
    """
    sport = ev.get("sport", "football")
    team_a = ev.get("team_a") or ev.get("event", "").split(" vs ")[0]
    team_b = ev.get("team_b") or (ev.get("event", "").split(" vs ")[1] if " vs " in ev.get("event", "") else "")
    event = ev.get("event", "")
    competition = ev.get("competition", "")
    out: Dict[str, Any] = {"by_source": {}, "queries_run": [], "youtube_transcript": None}

    for src_key, spec in SOURCE_MATRIX.items():
        if sport not in spec.get("applies_to", []):
            out["by_source"][src_key] = {"label": spec["label"], "applies": False, "hits": []}
            continue
        q = spec["query"].format(event=event, competition=competition, team_a=team_a, team_b=team_b)
        out["queries_run"].append({"source": src_key, "query": q})
        hits = searxng_search(q, limit=spec.get("limit", 3), timeout=timeout)
        out["by_source"][src_key] = {
            "label": spec["label"],
            "applies": True,
            "query": q,
            "hits": hits,
        }

    # YouTube: pick first YouTube hit, attempt transcript extraction.
    yt_hits = out["by_source"].get("youtube", {}).get("hits", []) or []
    for h in yt_hits:
        vid = _extract_youtube_id(h.get("url", ""))
        if vid:
            tr = _yt_transcript_snippet(vid)
            if tr:
                out["youtube_transcript"] = tr
                break

    # Pick a single best evidence URL (prefer official/Whoscored, fall back to first)
    candidates = []
    for src_key in ("advanced_stats", "general", "twitter", "reddit", "youtube"):
        for h in out["by_source"].get(src_key, {}).get("hits", []) or []:
            u = h.get("url", "")
            if u:
                candidates.append((src_key, u, h.get("title"), h.get("snippet")))
    out["best_evidence"] = candidates[0] if candidates else None
    return out


def representative(c: Dict[str, Any]) -> str:
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


def normalize_event(event: Dict[str, Any], sport_v31: str, competition: str) -> Optional[Dict[str, Any]]:
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


def slug_key(ev: Dict[str, Any]) -> str:
    base = f"{ev['sport']}|{ev['competition']}|{ev['team_a']}|{ev['team_b']}|{ev['kickoff_wib']}"
    s = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return s[:120]


def ingest_for_date(target_date: Optional[str] = None, sports_filter: Optional[List[str]] = None,
                     enrich: bool = True) -> Dict[str, Any]:
    """Ingest ESPN fixtures for `target_date`. If None, today WIB.

    enrich=True also calls SearXNG for each event to attach an evidence URL.
    Without enrich, only ESPN fixture metadata is recorded (faster).

    Returns summary dict.
    """
    date_str = target_date or today_wib()
    target_day = datetime.fromisoformat(date_str).date()
    window_start = datetime.combine(target_day, datetime.min.time(), tzinfo=WIB)
    # Daily scan is a 7-day WIB window (spec: "00:00 WIB ambil 7 hari ke depan").
    # Bucket range spans 13 days: day-7 through day+5 UTC to ensure full
    # coverage of the 7-day WIB window, accounting for UTC→WIB date shift.
    window_end = window_start + timedelta(days=7)
    espn_buckets = [
        (target_day + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(-7, 8)
    ]

    all_events: List[Dict[str, Any]] = []
    no_event: List[Dict[str, Any]] = []
    sports_covered: List[str] = []
    sport_has_event: Dict[str, bool] = {s: False for s in ("football", "tennis", "motorsport", "basketball", "nfl")}
    endpoint_probe: Dict[str, Dict[str, Any]] = {}

    for espn_path, sport_v31, competition in LEAGUE_CONFIG:
        if sports_filter and sport_v31 not in sports_filter:
            continue
        endpoint_probe.setdefault(espn_path, {"ok_buckets": [], "failed_buckets": [], "events_seen": 0, "events_in_window": 0, "source_type": "espn_site_api"})
        for espn_date in espn_buckets:
            result = espn_fetch(espn_path, espn_date)
            if not result.get("ok"):
                endpoint_probe[espn_path]["failed_buckets"].append({"date": espn_date, "error": result.get("error")})
                audit("espn_fetch_failed", "error", {"path": espn_path, "date_bucket": espn_date, "error": result.get("error")})
                continue
            endpoint_probe[espn_path]["ok_buckets"].append(espn_date)
            events = result["data"].get("events", [])
            endpoint_probe[espn_path]["events_seen"] += len(events)
            for ev in events:
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

    for source_path, sport_v31, competition, source_kind in EXTERNAL_SOURCE_CONFIG:
        if sports_filter and sport_v31 not in sports_filter:
            continue
        events, probe = fetch_external_source(source_path, source_kind, date_str, window_start, window_end)
        probe.setdefault("source_type", "official_api")
        probe["source_kind"] = source_kind
        probe["competition"] = competition
        endpoint_probe[source_path] = probe
        for norm in events:
            all_events.append(norm)
            sport_has_event[sport_v31] = True

    # ── Fallback: TheSportsDB for football if ESPN returned zero football events ──
    # Only trigger when ESPN had some successful buckets (not a network failure)
    # but still ended up with no football events in the window.
    football_probes = {
        path: probe
        for path, probe in endpoint_probe.items()
        if any(sport in path for sport in ("soccer", "football")) and path.startswith("soccer/")
    }
    football_had_events = any(
        probe.get("events_in_window", 0) > 0 for probe in football_probes.values()
    )
    if not football_had_events and not sports_filter or "football" in (sports_filter or []):
        # Check if ESPN at least reached the API (has some ok_buckets)
        espn_football_reached = any(
            probe.get("ok_buckets") for probe in football_probes.values()
        )
        if espn_football_reached:
            audit("thesportsdb_fallback", "triggered", {
                "reason": "espn_football_zero_events_despite_reach",
                "window": f"{window_start.date()} to {window_end.date()}",
            })
            tsdb_events, tsdb_probe = fetch_thesportsdb_events(window_start, window_end)
            endpoint_probe["thesportsdb/fallback"] = tsdb_probe
            for ev in tsdb_events:
                ev["fixture_source_path"] = "thesportsdb/fallback"
                ev["fixture_source_name"] = "TheSportsDB"
                ev["fixture_source_competition"] = ev.get("competition", "")
                all_events.append(ev)
                sport_has_event[ev.get("sport", "football")] = True
            if tsdb_probe.get("events_in_window"):
                audit("thesportsdb_fallback", "ok", {
                    "events_ingested": tsdb_probe["events_in_window"],
                    "leagues_reached": len(tsdb_probe.get("ok_buckets", [])),
                })

    source_classification = {path: annotate_endpoint_probe(path, probe) for path, probe in endpoint_probe.items()}

    audit("espn_3bucket_probe", "ok", {
        "date": date_str,
        "buckets": espn_buckets,
        "window_start_wib": window_start.isoformat(timespec="minutes"),
        "window_end_wib": window_end.isoformat(timespec="minutes"),
        "endpoints": source_classification,
    })

    # NO_EVENT entries for sports still empty
    for sport_v31 in ("football", "tennis", "motorsport", "basketball", "nfl"):
        if not sport_has_event.get(sport_v31):
            no_event.append({
                "sport": sport_v31,
                "reason": "no_fixtures_in_espn_api_window",
            })

    # Assign IDs + dedupe, and enrich each ESPN fixture with SearXNG evidence.
    seen_keys = set()
    unique: List[Dict[str, Any]] = []
    for ev in all_events:
        k = slug_key(ev)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        ev["event_id"] = k
        ev["needs_research"] = True
        ev["researched"] = False
        # v3.1 5-source research matrix (general + twitter + reddit + youtube + advanced_stats).
        # YouTube transcript is best-effort (yt-dlp, no cookies required).
        research = multi_source_research(ev, timeout=12)
        ev["source_research"] = research
        # Backwards-compatible single-query summary fields (LLM still reads these).
        q = research.get("queries_run", [{}])[0].get("query") if research.get("queries_run") else ""
        ev["searxng_query"] = q
        # Flatten all SearXNG hits across sources for the LLM to see at a glance.
        flat_evidence = []
        for src_key, src in (research.get("by_source") or {}).items():
            for h in (src.get("hits") or []):
                flat_evidence.append({
                    "source": src_key,
                    "title": h.get("title"),
                    "url": h.get("url"),
                    "snippet": h.get("snippet"),
                    "engine": h.get("engine"),
                })
        ev["searxng_evidence"] = flat_evidence
        degraded = len(flat_evidence) == 0
        fixture_source_name = ev.get("fixture_source_name") or "ESPN"
        sources_used = [fixture_source_name] + sorted({h.get("source") for h in flat_evidence if h.get("source")})
        ev["DATA_SOURCE_DEGRADED"] = degraded
        fixture_source_path = ev.get("fixture_source_path")
        fixture_source_status = (source_classification.get(fixture_source_path) or {}).get("classification") if fixture_source_path else None
        ev["data_source"] = {
            "fixture_source": fixture_source_name,
            "fixture_source_path": fixture_source_path,
            "fixture_source_competition": ev.get("fixture_source_competition"),
            "fixture_source_status": fixture_source_status,
            "research_primary": "SearXNG",
            "sources_used": sources_used or [fixture_source_name],
            "fallback_sources_used": [] if not degraded else ["llm-wiki"],
            "DATA_SOURCE_DEGRADED": degraded,
            "degraded_reason": None if not degraded else "searxng_returned_no_research_evidence",
            "confidence_penalty_applied": -15 if degraded else 0,
            "source_event_shape": ev.get("source_event_shape"),
        }
        # Prefer advanced_stats evidence_url > general > twitter > reddit > youtube.
        be = research.get("best_evidence")
        if be:
            ev["evidence_url"] = be[1]
            ev["evidence_title"] = be[2]
            ev["evidence_source"] = be[0]
        else:
            ev["evidence_url"] = None
            ev["evidence_title"] = None
            ev["evidence_source"] = None
        if research.get("youtube_transcript"):
            ev["youtube_transcript"] = research["youtube_transcript"]
        unique.append(ev)

    # Write schedule JSON
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    schedule = {
        "date_wib": date_str,
        "generated_at_wib": now_wib().isoformat(timespec="seconds"),
        "generator": "sports_v32_multi_source_ingest",
        "searxng_endpoint": "http://10.10.10.5:8888",
        "sports_covered": [s for s, has in sport_has_event.items() if has],
        "fixture_source_classification": source_classification,
        "no_event": no_event,
        "events": unique,
        "event_count": len(unique),
        "no_event_count": len(no_event),
    }
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    out_sched = SCHEDULE_DIR / f"{date_str}.json"
    out_sched.write_text(json.dumps(schedule, indent=2, ensure_ascii=False))

    # Write predictions stubs while preserving already researched predictions.
    # This makes the ingester safe to re-run during watcher ticks / audits.
    out_pred = PRED_DIR / f"{date_str}.json"
    existing_by_id: Dict[str, Dict[str, Any]] = {}
    if out_pred.exists():
        try:
            existing_doc = json.loads(out_pred.read_text())
            for row in existing_doc.get("predictions", []) if isinstance(existing_doc, dict) else []:
                if row.get("match_id"):
                    existing_by_id[row["match_id"]] = row
        except Exception:
            existing_by_id = {}
    preds = []
    for ev in unique:
        stub = {
            "match_id": ev["event_id"],
            "sport": ev["sport"],
            "competition": ev["competition"],
            "event": ev["event"],
            "kickoff_wib": ev["kickoff_wib"],
            "venue": ev.get("venue", ""),
            "evidence_url": ev.get("evidence_url"),
            "evidence_title": ev.get("evidence_title"),
            "evidence_source": ev.get("evidence_source"),
            "searxng_query": ev.get("searxng_query"),
            "searxng_evidence": ev.get("searxng_evidence", []),
            "source_research": ev.get("source_research"),
            "youtube_transcript": ev.get("youtube_transcript"),
            "predicted_outcome": None,
            "predicted_score_or_result": None,
            "confidence_percent": None,
            "confidence_label": None,
            "confidence_breakdown": None,
            "confidence_model_version": "v3.2",
            "risk_score_1_to_10": None,
            "no_pick": False if ev.get("prediction_eligible", True) else True,
            "competition_level": ev.get("competition_level") or "senior",
            "prediction_eligible": ev.get("prediction_eligible", True),
            "validation_status": ev.get("validation"),
            "validation": ev.get("validation"),
            "accuracy_excluded": ev.get("accuracy_excluded", False),
            "report_label": ev.get("report_label"),
            "DATA_SOURCE_DEGRADED": ev.get("DATA_SOURCE_DEGRADED", False),
            "data_source": ev.get("data_source"),
            "reasoning": [],
            "researched": False,
            "stub": True,
            "espn_event_id": ev.get("espn_event_id"),
            "team_a": ev["team_a"],
            "team_b": ev["team_b"],
        }
        old = existing_by_id.get(ev["event_id"])
        if old and old.get("researched") and not old.get("stub"):
            # Preserve prediction fields, refresh only discovery/evidence metadata.
            old.update({k: stub[k] for k in ["sport", "competition", "event", "kickoff_wib", "venue", "evidence_url", "evidence_title", "evidence_source", "searxng_query", "searxng_evidence", "source_research", "youtube_transcript", "competition_level", "prediction_eligible", "validation_status", "validation", "accuracy_excluded", "report_label", "DATA_SOURCE_DEGRADED", "data_source", "espn_event_id", "team_a", "team_b"]})
            preds.append(old)
        else:
            preds.append(stub)
    pred_doc = {
        "date_wib": date_str,
        "generated_at_wib": now_wib().isoformat(timespec="seconds"),
        "generator": "sports_v32_multi_source_ingest",
        "fixture_source_classification": source_classification,
        "predictions": preds,
    }
    out_pred = PRED_DIR / f"{date_str}.json"
    out_pred.write_text(json.dumps(pred_doc, indent=2, ensure_ascii=False))

    audit("espn_ingest_complete", "ok", {
        "date": date_str,
        "events": len(unique),
        "no_event": len(no_event),
        "sports_covered": schedule["sports_covered"],
        "fixture_source_classification": {path: info.get("classification") for path, info in source_classification.items()},
    })

    return {
        "ok": True,
        "date_wib": date_str,
        "events_total": len(unique),
        "no_event_total": len(no_event),
        "sports_with_events": schedule["sports_covered"],
        "fixture_source_classification": source_classification,
        "schedule_file": str(out_sched),
        "predictions_file": str(out_pred),
    }


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Sport Scanning AI v3.1 — ESPN fixture ingester")
    p.add_argument("--date", default=today_wib())
    p.add_argument("--sport", action="append")
    args = p.parse_args()
    result = ingest_for_date(args.date, args.sport)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
