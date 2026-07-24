#!/usr/bin/env python3
"""Sports v3.2 cron failure/skip alert watchdog.

Script-only guard for unattended operation. Silent on healthy state.
Alerts Discord + email when a core sports cron job is errored/skipped, delivery
failed, or provider/model pin snapshots are missing/mismatched.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import fcntl, sys, os
LOCK_FILE = /var/run/sportapp/sport-cronalert.lock
try:
    lock_fd = os.open(LOCK_FILE, os.O_CREAT|os.O_RDWR)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print([SKIPPED] cron-alert already running)
    sys.exit(0)


JOBS_PATH = Path("/opt/sport-prediction/current/engine/data/jobs.json")
SHARED_ROOT = Path("/opt/sport-prediction/current/engine/data")
ALERT_DIR = SHARED_ROOT / "watchdog-alerts"
DISCORD_OUTBOX = SHARED_ROOT / "discord-outbox"
EMAIL_OUTBOX = SHARED_ROOT / "email-outbox"
STATE_PATH = ALERT_DIR / "cron-failure-alert-state.json"
DISCORD_TARGET = "discord:1515327116189630526"
WIB = ZoneInfo("Asia/Jakarta")
PIN_PROVIDER = "minimax-oauth"
PIN_MODEL = "minimax-m2.7"
# Per-job expected pins. All core jobs are explicitly pinned to MiniMax-M2.7
# after the daily-job provider migration. Script-only watchers are no_agent=true,
# so the pin is used for scheduler drift safety, not inference spend.
EXPECTED_PINS = {
    "sport-scanning-v3.2-daily-step1-3-scan-research-report": ("minimax-oauth", "minimax-m2.7"),
}
SPORTS_DAILY_MD = Path("/opt/sport-prediction/current/engine/data/sports-daily.md")
SPORTS_DAILY_STALE_HOURS = 25
RESEARCH_GAP_GRACE_START = time(0, 0)
RESEARCH_GAP_GRACE_END = time(0, 30)
CORE_JOB_NAMES = {
    "sport-scanning-v3.2-daily-step1-3-scan-research-report",
    "sport-scanning-v3.2-prematch-h1-monitor",
    "sport-scanning-v3.2-result-capture-5m",
    "sport-scanning-v3.2-eod-summary-ml",
    "sport-scanning-v3.2-10-10-achievement-watchdog",
}


def now_wib() -> datetime:
    return datetime.now(WIB)


def load_jobs() -> list[dict]:
    data = json.loads(JOBS_PATH.read_text())
    return data.get("jobs") or []


def norm_model(value: object) -> str:
    return str(value or "").strip().lower()


def is_research_gap_alert(alert: dict) -> bool:
    alert_type = str(alert.get("type") or "").lower()
    return "research" in alert_type and ("gap" in alert_type or "incomplete" in alert_type)


def in_research_gap_grace_period(now: datetime) -> bool:
    return RESEARCH_GAP_GRACE_START <= now.time() < RESEARCH_GAP_GRACE_END


def apply_research_gap_grace_period(alerts: list[dict], now: datetime) -> list[dict]:
    if not in_research_gap_grace_period(now):
        return alerts
    return [alert for alert in alerts if not is_research_gap_alert(alert)]


# Staleness thresholds per job schedule (hours)
STALE_THRESHOLDS = {
    "sport-scanning-v3.2-daily-step1-3-scan-research-report": 27,  # daily+margin
    "sport-scanning-v3.2-prematch-h1-monitor": 0.5,               # 30min for 5-min job
    "sport-scanning-v3.2-result-capture-5m": 0.5,
    "sport-scanning-v3.2-eod-summary-ml": 1.5,                    # 90min for 30-min job
    "sport-scanning-v3.2-10-10-achievement-watchdog": 1.5,
}

def collect_alerts(jobs: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    by_name = {j.get("name"): j for j in jobs}
    for name in sorted(CORE_JOB_NAMES):
        job = by_name.get(name)
        if not job:
            alerts.append({"severity": "critical", "job": name, "type": "missing_job"})
            continue
        status = job.get("last_status")
        last_error = job.get("last_error")
        delivery_error = job.get("last_delivery_error")
        if job.get("enabled") is not True or job.get("state") != "scheduled":
            alerts.append({
                "severity": "critical",
                "job": name,
                "job_id": job.get("id"),
                "type": "not_scheduled_or_disabled",
                "enabled": job.get("enabled"),
                "state": job.get("state"),
            })
        if status == "error" or last_error:
            err = str(last_error or "")
            typ = "provider_model_drift_skip" if "drifted" in err or "Skipped to prevent unintended spend" in err else "cron_last_run_error"
            alerts.append({
                "severity": "critical",
                "job": name,
                "job_id": job.get("id"),
                "type": typ,
                "last_run_at": job.get("last_run_at"),
                "last_error": err[-1500:],
            })
        if delivery_error:
            alerts.append({
                "severity": "warning",
                "job": name,
                "job_id": job.get("id"),
                "type": "delivery_error",
                "last_run_at": job.get("last_run_at"),
                "last_delivery_error": str(delivery_error)[-1000:],
            })
        provider = job.get("provider")
        model = job.get("model")
        ps = job.get("provider_snapshot")
        ms = job.get("model_snapshot")
        if not provider or not model or not ps or not ms:
            alerts.append({
                "severity": "warning",
                "job": name,
                "job_id": job.get("id"),
                "type": "provider_model_pin_missing",
                "provider": provider,
                "model": model,
                "provider_snapshot": ps,
                "model_snapshot": ms,
            })
        elif str(provider) != str(ps) or norm_model(model) != norm_model(ms):
            alerts.append({
                "severity": "warning",
                "job": name,
                "job_id": job.get("id"),
                "type": "provider_model_snapshot_mismatch",
                "provider": provider,
                "model": model,
                "provider_snapshot": ps,
                "model_snapshot": ms,
            })
        expected_provider, expected_model = EXPECTED_PINS.get(name, (PIN_PROVIDER, PIN_MODEL))
        if str(provider) != expected_provider or norm_model(model) != norm_model(expected_model):
            alerts.append({
                "severity": "warning",
                "job": name,
                "job_id": job.get("id"),
                "type": "provider_model_not_expected_pin",
                "expected_provider": expected_provider,
                "expected_model": expected_model,
                "provider": provider,
                "model": model,
            })

    # Daily report staleness guard: sports-daily.md must be refreshed at least daily.
    now = now_wib()
    if not SPORTS_DAILY_MD.exists():
        alerts.append({
            "severity": "critical",
            "job": "sports-daily.md",
            "type": "sports_daily_report_missing",
            "path": str(SPORTS_DAILY_MD),
        })
    else:
        mtime = datetime.fromtimestamp(SPORTS_DAILY_MD.stat().st_mtime, tz=WIB)
        age_hours = (now - mtime).total_seconds() / 3600
        if age_hours > SPORTS_DAILY_STALE_HOURS:
            alerts.append({
                "severity": "critical",
                "job": "sports-daily.md",
                "type": "sports_daily_report_stale_gt_25h",
                "path": str(SPORTS_DAILY_MD),
                "mtime_wib": mtime.isoformat(timespec="seconds"),
                "age_hours": round(age_hours, 2),
                "threshold_hours": SPORTS_DAILY_STALE_HOURS,
            })

    # Daily job freshness guard: after 00:20 WIB, today's run should have happened.
    daily = by_name.get("sport-scanning-v3.2-daily-step1-3-scan-research-report")
    now = now_wib()
    if daily and now.time() >= time(0, 20):
        last_run = str(daily.get("last_run_at") or "")
        if not last_run.startswith(now.date().isoformat()):
            alerts.append({
                "severity": "critical",
                "job": daily.get("name"),
                "job_id": daily.get("id"),
                "type": "daily_scan_stale_after_0020_wib",
                "today_wib": now.date().isoformat(),
                "last_run_at": daily.get("last_run_at"),
                "next_run_at": daily.get("next_run_at"),
            })

    # Per-job stale-last_run guard: detect when a job hasn't fired in longer than
    # its schedule allows (catches: paused jobs, scheduler dead, silent failures).
    # This is independent of the enabled/state check — a job can be enabled+scheduled
    # but the scheduler may have stalled silently (e.g. Hermes restart, context crash).
    now = now_wib()
    for name, threshold_hours in STALE_THRESHOLDS.items():
        job = by_name.get(name)
        if not job:
            continue  # already caught by "missing_job" above
        last_run_str = job.get("last_run_at") or ""
        if not last_run_str:
            # Never ran — only alert if we're past the threshold since job creation
            created = job.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    created_dt = created_dt.astimezone(WIB)
                    age_hours = (now - created_dt).total_seconds() / 3600
                    if age_hours > threshold_hours:
                        alerts.append({
                            "severity": "critical",
                            "job": name,
                            "job_id": job.get("id"),
                            "type": "never_run_stale",
                            "threshold_hours": threshold_hours,
                            "created_at": created,
                            "age_hours": round(age_hours, 2),
                        })
                except Exception:
                    pass
            continue
        try:
            last_run_dt = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
            last_run_dt = last_run_dt.astimezone(WIB)
            stale_hours = (now - last_run_dt).total_seconds() / 3600
            if stale_hours > threshold_hours:
                alerts.append({
                    "severity": "critical",
                    "job": name,
                    "job_id": job.get("id"),
                    "type": "last_run_stale",
                    "threshold_hours": threshold_hours,
                    "stale_hours": round(stale_hours, 2),
                    "last_run_at": last_run_str,
                    "enabled": job.get("enabled"),
                    "state": job.get("state"),
                })
        except Exception:
            pass

    return alerts


def fingerprint(alerts: list[dict]) -> str:
    payload = json.dumps(alerts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def render_text(alerts: list[dict], fp: str) -> str:
    lines = [
        "🔴 SPORTS CRON FAILURE/SKIP ALERT",
        "",
        f"Generated: {now_wib().strftime('%Y-%m-%d %H:%M WIB')}",
        f"Fingerprint: {fp}",
        f"Alerts: {len(alerts)}",
        "",
    ]
    for a in alerts[:20]:
        lines.append(f"- [{a.get('severity')}] {a.get('job')} — {a.get('type')}")
        if a.get("last_run_at"):
            lines.append(f"  last_run_at: {a.get('last_run_at')}")
        if a.get("last_error"):
            lines.append(f"  last_error: {a.get('last_error')}")
        if a.get("provider") or a.get("provider_snapshot"):
            lines.append(f"  provider/model: {a.get('provider')}/{a.get('model')} snapshot={a.get('provider_snapshot')}/{a.get('model_snapshot')}")
    lines += [
        "",
        "Action: inspect cronjob list and jobs.json before unattended operation continues.",
    ]
    return "\n".join(lines)


def send_discord(text: str, fp: str) -> dict:
    import shutil
    DISCORD_OUTBOX.mkdir(parents=True, exist_ok=True)
    local_path = DISCORD_OUTBOX / f"cron-failure-alert-{fp}.txt"
    local_path.write_text(text)
    if shutil.which("hermes") is None:
        # hermes CLI not available (LXC host) — write to outbox only, skip delivery
        return {"sent": False, "exit_code": -1, "output": "hermes not found — saved to outbox only", "file": str(local_path)}
    proc = subprocess.run(
        ["hermes", "send", "--quiet", "--to", DISCORD_TARGET, "--file", str(local_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        env={**os.environ},  # NOTE: /Users/beem does not exist on LXC
    )
    return {"sent": proc.returncode == 0, "exit_code": proc.returncode, "output": (proc.stdout or "")[-500:], "file": str(local_path)}


def send_email(text: str, fp: str) -> dict:
    import sports_v3_engine as engine  # type: ignore

    EMAIL_OUTBOX.mkdir(parents=True, exist_ok=True)
    subject = f"[SPORT WATCHDOG] Cron failure/skip alert — {now_wib().strftime('%Y-%m-%d')} — {fp}"
    html_path = EMAIL_OUTBOX / f"cron-failure-alert-{fp}.html"
    html_path.write_text("<html><body><pre>" + html.escape(text) + "</pre></body></html>")
    result = engine.send_email(subject, html_path, text, f"cron-failure-alert-{fp}")

    verifier = Path("/opt/sport-prediction/current/engine/scripts/verify_email_in_sent.py")
    if result.get("sent") and verifier.exists():
        proc = subprocess.run(
            ["python3", str(verifier), "--subject", subject[:80], "--since", now_wib().date().isoformat()],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=90,
            env={**os.environ},  # NOTE: /Users/beem does not exist on LXC
        )
        result["imap_verified_in_sent"] = proc.returncode == 0
        result["imap_verify_exit_code"] = proc.returncode
        result["imap_verify_output"] = (proc.stdout or "")[-1000:]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print health result, do not send/dedupe")
    args = ap.parse_args()

    ALERT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = load_jobs()
    alerts = apply_research_gap_grace_period(collect_alerts(jobs), now_wib())
    if args.dry_run:
        print(json.dumps({"ok": not alerts, "alerts": alerts}, indent=2, ensure_ascii=False))
        return 0 if not alerts else 1
    if not alerts:
        return 0

    fp = fingerprint(alerts)
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    if state.get("last_fingerprint") == fp:
        return 0

    text = render_text(alerts, fp)
    discord = send_discord(text, fp)
    email = send_email(text, fp)
    state = {
        "last_fingerprint": fp,
        "last_alert_at_wib": now_wib().isoformat(timespec="seconds"),
        "alerts": alerts,
        "discord": discord,
        "email": email,
    }
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(json.dumps({"alert_sent": True, "fingerprint": fp, "discord_sent": discord.get("sent"), "email_sent": email.get("sent"), "email_imap_verified": email.get("imap_verified_in_sent")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
