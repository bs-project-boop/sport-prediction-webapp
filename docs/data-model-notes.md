# Sport Prediction Legacy Data Model Notes

**Prepared:** 2026-07-19 WIB
**Phase:** Kickoff / Phase 0
**Source:** `/Users/beem/sport-prediction-dev/reference/shared-scripts/sports_v3_engine.py` and related exported ingestion/watcher scripts

## Scope and important distinction

The export contains the legacy source code and schema references, but not the live `/Users/beem/.hermes-shared/reports/sports/v3/` daily JSON artifacts. Therefore this document records the schema from the engine's readers/writers and the exported schema reference files. A production ingestion implementation must still validate against live files with fixture samples before enabling writes.

Two contracts exist:

- **v3.2 daily contract:** one JSON document per date for schedules, predictions, and state; one JSONL file per date for audit.
- **Older monthly prediction-log contract:** `predictions/YYYY-MM.json`, with nested `phases.initial`, `phases.prematch`, `phases.result`, `phases.validation`, and optional `phases.postmortem`.

Do not merge the two contracts by assuming that `outcome_correct` is present in the v3.2 state event or that the monthly `phases` object is always present in daily files.

## 1. Paths and serialization behavior

The engine hardcodes the following root:

```text
/Users/beem/.hermes-shared/reports/sports/v3
```

Directories created by `ensure_dirs()`:

```text
schedules/
predictions/
state/
email-outbox/
audit/
eod/
```

File patterns:

```text
schedules/YYYY-MM-DD.json
predictions/YYYY-MM-DD.json
state/YYYY-MM-DD.json
email-outbox/<date-and-tag>.html
email-outbox/<date-and-tag>.mml
email-outbox/<slug>.sent.json
audit/YYYY-MM-DD.jsonl
eod/YYYY-MM-DD.md
eod/YYYY-MM-DD-partial.md
```

Serialization:

- JSON uses `json.dumps(..., indent=2, ensure_ascii=False)`.
- Audit uses one JSON object per line.
- `read_json()` returns the supplied default for a missing or invalid file; malformed JSON is silently treated as absent by the legacy engine.
- `write_json()` creates parent directories but does not use an atomic temporary-file/rename operation.
- State writes update `updated_at_wib` immediately before serialization.

Timezone:

```text
WIB = UTC+07:00
```

## 2. Schedule document: `schedules/YYYY-MM-DD.json`

### Top-level fields

Written by `sports_v31_searxng_scanner.py` or `sports_v31_espn_ingest.py`:

```json
{
  "date_wib": "YYYY-MM-DD",
  "generated_at_wib": "ISO-8601 timestamp",
  "generator": "sports_v31_searxng_scanner | sports_v32_multi_source_ingest",
  "searxng_endpoint": "URL or null",
  "sports_covered": ["football", "tennis", "motorsport", "basketball", "nfl"],
  "fixture_source_classification": {},
  "no_event": [],
  "events": [],
  "event_count": 0,
  "no_event_count": 0
}
```

`fixture_source_classification` is present in the v3.2 multi-source ingester and may be absent in older v3.1 files. It maps source path to endpoint probe metadata, including fields such as:

```text
ok_buckets: list[string]
failed_buckets: list[object]
events_seen: integer
events_in_window: integer
source_type: string
classification: ok | ok_zero_events | endpoint_invalid_or_unsupported | DATA_SOURCE_DEGRADED
source_kind: string, when external source
competition: string, when external source
```

### `no_event[]` item fields

At minimum:

```text
sport: string
reason: string
```

The SearXNG scanner also writes:

```text
sport_full_name: string
scanned_at_wib: ISO-8601 timestamp
```

### `events[]` fields from SearXNG scanner stub

```text
event_id: string
sport: string
competition: string, initially empty
 event: string, initially empty
kickoff_wib: string, initially empty
venue: string, initially empty
evidence_url: string|null
evidence_title: string|null
evidence_snippet: string|null
evidence_primary: boolean
needs_research: boolean
scanned_at_wib: ISO-8601 timestamp
```

### `events[]` fields from ESPN normalization

Core normalized fields:

```text
event_id: string, assigned from slug_key after normalization
sport: football | tennis | motorsport | basketball | nfl
competition: string
event: string, normally "team_a vs team_b"
team_a: string
team_b: string
kickoff_wib: "YYYY-MM-DD HH:MM"
kickoff_utc: source ISO timestamp
venue: string
status: string
espn_event_id: string|null
espn_league_slug: string
espn_competition_id: string|null
fixture_source_path: string
fixture_source_competition: string
fixture_source_name: string
source_event_shape: string|null
needs_research: boolean
researched: boolean
source_research: object
searxng_query: string
searxng_evidence: list[object]
DATA_SOURCE_DEGRADED: boolean
data_source: object
evidence_url: string|null
evidence_title: string|null
evidence_source: string|null
youtube_transcript: object|null, optional
```

External official-source events can add source-specific identifiers, for example:

```text
motogp_event_id
motogp_session_id
motogp_category_uuid
motogp_category_name
motogp_session_type
motogp_weekend_start
motogp_weekend_end
euroleague_game_code
euroleague_identifier
euroleague_season_code
fiba_game_id
fiba_game_name
fiba_competition_id
fiba_competition_code
fiba_round_name
fiba_group_pairing_code
competition_level
prediction_eligible
validation
accuracy_excluded
report_label
```

These source-specific fields should be preserved in a JSONB `source_metadata` column rather than expanded into the first schema migration unless dashboard queries require them.

### `data_source` object

The v3.2 ingester writes:

```text
fixture_source: string
fixture_source_path: string|null
fixture_source_competition: string|null
fixture_source_status: string|null
research_primary: "SearXNG"
sources_used: list[string]
fallback_sources_used: list[string]
DATA_SOURCE_DEGRADED: boolean
degraded_reason: string|null
confidence_penalty_applied: integer, normally 0 or -15
source_event_shape: string|null
```

## 3. Prediction document: `predictions/YYYY-MM-DD.json`

### Top-level fields

```json
{
  "date_wib": "YYYY-MM-DD",
  "generated_at_wib": "ISO-8601 timestamp",
  "generator": "sports_v31_searxng_scanner | sports_v32_multi_source_ingest",
  "fixture_source_classification": {},
  "meta": {},
  "predictions": []
}
```

`meta` is present in the older monthly contract and may be present in degraded fallback artifacts. It is not guaranteed in the v3.2 daily writer.

### Daily `predictions[]` fields

Discovery/stub and researched rows share these fields:

```text
match_id: string
event_id: represented by match_id in prediction rows
sport: string
competition: string
event: string
kickoff_wib: string
venue: string
evidence_url: string|null
evidence_title: string|null
evidence_source: string|null
searxng_query: string|null
searxng_evidence: list[object]
source_research: object|null
youtube_transcript: object|null
predicted_outcome: string|null
predicted_score_or_result: string|null
confidence_percent: integer|null
confidence_label: HIGH | MEDIUM | LOW | COIN FLIP | UNKNOWN | null
confidence_breakdown: object|null
confidence_model_version: "v3.2"
risk_score_1_to_10: integer|null
no_pick: boolean
competition_level: senior | junior | string
prediction_eligible: boolean
validation_status: string|null
validation: string|null
accuracy_excluded: boolean
report_label: string|null
DATA_SOURCE_DEGRADED: boolean
data_source: object|null
reasoning: list[string]
researched: boolean
stub: boolean
espn_event_id: string|null
team_a: string
team_b: string
```

The existing ingester preserves a researched, non-stub row on re-run and refreshes only discovery/evidence metadata. This is an important idempotency rule for ingestion.

### Fallback/degraded prediction fields

`v32_daily_quota_safe_fallback.py` can emit stub rows with:

```text
match_id
date_wib
sport
competition
event
kickoff_wib
researched: false
stub: true
predicted_outcome: null
predicted_score_or_result: null
confidence_percent: null
confidence_label: null
risk_score_1_to_10: null
reasoning: []
data_source: object
DATA_SOURCE_DEGRADED: true
phases: {initial: {}, prematch: {}, result: {}, validation: {}}
```

Fallback document metadata includes:

```text
meta.date_wib
meta.created_at_wib
meta.status = DEGRADED_LLM_UNAVAILABLE_STUBS_ONLY
meta.research_complete = false
```

## 4. State document: `state/YYYY-MM-DD.json`

### Top-level fields

Created by `load_state()`:

```text
date_wib: string
created_at_wib: ISO-8601 timestamp
updated_at_wib: ISO-8601 timestamp|null
discord_channel: string
email_to: string
reports: object
events: object keyed by event_id
no_event: list[object]
fixture_source_classification: object, added during normalization
```

Default `reports` object:

```json
{
  "initial_48h": {
    "discord_sent": false,
    "email_sent": false
  },
  "eod": {
    "discord_sent": false,
    "email_sent": false
  }
}
```

Additional report keys can appear:

```text
initial_48h.discord_channel
initial_48h.email_result
initial_48h.marked_at_wib
eod.email_result
eod.sent_at_wib
eod.guard
eod_partial.*
```

### `events[event_id]` core fields

Normalization constructs or preserves:

```text
event_id: string
sport: string
event: string
competition: string
kickoff_wib: string
status: scheduled | completed | postponed | cancelled | no_prediction | backfill_failed | research_backfill_required | result_pending_after_60m | string
prediction: object
confidence_breakdown: object
confidence_label: string
data_source: object
DATA_SOURCE_DEGRADED: boolean
competition_level: string
prediction_eligible: boolean
accuracy_excluded: boolean
report_label: string|null
reasoning: list[string]
evidence_url: string|null
evidence_title: string|null
pre_match_alert_sent: boolean
post_match_report_sent: boolean
result_retry_count: integer
result_pending_notified: boolean
next_result_retry_after_wib: string|null
actual_result: string|null
actual_winner: string|null
validation: string|null
validation_status: string|null
source_prediction_file: string
```

Optional lifecycle/backfill fields:

```text
backfill_attempts: integer
backfill_alert_sent: boolean
backfill_alert_sent_at_wib: timestamp
backfill_required_since_wib: timestamp
backfill_terminal: boolean
backfill_status: completed | failed
backfill_completed_at_wib: timestamp
last_backfill_attempt_at_wib: timestamp
prediction_ineligible_reason: kickoff_passed_before_backfill | backfill_failed
result_pending_newly_notified: boolean
result_pending_email_sent: boolean
result_capture_blocked: boolean
result_capture_block_reason: missing_prediction_preflight
result_captured_at_wib: timestamp
lesson_learnt: string
lesson_json: object
post_match_email_sent: boolean
post_match_email_batch_pending: boolean
pre_match_checked_at_wib: timestamp
pre_match_note: string
pre_match_email_sent: boolean
pre_match_research: list[object]
pre_match_research_by_source: object
pre_match_research_query: string
```

### Nested `prediction` object in state

```text
outcome: string, possibly NO_PICK
score_or_result: string
confidence_percent: integer
risk_score_1_to_10: integer
confidence_breakdown: object
confidence_label: string
no_pick: boolean
confidence_weights: object, generated by v3.2 normalization
confidence_model_version: "v3.2"
DATA_SOURCE_DEGRADED: boolean
confidence_penalty_applied: integer
no_pick_reason: string, normally confidence_below_40
```

## 5. Confidence model

Confidence is a weighted score in the range 0–100. Each factor is clamped to 0–100 before weighting. Missing or invalid factors default to 50.

Factors:

```text
form
h2h
player_condition
home_away
market_odds
contextual
```

Canonical weights:

```text
football:   form .25, h2h .15, player_condition .20, home_away .15, market_odds .15, contextual .10
tennis:     form .20, h2h .20, player_condition .25, home_away .15, market_odds .10, contextual .10
motorsport: form .15, h2h .10, player_condition .20, home_away .20, market_odds .20, contextual .15
basketball: form .25, h2h .15, player_condition .20, home_away .15, market_odds .15, contextual .10
nfl:        form .20, h2h .15, player_condition .20, home_away .15, market_odds .15, contextual .15
```

Formula:

```text
weighted_score = sum(clamp(factor_score, 0, 100) * adjusted_weight)
penalty = -15 when DATA_SOURCE_DEGRADED else 0
confidence = clamp(round(weighted_score + penalty), 0, 100)
```

Weights can be adjusted from:

```text
/Users/beem/.hermes-shared/reports/sports/meta-learning/weight-adjustments.json
```

Adjustments are applied only when `status` is not explicitly something other than `applied`, match the sport, and contain a known factor. Weights are re-normalized after deltas.

Labels:

```text
>= 75: HIGH
>= 55: MEDIUM
>= 40: LOW
< 40: COIN FLIP
invalid/missing: UNKNOWN
```

## 6. NO_PICK and degraded mode

`NO_PICK` is true when either:

```text
prediction.outcome.upper() == "NO_PICK"
prediction.no_pick is truthy
```

A prediction with confidence below 40 is normalized to:

```text
outcome: NO_PICK
no_pick: true
no_pick_reason: confidence_below_40
score_or_result: existing score or "—"
```

If no reasoning exists, the engine inserts:

```text
NO_PICK: confidence below 40 after data-source degradation penalty.
Fixture is retained in schedule, but no winner/score prediction is validated until sufficient evidence exists.
```

`DATA_SOURCE_DEGRADED` is propagated from the event/data-source object. The confidence penalty is `-15` when degraded. Degraded mode does not invent a winner and should remain visible to the UI.

A blank prediction is different from `NO_PICK`:

- `NO_PICK` is an intentional, eligible decision to abstain.
- Blank outcome/score or em-dash placeholders mean no usable pre-match prediction exists.
- A blank result is validated as `NO_PREDICTION` and excluded from the accuracy denominator.

Late fixture stubs are eligible for backfill only before kickoff. After kickoff they become terminal `no_prediction`, with `prediction_eligible=false`, `validation=NO_PREDICTION`, and `accuracy_excluded=true`. Failed backfill becomes terminal after three attempts.

## 7. Result and validation rules

`validation_status_v32()` returns:

```text
NO_PICK                if prediction is NO_PICK
NO_PREDICTION          if outcome/score is blank
SALAH                 if predicted winner is wrong
BENAR                 if outcome is correct and sport score threshold passes
SEBAGIAN BENAR        if outcome is correct but score threshold fails
```

Thresholds implemented by the engine:

```text
football:   sum of absolute score component deltas <= 1
basketball: sum of absolute score component deltas <= 8
nfl:        sum of absolute score component deltas <= 7
tennis:     absolute difference in total sets <= 1
other:      normalized exact score string match
```

The exported Sports profile governance document additionally defines motorsport top-three semantics. The current `sports_v3_engine.py` fallback validation branch does not implement a dedicated motorsport top-three comparator; this is a migration gap to preserve as an explicit adapter rule rather than silently rewriting the legacy engine.

## 8. Older monthly prediction-log contract

Reference path:

```text
~/.hermes-shared/reports/sports/predictions/YYYY-MM.json
```

Top-level:

```json
{
  "meta": {},
  "predictions": [],
  "accuracy_stats": {}
}
```

Per-match fields:

```text
match_id: string
date: YYYY-MM-DD
kickoff_wib: string, often HH:MM in older files
teams.home: string
teams.away: string
competition: string
phases.initial: object
phases.prematch: object
phases.result: object
phases.validation: object
phases.postmortem: object|null
```

`phases.initial`:

```text
timestamp_wib
regime_detected
prediction.outcome
prediction.predicted_score
prediction.confidence
prediction.risk
ensemble_prediction
models
_backfilled, optional boolean
```

`phases.result`:

```text
timestamp_wib
actual_score
winner
goals: list[object]
half_time_score
_source
_backfilled, optional boolean
```

`phases.validation`:

```text
timestamp_wib
outcome_correct: boolean|null
score_correct: boolean|null
score_diff: integer|null
regime_mismatch: boolean
confidence_quality: string
declared_confidence: number
actual_reliability: number
```

Critical rule: `outcome_correct` belongs under `phases.validation`, not `phases.result`. `null` means not validated or backfilled without an original prediction; it must not be converted to false.

## 9. Audit JSONL: `audit/YYYY-MM-DD.jsonl`

Base engine record:

```json
{
  "ts_wib": "ISO-8601 timestamp",
  "action": "string",
  "status": "ok | error | blocked | skipped | deduped | failed | string",
  "details": {}
}
```

The ESPN/SearXNG modules add:

```text
module: v31_espn_ingest | v31_searxng_scanner | other module name
```

Typical actions:

```text
normalize_state
email_send
initial_report_marked
supplemental_48h_sent
prematch_marked
result_retry
result_capture_blocked_no_prediction
result_completed
eod_check
eod_sent
eod_partial_sent
reconcile
validate
espn_fetch_failed
espn_3bucket_probe
espn_ingest_complete
searxng_healthcheck
sport_scan_complete
searxng_query_failed
v32_weight_adjustments_updated
backfill_attempt
backfill_queue_expired
```

Audit `details` is action-specific and may include event IDs, source probe counts, email idempotency keys, validation errors, retry counts, and error summaries. It must not contain PINs, passwords, API keys, or full credential-bearing URLs.

## 10. Lesson JSON

`build_lesson_json()` produces:

```text
match_id
date
sport
competition
team_home
team_away
predicted_winner
actual_winner
predicted_score
actual_score
confidence_pct
confidence_breakdown
risk_score
validation_status
factors_missed: list[string]
pattern_tags: list[string]
postmortem
```

Pattern tags map to confidence factors:

```text
underestimated_home_advantage -> home_away
overestimated_form -> form
injury_late_news -> player_condition
weather_impact -> contextual
rotation_surprise -> player_condition
market_odds_misleading -> market_odds
motivational_factor -> contextual
fatigue_underestimated -> player_condition
surface_form_ignored -> home_away
tactical_surprise -> contextual
```

Repeated pattern tags at least three times in a 14-day window create a `delta_weight=0.05` adjustment record, deduplicated by `(sport, pattern_tag, factor)`.

## 11. Data-source and business-flow summary

- Fixture discovery: ESPN site APIs across configured leagues plus approved official source APIs/pages for MotoGP, EuroLeague, FIBA, IBL, and Grand Slam tennis.
- Research/evidence: local SearXNG at `http://10.10.10.5:8888`, with a five-source matrix in v3.2: general, Twitter, Reddit, YouTube, and advanced stats.
- Prediction generation: external LLM cron workflow; the deterministic engine normalizes, validates, persists, deduplicates, and renders. The engine itself is not the research model.
- Reports: Discord delivery is performed by watcher scripts/Hermes CLI; email is sent through Himalaya. The engine maintains email idempotency markers and audit records.
- Outputs: JSON schedule/prediction/state, JSONL audit, HTML/MML email outbox, Markdown EOD report, and Discord outbox text.

## 12. Migration implications

For the new PostgreSQL app:

- Preserve original JSON source files and source path/date as immutable ingestion metadata.
- Use a deterministic `source_record_id`/idempotency key based on source file, date, and event/match ID.
- Store unknown and source-specific fields in JSONB during the first migration rather than dropping them.
- Keep `NO_PICK`, `NO_PREDICTION`, and null validation states distinct.
- Store `DATA_SOURCE_DEGRADED` and `confidence_penalty_applied` explicitly.
- Do not modify the legacy engine or its JSON writers in the initial application phase.
- Ingestion must be read-only against the legacy report tree and must skip corrupt files with an audit error rather than aborting the full scan.
- Accuracy queries must exclude `NO_PICK`, `NO_PREDICTION`, and `accuracy_excluded=true` rows according to the legacy denominator rules.
