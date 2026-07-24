#!/usr/bin/env python3
"""Sport Scanning AI v3.2 explicit watcher for Steps 4-8.

Runs every 5 minutes. Uses deterministic engine for state/email dedupe and
Hermes CLI for Discord delivery.

Flow:
- Step 4/5: detect H-1 prematch events, re-search via SearXNG, send Discord,
  then call engine mark-prematch for HTML email + state flags.
- Step 6/7: detect result-due events, query ESPN structured scoreboard +
  SearXNG evidence, call engine complete-result or mark-pending, send Discord.
- Step 8: when all events terminal, call engine eod and send EOD Discord.

The engine remains source of truth for email idempotency and state flags.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from html import escape
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WIB = timezone(timedelta(hours=7))
ROOT = Path("/opt/sport-prediction/current/engine/data")
ENGINE_PATH = Path("/opt/sport-prediction/current/engine/scripts/sports_v3_engine.py")
SEARXNG_URL = "http://10.10.10.5:8888"
DISCORD_TARGET = "discord:1515327116189630526"
OUTBOX = ROOT / "discord-outbox"
OUTBOX.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("sports_v3_engine", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(engine)  # type: ignore


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().date().isoformat()


def audit(action: str, status: str, details: Dict[str, Any], date: Optional[str] = None) -> None:
    engine.audit(action, status, {"module": "sports_v31_watch", **details}, date=date or today_wib())


def hermes_send(text: str, tag: str) -> Dict[str, Any]:
    import shutil
    path = OUTBOX / f"{tag}.txt"
    path.write_text(text)
    if shutil.which("hermes") is None:
        # hermes CLI not available (LXC host) — write to outbox only, skip delivery
        result = {"sent": False, "exit_code": -1, "output": "hermes not found — saved to outbox only", "file": str(path)}
        audit("discord_send", "skipped_no_hermes", {"tag": tag, **result})
        return result
    proc = subprocess.run(
        ["hermes", "send", "--quiet", "--to", DISCORD_TARGET, "--file", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        env={**os.environ},  # NOTE: /Users/beem does not exist on LXC
    )
    result = {"sent": proc.returncode == 0, "exit_code": proc.returncode, "output": proc.stdout[-500:], "file": str(path)}
    audit("discord_send", "ok" if result["sent"] else "error", {"tag": tag, **result})
    return result


def searxng_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    params = {"q": query, "format": "json", "language": "en", "safesearch": 0}
    url = f"{SEARXNG_URL}/search?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-SportWatcher/3.2"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        out = []
        seen = set()
        for item in data.get("results", []) or []:
            u = item.get("url")
            if not u or u in seen:
                continue
            seen.add(u)
            out.append({"title": item.get("title"), "url": u, "snippet": item.get("content"), "engine": item.get("engine")})
            if len(out) >= limit:
                break
        return out
    except Exception as exc:
        audit("searxng_watch_failed", "error", {"query": query, "error": str(exc)[:200]})
        return []


def render_backfill_alert(ev: Dict[str, Any]) -> str:
    return "\n".join([
        f"⚠️ BACKFILL REQUIRED: {ev.get('event')} — kickoff {ev.get('kickoff_wib')} WIB, research belum ada",
        "",
        f"Sport: {ev.get('sport','unknown')}",
        f"Competition: {ev.get('competition','')}",
        "Policy: only backfill before kickoff; after kickoff becomes permanent NO_PREDICTION.",
    ])


def _research_hit_count(r: Any) -> int:
    if isinstance(r, list):
        return len(r)
    if isinstance(r, dict):
        return sum(len(src.get("hits") or []) for src in (r.get("by_source") or {}).values())
    return 0


def run_backfill_queue(date: str) -> int:
    """Process late-discovered fixture stubs before the H-1 prematch monitor."""
    state = engine.normalize_daily_state(date)
    queue = engine.backfill_queue_events(date, state)
    if not queue:
        return 0
    acted = 0
    try:
        from sports_v31_espn_ingest import multi_source_research
    except ImportError:
        multi_source_research = None
    for ev in queue:
        if not ev.get("backfill_alert_sent"):
            hermes_send(render_backfill_alert(ev), f"{date}-backfill-required-{ev['event_id'][:30]}")
            engine.mark_backfill_alert_sent(date, ev["event_id"])
            acted += 1
        kickoff = engine.parse_wib(ev.get("kickoff_wib", ""))
        if not kickoff:
            engine.record_backfill_attempt(date, ev["event_id"], False, reason="invalid_kickoff")
            acted += 1
            continue
        mins_to_kickoff = (kickoff - now_wib()).total_seconds() / 60
        if mins_to_kickoff <= 30:
            audit("backfill_waiting_too_close", "skipped", {"event_id": ev.get("event_id"), "minutes_to_kickoff": mins_to_kickoff}, date=date)
            continue
        if int(ev.get("backfill_attempts") or 0) >= 3:
            continue
        research = None
        if multi_source_research:
            try:
                research = multi_source_research(ev, timeout=12)
            except Exception as exc:
                audit("backfill_research_error", "error", {"event_id": ev.get("event_id"), "error": str(exc)[:200]}, date=date)
        if research is None:
            q = f"{ev.get('event')} {ev.get('competition')} preview injury lineup form"
            research = {"by_source": {"general": {"hits": searxng_search(q, 5)}}}
        hits = _research_hit_count(research)
        result = engine.record_backfill_attempt(date, ev["event_id"], hits > 0, evidence_count=hits, reason="no_research_hits")
        audit("backfill_queue_processed", "ok" if result.get("ok") else "failed", {"event_id": ev.get("event_id"), "hits": hits, "result": result}, date=date)
        acted += 1
    return acted


def render_prematch_with_research(events: List[Dict[str, Any]], research: Dict[str, Any]) -> str:
    """Render prematch alert. `research` accepts either:
       - flat list of SearXNG hits (legacy), OR
       - dict with `by_source` (new 5-source matrix).
    """
    def _flatten(r: Any) -> List[Dict[str, Any]]:
        if isinstance(r, list):
            return r
        if isinstance(r, dict):
            flat = []
            for src_key, src in (r.get("by_source") or {}).items():
                for h in (src.get("hits") or []):
                    flat.append({**h, "source": src_key})
            return flat
        return []

    lines = ["⚡ PRE-MATCH ALERT — 1 JAM LAGI!", ""]
    for ev in events:
        pred = ev.get("prediction", {}) or {}
        hits = _flatten(research.get(ev["event_id"]))
        update_line = "Tidak Berubah ✅"
        status_hit = next((h for h in hits if re.search(r"postponed|cancelled|delayed", (h.get("title") or "") + " " + (h.get("snippet") or ""), re.I)), None)
        if status_hit:
            update_line = f"Potential status signal ⚠️ — {status_hit.get('title','')[:90]}"
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⚽ {ev.get('competition','')}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 {ev.get('kickoff_wib','')} WIB",
            f"🆚 {ev.get('event','')}",
            f"🎯 Prediksi : {pred.get('outcome')} {pred.get('score_or_result')}",
            f"📈 Confidence: {pred.get('confidence_percent')}% ({pred.get('confidence_label') or engine.confidence_label(pred.get('confidence_percent'))}) | Risk: {pred.get('risk_score_1_to_10')}/10",
            f"🔄 Update   : {update_line}",
            "📝 Latest evidence (5-source):",
        ]
        for h in hits[:3]:
            src_tag = f"[{h.get('source','?')}]" if h.get("source") else ""
            lines.append(f"• {src_tag} {str(h.get('title') or '')[:110]}")
        if not hits:
            lines.append("• No new SearXNG evidence; original prediction retained.")
        lines.append("")
    return "\n".join(lines).strip()


def run_prematch(date: str) -> int:
    state = engine.normalize_daily_state(date)
    due = engine.due_prematch_events(date, state)
    if not due:
        return 0
    # Batch events within 15 minutes; current due function already returns H-1 window.
    # v3.1: Use 5-source research matrix for richer H-1 re-check.
    research: Dict[str, Dict[str, Any]] = {}
    try:
        from sports_v31_espn_ingest import multi_source_research
    except ImportError:
        multi_source_research = None
    for ev in due:
        if multi_source_research:
            try:
                r = multi_source_research(ev, timeout=12)
                research[ev["event_id"]] = r
                # Flatten hits for backwards-compatible display path
                flat = []
                for src_key, src in (r.get("by_source") or {}).items():
                    for h in (src.get("hits") or []):
                        flat.append(h)
                ev["pre_match_research"] = flat
                ev["pre_match_research_by_source"] = r
                ev["pre_match_research_query"] = (r.get("queries_run") or [{}])[0].get("query", "")
            except Exception:
                research[ev["event_id"]] = {"hits": []}
                ev["pre_match_research"] = searxng_search(
                    f"{ev.get('event')} {ev.get('competition')} lineup injury weather postponed cancelled", 5
                )
                ev["pre_match_research_query"] = "fallback"
        else:
            q = f"{ev.get('event')} {ev.get('competition')} lineup injury weather postponed cancelled"
            research[ev["event_id"]] = {"by_source": {"general": {"hits": searxng_search(q, 5)}}}
            ev["pre_match_research"] = searxng_search(q, 5)
            ev["pre_match_research_query"] = q
    text = render_prematch_with_research(due, research)
    hermes_send(text, f"{date}-prematch-{'-'.join(e['event_id'][:12] for e in due)}")
    note = "5-source SearXNG H-1 research performed; see audit/state for evidence."
    # engine sends HTML email + flags state
    engine.mark_prematch_sent(date, [e["event_id"] for e in due], note=note)
    return len(due)


def _hour_key() -> str:
    return now_wib().strftime("%Y%m%d%H")


def _sport_color(sport: str) -> str:
    return (engine.SPORT_META.get((sport or "unknown").lower(), engine.SPORT_META["unknown"])[1])


def _email_shell(title: str, inner_html: str) -> str:
    # Gmail mobile dark mode aggressively rewrites semi-transparent rgba() header
    # pills into light gray blocks, which makes white title rules render as dark
    # / low-contrast text. Use solid dark pills with explicit bgcolor + inline
    # color on nested spans, matching the older readable batch header style.
    generated = now_wib().strftime('%Y-%m-%d %H:%M WIB')
    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta charset="utf-8"></head>
<body style="margin:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827;">
  <div style="max-width:760px;margin:0 auto;padding:14px;">
    <div style="background:#0f172a;background-image:linear-gradient(135deg,#020617 0%,#0f172a 45%,#1d4ed8 100%);border-radius:18px;padding:28px 28px;margin-bottom:14px;box-shadow:0 10px 24px rgba(2,6,23,.25);">
      <div bgcolor="#202124" style="display:inline-block;background:#202124 !important;border:2px solid #374151;border-radius:999px;padding:9px 18px;margin-bottom:18px;color:#ffffff !important;font-size:13px;line-height:1.2;letter-spacing:.10em;text-transform:uppercase;font-weight:900 !important;text-shadow:0 2px 4px rgba(0,0,0,1), 0 0 8px rgba(0,0,0,0.9) !important;"><span style="color:#ffffff !important;">SPORT SCANNING AI V3.2</span></div>
      <div style="line-height:12px;font-size:12px;">&nbsp;</div>
      <div bgcolor="#202124" style="display:inline-block;background:#202124 !important;border:2px solid #374151;border-radius:14px;padding:16px 24px;color:#ffffff !important;font-size:28px;line-height:1.18;font-weight:900 !important;text-shadow:0 2px 4px rgba(0,0,0,1), 0 0 8px rgba(0,0,0,0.9) !important;"><span style="color:#ffffff !important;font-weight:900 !important;">{escape(title)}</span></div>
      <div style="line-height:18px;font-size:18px;">&nbsp;</div>
      <div bgcolor="#202124" style="display:inline-block;background:#202124 !important;border:2px solid #374151;border-radius:999px;padding:10px 18px;color:#ffffff !important;font-size:13px;line-height:1.2;font-weight:900 !important;text-shadow:0 2px 4px rgba(0,0,0,1), 0 0 8px rgba(0,0,0,0.9) !important;"><span style="color:#ffffff !important;font-weight:900 !important;">Generated {generated}</span></div>
    </div>
    {inner_html}
    <div style="font-size:11px;color:#64748b;text-align:center;margin:18px 0 4px;">Probabilistic sports analysis · No betting recommendation · WIB timezone</div>
  </div>
</body></html>"""


def _summary_box(items: Dict[str, Any]) -> str:
    cells = []
    for k, v in items.items():
        cells.append(f"<div style='display:inline-block;vertical-align:top;min-width:145px;margin:5px;padding:11px 13px;border-radius:14px;background:#eff6ff;border:1px solid #bfdbfe;'><div style='font-size:11px;color:#475569;text-transform:uppercase;font-weight:800;letter-spacing:.04em;'>{escape(str(k))}</div><div style='font-size:20px;font-weight:900;color:#0f172a;margin-top:3px;'>{escape(str(v))}</div></div>")
    return "<div style='background:#ffffff;border-radius:16px;padding:12px;margin-bottom:14px;border:1px solid #e5e7eb;box-shadow:0 1px 4px rgba(15,23,42,.06);'>" + "".join(cells) + "</div>"


def render_result_pending_batch_html(date: str, events: List[Dict[str, Any]]) -> str:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in sorted(events, key=lambda e: (e.get("sport", ""), e.get("kickoff_wib", ""), e.get("event", ""))):
        grouped[ev.get("sport", "unknown")].append(ev)
    inner = _summary_box({
        "Tanggal": date,
        "Generated": now_wib().strftime('%H:%M WIB'),
        "Pending matches": len(events),
    })
    for sport in engine.SPORTS + sorted(set(grouped) - set(engine.SPORTS)):
        rows = grouped.get(sport) or []
        if not rows:
            continue
        color = _sport_color(sport)
        label = engine.SPORT_META.get(sport, (sport.upper(), color))[0]
        table_rows = "".join(
            "<tr>"
            f"<td style='padding:9px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#0f172a;'>{escape(str(ev.get('kickoff_wib','')))} WIB</td>"
            f"<td style='padding:9px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#0f172a;'>{escape(str(ev.get('competition','')))}</td>"
            f"<td style='padding:9px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#0f172a;font-weight:700;'>{escape(str(ev.get('event','')))}</td>"
            f"<td style='padding:9px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#0f172a;text-align:center;'>{escape(str(ev.get('result_retry_count',0)))}</td>"
            "</tr>"
            for ev in rows
        )
        inner += f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;margin:12px 0;box-shadow:0 1px 4px rgba(15,23,42,.06);">
          <div style="background:{color};color:#ffffff;padding:11px 13px;font-weight:900;font-size:15px;">{escape(label)} · {len(rows)} pending</div>
          <div style="overflow-x:auto;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;min-width:560px;">
              <thead><tr style="background:#f8fafc;">
                <th align="left" style="padding:9px;border-bottom:1px solid #cbd5e1;font-size:12px;color:#334155;text-transform:uppercase;">Kickoff WIB</th>
                <th align="left" style="padding:9px;border-bottom:1px solid #cbd5e1;font-size:12px;color:#334155;text-transform:uppercase;">Competition</th>
                <th align="left" style="padding:9px;border-bottom:1px solid #cbd5e1;font-size:12px;color:#334155;text-transform:uppercase;">Match</th>
                <th align="center" style="padding:9px;border-bottom:1px solid #cbd5e1;font-size:12px;color:#334155;text-transform:uppercase;">Retry</th>
              </tr></thead>
              <tbody>{table_rows}</tbody>
            </table>
          </div>
        </div>"""
    return _email_shell("[RESULT PENDING] Hourly Batch", inner)


def _validation_style(validation: str) -> Tuple[str, str]:
    v = (validation or "").upper()
    if "SEBAGIAN" in v:
        return "#fef3c7", "#92400e"
    if "SALAH" in v:
        return "#fee2e2", "#991b1b"
    if "BENAR" in v:
        return "#dcfce7", "#166534"
    return "#f1f5f9", "#334155"


def _running_accuracy(events: List[Dict[str, Any]]) -> Tuple[int, int, str]:
    denom = 0
    correct = 0
    for ev in events:
        val = str(ev.get("validation") or "").upper()
        if val == "NO_PREDICTION" or engine.is_no_pick_prediction(ev.get("prediction") or {}):
            continue
        if any(x in val for x in ["BENAR", "SEBAGIAN", "SALAH"]):
            denom += 1
            if val == "BENAR":
                correct += 1
    pct = "—" if denom == 0 else f"{round(correct * 100 / denom, 1)}%"
    return correct, denom, pct


def render_postmatch_batch_html(date: str, events: List[Dict[str, Any]], texts: Optional[List[str]] = None) -> str:
    correct, denom, pct = _running_accuracy(events)
    inner = _summary_box({
        "Tanggal": date,
        "Generated": now_wib().strftime('%H:%M WIB'),
        "Completed matches": len(events),
        "Running accuracy": f"{correct}/{denom} = {pct}",
    })
    for ev in events:
        pred = ev.get("prediction") or {}
        color = _sport_color(ev.get("sport", "unknown"))
        label = engine.SPORT_META.get(ev.get("sport", "unknown"), (str(ev.get("sport", "unknown")).upper(), color))[0]
        bg, fg = _validation_style(str(ev.get("validation") or ""))
        try:
            resolved_prediction = engine._resolve_outcome_label(ev, pred)  # type: ignore[attr-defined]
        except Exception:
            raw_outcome = str(pred.get('outcome') or '—')
            code = raw_outcome.lower().strip()
            team_a = str(ev.get('team_a') or ev.get('team_home') or (ev.get('event','').split(' vs ')[0] if ' vs ' in str(ev.get('event','')) else '')).strip()
            team_b = str(ev.get('team_b') or ev.get('team_away') or (ev.get('event','').split(' vs ')[1] if ' vs ' in str(ev.get('event','')) else '')).strip()
            resolved_prediction = {'home': team_a or 'Home', 'home_win': team_a or 'Home', 'away': team_b or 'Away', 'away_win': team_b or 'Away', 'draw': 'Draw'}.get(code, raw_outcome)
        prediction = f"{resolved_prediction} · {pred.get('score_or_result') or '—'} · {pred.get('confidence_percent') or '—'}%"
        actual = f"{ev.get('actual_winner') or '—'} · {ev.get('actual_result') or '—'}"
        lesson = ev.get("lesson_learnt") or "No durable lesson extracted."
        inner += f"""
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;margin:12px 0;box-shadow:0 1px 4px rgba(15,23,42,.06);">
          <div style="background:{color};color:#ffffff;padding:11px 13px;font-weight:900;font-size:15px;">{escape(label)} · {escape(str(ev.get('competition','')))}</div>
          <div style="padding:13px;">
            <div style="font-size:17px;font-weight:900;color:#0f172a;margin-bottom:6px;">{escape(str(ev.get('event','')))}</div>
            <div style="font-size:12px;color:#64748b;margin-bottom:10px;">Kickoff {escape(str(ev.get('kickoff_wib','')))} WIB</div>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
              <tr><th align="left" style="width:34%;padding:10px;background:#f8fafc;color:#334155;font-size:12px;text-transform:uppercase;border-bottom:1px solid #e5e7eb;">Prediction</th><td style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#0f172a;">{escape(prediction)}</td></tr>
              <tr><th align="left" style="padding:10px;background:#f8fafc;color:#334155;font-size:12px;text-transform:uppercase;border-bottom:1px solid #e5e7eb;">Actual</th><td style="padding:10px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#0f172a;font-weight:700;">{escape(actual)}</td></tr>
              <tr><th align="left" style="padding:10px;background:#f8fafc;color:#334155;font-size:12px;text-transform:uppercase;">Validation</th><td style="padding:10px;background:{bg};color:{fg};font-size:13px;font-weight:900;">{escape(str(ev.get('validation') or 'UNKNOWN'))}</td></tr>
            </table>
            <div style="margin-top:11px;background:#f8fafc;border-left:4px solid {color};border-radius:10px;padding:10px 12px;">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#475569;font-weight:900;margin-bottom:5px;">Lesson Learnt</div>
              <div style="font-size:13px;line-height:1.45;color:#0f172a;">{escape(str(lesson))}</div>
            </div>
          </div>
        </div>"""
    return _email_shell("[POST-MATCH] Hourly Batch", inner)


def send_result_pending_batch(date: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not events:
        return {"sent": False, "reason": "no_events"}
    # Hourly batching. Base idempotency key retained in audit: YYYY-MM-DD-result-pending.
    hour = _hour_key()
    tag = f"{date}-result-pending-{hour}"
    lines = [
        "⏳ RESULT PENDING — HOURLY BATCH",
        "",
        f"Date: {date}",
        f"Generated: {now_wib().strftime('%Y-%m-%d %H:%M WIB')}",
        f"Pending matches: {len(events)}",
        "Idempotency base: " + f"{date}-result-pending",
        "",
    ]
    for ev in sorted(events, key=lambda e: e.get("kickoff_wib", "")):
        lines.append(f"- {ev.get('kickoff_wib')} WIB | {ev.get('sport','').upper()} | {ev.get('competition','')} | {ev.get('event')} | retry={ev.get('result_retry_count')}")
    text = "\n".join(lines)
    html_path = engine.EMAIL_DIR / f"{tag}.html"
    html_path.write_text(render_result_pending_batch_html(date, events))
    email = engine.send_email(f"[RESULT PENDING] Hourly Batch — {date} — {now_wib().strftime('%H:00 WIB')}", html_path, text, tag)
    state = engine.load_state(date)
    for ev in events:
        sid = ev.get("event_id")
        if sid in state.get("events", {}):
            state["events"][sid]["result_pending_email_sent"] = bool(email.get("sent"))
            state["events"][sid]["result_pending_email_batch_key"] = tag
    engine.save_state(date, state)
    audit("result_pending_batch_email", "ok" if email.get("sent") else "deduped_or_error", {"tag": tag, "base_idempotency_key": f"{date}-result-pending", "events": [e.get("event_id") for e in events], "email": email}, date=date)
    return email


def send_postmatch_batch(date: str, event_ids: List[str], texts: List[str]) -> Dict[str, Any]:
    if not event_ids:
        return {"sent": False, "reason": "no_events"}
    hour = _hour_key()
    tag = f"{date}-postmatch-batch-{hour}"
    state = engine.load_state(date)
    events = [state.get("events", {}).get(eid, {}) for eid in event_ids]
    lines = [
        "🏁 POST-MATCH RESULT — HOURLY BATCH",
        "",
        f"Date: {date}",
        f"Generated: {now_wib().strftime('%Y-%m-%d %H:%M WIB')}",
        f"Completed matches: {len(event_ids)}",
        "",
    ]
    for ev, text in zip(events, texts):
        lines += ["━━━━━━━━━━━━━━━━━━━━━━━━", text, ""]
    body = "\n".join(lines).strip()
    html_path = engine.EMAIL_DIR / f"{tag}.html"
    html_path.write_text(render_postmatch_batch_html(date, events, texts))
    email = engine.send_email(f"[POST-MATCH] Hourly Batch — {date} — {now_wib().strftime('%H:00 WIB')}", html_path, body, tag)
    for eid in event_ids:
        if eid in state.get("events", {}):
            delivered = bool(email.get("sent")) and not bool(email.get("deduped"))
            state["events"][eid]["post_match_email_sent"] = delivered
            state["events"][eid]["post_match_email_batch_key"] = tag
            state["events"][eid]["post_match_email_batch_pending"] = not delivered
    engine.save_state(date, state)
    audit("postmatch_batch_email", "ok" if email.get("sent") else "deduped_or_error", {"tag": tag, "events": event_ids, "email": email}, date=date)
    return email


def espn_scoreboard_for_event(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sport_path = "soccer/fifa.world" if ev.get("competition") == "FIFA World Cup 2026" else None
    if not sport_path:
        return None
    # Query kickoff UTC date and WIB date neighbor to handle timezone crossing
    dates = set()
    kw = ev.get("kickoff_wib", "")[:10]
    if kw:
        d = datetime.fromisoformat(kw).date()
        for off in (-1, 0, 1):
            dates.add((d + timedelta(days=off)).strftime("%Y%m%d"))
    for ds in sorted(dates):
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={ds}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception:
            continue
        wanted = ev.get("event", "").lower()
        for event in data.get("events", []) or []:
            comps = event.get("competitions", [])
            if not comps:
                continue
            comp = comps[0]
            competitors = comp.get("competitors", [])
            names = []
            for c in competitors:
                t = c.get("team", {})
                names.append(t.get("displayName") or t.get("shortName") or "")
            blob = " vs ".join(names).lower()
            if all(part.strip().lower() in blob for part in ev.get("event", "").split(" vs ")):
                return {"event": event, "competition": comp, "competitors": competitors, "url": url}
    return None


def score_from_espn(match: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    comp = match["competition"]
    st = comp.get("status", {}).get("type", {})
    completed = bool(st.get("completed")) or st.get("state") == "post"
    if not completed:
        return None
    comps = match["competitors"]
    if len(comps) < 2:
        return None
    # ESPN competitors order is often home/away, but our event string is team_a vs team_b.
    scores = []
    names = []
    winners = []
    for c in comps[:2]:
        t = c.get("team", {})
        names.append(t.get("displayName") or t.get("shortName") or "")
        scores.append(int(c.get("score") or 0))
        if c.get("winner"):
            winners.append(names[-1])
    actual = f"{scores[0]}-{scores[1]}"
    winner = "draw" if scores[0] == scores[1] else (winners[0] if winners else names[0 if scores[0] > scores[1] else 1])
    return actual, winner


def validate_prediction(ev: Dict[str, Any], actual_score: str, actual_winner: str) -> str:
    """v3.2 sport-specific validation thresholds delegated to engine."""
    try:
        engine.normalize_prediction_v32(ev)
        return engine.validation_status_v32(ev, actual_score, actual_winner)
    except Exception:
        pred = ev.get("prediction", {}) or {}
        pred_outcome = str(pred.get("outcome") or "").lower()
        pred_score = str(pred.get("score_or_result") or "")
        aw = actual_winner.lower()
        if aw == "draw":
            outcome_ok = pred_outcome == "draw"
        else:
            outcome_ok = pred_outcome and pred_outcome in aw
        score_ok = pred_score.replace(" ", "") == actual_score.replace(" ", "")
        if outcome_ok and score_ok:
            return "BENAR"
        if outcome_ok or score_ok:
            return "SEBAGIAN BENAR"
        return "SALAH"


def _is_already_completed_in_other_date(ev: Dict[str, Any], this_date: str) -> bool:
    """Check if this event (by slug_key) was already completed in another date's state.
    Prevents duplicate post-match emails when an event lives in multiple date buckets
    (e.g. rolling-48h ingest puts a match into both today and tomorrow's state).
    """
    try:
        from sports_v3_engine import slug_key as _slug, STATE_DIR as _STATE_DIR, load_state
        key = _slug({"sport": ev.get("sport"), "competition": ev.get("competition"),
                     "team_a": ev.get("team_a") or ev.get("event", "").split(" vs ")[0],
                     "team_b": ev.get("team_b") or (ev.get("event", "").split(" vs ")[1] if " vs " in ev.get("event", "") else ""),
                     "kickoff_wib": ev.get("kickoff_wib")})
        # Look at most recent other-date states
        for f in sorted(_STATE_DIR.glob("*.json"), reverse=True)[:14]:
            d = f.stem
            if d == this_date:
                continue
            try:
                st = load_state(d)
            except Exception:
                continue
            if not st or not isinstance(st.get("events"), dict):
                continue
            other = st["events"].get(key) or st["events"].get(ev.get("event_id", ""))
            if other and other.get("status") == "completed":
                return True
    except Exception:
        return False
    return False


def run_results(date: str) -> int:
    state = engine.normalize_daily_state(date)
    due = engine.expected_finished_events(date, state)
    count = 0
    pending_batch: List[Dict[str, Any]] = []
    postmatch_ids: List[str] = []
    postmatch_texts: List[str] = []
    for ev in due:
        # Skip if same event already completed in another date's state — prevents
        # duplicate post-match reports for events that span multiple date buckets
        # (rolling-48h ingest). The earlier state already sent the report.
        if _is_already_completed_in_other_date(ev, date):
            audit("results_skipped_duplicate", "ok", {"event_id": ev.get("event_id"), "date": date, "reason": "already_completed_in_other_date"})
            continue
        match = espn_scoreboard_for_event(ev)
        result = score_from_espn(match) if match else None
        if result:
            actual_score, winner = result
            if engine.is_blank_prediction((ev.get("prediction") or {})):
                text = engine.complete_result(date, ev["event_id"], actual_score, winner, "NO_PREDICTION", "Normal validation blocked: missing pre-match prediction before result capture.")
                hermes_send(text, f"{date}-result-blocked-no-prediction-{ev['event_id'][:24]}")
                count += 1
                continue
            validation = validate_prediction(ev, actual_score, winner)
            lesson = f"Result captured from ESPN scoreboard; prediction validation={validation}. Re-check scoreline volatility and lineup evidence for future calibration."
            text = engine.complete_result(date, ev["event_id"], actual_score, winner, validation, lesson, send_email_report=False)
            hermes_send(text, f"{date}-postmatch-{ev['event_id'][:30]}")
            postmatch_ids.append(ev["event_id"])
            postmatch_texts.append(text)
            count += 1
        else:
            # Avoid retry-timeout cascades: perform web confirmation only on the
            # first failed capture attempt. Later 5-minute retries are state-only
            # until the structured result source returns a final score.
            if int(ev.get("result_retry_count") or 0) == 0:
                searxng_search(f"{ev.get('event')} final score {ev.get('competition')}", 3)
            pending = engine.mark_result_pending(date, ev["event_id"])
            if pending.get("result_pending_notified"):
                pending_batch.append(dict(pending))
            count += 1
    # Include all currently unresolved pending results in the hourly batch, even
    # when they are not due for a retry in this specific 5-minute tick.
    latest_for_pending = engine.load_state(date)
    seen_pending = {p.get("event_id") for p in pending_batch}
    for ev in latest_for_pending.get("events", {}).values():
        if ev.get("status") == "result_pending_after_60m" and ev.get("event_id") not in seen_pending:
            pending_batch.append(dict(ev))
            seen_pending.add(ev.get("event_id"))
    if pending_batch:
        pending_email = send_result_pending_batch(date, pending_batch)
        # Discord batch mirrors the hourly email only when the hourly send is not deduped.
        if pending_email.get("sent") and not pending_email.get("deduped"):
            text = "⏳ RESULT PENDING — BATCH\n\n" + "\n".join(
                f"- {p.get('kickoff_wib')} WIB | {p.get('event')} | retry={p.get('result_retry_count')}" for p in pending_batch
            )
            hermes_send(text, f"{date}-result-pending-batch-{_hour_key()}")
    # If previous completions landed after an hourly post-match batch was already
    # sent, keep them queued and deliver on the next hour's batch.
    latest_state = engine.load_state(date)
    for ev in latest_state.get("events", {}).values():
        if ev.get("post_match_email_batch_pending") and ev.get("event_id") not in postmatch_ids:
            pred = ev.get("prediction", {}) or {}
            text = "\n".join([
                "🏁 POST-MATCH RESULT", "",
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                f"{ev.get('sport','').upper()} — {ev.get('competition','')}",
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                f"📅 {ev.get('kickoff_wib')} WIB",
                f"🆚 {ev.get('event')}",
                f"🎯 Prediksi      : {pred.get('outcome')} {pred.get('score_or_result')} | {pred.get('confidence_percent')}%",
                f"✅ Actual Result : {ev.get('actual_winner')} {ev.get('actual_result')}",
                f"🎖️ Status        : {ev.get('validation')}", "",
                "💡 Lesson Learnt:",
                f"• {ev.get('lesson_learnt') or 'No durable lesson extracted.'}",
            ])
            postmatch_ids.append(ev.get("event_id"))
            postmatch_texts.append(text)
    if postmatch_ids:
        send_postmatch_batch(date, postmatch_ids, postmatch_texts)
    return count


def run_eod(date: str) -> int:
    state = engine.load_state(date)
    guard = engine.eod_guard_status(state)
    if not guard.get("ready"):
        return 0
    mode = guard.get("mode") or "final"
    report_key = "eod_partial" if mode == "partial" else "eod"
    if state.get("reports", {}).get(report_key, {}).get("email_sent"):
        return 0
    text = engine.render_eod(date, state)
    if mode == "partial":
        text = "⏳ EOD PARTIAL — pending results unresolved\n\n" + text
    hermes_send(text, f"{date}-{'eod-partial' if mode == 'partial' else 'eod'}")
    engine.maybe_send_eod(date)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_wib())
    parser.add_argument("--mode", choices=["all", "prematch", "results", "eod", "status"], default="all")
    args = parser.parse_args(argv)
    date = args.date
    if args.mode == "status":
        print(json.dumps(engine.status(date), indent=2, ensure_ascii=False))
        return 0
    acted = 0
    if args.mode in ("all", "prematch"):
        acted += run_backfill_queue(date)
        acted += run_prematch(date)
    if args.mode in ("all", "results"):
        acted += run_results(date)
    if args.mode in ("all", "eod"):
        acted += run_eod(date)
    if acted == 0:
        print("[SILENT]")
    else:
        print(json.dumps({"date": date, "actions": acted, "status": engine.status(date)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
