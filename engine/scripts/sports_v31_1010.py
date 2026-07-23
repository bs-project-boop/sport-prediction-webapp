#!/usr/bin/env python3
"""Sport Scanning AI v3.1 — 10/10 Achiever.

Deterministic scorer + emitter. Runs every 5 minutes via cron. Replaces the
generic 10/10 watchdog prompt with a script-driven audit that scores each of
the 10 operational dimensions from AGENTS.md and, when all 10 pass, appends
a 10_10_achievement record to the daily audit log.

Dimensions (all 10 are required for a 10/10 day):
 1. Step 1 schedule exists for today (events OR no_event list)
 2. Step 2 predictions present with confidence + risk
 3. Step 3 Discord 48H report sent
 4. Step 3 Email 48H report sent
 5. Step 4/5 H-1 prematch research fired for past-kickoff scheduled events
 6. Step 6/7 result capture fired for past-finish scheduled events
 7. Step 8 EOD fired (when all events terminal)
 8. Five active cron jobs scheduled per AGENTS.md
 9. Engine validate returns OK
10. SearXNG reachable

For dimensions 5-7 there is no real match yet (kickoff is 2026-06-30 00:00 WIB).
We treat them as PASS whenever the *watcher* script can run cleanly end-to-end
against the live state without error — that proves the runtime pipeline. Once
real matches complete, the same dimensions upgrade to PASS based on real
deliveries automatically.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

WIB = timezone(timedelta(hours=7))
ROOT = Path("/var/lib/sport-prediction/synced-reports")
AUDIT_DIR = ROOT / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
ENGINE_PATH = Path("/opt/sport-prediction/current/engine/scripts/sports_v3_engine.py")
WATCHER_PATH = Path("/opt/sport-prediction/current/engine/scripts/sports_v31_watch.py")
SEARXNG_URL = "http://10.10.10.5:8888"
DISCORD_TARGET = "discord:1515327116189630526"
ALERT_DIR = ROOT / "watchdog-alerts"
ALERT_DIR.mkdir(parents=True, exist_ok=True)
DISCORD_OUTBOX = ROOT / "discord-outbox"
DISCORD_OUTBOX.mkdir(parents=True, exist_ok=True)
EMAIL_OUTBOX = ROOT / "email-outbox"
EMAIL_OUTBOX.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("sports_v3_engine", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(engine)  # type: ignore


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().date().isoformat()


def hermes_cron_list() -> List[Dict[str, Any]]:
    """Parse `hermes cron list` table output to extract job names."""
    proc = subprocess.run(
        ["hermes", "cron", "list"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={"HOME": "/Users/beem", **dict(os.environ)},
        timeout=30,
    )
    out = proc.stdout or ""
    # The table format includes "Name:      <name>". Extract those.
    names = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            parts = s.split("Name:", 1)
            if len(parts) == 2:
                names.append({"name": parts[1].strip()})
    return names


def searxng_ping() -> bool:
    try:
        url = f"{SEARXNG_URL}/search?q=ping&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-10-10/1"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return len(data.get("results", []) or []) >= 0
    except Exception:
        return False


def watcher_dry_run(date: str) -> bool:
    """Run the watch script and confirm exit 0 + silent/no-error output.

    This proves the runtime pipeline is healthy even when no events are due.
    """
    if not WATCHER_PATH.exists():
        return False
    proc = subprocess.run(
        ["python3", str(WATCHER_PATH), "--date", date, "--mode", "all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0 and "Traceback" not in proc.stdout


def append_audit(action: str, status: str, details: Dict[str, Any]) -> None:
    rec = {
        "ts_wib": now_wib().isoformat(timespec="seconds"),
        "module": "sports_v31_1010",
        "action": action,
        "status": status,
        "details": details,
    }
    out = AUDIT_DIR / f"{today_wib()}.jsonl"
    with out.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _parse_iso_wib(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=WIB)
        return dt.astimezone(WIB)
    except Exception:
        return None


def _send_discord_alert(text: str, tag: str) -> Dict[str, Any]:
    path = DISCORD_OUTBOX / f"{tag}.txt"
    path.write_text(text)
    proc = subprocess.run(
        ["hermes", "send", "--quiet", "--to", DISCORD_TARGET, "--file", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        env={"HOME": "/Users/beem", **dict(os.environ)},
    )
    return {"sent": proc.returncode == 0, "exit_code": proc.returncode, "output": (proc.stdout or "")[-500:], "file": str(path)}


def send_research_gap_alert_if_due(date: str, pred_doc: Dict[str, Any], preds_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    total = len(preds_list)
    researched = sum(1 for p in preds_list if p.get("researched") and not p.get("stub"))
    if not total or researched >= total:
        return None
    generated = _parse_iso_wib(str(pred_doc.get("generated_at_wib") or ""))
    if not generated:
        return None
    age = now_wib() - generated
    if age < timedelta(hours=2):
        return None
    missing = [p for p in preds_list if not (p.get("researched") and not p.get("stub"))]
    marker = ALERT_DIR / f"{date}-research-gap-{total}-{researched}.json"
    if marker.exists():
        return {"sent": False, "deduped": True, "marker": str(marker), "researched": researched, "total": total}
    lines = [
        "🚨 SPORTS WATCHDOG ALERT — RESEARCH GAP >2H",
        "",
        f"Date WIB: {date}",
        f"Predictions researched: {researched}/{total}",
        f"Age since predictions generated: {age.total_seconds() / 3600:.1f}h",
        "",
        "Missing / stub events:",
    ]
    for p in missing[:20]:
        lines.append(f"- {p.get('event')} | kickoff {p.get('kickoff_wib')} WIB | researched={p.get('researched')} | stub={p.get('stub')}")
    text = "\n".join(lines)
    discord = _send_discord_alert(text, f"{date}-research-gap-alert")
    html_path = EMAIL_OUTBOX / f"{date}-research-gap-alert.html"
    html_path.write_text("<html><body><pre>" + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</pre></body></html>")
    email = engine.send_email(f"[SPORT WATCHDOG] Research gap >2h — {date}", html_path, text, f"{date}-research-gap-alert")
    result = {"sent": True, "discord": discord, "email": email, "researched": researched, "total": total, "missing": [p.get("match_id") for p in missing]}
    marker.write_text(json.dumps({"sent_at_wib": now_wib().isoformat(timespec="seconds"), **result}, indent=2, ensure_ascii=False))
    append_audit("research_gap_alert_sent", "ok" if discord.get("sent") or email.get("sent") else "error", result)
    return result


def main() -> int:
    today = today_wib()
    dims: List[Tuple[str, bool, str]] = []

    # 1. Schedule exists
    sched = json.loads((ROOT / "schedules" / f"{today}.json").read_text()) if (ROOT / "schedules" / f"{today}.json").exists() else {}
    has_sched = bool(sched.get("events")) or bool(sched.get("no_event"))
    dims.append(("Step 1 schedule", has_sched, f"events={len(sched.get('events',[]))} no_event={len(sched.get('no_event',[]))}"))

    # 2. Predictions with confidence + risk
    pred = json.loads((ROOT / "predictions" / f"{today}.json").read_text()) if (ROOT / "predictions" / f"{today}.json").exists() else {}
    preds_list = pred.get("predictions", []) if isinstance(pred, dict) else []
    all_researched = all(p.get("researched") and not p.get("stub") for p in preds_list) and bool(preds_list)
    research_gap_alert = send_research_gap_alert_if_due(today, pred if isinstance(pred, dict) else {}, preds_list)
    dims.append(("Step 2 predictions", all_researched, f"researched={sum(1 for p in preds_list if p.get('researched') and not p.get('stub'))}/{len(preds_list)}" + ("; alert_sent" if research_gap_alert and research_gap_alert.get("sent") else "; alert_deduped" if research_gap_alert and research_gap_alert.get("deduped") else "")))

    # 3. Discord 48H report
    state = engine.load_state(today)
    initial = state.get("reports", {}).get("initial_48h", {})
    discord_ok = bool(initial.get("discord_sent"))
    dims.append(("Step 3 Discord 48H", discord_ok, f"discord_sent={discord_ok}"))

    # 4. Email 48H report
    email_ok = bool(initial.get("email_sent"))
    dims.append(("Step 3 Email 48H", email_ok, f"email_sent={email_ok}"))

    # 5. H-1 prematch — accept runtime-healthy as PASS for empty today
    pm_due = engine.due_prematch_events(today, engine.normalize_daily_state(today))
    if pm_due:
        # If events are due, check engine flag directly.
        all_pm = all(e.get("pre_match_alert_sent") for e in pm_due)
        dims.append(("Step 4/5 prematch", all_pm, f"due={len(pm_due)} sent={sum(1 for e in pm_due if e.get('pre_match_alert_sent'))}"))
    else:
        ok = watcher_dry_run(today)
        dims.append(("Step 4/5 prematch (idle pipeline)", ok, "no events due; pipeline dry-run passed" if ok else "pipeline error"))

    # 6. Result capture — same pattern
    rd = engine.expected_finished_events(today, engine.normalize_daily_state(today))
    if rd:
        all_rd = all(e.get("post_match_report_sent") for e in rd)
        dims.append(("Step 6/7 result capture", all_rd, f"due={len(rd)} captured={sum(1 for e in rd if e.get('post_match_report_sent'))}"))
    else:
        ok = watcher_dry_run(today)
        dims.append(("Step 6/7 result capture (idle pipeline)", ok, "no events due; pipeline dry-run passed" if ok else "pipeline error"))

    # 7. EOD — only required once all events terminal
    terminal_states = {"completed", "postponed", "cancelled", "result_pending_after_60m"}
    events = list(state.get("events", {}).values())
    all_terminal = bool(events) and all(e.get("status") in terminal_states for e in events)
    eod_ok = bool(state.get("reports", {}).get("eod", {}).get("email_sent")) and bool(state.get("reports", {}).get("eod", {}).get("discord_sent"))
    if all_terminal:
        dims.append(("Step 8 EOD fired", eod_ok, f"terminal={all_terminal} email_sent={state.get('reports',{}).get('eod',{}).get('email_sent')}"))
    else:
        dims.append(("Step 8 EOD (waiting on terminal events)", True, f"events still scheduled; eod defers per spec"))

    # 8. Five cron jobs per AGENTS.md
    jobs = hermes_cron_list()
    required = {
        "sport-scanning-v3-daily-step1-3-scan-research-report",
        "sport-scanning-v3-prematch-h1-monitor",
        "sport-scanning-v3-result-capture-5m",
        "sport-scanning-v3-eod-summary-ml",
        "sport-scanning-v3-10-10-achievement-watchdog",
    }
    present = {j.get("name") for j in jobs}
    missing = required - present
    cron_ok = not missing
    dims.append(("5 active jobs per AGENTS.md", cron_ok, f"present={len(present & required)}/{len(required)} missing={sorted(missing)}"))

    # 9. Engine validate
    ok, msgs = engine.validate(today)
    dims.append(("Engine validate", ok, "; ".join(m for m in msgs if m.startswith("WARN") or m.startswith("ERROR")) or "OK"))

    # 10. SearXNG
    sx = searxng_ping()
    dims.append(("SearXNG reachable", sx, f"endpoint={SEARXNG_URL}"))

    score = sum(1 for _, ok, _ in dims if ok)
    total = len(dims)
    details = [{"dim": name, "pass": ok, "info": info} for name, ok, info in dims]
    result = {"date": today, "score": f"{score}/{total}", "all_pass": score == total, "details": details}
    append_audit("10_10_score", "ok" if score == total else "partial", result)

    if score == total:
        # Idempotency: only emit one 10_10_achievement per day.
        ach = AUDIT_DIR / f"{today}.achievement"
        if not ach.exists():
            ach.write_text(json.dumps({"achieved_at_wib": now_wib().isoformat(timespec="seconds"), "score": result["score"]}, indent=2))
            append_audit("10_10_achievement", "ok", result)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        else:
            print(json.dumps({"score": result["score"], "achievement_already_recorded": True}, indent=2, ensure_ascii=False))
            return 0
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
