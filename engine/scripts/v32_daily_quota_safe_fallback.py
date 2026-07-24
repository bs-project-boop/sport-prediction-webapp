#!/usr/bin/env python3
"""Quota-safe daily fallback for Sports v3.2.

Runs before the agentic daily scan. It guarantees fixture/stub artifacts and a
clear degraded sports-daily.md exist even if the later LLM research phase fails
with 429/503/timeout. It never sends the 48H email because research is not done.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import fcntl, sys, os
LOCK_FILE = "/var/run/sportapp/sport-daily.lock"
lock_fd = os.open(LOCK_FILE, os.O_CREAT|os.O_RDWR)
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("[SKIPPED] daily scan already running (lock held)")
    sys.exit(0)


WIB = timezone(timedelta(hours=7))
ROOT = Path("/opt/sport-prediction/current/engine/data")
SCHEDULE_DIR = ROOT / "schedules"
PRED_DIR = ROOT / "predictions"
STATE_DIR = ROOT / "state"
AUDIT_DIR = ROOT / "audit"
DISCORD_OUTBOX = ROOT / "discord-outbox"
DAILY_MD = Path("/opt/sport-prediction/current/engine/data/sports-daily.md")
INGEST = Path("/opt/sport-prediction/current/engine/scripts/sports_v31_espn_ingest.py")
ENGINE = Path("/opt/sport-prediction/current/engine/scripts/sports_v3_engine.py")
DISCORD_TARGET = "discord:1515327116189630526"


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().date().isoformat()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def audit(action: str, status: str, details: dict, date: str) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts_wib": now_wib().isoformat(timespec="seconds"),
        "module": "v32_daily_quota_safe_fallback",
        "action": action,
        "status": status,
        "details": details,
    }
    with (AUDIT_DIR / f"{date}.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run(cmd: list[str], timeout: int = 300) -> dict:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        env={**os.environ},  # NOTE: /Users/beem does not exist on LXC
    )
    return {"exit_code": proc.returncode, "output": (proc.stdout or "")[-4000:]}


def ensure_stub_doc(date: str) -> dict:
    pred_path = PRED_DIR / f"{date}.json"
    sched_path = SCHEDULE_DIR / f"{date}.json"
    pred_doc = read_json(pred_path, None)
    if isinstance(pred_doc, dict) and isinstance(pred_doc.get("predictions"), list):
        return pred_doc

    schedule = read_json(sched_path, {}) or {}
    events = schedule.get("events") or []
    predictions = []
    for ev in events:
        event_name = ev.get("event") or ev.get("name") or "unknown_event"
        predictions.append({
            "match_id": ev.get("event_id") or ev.get("id") or event_name.lower().replace(" ", "_"),
            "date_wib": date,
            "sport": ev.get("sport") or "unknown",
            "competition": ev.get("competition") or "unknown",
            "event": event_name,
            "kickoff_wib": ev.get("kickoff_wib") or ev.get("start_time_wib") or "",
            "researched": False,
            "stub": True,
            "predicted_outcome": None,
            "predicted_score_or_result": None,
            "confidence_percent": None,
            "confidence_label": None,
            "risk_score_1_to_10": None,
            "reasoning": [],
            "data_source": {
                "fixture_source": ev.get("source") or "fixture_ingest",
                "research_primary": None,
                "sources_used": [ev.get("source") or "fixture_ingest"],
                "fallback_sources_used": [],
                "DATA_SOURCE_DEGRADED": True,
                "confidence_penalty_applied": 0,
            },
            "DATA_SOURCE_DEGRADED": True,
            "phases": {"initial": {}, "prematch": {}, "result": {}, "validation": {}},
        })
    pred_doc = {
        "meta": {
            "date_wib": date,
            "created_at_wib": now_wib().isoformat(timespec="seconds"),
            "status": "DEGRADED_LLM_UNAVAILABLE_STUBS_ONLY",
            "research_complete": False,
        },
        "predictions": predictions,
    }
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    pred_path.write_text(json.dumps(pred_doc, indent=2, ensure_ascii=False))
    return pred_doc


def write_degraded_daily(date: str, reason: str, ingest_res: dict, init_res: dict) -> str:
    schedule = read_json(SCHEDULE_DIR / f"{date}.json", {}) or {}
    pred_doc = read_json(PRED_DIR / f"{date}.json", {}) or {}
    state = read_json(STATE_DIR / f"{date}.json", {}) or {}
    events = schedule.get("events") or []
    preds = pred_doc.get("predictions") if isinstance(pred_doc, dict) else []
    preds = preds if isinstance(preds, list) else []
    researched = [p for p in preds if p.get("researched") is True and not p.get("stub")]
    stubs = [p for p in preds if p.get("stub") is True or not p.get("researched")]
    now = now_wib()
    lines = [
        "# Sports Daily Report",
        f"**Date:** {date} | **Status:** 🟡 [DEGRADED - LLM UNAVAILABLE] | **Generated:** {now:%H:%M} WIB",
        "",
        "## Summary",
        f"Fixture ingest ran, but LLM research was unavailable or not completed. Created/kept {len(preds)} prediction stub(s); researched predictions: {len(researched)}.",
        "",
        "## Details",
        f"- **Mode:** DEGRADED — research skipped / incomplete",
        f"- **Reason:** {reason}",
        f"- **Schedule events:** {len(events)}",
        f"- **Prediction stubs:** {len(stubs)}",
        f"- **State events:** {len((state.get('events') or {})) if isinstance(state, dict) else 0}",
        f"- **48H email:** not sent because research is incomplete",
        "",
        "## Upcoming / Stub Events",
    ]
    if preds:
        for p in preds[:10]:
            lines.append(f"- {p.get('event') or p.get('match_id')} — {p.get('kickoff_wib') or 'time TBD'} · prediction: STUB / research pending")
        if len(preds) > 10:
            lines.append(f"- ...and {len(preds)-10} more stub/event row(s)")
    else:
        lines.append("- No events found in the current fixture window.")
    lines += [
        "",
        "## Action Required",
        "- [ ] Recovery required: run LLM research when provider quota is available.",
        "",
        "## Source/Freshness",
        f"- **Schedule:** `{SCHEDULE_DIR / (date + '.json')}`",
        f"- **Predictions:** `{PRED_DIR / (date + '.json')}`",
        f"- **State:** `{STATE_DIR / (date + '.json')}`",
        f"- **Ingest exit:** {ingest_res.get('exit_code')}",
        f"- **Init exit:** {init_res.get('exit_code')}",
        "",
        "## Improvement Loop",
        "- Daily artifact is now quota-safe: report/stubs exist even when LLM research fails.",
    ]
    text = "\n".join(lines) + "\n"
    DAILY_MD.parent.mkdir(parents=True, exist_ok=True)
    DAILY_MD.write_text(text)
    return text


def send_discord_alert(date: str, reason: str) -> dict:
    DISCORD_OUTBOX.mkdir(parents=True, exist_ok=True)
    msg = f"⚠️ DAILY SCAN DEGRADED — LLM unavailable, research skipped, stubs created\nDate: {date} WIB\nReason: {reason}\nEmail 48H report: not sent until research completes."
    path = DISCORD_OUTBOX / f"daily-scan-degraded-{date}.txt"
    path.write_text(msg)
    proc = subprocess.run(
        ["hermes", "send", "--quiet", "--to", DISCORD_TARGET, "--file", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        env={**os.environ},  # NOTE: /Users/beem does not exist on LXC
    )
    return {"sent": proc.returncode == 0, "exit_code": proc.returncode, "output": (proc.stdout or "")[-500:], "file": str(path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today_wib())
    ap.add_argument("--reason", default="LLM unavailable or research not completed")
    ap.add_argument("--alert", action="store_true")
    args = ap.parse_args()

    ensure = [SCHEDULE_DIR, PRED_DIR, STATE_DIR, AUDIT_DIR]
    for d in ensure:
        d.mkdir(parents=True, exist_ok=True)

    ingest_res = run(["python3", str(INGEST), "--date", args.date], timeout=600)
    pred_doc = ensure_stub_doc(args.date)
    init_res = run(["python3", str(ENGINE), "init", "--date", args.date], timeout=180)
    report = write_degraded_daily(args.date, args.reason, ingest_res, init_res)
    alert_res = None
    if args.alert:
        alert_res = send_discord_alert(args.date, args.reason)
    audit("daily_quota_safe_fallback", "ok" if ingest_res.get("exit_code") == 0 else "warn", {
        "date": args.date,
        "reason": args.reason,
        "ingest": ingest_res,
        "init": init_res,
        "predictions": len((pred_doc or {}).get("predictions") or []),
        "daily_md": str(DAILY_MD),
        "discord_alert": alert_res,
        "email_48h_sent": False,
    }, args.date)
    print(json.dumps({
        "fallback_ready": True,
        "date": args.date,
        "schedule_exists": (SCHEDULE_DIR / f"{args.date}.json").exists(),
        "predictions_exists": (PRED_DIR / f"{args.date}.json").exists(),
        "state_exists": (STATE_DIR / f"{args.date}.json").exists(),
        "daily_md_exists": DAILY_MD.exists(),
        "predictions": len((pred_doc or {}).get("predictions") or []),
        "ingest_exit": ingest_res.get("exit_code"),
        "init_exit": init_res.get("exit_code"),
        "alert": alert_res,
    }, indent=2, ensure_ascii=False))
    return 0 if ingest_res.get("exit_code") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

