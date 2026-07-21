# ibl_client.py — IBL Indonesia HTML scraper for Stage 1 Discovery
from __future__ import annotations

import html as html_module
import re
from datetime import datetime, timezone, timedelta
from typing import Any

WIB = timezone(timedelta(hours=7))
IBL_SCHEDULE_URL = "https://iblindonesia.com/games/schedule"

IBL_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def http_text(url: str, timeout: int = 20) -> dict[str, Any]:
    import urllib.request, urllib.error
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


def _html_to_plain_text(raw_html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", raw_html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html_module.unescape(re.sub(r"\s+", " ", text)).strip()


def _parse_ibl_datetime(month: str, day: str, year: str, hm: str) -> datetime | None:
    try:
        return datetime(int(year), IBL_MONTHS[month], int(day), int(hm[:2]), int(hm[3:5]), tzinfo=WIB)
    except Exception:
        return None


def parse_ibl_schedule_html(raw_html: str, path: str = "ibl/official") -> list[dict]:
    text = _html_to_plain_text(raw_html)
    events: list[dict] = []
    chunks = re.split(r"\bDATE/TIME\s*:\s*", text)
    for chunk in chunks[1:]:
        chunk = re.split(r"\s+\*Last update\b|\s+Copyright\b|\s+CONTACT US\b", chunk, maxsplit=1)[0].strip()
        m = re.match(
            r"([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})\s*\|\s*(\d{2}:\d{2})\s+VENUE\s*:\s*(.+?)\s+(.+?)\s+(\d{1,3})\s+FINAL\s+(\d{1,3})\s+(.+)$",
            chunk,
        )
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


def fetch_ibl_official_html(
    date_str: str, window_start: datetime, window_end: datetime
) -> tuple[list[dict], dict]:
    path = "ibl/official"
    probe: dict[str, Any] = {
        "ok_buckets": [],
        "failed_buckets": [],
        "events_seen": 0,
        "events_in_window": 0,
        "source_type": "official_html",
        "url": IBL_SCHEDULE_URL,
        "offseason_policy": "ok_zero_events when official page has no parsed match inside 48h WIB window",
    }
    res = http_text(IBL_SCHEDULE_URL, timeout=20)
    if not res.get("ok"):
        probe["failed_buckets"].append({
            "step": "schedule_html",
            "status_code": res.get("status_code"),
            "error": res.get("error"),
            "body": res.get("body"),
        })
        return [], probe
    probe["ok_buckets"].append("schedule_html")
    events = parse_ibl_schedule_html(res.get("text") or "", path=path)
    probe["events_seen"] = len(events)
    out: list[dict] = []
    for ev in events:
        kickoff = parse_wib(ev.get("kickoff_wib", ""))
        if not kickoff or not (window_start <= kickoff < window_end):
            continue
        out.append(ev)
        probe["events_in_window"] += 1
    probe["season_window_status"] = "active" if probe["events_in_window"] else "offseason_or_no_matches_in_48h_window"
    return out, probe
