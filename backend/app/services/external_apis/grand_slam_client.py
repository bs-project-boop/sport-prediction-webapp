# grand_slam_client.py — Grand Slam API clients for Stage 1 Discovery
# Includes: Wimbledon, US Open, Australian Open, Roland Garros
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

WIB = timezone(timedelta(hours=7))
WIMBLEDON_CONFIG_URL = "https://www.wimbledon.com/en_GB/json/gen/config_web.json"
US_OPEN_CONFIG_URL = "https://www.usopen.org/en_US/json/gen/config_web.json"
AUSTRALIAN_OPEN_API_TEMPLATE = "https://prod-scores-api.ausopen.com/year/{year}/period/{period}/day/{day}/schedule"
ROLAND_GARROS_MATCHES_URL = "https://www.rolandgarros.com/en-us/matches"


def http_json(url: str, timeout: int = 20) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-SportScanner/3.2", "Accept": "application/json,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read()), "url": url}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": url}


def http_text(url: str, timeout: int = 25) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-SportScanner/3.2", "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "text": r.read().decode("utf-8", errors="replace"), "url": url}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            body = ""
        return {"ok": False, "error": str(exc)[:200], "url": url, "status_code": exc.code, "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": url}


def parse_wib(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
    except Exception:
        return None


def _date_from_epoch(epoch: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(epoch), timezone.utc).astimezone(WIB)
    except Exception:
        return None


def _slam_status(raw: Any, code: Any = None) -> str:
    s = str(raw or code or "scheduled")
    low = s.lower()
    if low in {"completed", "complete", "finished"} or str(code or "").upper() in {"D", "C", "CMP"}:
        return "completed"
    if "live" in low or "progress" in low:
        return "live"
    return s


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


def _scoreline_from_sets(scores: Any) -> str | None:
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


def _config_schedule_candidates(config_url: str, config: dict, target_year: int) -> list[str]:
    scoring = config.get("scoring") or {}
    sd = config.get("scoringData") or {}
    schedule_days = sd.get("scheduleDays") or ""
    candidates: list[str] = []

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


def _fetch_ibm_grand_slam_from_config(
    config_url: str, competition: str, path: str,
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    target_year = datetime.fromisoformat(date_str).year
    probe: dict[str, Any] = {
        "ok_buckets": [], "failed_buckets": [],
        "events_seen": 0, "events_in_window": 0,
        "source_type": "official_json_feed",
        "config_url": config_url,
        "auto_discovery": "config_web.json scoringData.scheduleDays + eventDays.feedUrl"
    }
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
    out: list[dict] = []

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
                team_a = _team_name_from_slam_team(match.get("team1"))
                team_b = _team_name_from_slam_team(match.get("team2"))
                if team_a == "TBD" or team_b == "TBD":
                    continue
                dt_wib = _date_from_epoch(court.get("startEpoch"))
                if not dt_wib:
                    continue
                status = _slam_status(match.get("status"), match.get("statusCode"))
                out.append({
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
                })
                kickoff = parse_wib(out[-1]["kickoff_wib"])
                if kickoff and window_start <= kickoff < window_end:
                    probe["events_in_window"] += 1
    return out, probe


def fetch_wimbledon_official(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    events, probe = _fetch_ibm_grand_slam_from_config(
        WIMBLEDON_CONFIG_URL, "Wimbledon", "tennis/grand_slam/wimbledon",
        date_str, window_start, window_end
    )
    return events, probe


def fetch_us_open_official(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    events, probe = _fetch_ibm_grand_slam_from_config(
        US_OPEN_CONFIG_URL, "US Open", "tennis/grand_slam/us_open",
        date_str, window_start, window_end
    )
    return events, probe


def fetch_australian_open_official(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    year = datetime.fromisoformat(date_str).year
    path = "tennis/grand_slam/australian_open"
    periods = ["MD", "QD", "PT", "CH", "JR", "WC", "D"]
    probe: dict[str, Any] = {
        "ok_buckets": [], "failed_buckets": [],
        "events_seen": 0, "events_in_window": 0,
        "source_type": "official_api",
        "api_template": AUSTRALIAN_OPEN_API_TEMPLATE,
        "period_codes_probed": periods,
        "valid_period_codes": [],
    }
    out: list[dict] = []
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
                        team_a_ref = teams[0]
                        team_b_ref = teams[1]
                        # look up by uuid
                        team_a = _ao_team_name(team_a_ref, teams_by_id, players_by_id)
                        team_b = _ao_team_name(team_b_ref, teams_by_id, players_by_id)
                        if team_a == "TBD" or team_b == "TBD":
                            continue
                        dt_wib = _date_from_epoch(session_ts)
                        if not dt_wib:
                            continue
                        status = _slam_status(act.get("match_state"), (act.get("match_status") or {}).get("abbr"))
                        ev = {
                            "sport": "tennis",
                            "competition": "Australian Open",
                            "event": f"{team_a} vs {team_b}",
                            "team_a": team_a,
                            "team_b": team_b,
                            "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
                            "kickoff_utc": dt_wib.astimezone(timezone.utc).isoformat(),
                            "venue": court_name,
                            "status": status,
                            "fixture_source_path": path,
                            "fixture_source_competition": "Australian Open",
                            "fixture_source_name": "Australian Open Official API",
                            "grand_slam_match_id": act.get("match_id") or act.get("uuid"),
                            "grand_slam_event_name": (events_by_id.get(str(act.get("event_uuid"))) or {}).get("name"),
                            "grand_slam_round": (rounds_by_id.get(str(act.get("round_id"))) or {}).get("name"),
                            "source_feed_url": url,
                            "source_event_shape": "australian_open_schedule_activity",
                        }
                        kickoff = parse_wib(ev["kickoff_wib"])
                        if kickoff and window_start <= kickoff < window_end:
                            out.append(ev)
                            probe["events_in_window"] += 1
    return out, probe


def _ao_team_name(team_ref: dict, teams_by_id: dict, players_by_id: dict) -> str:
    team = teams_by_id.get(str(team_ref.get("team_id"))) or {}
    names = []
    for pid in team.get("players") or []:
        p = players_by_id.get(str(pid)) or {}
        names.append(p.get("full_name") or p.get("short_name") or "TBD")
    return " / ".join([n for n in names if n and n != "TBD"]) or "TBD"


def fetch_roland_garros_official(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    path = "tennis/grand_slam/roland_garros"
    probe: dict[str, Any] = {
        "ok_buckets": [], "failed_buckets": [],
        "events_seen": 0, "events_in_window": 0,
        "source_type": "official_ssr",
        "url": ROLAND_GARROS_MATCHES_URL,
        "parser": "window.__NUXT__ SSR regex"
    }
    res = http_text(ROLAND_GARROS_MATCHES_URL, timeout=25)
    if not res.get("ok"):
        probe["failed_buckets"].append({"step": "matches_page", "error": res.get("error")})
        return [], probe
    raw = res.get("text") or ""
    out: list[dict] = []
    probe["ok_buckets"].append("matches_page")
    margs = re.search(r"window\.__NUXT__=\(function\(([^)]*)\).*?\}\((.*)\)\);</script>", raw, re.S)
    varmap: dict = {}
    if margs:
        names = [x.strip() for x in margs.group(1).split(",")]
        vals = re.findall(r'"((?:\\.|[^"\\])*)"|\b(null|false|true|\d+)\b', margs.group(2))
        flat = [(a or b) for a, b in vals]
        for n, v in zip(names, flat):
            varmap[n] = v.encode().decode("unicode_escape") if isinstance(v, str) else str(v)
    default_date = varmap.get("p") or ""

    for block in re.findall(
        r'\{id:"([A-Z]{1,3}\d{3})"(.*?)(?=\},\{id:"[A-Z]{1,3}\d{3}"|\]\}\],fetch)',
        raw, flags=re.S
    ):
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
        ev = {
            "sport": "tennis",
            "competition": "Roland Garros",
            "event": f"{team_a} vs {team_b}",
            "team_a": team_a,
            "team_b": team_b,
            "kickoff_wib": dt_wib.strftime("%Y-%m-%d %H:%M"),
            "kickoff_utc": dt_wib.astimezone(timezone.utc).isoformat(),
            "venue": (court_m.group(1) or varmap.get(court_m.group(2), "")) if court_m else "",
            "status": _slam_status(status_m.group(1) if status_m else "scheduled"),
            "fixture_source_path": path,
            "fixture_source_competition": "Roland Garros",
            "fixture_source_name": "Roland Garros Official SSR",
            "grand_slam_match_id": match_id,
            "grand_slam_event_name": type_m.group(1) if type_m else None,
            "source_feed_url": ROLAND_GARROS_MATCHES_URL,
            "source_event_shape": "roland_garros_nuxt_match",
        }
        kickoff = parse_wib(ev["kickoff_wib"])
        if kickoff and window_start <= kickoff < window_end:
            out.append(ev)
            probe["events_in_window"] += 1
    return out, probe
