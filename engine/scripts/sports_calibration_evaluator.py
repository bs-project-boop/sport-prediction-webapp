#!/usr/bin/env python3
"""Sports v3.2 confidence calibration evaluator.

Runs at EOD after result capture. It evaluates whether confidence buckets are
empirically calibrated and writes suggested (not applied) weight adjustments only
when enough data exists.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

WIB = timezone(timedelta(hours=7))
ROOT = Path("/opt/sport-prediction/current/engine/data/v3")
STATE_DIR = ROOT / "state"
OUTBOX = ROOT / "discord-outbox"
META_DIR = Path("/opt/sport-prediction/current/engine/data/meta-learning")
HISTORY_PATH = META_DIR / "calibration-history.json"
WEIGHT_ADJUSTMENTS_PATH = META_DIR / "weight-adjustments.json"
ENGINE_PATH = Path("/var/lib/sport-prediction/.hermes-shared/scripts/sports_v3_engine.py")
DISCORD_TARGET = "discord:1515327116189630526"
MIN_SAMPLE = 20
ERROR_THRESHOLD_PCT = 15.0

spec = importlib.util.spec_from_file_location("sports_v3_engine", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(engine)  # type: ignore


def now_wib() -> datetime:
    return datetime.now(WIB)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def bucket(conf: float) -> str:
    if conf >= 75:
        return "HIGH"
    if conf >= 55:
        return "MEDIUM"
    if conf >= 40:
        return "LOW"
    return "COIN_FLIP"


def iter_completed_events() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in sorted(STATE_DIR.glob("*.json")):
        state = read_json(path, {}) or {}
        for ev in (state.get("events") or {}).values():
            if ev.get("status") != "completed":
                continue
            if ev.get("accuracy_excluded") or str(ev.get("validation") or "") == "NO_PREDICTION":
                continue
            pred = ev.get("prediction") or {}
            if engine.is_no_pick_prediction(pred):
                continue
            conf = pred.get("confidence_percent")
            try:
                conf_f = float(conf)
            except Exception:
                continue
            validation = str(ev.get("validation") or "").upper()
            if not any(x in validation for x in ["BENAR", "SEBAGIAN", "SALAH"]):
                continue
            rows.append({
                "date": path.stem,
                "sport": (ev.get("sport") or "unknown").lower(),
                "confidence": max(0.0, min(100.0, conf_f)),
                "bucket": bucket(conf_f),
                "correct": validation == "BENAR",
                "partial": "SEBAGIAN" in validation,
                "validation": validation,
                "event_id": ev.get("event_id"),
            })
    return rows


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_sport: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sport[r["sport"]].append(r)
    sports = sorted(set(list(engine.SPORTS) + list(by_sport.keys())))
    out: Dict[str, Any] = {}
    for sport in sports:
        items = by_sport.get(sport, [])
        n = len(items)
        bucket_stats: Dict[str, Any] = {}
        for b in ["HIGH", "MEDIUM", "LOW", "COIN_FLIP"]:
            b_items = [x for x in items if x["bucket"] == b]
            bn = len(b_items)
            bucket_stats[b] = {
                "matches": bn,
                "mean_confidence_pct": round(sum(x["confidence"] for x in b_items) / bn, 2) if bn else None,
                "accuracy_pct": round(100.0 * sum(1 for x in b_items if x["correct"]) / bn, 2) if bn else None,
            }
        if n < MIN_SAMPLE:
            out[sport] = {
                "sample_size": n,
                "status": "INSUFFICIENT_DATA",
                "message": f"INSUFFICIENT_DATA: {n}/{MIN_SAMPLE} matches",
                "bucket_distribution": bucket_stats,
            }
            continue
        mean_conf = sum(x["confidence"] for x in items) / n
        acc = 100.0 * sum(1 for x in items if x["correct"]) / n
        error = abs(mean_conf - acc)
        direction = "over_confident" if mean_conf > acc else "under_confident"
        needs = error > ERROR_THRESHOLD_PCT
        out[sport] = {
            "sample_size": n,
            "status": "NEEDS_RECALIBRATION" if needs else "OK",
            "mean_confidence_pct": round(mean_conf, 2),
            "actual_accuracy_pct": round(acc, 2),
            "calibration_error_pct": round(error, 2),
            "direction": direction,
            "needs_recalibration": needs,
            "bucket_distribution": bucket_stats,
        }
        if needs:
            delta = -0.03 if direction == "over_confident" else 0.03
            out[sport]["suggested_weight_adjustment"] = {
                "type": "global_confidence_bias_review",
                "direction": direction,
                "detail": "Suggested approval-gated calibration review. Do not auto-apply; inspect factor-level errors before approving.",
                "factor": "contextual",
                "delta_weight": delta,
            }
    return out


def append_history(date: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    hist = read_json(HISTORY_PATH, {"runs": []}) or {"runs": []}
    hist.setdefault("runs", []).append({
        "run_at_wib": now_wib().isoformat(timespec="seconds"),
        "date": date,
        "min_sample": MIN_SAMPLE,
        "error_threshold_pct": ERROR_THRESHOLD_PCT,
        "sports": summary,
    })
    # keep file bounded
    hist["runs"] = hist["runs"][-365:]
    write_json(HISTORY_PATH, hist)
    return hist


def upsert_suggestions(date: str, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = read_json(WEIGHT_ADJUSTMENTS_PATH, {"adjustments": []}) or {"adjustments": []}
    data.setdefault("adjustments", [])
    suggestions: List[Dict[str, Any]] = []
    existing_keys = {(a.get("sport"), a.get("status"), a.get("date"), a.get("direction")) for a in data["adjustments"]}
    for sport, rec in summary.items():
        if not rec.get("needs_recalibration"):
            continue
        sug = rec.get("suggested_weight_adjustment") or {}
        item = {
            "date": date,
            "created_at_wib": now_wib().isoformat(timespec="seconds"),
            "sport": sport,
            "status": "suggested",
            "direction": rec.get("direction"),
            "sample_size": rec.get("sample_size"),
            "mean_confidence_pct": rec.get("mean_confidence_pct"),
            "actual_accuracy_pct": rec.get("actual_accuracy_pct"),
            "calibration_error_pct": rec.get("calibration_error_pct"),
            "factor": sug.get("factor", "contextual"),
            "delta_weight": sug.get("delta_weight", 0),
            "detail": sug.get("detail"),
            "approval_command": f"approve sports calibration {sport} {date}",
        }
        key = (item["sport"], item["status"], item["date"], item["direction"])
        if key not in existing_keys:
            data["adjustments"].append(item)
        suggestions.append(item)
    write_json(WEIGHT_ADJUSTMENTS_PATH, data)
    return suggestions


def send_discord(text: str, tag: str) -> Dict[str, Any]:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    path = OUTBOX / f"{tag}.txt"
    path.write_text(text)
    proc = subprocess.run(
        ["hermes", "send", "--quiet", "--to", DISCORD_TARGET, "--file", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        env={"HOME": "/var/lib/sport-prediction", **dict(os.environ)},
    )
    return {"sent": proc.returncode == 0, "exit_code": proc.returncode, "output": proc.stdout[-500:], "file": str(path)}


def alert_suggestions(date: str, suggestions: List[Dict[str, Any]], no_send: bool = False) -> List[Dict[str, Any]]:
    results = []
    for s in suggestions:
        text = (
            f"🎯 CALIBRATION SUGGESTED: {s['sport']} — confidence {s['mean_confidence_pct']}% "
            f"vs actual accuracy {s['actual_accuracy_pct']}% over {s['sample_size']} matches.\n"
            f"Suggested adjustment: {s['direction']}; factor={s['factor']} delta_weight={s['delta_weight']}.\n"
            f"Approve dengan: {s['approval_command']}"
        )
        tag = f"{date}-calibration-suggested-{s['sport']}"
        if no_send:
            results.append({"sport": s["sport"], "discord": {"sent": False, "reason": "no_send"}, "email": {"sent": False, "reason": "no_send"}})
            continue
        discord = send_discord(text, tag)
        html_path = ROOT / "email-outbox" / f"{tag}.html"
        html_path.write_text(engine.html_wrap("[CALIBRATION SUGGESTED]", text))
        email = engine.send_email(f"[SPORT CALIBRATION] Suggested adjustment — {s['sport']} — {date}", html_path, text, tag)
        results.append({"sport": s["sport"], "discord": discord, "email": email})
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=now_wib().date().isoformat())
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()
    rows = iter_completed_events()
    summary = summarize(rows)
    append_history(args.date, summary)
    suggestions = upsert_suggestions(args.date, summary)
    alert_results = alert_suggestions(args.date, suggestions, no_send=args.no_send) if suggestions else []
    result = {
        "ok": True,
        "date": args.date,
        "history_file": str(HISTORY_PATH),
        "weight_adjustments_file": str(WEIGHT_ADJUSTMENTS_PATH),
        "sports": summary,
        "suggestions": suggestions,
        "alerts": alert_results,
    }
    if suggestions:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # For no_agent cron: stay silent when no approval-worthy signal exists.
        print("[SILENT]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
