#!/usr/bin/env python3
"""Sport Scanning AI v3.2 deterministic state engine.

This script is the non-LLM backbone for the v3 flow:
- state/queue creation from daily schedule + predictions
- sent flags and dedupe
- retry counters for result capture
- email delivery via Himalaya
- audit log for every side effect
- production readiness validation

LLM cron jobs still perform web search/deep research. This engine enforces state,
report files, email sending, and idempotency so the flow is not prompt-only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WIB = timezone(timedelta(hours=7))
ROOT = Path("/opt/sport-prediction/current/engine/data")
SCHEDULE_DIR = ROOT / "schedules"
PRED_DIR = ROOT / "predictions"
STATE_DIR = ROOT / "state"
EMAIL_DIR = ROOT / "email-outbox"
AUDIT_DIR = ROOT / "audit"
EOD_DIR = ROOT / "eod"
DAILY_MD = Path("/opt/sport-prediction/current/engine/data/sports-daily.md")
HIMALAYA = Path("/opt/homebrew/bin/himalaya")
EMAIL_TO = "bntng.sfyn@gmail.com"
EMAIL_FROM = "bntng.sfyn@gmail.com"
DISCORD_CHANNEL = "1515327116189630526"
SPORTS = ["football", "tennis", "motorsport", "basketball", "nfl"]
DEFAULT_DURATIONS_MIN = {
    "football": 135,
    "tennis": 180,
    "motorsport": 150,
    "basketball": 150,
    "nfl": 240,
}


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().date().isoformat()


def ensure_dirs() -> None:
    for d in [SCHEDULE_DIR, PRED_DIR, STATE_DIR, EMAIL_DIR, AUDIT_DIR, EOD_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "event"


def parse_wib(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip().replace("T", " ")
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=0, minute=0)
            return dt.replace(tzinfo=WIB)
        except Exception:
            continue
    return None


def event_key_from_prediction(p: Dict[str, Any]) -> str:
    base = f"{p.get('sport','unknown')}|{p.get('competition','')}|{p.get('event','')}|{p.get('kickoff_wib','')}"
    return slugify(base)[:120]


def audit(action: str, status: str, details: Dict[str, Any], date: Optional[str] = None) -> None:
    ensure_dirs()
    rec = {
        "ts_wib": now_wib().isoformat(timespec="seconds"),
        "action": action,
        "status": status,
        "details": details,
    }
    path = AUDIT_DIR / f"{date or today_wib()}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_daily(date: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    schedule = read_json(SCHEDULE_DIR / f"{date}.json", {}) or {}
    predictions = read_json(PRED_DIR / f"{date}.json", {}) or {}
    return schedule, predictions


def load_state(date: str) -> Dict[str, Any]:
    path = STATE_DIR / f"{date}.json"
    state = read_json(path, None)
    if state is None:
        state = {
            "date_wib": date,
            "created_at_wib": now_wib().isoformat(timespec="seconds"),
            "updated_at_wib": None,
            "discord_channel": DISCORD_CHANNEL,
            "email_to": EMAIL_TO,
            "reports": {
                "initial_48h": {"discord_sent": False, "email_sent": False},
                "eod": {"discord_sent": False, "email_sent": False},
            },
            "events": {},
            "no_event": [],
        }
    return state


def save_state(date: str, state: Dict[str, Any]) -> None:
    state["updated_at_wib"] = now_wib().isoformat(timespec="seconds")
    write_json(STATE_DIR / f"{date}.json", state)


def normalize_daily_state(date: str) -> Dict[str, Any]:
    schedule, pred_doc = load_daily(date)
    preds = pred_doc.get("predictions", []) if isinstance(pred_doc, dict) else []
    state = load_state(date)
    state["no_event"] = schedule.get("no_event", []) if isinstance(schedule, dict) else []
    state["fixture_source_classification"] = schedule.get("fixture_source_classification", {}) if isinstance(schedule, dict) else {}
    for p in preds:
        key = event_key_from_prediction(p)
        existing = state["events"].get(key, {})
        kickoff = p.get("kickoff_wib") or ""
        sport = p.get("sport") or "unknown"
        existing.update({
            "event_id": key,
            "sport": sport,
            "event": p.get("event", ""),
            "competition": p.get("competition", ""),
            "kickoff_wib": kickoff,
            "status": existing.get("status", "scheduled"),
            "prediction": {
                "outcome": p.get("predicted_outcome"),
                "score_or_result": p.get("predicted_score_or_result"),
                "confidence_percent": p.get("confidence_percent"),
                "risk_score_1_to_10": p.get("risk_score_1_to_10"),
                "confidence_breakdown": p.get("confidence_breakdown") or (p.get("prediction") or {}).get("confidence_breakdown"),
                "confidence_label": p.get("confidence_label"),
                "no_pick": p.get("no_pick", False),
            },
            "confidence_breakdown": p.get("confidence_breakdown") or (p.get("prediction") or {}).get("confidence_breakdown"),
            "data_source": p.get("data_source") or {"fixture_source": "ESPN", "research_primary": "SearXNG", "sources_used": ["ESPN", "SearXNG"], "fallback_sources_used": [], "DATA_SOURCE_DEGRADED": bool(p.get("DATA_SOURCE_DEGRADED")), "confidence_penalty_applied": 0},
            "DATA_SOURCE_DEGRADED": bool(p.get("DATA_SOURCE_DEGRADED", False)),
            "competition_level": p.get("competition_level") or "senior",
            "prediction_eligible": p.get("prediction_eligible", True),
            "accuracy_excluded": p.get("accuracy_excluded", False),
            "report_label": p.get("report_label"),
            "reasoning": p.get("reasoning") or [],
            "evidence_url": p.get("evidence_url"),
            "evidence_title": p.get("evidence_title"),
            "pre_match_alert_sent": existing.get("pre_match_alert_sent", False),
            "post_match_report_sent": existing.get("post_match_report_sent", False),
            "result_retry_count": existing.get("result_retry_count", 0),
            "result_pending_notified": existing.get("result_pending_notified", False),
            "next_result_retry_after_wib": existing.get("next_result_retry_after_wib"),
            "actual_result": existing.get("actual_result") or p.get("actual_result"),
            "actual_winner": existing.get("actual_winner") or p.get("actual_winner"),
            "validation": existing.get("validation") or p.get("validation"),
            "source_prediction_file": str(PRED_DIR / f"{date}.json"),
        })
        normalize_prediction_v32(existing)
        kickoff_dt = parse_wib(kickoff)
        if is_prediction_stub_row(p):
            existing.setdefault("backfill_attempts", 0)
            existing.setdefault("backfill_alert_sent", False)
            if kickoff_dt and now_wib() >= kickoff_dt:
                existing["status"] = "no_prediction"
                existing["prediction_eligible"] = False
                existing["prediction_ineligible_reason"] = "kickoff_passed_before_backfill"
                existing["validation"] = "NO_PREDICTION"
                existing["validation_status"] = "NO_PREDICTION"
                existing["accuracy_excluded"] = True
                existing["backfill_terminal"] = True
            elif existing.get("status") not in ["backfill_failed", "no_prediction", "completed", "postponed", "cancelled"]:
                existing["status"] = "research_backfill_required"
                existing["backfill_required_since_wib"] = existing.get("backfill_required_since_wib") or now_wib().isoformat(timespec="seconds")
        if existing.get("prediction_eligible") is False:
            existing["validation"] = "NO_PREDICTION"
            existing["validation_status"] = "NO_PREDICTION"
            existing["accuracy_excluded"] = True
            existing.setdefault("lesson_learnt", "Fixture is excluded from prediction/accuracy by eligibility policy.")
        # If we have an actual_result and the kickoff has passed, mark as completed
        if existing.get("actual_result") and kickoff_dt and now_wib() > kickoff_dt:
            if existing.get("status") not in ["completed", "postponed", "cancelled"]:
                existing["status"] = "completed"
                existing.setdefault("result_captured_at_wib", now_wib().isoformat(timespec="seconds"))
        state["events"][key] = existing
    save_state(date, state)
    audit("normalize_state", "ok", {"date": date, "events": len(state["events"]), "no_event": state["no_event"]})
    return state


def render_plain_report_from_daily() -> str:
    if DAILY_MD.exists():
        return DAILY_MD.read_text()
    return "SPORT SCAN REPORT not available yet."


SPORT_META = {
    "football": ("⚽ Football", "#2e7d32"),
    "tennis": ("🎾 Tennis", "#6a1b9a"),
    "motorsport": ("🏎️ Motorsport", "#c62828"),
    "basketball": ("🏀 Basketball", "#e65100"),
    "nfl": ("🏈 NFL", "#1565c0"),
    "unknown": ("Sport", "#334155"),
}

CONFIDENCE_WEIGHTS = {
    "football": {"form": 0.25, "h2h": 0.15, "player_condition": 0.20, "home_away": 0.15, "market_odds": 0.15, "contextual": 0.10},
    "tennis": {"form": 0.20, "h2h": 0.20, "player_condition": 0.25, "home_away": 0.15, "market_odds": 0.10, "contextual": 0.10},
    "motorsport": {"form": 0.15, "h2h": 0.10, "player_condition": 0.20, "home_away": 0.20, "market_odds": 0.20, "contextual": 0.15},
    "basketball": {"form": 0.25, "h2h": 0.15, "player_condition": 0.20, "home_away": 0.15, "market_odds": 0.15, "contextual": 0.10},
    "nfl": {"form": 0.20, "h2h": 0.15, "player_condition": 0.20, "home_away": 0.15, "market_odds": 0.15, "contextual": 0.15},
}
CONFIDENCE_FACTORS = ["form", "h2h", "player_condition", "home_away", "market_odds", "contextual"]
WEIGHT_ADJUSTMENTS = Path("/opt/sport-prediction/current/engine/data/meta-learning/weight-adjustments.json")


def confidence_label(value: Any) -> str:
    try:
        v = float(value)
    except Exception:
        return "UNKNOWN"
    if v >= 75:
        return "HIGH"
    if v >= 55:
        return "MEDIUM"
    if v >= 40:
        return "LOW"
    return "COIN FLIP"


def load_weight_adjustments() -> Dict[str, Any]:
    data = read_json(WEIGHT_ADJUSTMENTS, {}) or {}
    return data if isinstance(data, dict) else {}


def adjusted_weights(sport: str) -> Dict[str, float]:
    sport = (sport or "unknown").lower()
    weights = dict(CONFIDENCE_WEIGHTS.get(sport, CONFIDENCE_WEIGHTS["football"]))
    data = load_weight_adjustments()
    for adj in data.get("adjustments", []) if isinstance(data.get("adjustments", []), list) else []:
        if adj.get("status", "applied") != "applied":
            continue
        if adj.get("sport") != sport:
            continue
        factor = adj.get("factor")
        delta = float(adj.get("delta_weight", 0) or 0)
        if factor in weights:
            weights[factor] = max(0.0, weights[factor] + delta)
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def calculate_confidence(sport: str, breakdown: Dict[str, Any], degraded: bool = False) -> Tuple[int, Dict[str, float], int]:
    weights = adjusted_weights(sport)
    score = 0.0
    clean: Dict[str, float] = {}
    for f in CONFIDENCE_FACTORS:
        try:
            val = float((breakdown or {}).get(f, 50))
        except Exception:
            val = 50.0
        val = max(0.0, min(100.0, val))
        clean[f] = val
        score += val * weights.get(f, 0.0)
    penalty = -15 if degraded else 0
    score = max(0.0, min(100.0, score + penalty))
    return int(round(score)), weights, penalty


def default_confidence_breakdown(confidence: Any) -> Dict[str, int]:
    try:
        v = int(round(float(confidence)))
    except Exception:
        v = 50
    return {f: max(0, min(100, v)) for f in CONFIDENCE_FACTORS}


def is_no_pick_prediction(pred: Dict[str, Any]) -> bool:
    return str((pred or {}).get("outcome") or "").upper() == "NO_PICK" or bool((pred or {}).get("no_pick"))


def is_blank_prediction(pred: Dict[str, Any]) -> bool:
    pred = pred or {}
    if is_no_pick_prediction(pred):
        return False
    outcome = str(pred.get("outcome") or "").strip()
    score = str(pred.get("score_or_result") or "").strip()
    return not outcome or not score or outcome == "—" or score == "—"


def is_prediction_stub_row(p: Dict[str, Any]) -> bool:
    """True when a prediction row is only a discovered fixture stub.

    These rows can appear after the initial 48H scan when a late fixture source
    surfaces a match. They must be backfilled only before kickoff; after kickoff
    they become permanent NO_PREDICTION to avoid hindsight prediction.
    """
    if not bool(p.get("stub")):
        return False
    if p.get("researched") and not p.get("stub"):
        return False
    if p.get("prediction_eligible") is False:
        return False
    pred = {
        "outcome": p.get("predicted_outcome"),
        "score_or_result": p.get("predicted_score_or_result"),
        "no_pick": p.get("no_pick", False),
    }
    return is_blank_prediction(pred)


def normalize_prediction_v32(ev: Dict[str, Any]) -> None:
    pred = ev.setdefault("prediction", {})
    degraded = bool(ev.get("DATA_SOURCE_DEGRADED") or (ev.get("data_source") or {}).get("DATA_SOURCE_DEGRADED"))
    breakdown = ev.get("confidence_breakdown") or pred.get("confidence_breakdown") or default_confidence_breakdown(pred.get("confidence_percent"))
    confidence, weights, penalty = calculate_confidence(ev.get("sport", "football"), breakdown, degraded)
    if pred.get("confidence_percent") not in (None, "", "—") and not ev.get("confidence_breakdown") and not pred.get("confidence_breakdown"):
        # Preserve legacy/backfilled confidence while still exposing auditable neutral breakdown.
        try:
            confidence = int(round(float(pred.get("confidence_percent")))) + penalty
            confidence = max(0, min(100, confidence))
        except Exception:
            pass
    pred["confidence_percent"] = confidence
    pred["confidence_label"] = confidence_label(confidence)
    pred["confidence_breakdown"] = breakdown
    pred["confidence_weights"] = weights
    pred["confidence_model_version"] = "v3.2"
    pred["DATA_SOURCE_DEGRADED"] = degraded
    pred["confidence_penalty_applied"] = penalty
    ev["confidence_breakdown"] = breakdown
    ev["confidence_label"] = pred["confidence_label"]
    ev["DATA_SOURCE_DEGRADED"] = degraded
    ev.setdefault("data_source", {"fixture_source": "ESPN", "research_primary": "SearXNG", "sources_used": ["ESPN", "SearXNG"], "fallback_sources_used": [], "DATA_SOURCE_DEGRADED": degraded, "confidence_penalty_applied": penalty})
    if confidence < 40:
        pred["outcome"] = "NO_PICK"
        pred["no_pick"] = True
        pred.setdefault("no_pick_reason", "confidence_below_40")
        pred["score_or_result"] = pred.get("score_or_result") or "—"
        ev.setdefault("reasoning", [])
        if not ev["reasoning"]:
            ev["reasoning"] = [
                "NO_PICK: confidence below 40 after data-source degradation penalty.",
                "Fixture is retained in schedule, but no winner/score prediction is validated until sufficient evidence exists.",
            ]


def score_parts(score: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"(\d+)\s*[-–:]\s*(\d+)", str(score or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def validation_status_v32(ev: Dict[str, Any], actual_score: str, actual_winner: str) -> str:
    pred = ev.get("prediction", {}) or {}
    if is_no_pick_prediction(pred):
        return "NO_PICK"
    pred_outcome = str(pred.get("outcome") or "").strip().lower()
    pred_score = str(pred.get("score_or_result") or "").strip()
    if not pred_outcome or not pred_score or pred_score == "—":
        return "NO_PREDICTION"
    resolved = _resolve_outcome_label(ev, pred).lower()
    aw = str(actual_winner or "").strip().lower()
    outcome_ok = (aw == "draw" and (pred_outcome == "draw" or resolved == "draw")) or (aw != "draw" and ((pred_outcome and aw in pred_outcome) or (pred_outcome and pred_outcome in aw) or (resolved and aw in resolved) or (resolved and resolved in aw)))
    if not outcome_ok:
        return "SALAH"
    ps = score_parts(pred_score)
    ac = score_parts(actual_score)
    sport = (ev.get("sport") or "").lower()
    if not ps or not ac:
        return "SEBAGIAN BENAR"
    if sport == "football":
        delta = abs(ps[0] - ac[0]) + abs(ps[1] - ac[1])
        return "BENAR" if delta <= 1 else "SEBAGIAN BENAR"
    if sport == "basketball":
        delta = abs(ps[0] - ac[0]) + abs(ps[1] - ac[1])
        return "BENAR" if delta <= 8 else "SEBAGIAN BENAR"
    if sport == "nfl":
        delta = abs(ps[0] - ac[0]) + abs(ps[1] - ac[1])
        return "BENAR" if delta <= 7 else "SEBAGIAN BENAR"
    if sport == "tennis":
        delta = abs((ps[0] + ps[1]) - (ac[0] + ac[1]))
        return "BENAR" if delta <= 1 else "SEBAGIAN BENAR"
    return "BENAR" if pred_score.replace(" ", "") == str(actual_score).replace(" ", "") else "SEBAGIAN BENAR"


def build_lesson_json(ev: Dict[str, Any], factors_missed: Optional[List[str]] = None, pattern_tags: Optional[List[str]] = None, postmortem: str = "") -> Dict[str, Any]:
    pred = ev.get("prediction", {}) or {}
    event = str(ev.get("event") or "")
    team_home = ev.get("team_a") or (event.split(" vs ")[0] if " vs " in event else "")
    team_away = ev.get("team_b") or (event.split(" vs ")[1] if " vs " in event else "")
    return {
        "match_id": ev.get("event_id") or slugify(f"{ev.get('kickoff_wib','')}-{ev.get('sport','')}-{event}"),
        "date": str(ev.get("kickoff_wib") or "")[:10],
        "sport": ev.get("sport"),
        "competition": ev.get("competition"),
        "team_home": team_home,
        "team_away": team_away,
        "predicted_winner": _resolve_outcome_label(ev, pred),
        "actual_winner": ev.get("actual_winner"),
        "predicted_score": pred.get("score_or_result"),
        "actual_score": ev.get("actual_result"),
        "confidence_pct": pred.get("confidence_percent"),
        "confidence_breakdown": pred.get("confidence_breakdown") or ev.get("confidence_breakdown") or {},
        "risk_score": pred.get("risk_score_1_to_10"),
        "validation_status": str(ev.get("validation") or "").replace(" ", "_"),
        "factors_missed": factors_missed or [],
        "pattern_tags": pattern_tags or [],
        "postmortem": postmortem or ev.get("lesson_learnt") or "No durable lesson extracted.",
    }


PATTERN_FACTOR_MAP = {
    "underestimated_home_advantage": "home_away",
    "overestimated_form": "form",
    "injury_late_news": "player_condition",
    "weather_impact": "contextual",
    "rotation_surprise": "player_condition",
    "market_odds_misleading": "market_odds",
    "motivational_factor": "contextual",
    "fatigue_underestimated": "player_condition",
    "surface_form_ignored": "home_away",
    "tactical_surprise": "contextual",
}


def update_weight_adjustments_from_lessons(date: str) -> Dict[str, Any]:
    """v3.2 pattern-tag learning: if same tag appears >=3x in 14 days for a sport,
    write a +5 percentage-point factor adjustment record. Existing records are
    idempotently preserved by (sport, pattern_tag, factor).
    """
    try:
        end = datetime.fromisoformat(date).date()
    except Exception:
        end = now_wib().date()
    start = end - timedelta(days=13)
    counts: Dict[Tuple[str, str], int] = {}
    for path in sorted(STATE_DIR.glob("*.json")):
        try:
            d = datetime.fromisoformat(path.stem).date()
        except Exception:
            continue
        if not (start <= d <= end):
            continue
        st = read_json(path, {}) or {}
        for ev in (st.get("events") or {}).values():
            lesson = ev.get("lesson_json") or {}
            if not isinstance(lesson, dict):
                continue
            sport = str(lesson.get("sport") or ev.get("sport") or "unknown")
            for tag in lesson.get("pattern_tags") or []:
                counts[(sport, str(tag))] = counts.get((sport, str(tag)), 0) + 1
    existing = read_json(WEIGHT_ADJUSTMENTS, {}) or {}
    adjustments = existing.get("adjustments", []) if isinstance(existing.get("adjustments", []), list) else []
    keys = {(a.get("sport"), a.get("pattern_tag"), a.get("factor")) for a in adjustments}
    added = []
    for (sport, tag), count in sorted(counts.items()):
        if count < 3:
            continue
        factor = PATTERN_FACTOR_MAP.get(tag)
        if not factor:
            continue
        key = (sport, tag, factor)
        if key in keys:
            continue
        rec = {"sport": sport, "pattern_tag": tag, "count_14d": count, "factor": factor, "delta_weight": 0.05, "created_at_wib": now_wib().isoformat(timespec="seconds"), "window_start": start.isoformat(), "window_end": end.isoformat()}
        adjustments.append(rec)
        added.append(rec)
    out = {"version": "v3.2", "updated_at_wib": now_wib().isoformat(timespec="seconds"), "adjustments": adjustments, "counts_14d": {f"{s}:{t}": c for (s, t), c in counts.items()}}
    WEIGHT_ADJUSTMENTS.parent.mkdir(parents=True, exist_ok=True)
    WEIGHT_ADJUSTMENTS.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    audit("v32_weight_adjustments_updated", "ok", {"date": date, "added": added, "counts": out["counts_14d"]}, date=date)
    return out


def base_email_html(title: str, inner_html: str) -> str:
    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827;">
  <div style="max-width:720px;margin:0 auto;padding:14px;">
    <div style="background:#0f172a;background-image:linear-gradient(135deg,#020617,#1d4ed8);color:#ffffff;border-radius:16px;padding:18px 16px;margin-bottom:12px;">
      <div style="display:inline-block;background:#ffffff !important;color:#0f172a !important;border-radius:999px;padding:7px 11px;border:1px solid #dbeafe;box-shadow:0 2px 6px rgba(0,0,0,.22);">
        <span style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#0f172a !important;font-weight:900;">Sport Scanning AI v3.2</span>
      </div>
      <div style="background:#ffffff !important;color:#0f172a !important;border-radius:12px;padding:12px 14px;margin:12px 0 0;border:2px solid #dbeafe;box-shadow:0 4px 12px rgba(0,0,0,.25);">
        <div style="font-size:23px;line-height:1.25;color:#0f172a !important;font-weight:900;text-shadow:0 1px 0 rgba(15,23,42,.08);">{escape(title)}</div>
      </div>
      <div style="display:inline-block;background:#ffffff !important;color:#0f172a !important;border-radius:999px;padding:7px 11px;margin-top:12px;border:1px solid #dbeafe;box-shadow:0 2px 6px rgba(0,0,0,.22);">
        <span style="font-size:12px;color:#0f172a !important;font-weight:900;">Generated {now_wib().strftime('%Y-%m-%d %H:%M WIB')}</span>
      </div>
    </div>
    {inner_html}
    <div style="font-size:11px;color:#64748b;text-align:center;margin:18px 0 4px;">Probabilistic sports analysis · No betting recommendation · WIB timezone</div>
  </div>
</body></html>"""


def summary_box(items: Dict[str, Any]) -> str:
    cells = []
    for k, v in items.items():
        cells.append(f"<div style='display:inline-block;min-width:120px;margin:4px;padding:10px 12px;border-radius:12px;background:#eef2ff;border:1px solid #c7d2fe;'><div style='font-size:11px;color:#475569;text-transform:uppercase'>{escape(str(k))}</div><div style='font-size:20px;font-weight:700;color:#1e293b'>{escape(str(v))}</div></div>")
    return "<div style='background:white;border-radius:16px;padding:12px;margin-bottom:12px;border:1px solid #e5e7eb;'>" + "".join(cells) + "</div>"


def sport_label_color(sport: str) -> Tuple[str, str]:
    return SPORT_META.get((sport or "unknown").lower(), SPORT_META["unknown"])


def _resolve_outcome_label(ev: Dict[str, Any], pred: Dict[str, Any]) -> str:
    """Map generic outcome codes (home_win/away_win/draw) to actual team names from the
    event's team_a vs team_b labels, falling back to the literal outcome string if it
    doesn't match a known code. This makes prediction cards readable when the LLM
    produced a generic label.
    """
    raw = str(pred.get("outcome") or "").strip()
    if not raw:
        return "—"
    code = raw.lower()
    team_a = str(ev.get("team_a") or ev.get("event", "").split(" vs ")[0] if " vs " in str(ev.get("event", "")) else "").strip()
    team_b = str(ev.get("team_b") or (ev.get("event", "").split(" vs ")[1] if " vs " in str(ev.get("event", "")) else "")).strip()
    # Build a mapping based on which team is home/away in the ESPN-style slug.
    home = team_a or "Home"
    away = team_b or "Away"
    code_map = {
        "home_win": home,
        "away_win": away,
        "draw": "Draw",
        "home": home,
        "away": away,
    }
    if code in code_map:
        return code_map[code]
    # If outcome is a partial team name match, prefer that.
    for t in (team_a, team_b):
        if t and (code in t.lower() or t.lower() in code):
            return t
    return raw


def _prediction_for_card(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort prediction dict for rendering. Falls back in this order:
       1) Own `prediction` field if populated.
       2) For completed events: inherit prediction from a sibling state file where the
          same slug_key has the original prediction stored.
       3) For completed events with no original prediction: synthesize from actuals
          so the card shows actual_winner / actual_result / validation instead of None.
       4) Otherwise: em-dash placeholders.
    """
    pred = ev.get("prediction") or {}
    has_pred = any(pred.get(k) is not None for k in ("outcome", "score_or_result", "confidence_percent", "risk_score_1_to_10"))
    if has_pred:
        return pred
    # Try to inherit from sibling state where this event has an original prediction.
    if ev.get("status") == "completed" and ev.get("kickoff_wib"):
        try:
            from sports_v3_engine import STATE_DIR, load_state
            from sports_v31_espn_ingest import slug_key as _sk
            ta = str(ev.get("team_a") or ev.get("event", "").split(" vs ")[0])
            tb = str(ev.get("team_b") or (ev.get("event", "").split(" vs ")[1] if " vs " in ev.get("event", "") else ""))
            this_slug = _sk({"sport": ev.get("sport"), "competition": ev.get("competition"),
                             "team_a": ta, "team_b": tb, "kickoff_wib": ev.get("kickoff_wib")})
            for f in sorted(STATE_DIR.glob("*.json"), reverse=True)[:14]:
                try:
                    st = load_state(f.stem)
                except Exception:
                    continue
                if not st or not isinstance(st.get("events"), dict):
                    continue
                for other in st["events"].values():
                    if other.get("status") != "completed":
                        continue
                    other_ta = str(other.get("team_a") or other.get("event", "").split(" vs ")[0])
                    other_tb = str(other.get("team_b") or (other.get("event", "").split(" vs ")[1] if " vs " in other.get("event", "") else ""))
                    other_slug = _sk({"sport": other.get("sport"), "competition": other.get("competition"),
                                      "team_a": other_ta, "team_b": other_tb, "kickoff_wib": other.get("kickoff_wib")})
                    if other_slug == this_slug:
                        other_pred = other.get("prediction") or {}
                        if other_pred and any(other_pred.get(k) is not None for k in ("outcome", "score_or_result")):
                            return other_pred
        except Exception:
            pass
        # No sibling prediction found — fall back to actuals.
        return {
            "outcome": _resolve_outcome_label(ev, {"outcome": ev.get("actual_winner") or "—"}),
            "score_or_result": ev.get("actual_result") or "—",
            "confidence_percent": "—",
            "risk_score_1_to_10": "—",
        }
    return {
        "outcome": "—",
        "score_or_result": "—",
        "confidence_percent": "—",
        "risk_score_1_to_10": "—",
    }


def event_card(ev: Dict[str, Any]) -> str:
    pred = _prediction_for_card(ev)
    resolved_outcome = _resolve_outcome_label(ev, pred)
    label, color = sport_label_color(ev.get("sport", "unknown"))
    extra_label = f" · {ev.get('report_label')}" if ev.get("report_label") else ""
    reasoning = ev.get("reasoning") or []
    reasoning_html = ""
    if reasoning:
        items = "".join(
            f"<li style='margin:4px 0;line-height:1.45;'>{escape(str(r))[:300]}</li>"
            for r in reasoning[:6]
        )
        reasoning_html = (
            f"<div style='margin-top:10px;padding:10px 12px;background:#f1f5f9;"
            f"border-left:3px solid {color};border-radius:8px;'>"
            f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.06em;"
            f"color:#475569;margin-bottom:6px;font-weight:700;'>Reasoning</div>"
            f"<ul style='margin:0;padding-left:18px;font-size:13px;color:#0f172a;'>{items}</ul>"
            f"</div>"
        )
    evidence = ev.get("evidence_url") or ev.get("evidence") or ""
    evidence_html = ""
    if evidence:
        if isinstance(evidence, dict):
            url = evidence.get("url", "")
            title = evidence.get("title", "")
        else:
            url = str(evidence)
            title = url
        evidence_html = (
            f"<div style='margin-top:8px;font-size:12px;color:#475569;'>"
            f"📚 Source: <a href='{escape(url)}' style='color:#1d4ed8;text-decoration:none;'>"
            f"{escape(str(title)[:100])}</a></div>"
        )
    return f"""
    <div style="background:white;border:1px solid #e5e7eb;border-radius:14px;margin:10px 0;overflow:hidden;">
      <div style="background:{color};color:white;padding:9px 12px;font-weight:700;font-size:14px;">{escape(label)} · {escape(str(ev.get('competition','')))}{escape(extra_label)}</div>
      <div style="padding:12px;">
        <div style="font-weight:700;font-size:16px;margin-bottom:6px;">{escape(str(ev.get('event','')))}</div>
        <div style="font-size:13px;color:#475569;margin-bottom:8px;">📅 {escape(str(ev.get('kickoff_wib','')))} WIB · Status: {escape(str(ev.get('status','')))}</div>
        <div style="background:#f8fafc;border-radius:10px;padding:10px;font-size:14px;">
          <b>Prediction:</b> {escape('NO_PICK — confidence terlalu rendah' if is_no_pick_prediction(pred) else resolved_outcome + ' · ' + str(pred.get('score_or_result')))}<br>
          <b>Confidence:</b> {escape(str(pred.get('confidence_percent')))}% ({escape(str(pred.get('confidence_label') or confidence_label(pred.get('confidence_percent'))))}) · <b>Risk:</b> {escape(str(pred.get('risk_score_1_to_10')))}/10<br>
          <b>Data Source:</b> {escape(', '.join((ev.get('data_source') or {}).get('sources_used', ['SearXNG'])))}
        </div>
        {"<div style='margin-top:8px;background:#fff7ed;border:1px solid #fb923c;color:#9a3412;border-radius:10px;padding:9px;font-size:13px;font-weight:700;'>⚠️ DATA_SOURCE_DEGRADED — confidence penalty applied</div>" if (ev.get('DATA_SOURCE_DEGRADED') or pred.get('DATA_SOURCE_DEGRADED')) else ""}
        {reasoning_html}
        {evidence_html}
      </div>
    </div>"""


def render_events_email_html(title: str, text: str, events: List[Dict[str, Any]], no_event: Optional[List[Dict[str, Any]]] = None) -> str:
    sports = sorted({e.get("sport", "unknown") for e in events})
    completed_events = [e for e in events if e.get("status") == "completed"]
    upcoming_events = [e for e in events if e.get("status") != "completed"]
    inner = summary_box({
        "Total events": len(events),
        "Sport coverage": ", ".join(sports) or "none",
        "No event": len(no_event or []),
        "Completed (recap)": len(completed_events),
        "Upcoming": len(upcoming_events),
        "NO_PICK": sum(1 for e in upcoming_events if is_no_pick_prediction((e.get("prediction") or {}))),
        "Data Source Status": "DEGRADED" if any(e.get("DATA_SOURCE_DEGRADED") for e in upcoming_events) else "OK",
    })
    if any(e.get("DATA_SOURCE_DEGRADED") for e in upcoming_events):
        inner += "<div style='background:#fff7ed;border:1px solid #fb923c;color:#9a3412;border-radius:14px;padding:12px;margin-bottom:12px;font-weight:700;'>⚠️ DATA_SOURCE_DEGRADED — one or more events used fallback/stale sources; confidence penalty applied.</div>"
    # 48H preview emails must show only upcoming/scheduled events. Completed events
    # are excluded from cards and handled by post-match/EOD reports instead.
    for sport in SPORTS:
        sport_events = [e for e in upcoming_events if e.get("sport") == sport]
        if not sport_events:
            continue
        label, color = sport_label_color(sport)
        inner += f"<h2 style='font-size:16px;background:{color};color:white;padding:10px 12px;border-radius:12px;margin:12px 0 6px;'>{escape(label)}</h2>"
        inner += "".join(event_card(e) for e in sport_events)
    if no_event:
        inner += "<div style='background:white;border:1px solid #e5e7eb;border-radius:14px;padding:12px;margin-top:12px;'><b>📭 No Event</b><ul>"
        for n in no_event:
            inner += f"<li>{escape(str(n.get('sport')))} — {escape(str(n.get('reason','No event in 48h')))}</li>"
        inner += "</ul></div>"
    return base_email_html(title, inner)


def validation_color(status: str) -> str:
    s = status or ""
    if "SEBAGIAN" in s:
        return "#facc15"
    if "SALAH" in s:
        return "#ef4444"
    if "BENAR" in s:
        return "#22c55e"
    return "#94a3b8"


def render_postmatch_email_html(ev: Dict[str, Any], text: str) -> str:
    pred = _prediction_for_card(ev)
    resolved_outcome = _resolve_outcome_label(ev, pred)
    status = str(ev.get("validation") or "PENDING")
    color = validation_color(status)
    table = f"""
    <table style="width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;">
      <tr style="background:#f1f5f9;"><th style="text-align:left;padding:10px;">Item</th><th style="text-align:left;padding:10px;">Prediction</th><th style="text-align:left;padding:10px;">Actual</th></tr>
      <tr><td style="padding:10px;border-top:1px solid #e5e7eb;">Outcome</td><td style="padding:10px;border-top:1px solid #e5e7eb;">{escape(resolved_outcome)}</td><td style="padding:10px;border-top:1px solid #e5e7eb;">{escape(str(ev.get('actual_winner') or '—'))}</td></tr>
      <tr><td style="padding:10px;border-top:1px solid #e5e7eb;">Score/Result</td><td style="padding:10px;border-top:1px solid #e5e7eb;">{escape(str(pred.get('score_or_result') or '—'))}</td><td style="padding:10px;border-top:1px solid #e5e7eb;">{escape(str(ev.get('actual_result') or '—'))}</td></tr>
      <tr><td style="padding:10px;border-top:1px solid #e5e7eb;">Status</td><td colspan="2" style="padding:10px;border-top:1px solid #e5e7eb;background:{color};font-weight:700;">{escape(status)}</td></tr>
    </table>"""
    inner = summary_box({"Match": ev.get("event", ""), "Confidence": f"{pred.get('confidence_percent')}%", "Confidence Label": pred.get('confidence_label') or confidence_label(pred.get('confidence_percent')), "Risk": f"{pred.get('risk_score_1_to_10')}/10", "Status": status})
    inner += event_card(ev) + table
    lesson = ev.get('lesson_json') or build_lesson_json(ev)
    tags = lesson.get('pattern_tags') or [] if isinstance(lesson, dict) else []
    tag_html = ''.join(f"<span style='display:inline-block;background:#e0f2fe;color:#075985;border-radius:999px;padding:4px 8px;margin:3px;font-size:12px;'>🏷️ {escape(str(t))}</span>" for t in tags)
    inner += f"<div style='background:white;border-radius:14px;padding:12px;margin-top:12px;border:1px solid #e5e7eb;'><b>💡 Lesson Learnt</b><br>{escape(str(ev.get('lesson_learnt') or (lesson.get('postmortem') if isinstance(lesson, dict) else 'No durable lesson extracted.')))}<div style='margin-top:8px;'>{tag_html}</div></div>"
    return base_email_html(f"[POST-MATCH] {ev.get('event')}", inner)


def render_eod_email_html(date: str, state: Dict[str, Any], text: str) -> str:
    events = list(state.get("events", {}).values())
    inner = summary_box({"Total events": len(events), "Completed": sum(1 for e in events if e.get('status') == 'completed'), "Pending": sum(1 for e in events if e.get('status') not in {'completed','postponed','cancelled','result_pending_after_60m'}), "NO_PICK": sum(1 for e in events if is_no_pick_prediction((e.get('prediction') or {}))), "Data Source Status": "DEGRADED" if any(e.get('DATA_SOURCE_DEGRADED') for e in events) else "OK"})
    rows = ""
    for sport in SPORTS:
        sport_events = [e for e in events if e.get("sport") == sport and e.get("status") == "completed"]
        no_pick = sum(1 for e in sport_events if is_no_pick_prediction((e.get("prediction") or {})))
        no_prediction = sum(1 for e in sport_events if str(e.get("validation") or "") == "NO_PREDICTION")
        total = len([e for e in sport_events if not is_no_pick_prediction((e.get("prediction") or {})) and str(e.get("validation") or "") != "NO_PREDICTION"])
        correct = sum(1 for e in sport_events if "BENAR" in str(e.get("validation", "")) and "SEBAGIAN" not in str(e.get("validation", "")))
        partial = sum(1 for e in sport_events if "SEBAGIAN" in str(e.get("validation", "")))
        wrong = sum(1 for e in sport_events if "SALAH" in str(e.get("validation", "")))
        acc = f"{(correct/total*100):.1f}%" if total else "-"
        label, color = sport_label_color(sport)
        rows += f"<tr><td style='padding:9px;border-top:1px solid #e5e7eb;color:{color};font-weight:700'>{escape(label)}</td><td style='padding:9px;border-top:1px solid #e5e7eb;'>{total}</td><td style='padding:9px;border-top:1px solid #e5e7eb;'>{correct}</td><td style='padding:9px;border-top:1px solid #e5e7eb;'>{partial}</td><td style='padding:9px;border-top:1px solid #e5e7eb;'>{wrong}</td><td style='padding:9px;border-top:1px solid #e5e7eb;'>{no_pick}</td><td style='padding:9px;border-top:1px solid #e5e7eb;'>{acc}</td></tr>"
    inner += "<div style='background:white;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;'><div style='padding:12px;font-weight:700;'>📈 Accuracy by Sport</div><table style='width:100%;border-collapse:collapse;font-size:13px;'><tr style='background:#f8fafc;'><th style='text-align:left;padding:9px;'>Sport</th><th style='text-align:left;padding:9px;'>Total</th><th style='text-align:left;padding:9px;'>Correct</th><th style='text-align:left;padding:9px;'>Partial</th><th style='text-align:left;padding:9px;'>Wrong</th><th style='text-align:left;padding:9px;'>No Pick</th><th style='text-align:left;padding:9px;'>Acc.</th></tr>" + rows + "</table></div>"
    inner += "".join(event_card(e) for e in events)
    return base_email_html(f"[END OF DAY] Sport Scan Summary — {date}", inner)


def html_wrap(title: str, body_text: str) -> str:
    safe = escape(body_text).replace("\n", "<br>\n")
    inner = summary_box({"Type": "Update", "Generated": now_wib().strftime('%H:%M WIB')})
    inner += f"<div style='background:white;border-radius:14px;border:1px solid #e5e7eb;padding:12px;font-size:14px;line-height:1.5'>{safe}</div>"
    return base_email_html(title, inner)


def mml_for(subject: str, html: str, text: str) -> str:
    # Himalaya template send expects MML tags to render HTML. Do not use raw
    # Content-Type headers here: they are treated as body text by the template
    # renderer in this setup. Keep this HTML-only: no plain text fallback part.
    return (
        f"From: {EMAIL_FROM}\n"
        f"To: {EMAIL_TO}\n"
        f"Subject: {subject}\n\n"
        f"<#multipart type=alternative>\n"
        f"<#part type=text/html>\n"
        f"{html}\n"
        f"<#/multipart>\n"
    )


def _email_marker_path(tag: str) -> Path:
    return EMAIL_DIR / f"{slugify(tag)}.sent.json"


def _audit_has_sent_email(tag: str, subject: str) -> bool:
    """Return True if audit already records a successful send for this logical email.

    Dedupe is keyed by tag/idempotency_key, not subject, because prematch
    batches can share one subject while representing different event groups.
    """
    tag_slug = slugify(tag)
    for path in sorted(AUDIT_DIR.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("action") != "email_send" or rec.get("status") != "ok":
                continue
            d = rec.get("details", {}) or {}
            if not d.get("sent"):
                continue
            mml_slug = slugify(Path(str(d.get("mml", ""))).stem)
            if d.get("idempotency_key") == tag or tag_slug in mml_slug:
                return True
    return False


def send_email(subject: str, html_path: Path, text: str, tag: str) -> Dict[str, Any]:
    html = html_path.read_text() if html_path.exists() else html_wrap(subject, text)
    mml_path = EMAIL_DIR / f"{today_wib()}-{tag}.mml"
    marker = _email_marker_path(tag)
    if marker.exists() or _audit_has_sent_email(tag, subject):
        result = {
            "sent": True,
            "deduped": True,
            "reason": "already_sent",
            "mml": str(mml_path),
            "html": str(html_path),
            "idempotency_key": tag,
        }
        audit("email_send", "deduped", {"subject": subject, **result})
        return result
    mml_path.write_text(mml_for(subject, html, text))
    if not HIMALAYA.exists():
        result = {"sent": False, "reason": "himalaya_missing", "mml": str(mml_path), "html": str(html_path), "idempotency_key": tag}
        audit("email_send", "skipped", result)
        return result
    proc = subprocess.run(
        [str(HIMALAYA), "template", "send"],
        input=mml_path.read_bytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ},  # NOTE: /Users/beem does not exist on LXC
        timeout=60,
    )
    result = {
        "sent": proc.returncode == 0,
        "deduped": False,
        "exit_code": proc.returncode,
        "output": proc.stdout.decode("utf-8", errors="replace")[-1000:],
        "mml": str(mml_path),
        "html": str(html_path),
        "idempotency_key": tag,
    }
    if result["sent"]:
        marker.write_text(json.dumps({"subject": subject, "tag": tag, "sent_at_wib": now_wib().isoformat(timespec="seconds"), "mml": str(mml_path)}, ensure_ascii=False, indent=2))
    audit("email_send", "ok" if result["sent"] else "error", {"subject": subject, **result})
    return result


def mark_initial_report_sent(date: str, send: bool = True) -> Dict[str, Any]:
    state = normalize_daily_state(date)
    text = render_plain_report_from_daily()
    html_path = EMAIL_DIR / f"{date}-48h-report.html"
    html_path.write_text(render_events_email_html(
        f"[SPORT SCAN] 48H Preview Report — {date}",
        text,
        list(state.get("events", {}).values()),
        state.get("no_event", []),
    ))
    email_result = {"sent": False, "reason": "not_requested"}
    if send:
        existing_report = state.get("reports", {}).get("initial_48h", {})
        if existing_report.get("email_sent"):
            email_result = {
                "sent": True,
                "deduped": True,
                "reason": "state_already_sent",
                "previous_result": existing_report.get("email_result", {}),
                "idempotency_key": f"{date}-48h-report",
            }
            audit("email_send", "deduped", {"subject": f"[SPORT SCAN] 48H Preview Report — {date}", **email_result}, date=date)
        else:
            email_result = send_email(f"[SPORT SCAN] 48H Preview Report — {date}", html_path, text[:3000], f"{date}-48h-report")
    state["reports"]["initial_48h"].update({
        "discord_sent": True,  # cron deliver status is external; mark after successful job run
        "discord_channel": DISCORD_CHANNEL,
        "email_sent": bool(email_result.get("sent")),
        "email_result": email_result,
        "marked_at_wib": now_wib().isoformat(timespec="seconds"),
    })
    save_state(date, state)
    audit("initial_report_marked", "ok", state["reports"]["initial_48h"])
    return email_result


def send_supplemental_48h(date: str) -> Dict[str, Any]:
    """Send a supplemental 48H report when late-discovered events (UTC spillover, etc.)
    need to be added to the already-sent daily report. Uses a distinct idempotency key
    (`YYYY-MM-DD-48h-supplemental`) so it does NOT collide with the original 48H key.
    """
    state = normalize_daily_state(date)
    events = list(state.get("events", {}).values())
    if not events:
        return {"sent": False, "reason": "no_events"}
    subject = f"[SPORT SCAN] 48H Preview Report — SUPPLEMENTAL — {date}"
    tag = f"{date}-48h-supplemental"
    text = render_plain_report_from_daily()
    html_path = EMAIL_DIR / f"{date}-48h-supplemental.html"
    html_path.write_text(render_events_email_html(subject, text, events, state.get("no_event", [])))
    email_result = send_email(subject, html_path, text[:3000], tag)
    audit("supplemental_48h_sent", "ok", {"subject": subject, **email_result}, date=date)
    return email_result


def due_prematch_events(date: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    n = now_wib()
    due = []
    for ev in state["events"].values():
        if ev.get("pre_match_alert_sent") or ev.get("status") in ["postponed", "cancelled", "research_backfill_required"]:
            continue
        kickoff = parse_wib(ev.get("kickoff_wib", ""))
        if not kickoff:
            continue
        mins = (kickoff - n).total_seconds() / 60
        if 45 <= mins <= 75:
            due.append(ev)
    return sorted(due, key=lambda e: e.get("kickoff_wib", ""))


def backfill_queue_events(date: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return events that need late research before kickoff.

    Eligibility is strict: if current time is already at/after kickoff, the event
    is made permanent NO_PREDICTION instead of researched.
    """
    n = now_wib()
    queued: List[Dict[str, Any]] = []
    changed = False
    for ev in state.get("events", {}).values():
        if ev.get("status") != "research_backfill_required":
            continue
        kickoff = parse_wib(ev.get("kickoff_wib", ""))
        if not kickoff or n >= kickoff:
            ev["status"] = "no_prediction"
            ev["prediction_eligible"] = False
            ev["prediction_ineligible_reason"] = "kickoff_passed_before_backfill"
            ev["validation"] = "NO_PREDICTION"
            ev["validation_status"] = "NO_PREDICTION"
            ev["accuracy_excluded"] = True
            ev["backfill_terminal"] = True
            changed = True
            continue
        queued.append(ev)
    if changed:
        save_state(date, state)
        audit("backfill_queue_expired", "ok", {"date": date})
    return sorted(queued, key=lambda e: e.get("kickoff_wib", ""))


def mark_backfill_alert_sent(date: str, event_id: str) -> None:
    state = load_state(date)
    ev = state.get("events", {}).get(event_id)
    if not ev:
        return
    ev["backfill_alert_sent"] = True
    ev["backfill_alert_sent_at_wib"] = now_wib().isoformat(timespec="seconds")
    save_state(date, state)
    audit("backfill_alert_marked", "ok", {"event_id": event_id}, date=date)


def record_backfill_attempt(date: str, event_id: str, success: bool, evidence_count: int = 0, reason: str = "") -> Dict[str, Any]:
    """Persist one backfill attempt in state and predictions JSON.

    A successful deterministic backfill writes a conservative NO_PICK prediction
    with research evidence attached. After 3 failed attempts before kickoff, the
    fixture is permanently excluded as NO_PREDICTION/backfill_failed.
    """
    state = load_state(date)
    ev = state.get("events", {}).get(event_id)
    if not ev:
        return {"ok": False, "reason": "event_not_found"}
    kickoff = parse_wib(ev.get("kickoff_wib", ""))
    if not kickoff or now_wib() >= kickoff:
        ev["status"] = "no_prediction"
        ev["prediction_eligible"] = False
        ev["prediction_ineligible_reason"] = "kickoff_passed_before_backfill"
        ev["validation"] = "NO_PREDICTION"
        ev["validation_status"] = "NO_PREDICTION"
        ev["accuracy_excluded"] = True
        save_state(date, state)
        return {"ok": False, "terminal": True, "reason": "kickoff_passed_before_backfill"}

    attempts = int(ev.get("backfill_attempts") or 0) + 1
    ev["backfill_attempts"] = attempts
    ev["last_backfill_attempt_at_wib"] = now_wib().isoformat(timespec="seconds")
    pred_path = PRED_DIR / f"{date}.json"
    pred_doc = read_json(pred_path, {}) or {}
    preds = pred_doc.get("predictions", []) if isinstance(pred_doc, dict) else []
    pred_row = None
    for row in preds:
        if event_key_from_prediction(row) == event_id or row.get("match_id") == event_id:
            pred_row = row
            break

    if success:
        ev["status"] = "scheduled"
        ev["backfill_status"] = "completed"
        ev["backfill_completed_at_wib"] = now_wib().isoformat(timespec="seconds")
        ev["prediction"] = {
            "outcome": "NO_PICK",
            "score_or_result": "insufficient late evidence for confident pick",
            "confidence_percent": 35,
            "risk_score_1_to_10": 8,
            "confidence_breakdown": default_confidence_breakdown(35),
            "confidence_label": "COIN FLIP",
            "no_pick": True,
        }
        ev["reasoning"] = [
            "Late fixture backfill completed before kickoff.",
            "Deterministic watcher gathered evidence but did not have enough time/context for a confident winner pick.",
            "NO_PICK preserves pre-match integrity and keeps event out of winner accuracy denominator.",
        ]
        if pred_row is not None:
            pred_row.update({
                "predicted_outcome": "NO_PICK",
                "predicted_score_or_result": "insufficient late evidence for confident pick",
                "confidence_percent": 35,
                "confidence_label": "COIN FLIP",
                "confidence_breakdown": default_confidence_breakdown(35),
                "risk_score_1_to_10": 8,
                "no_pick": True,
                "researched": True,
                "stub": False,
                "backfill_status": "completed",
                "backfill_attempts": attempts,
                "backfill_evidence_count": evidence_count,
                "reasoning": ev["reasoning"],
            })
            write_json(pred_path, pred_doc)
        save_state(date, state)
        audit("backfill_attempt", "ok", {"event_id": event_id, "attempts": attempts, "evidence_count": evidence_count}, date=date)
        return {"ok": True, "attempts": attempts, "status": "completed"}

    if attempts >= 3:
        ev["status"] = "backfill_failed"
        ev["prediction_eligible"] = False
        ev["prediction_ineligible_reason"] = "backfill_failed"
        ev["validation"] = "NO_PREDICTION"
        ev["validation_status"] = "NO_PREDICTION"
        ev["accuracy_excluded"] = True
        ev["backfill_status"] = "failed"
        if pred_row is not None:
            pred_row.update({
                "prediction_eligible": False,
                "prediction_ineligible_reason": "backfill_failed",
                "validation": "NO_PREDICTION",
                "validation_status": "NO_PREDICTION",
                "accuracy_excluded": True,
                "no_pick": True,
                "backfill_status": "failed",
                "backfill_attempts": attempts,
                "backfill_failure_reason": reason or "research_failed",
            })
            write_json(pred_path, pred_doc)
    save_state(date, state)
    audit("backfill_attempt", "failed", {"event_id": event_id, "attempts": attempts, "reason": reason}, date=date)
    return {"ok": False, "attempts": attempts, "status": ev.get("status"), "reason": reason}


def expected_finished_events(date: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    n = now_wib()
    due = []
    for ev in state["events"].values():
        if ev.get("post_match_report_sent") or ev.get("status") in ["completed", "postponed", "cancelled", "no_prediction", "backfill_failed"]:
            continue
        kickoff = parse_wib(ev.get("kickoff_wib", ""))
        if not kickoff:
            continue
        duration = DEFAULT_DURATIONS_MIN.get(ev.get("sport"), 150)
        if n >= kickoff + timedelta(minutes=duration):
            next_retry = parse_wib(ev.get("next_result_retry_after_wib") or "")
            if next_retry and n < next_retry:
                continue
            due.append(ev)
    return sorted(due, key=lambda e: e.get("kickoff_wib", ""))


def render_prematch_text(events: List[Dict[str, Any]]) -> str:
    lines = ["⚡ PRE-MATCH ALERT — 1 JAM LAGI!", ""]
    for ev in events:
        pred = ev.get("prediction", {})
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"{ev.get('sport','').upper()} — {ev.get('competition','')}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 {ev.get('kickoff_wib','')} WIB",
            f"🆚 {ev.get('event','')}",
            f"🎯 Prediksi : {pred.get('outcome')} {pred.get('score_or_result')}",
            f"📈 Confidence: {pred.get('confidence_percent')}% · Risk: {pred.get('risk_score_1_to_10')}/10",
            "🔄 Update   : Pending latest web re-check by agent ✅",
            "",
        ]
    return "\n".join(lines)


def mark_prematch_sent(date: str, event_ids: List[str], note: str = "") -> str:
    state = load_state(date)
    selected = [state["events"][eid] for eid in event_ids if eid in state.get("events", {})]
    if not selected:
        return "No selected prematch events."
    text = render_prematch_text(selected)
    tag = f"{date}-prematch-{slugify('-'.join(event_ids))[:40]}"
    html_path = EMAIL_DIR / f"{tag}.html"
    html_path.write_text(render_events_email_html("[PRE-MATCH] 1 Jam Lagi", text, selected, []))
    email_result = send_email(f"[PRE-MATCH] Sport Scanning AI — {date}", html_path, text, tag)
    for ev in selected:
        ev["pre_match_alert_sent"] = True
        ev["pre_match_checked_at_wib"] = now_wib().isoformat(timespec="seconds")
        ev["pre_match_note"] = note
        ev["pre_match_email_sent"] = bool(email_result.get("sent"))
    save_state(date, state)
    audit("prematch_marked", "ok", {"event_ids": event_ids, "email": email_result})
    return text


def mark_result_pending(date: str, event_id: str) -> Dict[str, Any]:
    state = load_state(date)
    ev = state["events"][event_id]
    ev["result_retry_count"] = int(ev.get("result_retry_count") or 0) + 1
    ev["result_pending_newly_notified"] = False
    if ev["result_retry_count"] >= 12:
        if not ev.get("result_pending_notified"):
            ev["result_pending_newly_notified"] = True
        ev["result_pending_notified"] = True
        ev["status"] = "result_pending_after_60m"
        ev["next_result_retry_after_wib"] = (now_wib() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
        # Email is intentionally batched by sports_v31_watch.py once per hour.
        # Do not send per-match RESULT PENDING email from this per-event retry path.
        ev["result_pending_email_sent"] = False
    save_state(date, state)
    audit("result_retry", "ok", {"event_id": event_id, "retry_count": ev["result_retry_count"], "status": ev.get("status"), "result_pending_newly_notified": ev.get("result_pending_newly_notified")})
    return ev


def complete_result(date: str, event_id: str, actual_result: str, winner: str, status: str, lessons: str = "", send_email_report: bool = True) -> str:
    state = load_state(date)
    ev = state["events"].get(event_id)
    if not ev:
        raise SystemExit(f"Unknown event_id: {event_id}")
    pred = ev.get("prediction", {}) or {}
    if is_blank_prediction(pred):
        ev["status"] = "completed"
        ev["actual_result"] = actual_result
        ev["actual_winner"] = winner
        ev["validation"] = "NO_PREDICTION"
        ev["lesson_learnt"] = lessons or "Result captured, but normal validation was blocked because the event had no stored pre-match prediction. Exclude from accuracy denominator."
        ev["lesson_json"] = build_lesson_json(ev, factors_missed=["missing_pre_match_prediction"], pattern_tags=["prediction_missing_before_result_capture"], postmortem=ev["lesson_learnt"])
        ev["result_captured_at_wib"] = now_wib().isoformat(timespec="seconds")
        ev["post_match_report_sent"] = False
        ev["result_capture_blocked"] = True
        ev["result_capture_block_reason"] = "missing_prediction_preflight"
        save_state(date, state)
        audit("result_capture_blocked_no_prediction", "blocked", {"event_id": event_id, "event": ev.get("event"), "actual_result": actual_result, "winner": winner}, date=date)
        return "\n".join([
            "⚠️ RESULT CAPTURE BLOCKED — NO_PREDICTION",
            "",
            f"📅 {ev.get('kickoff_wib')} WIB",
            f"🆚 {ev.get('event')}",
            f"✅ Actual Result : {winner} {actual_result}",
            "🎯 Prediksi      : MISSING",
            "🎖️ Status        : NO_PREDICTION",
            "",
            "Normal post-match validation/email was blocked because no pre-match prediction existed for this event.",
        ])
    ev["status"] = "completed"
    ev["actual_result"] = actual_result
    ev["actual_winner"] = winner
    ev["validation"] = status or validation_status_v32(ev, actual_result, winner)
    ev["lesson_learnt"] = lessons
    ev["lesson_json"] = build_lesson_json(ev, factors_missed=[] if ev.get("validation") == "BENAR" else [lessons or "Outcome variance exceeded model expectation"], pattern_tags=[] if ev.get("validation") == "BENAR" else ["tactical_surprise"], postmortem=lessons)
    ev["result_captured_at_wib"] = now_wib().isoformat(timespec="seconds")
    ev["post_match_report_sent"] = True
    pred = ev.get("prediction", {})
    text = "\n".join([
        "🏁 POST-MATCH RESULT", "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{ev.get('sport','').upper()} — {ev.get('competition','')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 {ev.get('kickoff_wib')} WIB",
        f"🆚 {ev.get('event')}",
        f"🎯 Prediksi      : {pred.get('outcome')} {pred.get('score_or_result')} | {pred.get('confidence_percent')}%",
        f"✅ Actual Result : {winner} {actual_result}",
        f"🎖️ Status        : {ev.get('validation')}", "",
        "💡 Lesson Learnt:",
        f"• {lessons or 'No durable lesson extracted.'}",
    ])
    tag = f"{date}-postmatch-{event_id[:40]}"
    html_path = EMAIL_DIR / f"{tag}.html"
    if send_email_report:
        html_path.write_text(render_postmatch_email_html(ev, text))
        email_result = send_email(f"[POST-MATCH] {ev.get('event')} — Hasil & Analisis | {date}", html_path, text, tag)
        ev["post_match_email_sent"] = bool(email_result.get("sent"))
    else:
        email_result = {"sent": False, "reason": "batched_hourly"}
        ev["post_match_email_sent"] = False
        ev["post_match_email_batch_pending"] = True
    save_state(date, state)
    audit("result_completed", "ok", {"event_id": event_id, "email": email_result})
    return text


def eod_guard_status(state: Dict[str, Any]) -> Dict[str, Any]:
    events = list((state or {}).get("events", {}).values())
    if not events:
        return {"ready": False, "mode": "none", "reason": "no_events", "pending_count": 0}
    if (state.get("reports", {}).get("eod", {}) or {}).get("email_sent"):
        return {"ready": False, "mode": "deduped", "reason": "eod_sent", "pending_count": 0}
    terminal_final = {"completed", "postponed", "cancelled"}
    unresolved = [e for e in events if e.get("status") not in terminal_final]
    result_pending = [e for e in events if e.get("status") == "result_pending_after_60m"]
    if not unresolved:
        return {"ready": True, "mode": "final", "reason": "all_results_captured", "pending_count": 0}
    if result_pending:
        return {"ready": False, "mode": "blocked", "reason": "result_pending_unresolved", "pending_count": len(unresolved)}
    kickoffs = [parse_wib(e.get("kickoff_wib", "")) for e in events]
    kickoffs = [k for k in kickoffs if k]
    last = max(kickoffs) if kickoffs else None
    if last and now_wib() >= last + timedelta(hours=3):
        return {"ready": True, "mode": "partial", "reason": "last_kickoff_plus_3h", "pending_count": len(unresolved), "last_kickoff_wib": last.strftime("%Y-%m-%d %H:%M")}
    return {"ready": False, "mode": "not_ready", "reason": "matches_pending", "pending_count": len(unresolved), "last_kickoff_wib": last.strftime("%Y-%m-%d %H:%M") if last else None}


def eod_ready(state: Dict[str, Any]) -> bool:
    return bool(eod_guard_status(state).get("ready"))


def render_eod(date: str, state: Dict[str, Any]) -> str:
    events = list(state.get("events", {}).values())
    completed = [e for e in events if e.get("status") == "completed"]
    correct = [e for e in completed if "BENAR" in str(e.get("validation", "")) and "SEBAGIAN" not in str(e.get("validation", ""))]
    partial = [e for e in completed if "SEBAGIAN" in str(e.get("validation", ""))]
    wrong = [e for e in completed if "SALAH" in str(e.get("validation", ""))]
    lines = [f"🌙 END OF DAY REPORT — {date}", "", "━━━━━━━━━━━━━━━━━━━━━━━━", "📊 REKAP SEMUA PERTANDINGAN HARI INI", "━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for sport in SPORTS:
        lines.append(f"{sport.upper()}")
        sport_events = [e for e in events if e.get("sport") == sport]
        if not sport_events:
            lines.append("• Tidak ada")
        for e in sport_events:
            pred = e.get("prediction", {})
            lines.append(f"• {e.get('event')} → Prediksi: {pred.get('score_or_result')} | Actual: {e.get('actual_result') or '-'} | {e.get('validation') or e.get('status')}")
        lines.append("")
    no_pick = [e for e in events if is_no_pick_prediction((e.get("prediction") or {}))]
    no_prediction = [e for e in completed if str(e.get("validation") or "") == "NO_PREDICTION"]
    total = len([e for e in completed if not is_no_pick_prediction((e.get("prediction") or {})) and str(e.get("validation") or "") != "NO_PREDICTION"])
    acc = (len(correct) / total * 100) if total else 0
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━", "📈 AKURASI HARI INI", "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 Prediksi Pemenang : {len(correct)}/{total} ({acc:.1f}%)",
        f"⚠️ Sebagian benar     : {len(partial)}",
        f"❌ Salah              : {len(wrong)}",
        f"📵 No Pick            : {len(no_pick)}", "",
        "━━━━━━━━━━━━━━━━━━━━━━━━", "🧠 MACHINE LEARNING UPDATE", "━━━━━━━━━━━━━━━━━━━━━━━━",
        "Pola kesalahan ditemukan hari ini:",
        "• Akan diperbarui dari lesson learnt post-match yang sudah selesai.",
        "Model Mnemosyne: ✅ Updated when durable lessons exist",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔄 Scan berikutnya: Besok 00.01 WIB",
    ]
    return "\n".join(lines)


def maybe_send_eod(date: str) -> Dict[str, Any]:
    state = load_state(date)
    guard = eod_guard_status(state)
    if not guard.get("ready"):
        pending = [e.get("event") for e in state.get("events", {}).values() if e.get("status") not in {"completed", "postponed", "cancelled"}]
        audit("eod_check", "not_ready", {"guard": guard, "pending": pending[:20], "count": len(pending)})
        return {"sent": False, "reason": guard.get("reason"), "pending_count": len(pending), "guard": guard}
    mode = guard.get("mode") or "final"
    report_key = "eod_partial" if mode == "partial" else "eod"
    if (state.get("reports", {}).get(report_key, {}) or {}).get("email_sent"):
        return {"sent": False, "reason": "already_sent", "guard": guard}
    update_weight_adjustments_from_lessons(date)
    text = render_eod(date, state)
    if mode == "partial":
        text = "⏳ EOD PARTIAL — pending results unresolved\n\n" + text
    md_path = EOD_DIR / f"{date}{'-partial' if mode == 'partial' else ''}.md"
    md_path.write_text(text)
    html_path = EMAIL_DIR / f"{date}-{'eod-partial' if mode == 'partial' else 'eod'}.html"
    html_path.write_text(render_eod_email_html(date, state, text))
    tag = f"{date}-{'eod-partial' if mode == 'partial' else 'eod'}"
    subj = f"[END OF DAY{' PARTIAL' if mode == 'partial' else ''}] Sport Scan Summary — {date}"
    email_result = send_email(subj, html_path, text, tag)
    state.setdefault("reports", {})[report_key] = {"discord_sent": True, "email_sent": bool(email_result.get("sent")), "email_result": email_result, "sent_at_wib": now_wib().isoformat(timespec="seconds"), "guard": guard}
    save_state(date, state)
    audit("eod_sent" if mode != "partial" else "eod_partial_sent", "ok", state["reports"][report_key])
    return email_result


def read_audit_records(date: str) -> List[Dict[str, Any]]:
    path = AUDIT_DIR / f"{date}.jsonl"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def reconcile_from_audit(date: str) -> Dict[str, Any]:
    """Repair state flags from deterministic audit log without resending anything."""
    state = load_state(date)
    changed: List[str] = []
    for rec in read_audit_records(date):
        if rec.get("status") != "ok":
            continue
        action = rec.get("action")
        details = rec.get("details", {}) or {}
        if action == "initial_report_marked":
            state.setdefault("reports", {}).setdefault("initial_48h", {}).update(details)
            changed.append("initial_48h")
        elif action == "prematch_marked":
            email_sent = bool((details.get("email") or {}).get("sent"))
            for eid in details.get("event_ids", []) or []:
                ev = state.get("events", {}).get(eid)
                if ev:
                    ev["pre_match_alert_sent"] = True
                    ev["pre_match_email_sent"] = email_sent
                    changed.append(f"prematch:{eid}")
        elif action == "result_completed":
            eid = details.get("event_id")
            ev = state.get("events", {}).get(eid)
            if ev:
                ev["post_match_report_sent"] = True
                ev["post_match_email_sent"] = bool((details.get("email") or {}).get("sent"))
                if ev.get("actual_result"):
                    ev["status"] = "completed"
                changed.append(f"postmatch:{eid}")
        elif action == "eod_sent":
            state.setdefault("reports", {})["eod"] = details
            changed.append("eod")
    save_state(date, state)
    audit("reconcile", "ok", {"date": date, "changed_count": len(changed), "changed": changed[:30]}, date=date)
    return {"date": date, "changed_count": len(changed), "changed": changed[:30]}


def consistency_check(date: str, state: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    events = state.get("events", {})
    for eid, ev in events.items():
        if ev.get("status") == "completed":
            pred = ev.get("prediction") or {}
            if str(ev.get("validation") or "") != "NO_PREDICTION" and pred.get("outcome") in (None, "", "—") and pred.get("score_or_result") in (None, "", "—"):
                errors.append(f"completed_missing_prediction_outcome_and_score:{eid}")
            for k in ["actual_result", "actual_winner", "validation", "result_captured_at_wib"]:
                if not ev.get(k):
                    errors.append(f"completed_missing_{k}:{eid}")
            if not ev.get("post_match_report_sent") and str(ev.get("validation") or "") != "NO_PREDICTION":
                errors.append(f"completed_without_postmatch_report:{eid}")
            if not ev.get("post_match_email_sent") and str(ev.get("validation") or "") != "NO_PREDICTION":
                warnings.append(f"completed_without_postmatch_email:{eid}")
            if not isinstance(ev.get("lesson_json"), dict):
                warnings.append(f"completed_missing_lesson_json:{eid}")
        if ev.get("status") not in {"completed", "postponed", "cancelled"}:
            normalize_prediction_v32(ev)
            pred = ev.get("prediction") or {}
            if is_no_pick_prediction(pred):
                try:
                    if float(pred.get("confidence_percent")) >= 40:
                        errors.append(f"no_pick_confidence_not_below_40:{eid}")
                except Exception:
                    errors.append(f"no_pick_missing_confidence:{eid}")
            else:
                for k in ["outcome", "score_or_result", "confidence_percent", "risk_score_1_to_10"]:
                    if pred.get(k) in (None, "", "—"):
                        errors.append(f"upcoming_missing_prediction_{k}:{eid}")
            if not pred.get("confidence_breakdown"):
                errors.append(f"upcoming_missing_confidence_breakdown:{eid}")
            if pred.get("confidence_label") != confidence_label(pred.get("confidence_percent")):
                errors.append(f"upcoming_bad_confidence_label:{eid}")
            if ev.get("DATA_SOURCE_DEGRADED") and pred.get("confidence_penalty_applied") != -15:
                errors.append(f"degraded_without_penalty:{eid}")
            if not ev.get("reasoning"):
                errors.append(f"upcoming_missing_reasoning:{eid}")
        if ev.get("pre_match_alert_sent") and ev.get("pre_match_email_sent") is False:
            warnings.append(f"prematch_without_email:{eid}")
        retry_count = int(ev.get("result_retry_count") or 0)
        if retry_count > 12 and ev.get("status") not in {"result_pending_after_60m", "no_prediction", "backfill_failed", "completed", "postponed", "cancelled"}:
            errors.append(f"retry_count_exceeded_without_pending_state:{eid}")
    reports = state.get("reports", {})
    if not reports.get("initial_48h", {}).get("discord_sent"):
        warnings.append("initial_48h_discord_not_marked_in_state")
    if not reports.get("initial_48h", {}).get("email_sent"):
        warnings.append("initial_48h_email_not_marked_in_state")
    return errors, warnings


def validate(date: str) -> Tuple[bool, List[str]]:
    ensure_dirs()
    errors: List[str] = []
    warnings: List[str] = []
    required_dirs = [SCHEDULE_DIR, PRED_DIR, STATE_DIR, EMAIL_DIR, AUDIT_DIR, EOD_DIR]
    for d in required_dirs:
        if not d.exists():
            errors.append(f"missing_dir:{d}")
    state_path = STATE_DIR / f"{date}.json"
    if not state_path.exists():
        warnings.append("state_not_initialized")
    pred_path = PRED_DIR / f"{date}.json"
    sched_path = SCHEDULE_DIR / f"{date}.json"
    if not pred_path.exists():
        warnings.append("today_predictions_missing")
    if not sched_path.exists():
        warnings.append("today_schedule_missing")
    if not HIMALAYA.exists():
        errors.append("himalaya_missing")
    state = load_state(date)
    c_errors, c_warnings = consistency_check(date, state)
    errors.extend(c_errors)
    warnings.extend(c_warnings)
    ok = not errors
    messages = [f"OK={ok}", *[f"ERROR:{e}" for e in errors], *[f"WARN:{w}" for w in warnings]]
    audit("validate", "ok" if ok else "error", {"date": date, "errors": errors, "warnings": warnings}, date=date)
    return ok, messages


def status(date: str) -> Dict[str, Any]:
    state = load_state(date)
    events = list(state.get("events", {}).values())
    by_status: Dict[str, int] = {}
    for e in events:
        by_status[e.get("status", "unknown")] = by_status.get(e.get("status", "unknown"), 0) + 1
    return {
        "date": date,
        "events": len(events),
        "by_status": by_status,
        "due_prematch": len(due_prematch_events(date, state)),
        "due_result": len(expected_finished_events(date, state)),
        "reports": state.get("reports", {}),
        "eod_guard": eod_guard_status(state),
        "state_file": str(STATE_DIR / f"{date}.json"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["init", "send-initial", "prematch-due", "backfill-queue", "mark-prematch", "result-due", "mark-pending", "complete-result", "eod", "validate", "status", "reconcile"])
    parser.add_argument("--date", default=today_wib())
    parser.add_argument("--event-id")
    parser.add_argument("--event-ids", nargs="*")
    parser.add_argument("--actual-result", default="")
    parser.add_argument("--winner", default="")
    parser.add_argument("--validation", default="")
    parser.add_argument("--lesson", default="")
    parser.add_argument("--no-send", action="store_true", help="For send-initial: mark existing report without sending email again")
    args = parser.parse_args(argv)
    ensure_dirs()

    if args.mode == "init":
        st = normalize_daily_state(args.date)
        print(json.dumps(status(args.date), indent=2, ensure_ascii=False))
    elif args.mode == "send-initial":
        res = mark_initial_report_sent(args.date, send=(not args.no_send))
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif args.mode == "prematch-due":
        st = normalize_daily_state(args.date)
        print(json.dumps(due_prematch_events(args.date, st), indent=2, ensure_ascii=False))
    elif args.mode == "backfill-queue":
        st = normalize_daily_state(args.date)
        print(json.dumps(backfill_queue_events(args.date, st), indent=2, ensure_ascii=False))
    elif args.mode == "mark-prematch":
        ids = args.event_ids or ([args.event_id] if args.event_id else [])
        print(mark_prematch_sent(args.date, ids))
    elif args.mode == "result-due":
        st = normalize_daily_state(args.date)
        print(json.dumps(expected_finished_events(args.date, st), indent=2, ensure_ascii=False))
    elif args.mode == "mark-pending":
        if not args.event_id:
            raise SystemExit("--event-id required")
        print(json.dumps(mark_result_pending(args.date, args.event_id), indent=2, ensure_ascii=False))
    elif args.mode == "complete-result":
        if not args.event_id:
            raise SystemExit("--event-id required")
        print(complete_result(args.date, args.event_id, args.actual_result, args.winner, args.validation, args.lesson))
    elif args.mode == "eod":
        print(json.dumps(maybe_send_eod(args.date), indent=2, ensure_ascii=False))
    elif args.mode == "validate":
        ok, messages = validate(args.date)
        print("\n".join(messages))
        return 0 if ok else 2
    elif args.mode == "reconcile":
        print(json.dumps(reconcile_from_audit(args.date), indent=2, ensure_ascii=False))
    elif args.mode == "status":
        print(json.dumps(status(args.date), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
