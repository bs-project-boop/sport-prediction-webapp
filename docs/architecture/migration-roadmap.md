# Roadmap Migrasi Prediction Engine ke FastAPI Backend

**Project:** Sport Prediction — Full Pipeline Migration | **Author:** Software Engineering Profile | **Date:** 2026-07-21

---

## Ringkasan

Roadmap ini menjabarkan 8 fase implementasi untuk memigrasikan seluruh logika prediksi dari legacy Python scripts (Sports profile) ke FastAPI backend (LXC 108). Setiap fase menghasilkan working software yang bisa divalidasi, bukan fase dokumentasi.

**Durasi estimasi total:** 6–10 minggu (tergantung availability dan testing cycles)

**Prinsip:** Setiap fase memiliki validasi criteria sebelum lanjut ke fase berikutnya. Fase M7 (testing) adalah gatekeeper sebelum M8 (cutover).

---

## Background Architecture

### Sistem Lama
- Engine: Python stdlib scripts di `/Users/beem/.hermes-shared/scripts/` dan `/Users/beem/sport-prediction-dev/reference/shared-scripts/`
- Scheduling: 6 Hermes cron jobs (daily scan, prematch watcher 5m, result watcher 5m, EOD watcher 30m, 10-10 watchdog, cron health)
- Storage: JSON files di `/Users/beem/.hermes-shared/reports/sports/v3/`
- Ingestion: Separate service yang consume JSON → PostgreSQL

### Sistem Baru
- Engine: FastAPI backend services di LXC 108
- Scheduling: systemd timers (fixed) + background workers (database polling)
- Storage: PostgreSQL (single source of truth)
- No ingestion needed — backend writes directly to DB

---

## Fase M1 — Stage 1: Discovery

**Tujuan:** Port logic fixture discovery dari `sports_v31_espn_ingest.py` ke FastAPI service layer

**Estimasi:** Medium | **Risiko:** Medium

### Cakupan
- [ ] Port ESPN API integration (semua 20+ league paths dari `LEAGUE_CONFIG`)
- [ ] Port external APIs: MotoGP PulseLive, EuroLeague, FIBA, IBL Indonesia
- [ ] Implementasi sliding window scan (-6h UTC hingga +24h UTC dari jam 00:00 WIB)
- [ ] `ok_zero_events` — liga off-season menghasilkan `NO_EVENT` record, bukan error
- [ ] Tulis matches ke database (INSERT, bukan overwrite jika sudah ada)
- [ ] Register stage2 jobs di `pipeline_jobs` untuk setiap match dengan kickoff time

### Source Code Ports
```
sports_v31_espn_ingest.py:
  - espn_fetch() → app/services/sources/espn.py
  - fetch_motogp_pulselive() → app/services/sources/motogp.py
  - fetch_euroleague_official() → app/services/sources/euroleague.py
  - fetch_fiba_official() → app/services/sources/fiba.py
  - fetch_ibl() → app/services/sources/ibl.py
  - fetch_tennis_grand_slams() → app/services/sources/tennis_grand_slam.py
```

### Validasi
- [ ] Output discovery backend dibanding kanandengan `sports_v31_espn_ingest.py` untuk 3 hari data — harus match ≥ 95%
- [ ] Semua league yang di-support engine lama juga di-support backend baru
- [ ] ok_zero_events correctly identified untuk 2 liga yang sedang off-season

### Test Scenario
```bash
# Run backend discovery
curl -X POST http://10.10.10.83:8100/api/v1/pipeline/discover \
  -H "X-Pin: 123456" \
  -d '{"date": "2026-07-25"}'

# Compare with engine
python3 sports_v31_espn_ingest.py --date 2026-07-25

# Diff results
```

---

## Fase M2 — Stage 2: Matrix Analysis

**Tujuan:** Port research/data gathering logic — deep research dari SearXNG, Polymarket, form analysis

**Estimasi:** High | **Risiko:** High (banyak external dependencies)

### Cakupan
- [ ] Port SearXNG scanner (`sports_v31_searxng_scanner.py`) → `app/services/sources/searxng.py`
- [ ] Port Polymarket integration (`polymarket.py`) → `app/services/sources/polymarket.py`
- [ ] Implementasi per-sport evidence gathering:
  - Football: form (last 5-10 matches), H2H, injuries, home/away record
  - Tennis: player form, H2H, surface record, recent tournament performance
  - Motorsport: driver form, constructor standing, circuit-specific performance
  - Basketball: team form, H2H, home/away splits
  - NFL: team form, H2H, injury report
- [ ] Evidence quality scoring (0-100)
- [ ] `data_source_degraded` flag — cascade ke fallback sources, apply -15 confidence penalty
- [ ] Tulis `matrix_analysis` records ke database
- [ ] Trigger stage3 inline setelah matrix analysis selesai

### Validasi
- [ ] Matrix analysis untuk 10 matches dibanding manual research — evidence completeness ≥ 80%
- [ ] Polymarket odds correctly fetched dan stored untuk ≥ 70% football/tennis matches
- [ ] DATA_SOURCE_DEGRADED correctly triggered when SearXNG returns < 3 results

---

## Fase M3 — Stage 3: Prediction Generation

**Tujuan:** Port confidence framework dan prediction logic dari `sports_v3_engine.py`

**Estimasi:** Medium | **Risiko:** Medium

### Cakupan
- [ ] Implementasi confidence framework per sport (bobot dari ADR-007):
  ```
  FOOTBALL:  form=25%, h2h=15%, player_condition=20%, home_away=15%, market_odds=15%, contextual=10%
  TENNIS:    form=20%, h2h=20%, player_condition=25%, home_away=15%, market_odds=10%, contextual=10%
  MOTORSPORT:form=15%, h2h=10%, player_condition=20%, home_away=20%, market_odds=20%, contextual=15%
  BASKETBALL:form=25%, h2h=15%, player_condition=20%, home_away=15%, market_odds=15%, contextual=10%
  NFL:       form=20%, h2h=15%, player_condition=20%, home_away=15%, market_odds=15%, contextual=15%
  ```
- [ ] NO_PICK logic: confidence < 40 → `predicted_outcome=NO_PICK`
- [ ] Confidence penalty: DATA_SOURCE_DEGRADED → -15
- [ ] Risk score computation
- [ ] Reasoning generation (structured text, bukan freeform)
- [ ] Tulis `predictions` records ke database
- [ ] Notification scheduling (Discord pre-match alert, 45-75 menit sebelum kickoff)

### Validasi
- [ ] Confidence score backend vs engine lama untuk 20 matches — variance ≤ 3 points
- [ ] NO_PICK decisions match (same confidence threshold)
- [ ] Risk scores match engine lama

---

## Fase M4 — Stage 4-5: Result + Win Reasoning + Validation

**Tujuan:** Port result capture dan implement Win Reasoning field baru

**Estimasi:** Medium | **Risiko:** Medium

### Cakupan
- [ ] Result capture: fetch actual results dari ESPN/league APIs setelah match selesai
- [ ] Implementasi Win Reasoning — field baru:
  - Winning factors (apa yang bikin tim menang)
  - Losing factors (apa yang bikin tim lain kalah)
  - Narrative (prose explanation)
  - Key moment
- [ ] Implementasi validation thresholds (dari ADR-007):
  ```
  FOOTBALL:  BENAR if delta_score <= 1
  TENNIS:    BENAR if delta_sets <= 1
  MOTORSPORT:BENAR if predicted in top 3
  BASKETBALL:BENAR if delta_score <= 8
  NFL:       BENAR if delta_score <= 7
  ```
- [ ] Tulis `win_reasoning` dan update `prediction_results` ke database
- [ ] Post-match notification (Discord + email)

### Validasi
- [ ] Validation results backend vs engine lama untuk 20 completed matches — must match 100%
- [ ] Win reasoning written for ≥ 90% completed matches
- [ ] NO_PREDICTION correctly flagged untuk matches tanpa prediction

---

## Fase M5 — Notification System

**Tujuan:** Port Discord + email notification dari `sports_v3_engine.py` ke FastAPI

**Estimasi:** Low | **Risiko:** Low

### Cakupan
- [ ] Discord webhook sender (format sesuai template engine lama)
- [ ] Himalaya email sender (MML format)
- [ ] Idempotency: `notification_audit` table — prevent double send
- [ ] Template parity: output notifikasi identik dengan engine lama
- [ ] 48H initial report, pre-match alert, post-match result, EOD summary

### Notification Templates (dari engine lama)

**Discord 48H Preview:**
```
[SPORT SCAN] 48H Preview — {date}
Total: {n_events} | Sports: {sports_list}
Completed: {n_completed} | Upcoming: {n_upcoming}
NO_PICK: {n_nopick}
Data Status: OK / DEGRADED
```

**Pre-match Alert (1 jam sebelum):**
```
⚡ PRE-MATCH — {kickoff_wib} WIB
{sport} — {competition}
{match}
🎯 {outcome} {score} @ {confidence}% | Risk: {risk}/10
```

**Post-match Result:**
```
🏁 {sport} — {competition}
{match}
✅ {actual_result} | Predicted: {predicted_outcome} {predicted_score}
🎖️ Status: {validation} ({correct/partial/wrong})
💡 Lesson: {lesson}
```

### Validasi
- [ ] Notifikasi terkirim untuk 10 test events — format identik dengan engine lama
- [ ] Idempotency: run notification twice with same idempotency key — only sent once
- [ ] Email HTML rendering matches engine lama output

---

## Fase M6 — Stage 6: Nightly Evaluation + ML Loop

**Tujuan:** Port calibration evaluator dan meta-learning dari `sports_calibration_evaluator.py` dan `sports_confidence_calibration.py`

**Estimasi:** Medium | **Risiko:** Medium

### Cakupan
- [ ] Calibration evaluation: compute accuracy per sport per confidence bucket
  - BUCKET HIGH: conf ≥ 75
  - BUCKET MEDIUM: conf 55-74
  - BUCKET LOW: conf 40-54
  - BUCKET COIN_FLIP: conf < 40
- [ ] Calibration error calculation: `abs(mean_confidence - actual_accuracy)`
- [ ] Threshold: ERROR_THRESHOLD_PCT = 15.0%
- [ ] Suggested weight adjustment (NOT auto-applied, hanya suggestion)
- [ ] Tulis `calibration_history` records
- [ ] Pattern-tag learning dari `update_weight_adjustments_from_lessons()`
  - If pattern_tag appears ≥ 3x in 14 days → write adjustment suggestion
- [ ] Tulis `weight_adjustments` records (status: pending_approval)
- [ ] Discord notification untuk calibration suggestions

### Validasi
- [ ] Calibration history untuk 14 hari matches vs engine lama — match ≥ 95%
- [ ] Suggested adjustments appear when calibration error > 15% dengan sample ≥ 20
- [ ] No auto-apply — all adjustments status=pending_approval

---

## Fase M7 — Testing Terhadap Data Real

**Tujuan:** Validasi penuh backend baru terhadap engine lama, minimal 7 hari data real

**Estimasi:** Medium | **Risiko:** Medium (blocking phase — M8 tidak boleh mulai sebelum M7 pass)

### Test Protocol

**Test #1: Discovery Parity**
```bash
# Untuk 7 hari consecutive, bandingkan:
# - Jumlah match discovered per sport
# - Kickoff times
# - Team names
# Pass criteria: ≥ 95% match
```

**Test #2: Prediction Parity**
```bash
# Untuk setiap match:
# - Confidence score: variance ≤ 3 points
# - NO_PICK decision: must match
# - Confidence breakdown per factor: variance ≤ 5 points per factor
# Pass criteria: ≥ 90% match untuk 7 hari × 20 match/day = 140 samples
```

**Test #3: Validation Parity**
```bash
# Untuk 20 completed matches:
# - Validation result (BENAR/SEBAGIAN/SALAH): must match 100%
# - Lesson extracted: structural match (same pattern_tags)
# Pass criteria: 100% match
```

**Test #4: Notification Output**
```bash
# Send 10 test notifications:
# - Compare HTML email output byte-for-byte
# - Compare Discord message format
# Pass criteria: byte-identical output
```

**Test #5: System Reliability (7 hari)**
```
- No missed matches (discovery coverage)
- No missed result captures
- No duplicate notifications sent
- Workers stay running (systemd restart on failure verified)
Pass criteria: 0 incidents over 7 days
```

### Gatekeeper Criteria

M8 (Cutover) tidak boleh dimulai sebelum:
- [ ] Test #1: Discovery parity ≥ 95%
- [ ] Test #2: Prediction parity ≥ 90%
- [ ] Test #3: Validation parity = 100%
- [ ] Test #4: Notification byte-identical
- [ ] Test #5: 7 hari zero incidents
- [ ] All failed tests documented dengan root cause analysis

---

## Fase M8 — Cutover

**Tujuan:** Matikan engine lama, aktifkan sepenuhnya backend baru

**Estimasi:** High | **Risiko:** High (irreversible step)

### Pre-Cutover Checklist
- [ ] M7 semua gatekeeper criteria pass
- [ ] Backend code di-commit ke GitHub private
- [ ] Rollback procedure tested (engine lama masih bisa di-restart)
- [ ] User explicitly approved cutover

### Cutover Procedure

**Step 1 — Freeze (T-1 hari):**
```
1. Disable semua Hermes cron jobs untuk sports profile:
   - sport-scanning-v3.2-daily-step1-3-scan-research-report
   - sport-scanning-v3.2-prematch-h1-monitor
   - sport-scanning-v3.2-result-capture-5m
   - sport-scanning-v3.2-eod-summary-ml
   - sport-scanning-v3.2-10-10-achievement-watchdog
   - sport-scanning-v3.2-cron-failure-alert
2. Flush any pending notifications in engine (disable send)
3. Note: ingestion service (JSON→DB) stays running for historical data
```

**Step 2 — Activate Backend:**
```
1. Enable systemd discovery timer:
   systemctl enable --now sport-prediction-discovery.timer
2. Enable systemd nightly timer:
   systemctl enable --now sport-prediction-nightly.timer
3. Start workers:
   systemctl enable --now sport-prediction-workers.service
4. Verify workers started:
   systemctl status sport-prediction-workers
5. Check pipeline_jobs for new jobs registered:
   SELECT COUNT(*) FROM pipeline_jobs WHERE status='pending';
```

**Step 3 — Monitor (T+24 jam):**
```
1. Monitor discovery coverage
2. Monitor stage2/stage45 polling
3. Monitor notification delivery
4. Verify Discord/email channels
5. Watch for any errors in workers
```

**Step 4 — Decommission (T+7 hari):**
```
1. Stop ingestion service (JSON→DB no longer needed)
2. Backup engine scripts ke archive/
3. Disable/cancel Hermes cron jobs (not delete)
4. Archive documentation: legacy-engine-v3.2-archive.md
```

### Rollback Procedure (If Issues Found)
```
1. Stop backend workers:
   systemctl stop sport-prediction-workers
2. Disable backend timers:
   systemctl stop sport-prediction-discovery.timer
   systemctl stop sport-prediction-nightly.timer
3. Re-enable Hermes cron jobs (invert Step 1)
4. Resume ingestion service if stopped
5. Backend code tagged: rollback-{date}
```

---

## Resource Requirements

| Resource | Estimasi |
|---|---|
| Development time (M1-M6) | 6-8 weeks |
| M7 testing period | 1-2 weeks |
| M8 cutover | 1 day |
| Post-cutover monitoring | 1 week |
| **Total** | **8-11 weeks** |

### Team
- 1 Software Engineering agent (coding)
- User provides: approval at each phase gate, final cutover approval

---

## Risk Register

| Phase | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| M2 | External API rate limiting | Medium | High | Implement rate limiting + cache |
| M2 | SearXNG instance down | Medium | Medium | Fallback chain: DuckDuckGo → direct scrape |
| M3 | Confidence framework behavioral diff | Low | High | Test against engine parity before M7 |
| M4 | Win reasoning subjectivity | Medium | Low | Structured output template |
| M5 | Notification double-send during cutover | High | Medium | Flush queue before activation |
| M7 | Coverage gap discovered | Medium | High | Minimum 7-day test before M8 |
| M8 | Engine lama cant be restored | Low | Critical | Keep scripts in archive, dont delete |

---

## Dependencies

```
M1 ──┬── M2 ──┬── M3 ──┬── M4 ──┬── M5
     │        │        │        │
     └────────┴────────┴────────┴────── M6 (parallel to M3-M5)
                                        │
                                        └──────── M7 ── M8
```

- M2 depends on M1 (needs matches to research)
- M3 depends on M2 (needs matrix analysis to generate predictions)
- M4 depends on M3 (needs predictions to validate)
- M5 can run parallel to M4
- M6 runs parallel to M3-M5 (it reads historical data)
- M7 gates M8

---

## Open Questions

1. **Legacy JSON artifacts** — setelah cutover, apakah `/Users/beem/.hermes-shared/reports/sports/v3/` tetap disimpan? Untuk berapa lama? Jawaban: Keep 90 days for forensic, then archive to cold storage.

2. **Polymarket API changes** — Polymarket tidak guarantee API stability. Jika API berubah, apakah fallback ke manual odds research? Jawaban: Polymarket failure = DATA_SOURCE_DEGRADED + -15 penalty, bukan blocker.

3. **Win reasoning automation** — Apakah win reasoning fully automated (structured extraction dari data sources) atau semi-automated (model generates, human approves)? Jawaban: Fully automated untuk M4, dengan structured template untuk konsistensi.

4. **Nightly evaluation override** — Apakah user mau approve weight adjustments sebelum applied, atau auto-apply dengan undo? Jawaban: Approval required (mirrors current behavior).
