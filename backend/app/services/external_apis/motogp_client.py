# motogp_client.py — MotoGP PulseLive API client for Stage 1 Discovery
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any

WIB = timezone(timedelta(hours=7))
MOTOGP_API_BASE = "https://api.motogp.pulselive.com/motogp/v1"


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


def fetch_motogp_pulselive(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    """Fetch MotoGP events for a date window from PulseLive API."""
    path = "motogp/pulselive"
    probe: dict[str, Any] = {
        "ok_buckets": [],
        "failed_buckets": [],
        "events_seen": 0,
        "events_in_window": 0,
        "source_type": "official_api",
        "api_base": MOTOGP_API_BASE,
    }
    target_year = datetime.fromisoformat(date_str).year

    # Get current season
    seasons_res = http_json(f"{MOTOGP_API_BASE}/results/seasons")
    if not seasons_res.get("ok"):
        probe["failed_buckets"].append({"step": "seasons", "error": seasons_res.get("error")})
        return [], probe
    seasons = seasons_res.get("data") or []
    season = next(
        (x for x in seasons if int(x.get("year") or 0) == target_year),
        next((x for x in seasons if x.get("current")), None),
    )
    if not season or not season.get("id"):
        probe["failed_buckets"].append({"step": "season_select", "error": f"no season for {target_year}"})
        return [], probe
    season_uuid = season["id"]
    probe["season_uuid"] = season_uuid
    probe["season_year"] = season.get("year")

    # Get MotoGP category
    cats_res = http_json(f"{MOTOGP_API_BASE}/results/categories?seasonUuid={urllib.parse.quote(season_uuid)}")
    if not cats_res.get("ok"):
        probe["failed_buckets"].append({"step": "categories", "error": cats_res.get("error")})
        return [], probe
    cats = cats_res.get("data") or []
    category = next(
        (c for c in cats if "motogp" in str(c.get("name", "")).lower()), None
    )
    if not category or not category.get("id"):
        probe["failed_buckets"].append({"step": "category_select", "error": "MotoGP category not found"})
        return [], probe
    category_uuid = category["id"]
    probe["category_uuid"] = category_uuid
    probe["category_name"] = category.get("name")

    # Get events
    events_raw: list[dict] = []
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
    out: list[dict] = []
    for ev in events_raw:
        event_id = ev.get("id")
        if not event_id:
            continue
        sessions: list[dict] = []
        sess_url = (
            f"{MOTOGP_API_BASE}/results/sessions?eventUuid={urllib.parse.quote(event_id)}"
            f"&categoryUuid={urllib.parse.quote(category_uuid)}"
        )
        sess_res = http_json(sess_url)
        if sess_res.get("ok"):
            sessions = sess_res.get("data") or []
        else:
            probe.setdefault("session_fetch_errors", []).append({
                "event_id": event_id, "error": sess_res.get("error")})

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
                "source_event_shape": "motogp_session",
            })
            probe["events_in_window"] += 1

        # Weekend fallback
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
                    "source_event_shape": "motogp_weekend",
                })
                probe["events_in_window"] += 1

    return out, probe
