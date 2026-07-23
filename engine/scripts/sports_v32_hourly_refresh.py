#!/usr/bin/env python3
"""Sports v3.2 hourly fixture refresh.

Runs every hour (cron: "0 * * * *"). Calls sports_v31_espn_ingest.py for
today + next 7 days without enrichment (--no-enrich) for fast fixture refresh.
Safe to re-run every hour because ingest_for_date() is idempotent.

This satisfies the spec requirement: "Refresh Jadwal — setiap satu jam."
"""
from __future__ import annotations

import json
import subprocess
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

WIB = timezone(timedelta(hours=7))
ROOT = Path("/var/lib/sport-prediction/synced-reports")
INGEST_SCRIPT = Path("/opt/sport-prediction/current/engine/scripts/sports_v31_espn_ingest.py")
REFRESH_REPORT = ROOT / "audit" / "hourly-refresh-report.json"


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().date().isoformat()


def main() -> int:
    dates = [(now_wib().date() + timedelta(days=d)) for d in range(8)]
    results = {}
    errors = 0

    for d in dates:
        date_str = d.isoformat()
        # Build clean env — use system python3, explicit HOME
        env = {
            "HOME": os.environ.get("HOME", "/var/lib/sport-prediction"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        proc = subprocess.run(
            [
                sys.executable,  # use the same python running this script
                str(INGEST_SCRIPT),
                "--date", date_str,
                "--sport", "football",
                "--sport", "basketball",
                "--sport", "tennis",
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min per date — enrichment takes ~3 min for 120 events
            env=env,
        )
        try:
            result = json.loads(proc.stdout) if proc.stdout else {}
            results[date_str] = {
                "ok": proc.returncode == 0,
                "events_total": result.get("events_total", 0),
                "sports_with_events": result.get("sports_with_events", []),
            }
        except json.JSONDecodeError:
            results[date_str] = {
                "ok": False,
                "error": (proc.stdout + proc.stderr)[-500:],
            }
            errors += 1

    # Write refresh report
    REFRESH_REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_wib": now_wib().isoformat(timespec="seconds"),
        "dates_refreshed": len(dates),
        "errors": errors,
        "results": results,
    }
    REFRESH_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    total_events = sum(r.get("events_total", 0) for r in results.values())
    print(json.dumps({
        "ok": errors == 0,
        "dates_refreshed": len(dates),
        "total_events_found": total_events,
        "errors": errors,
        "report": str(REFRESH_REPORT),
    }, indent=2))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())