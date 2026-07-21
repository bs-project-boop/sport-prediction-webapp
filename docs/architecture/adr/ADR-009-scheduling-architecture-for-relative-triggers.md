# ADR-009 — Scheduling Architecture untuk Trigger Relatif (T-2 Jam, T+15 Menit) di systemd/LXC

**Date:** 2026-07-21 | **Status:** Proposed | **Scope:** Sport Prediction Backend — Scheduling + Worker Architecture

---

## Context

Enam stage pipeline baru dari ADR-007:

| # | Stage | Trigger |
|---|---|---|
| 1 | Discovery | 00:00 WIB (fixed) |
| 2 | Matrix Analysis | T-2 jam sebelum kickoff (relatif) |
| 3 | Prediction Generation | Langsung setelah Stage 2 (relatif-ke-stage2) |
| 4 | Result + Win Reasoning | T+15 menit setelah match selesai (relatif) |
| 5 | Validation | Bersamaan Stage 4 (relatif-ke-stage4) |
| 6 | Nightly Evaluation | 22:00 WIB (fixed) |

Stage 2 dan 4-5 punya **trigger relatif terhadap waktu match** — tidak bisa dijadwalkan dengan systemd timer fixed-schedule biasa.

Engine lama menggunakan polling script setiap 5 menit (`v31_prematch_noagent.sh`, `v31_results_noagent.sh`) untuk mencapai fungsi yang sama.

---

## Decision

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     LXC 108 (10.10.10.83)                          │
│                                                                     │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐    │
│  │ systemd timers │  │           FastAPI Backend                │    │
│  │              │  │                                           │    │
│  │ timer.discovery│ │  ┌─────────────────────────────────┐   │    │
│  │ (00:00 WIB)   │──│──│ discovery_worker (async)        │   │    │
│  │              │  │  │ - Fetch ESPN + external APIs     │   │    │
│  │ timer.nightly │  │  │ - Write matches to DB           │   │    │
│  │ (22:00 WIB)   │──│──│ - Register stage2 jobs           │   │    │
│  │              │  │  └─────────────────────────────────┘   │    │
│  └──────────────┘  │                                           │    │
│                    │  ┌─────────────────────────────────┐   │    │
│                    │  │ stage2_worker (polling 60s)     │   │    │
│                    │  │ - SELECT * FROM pipeline_jobs   │   │    │
│                    │  │   WHERE stage='stage2'          │   │    │
│                    │  │   AND status='pending'          │   │    │
│                    │  │   AND scheduled_time <= NOW()   │   │    │
│                    │  │ - Run matrix analysis            │   │    │
│                    │  │ - Trigger stage3 inline          │   │    │
│                    │  └─────────────────────────────────┘   │    │
│                    │                                           │    │
│                    │  ┌─────────────────────────────────┐   │    │
│                    │  │ stage45_worker (polling 60s)    │   │    │
│                    │  │ - SELECT * FROM pipeline_jobs   │   │    │
│                    │  │   WHERE stage IN ('stage4','stage5')   │   │
│                    │  │   AND status='pending'          │   │    │
│                    │  │   AND scheduled_time <= NOW()   │   │    │
│                    │  │ - Run result + validation        │   │    │
│                    │  └─────────────────────────────────┘   │    │
│                    │                                           │    │
│                    │  ┌─────────────────────────────────┐   │    │
│                    │  │ nightly_worker (triggered by timer) │   │
│                    │  │ - Calibration eval              │   │    │
│                    │  │ - Weight adjustment suggestions  │   │    │
│                    │  └─────────────────────────────────┘   │    │
│                    │                                           │    │
│                    │  ┌─────────────────────────────────┐   │    │
│                    │  │ notification_service             │   │    │
│                    │  │ - Discord webhook / Himalaya    │   │    │
│                    │  │ - idempotency via notif_audit  │   │    │
│                    │  └─────────────────────────────────┘   │    │
│                    └───────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Detail

#### 1. systemd Timer (Fixed Schedules)

```ini
# /etc/systemd/system/sport-prediction-discovery.timer
[Timer]
OnCalendar=*-*-* 00:00:00 Asia/Jakarta
Persistent=true

# /etc/systemd/system/sport-prediction-nightly.timer
[Timer]
OnCalendar=*-*-* 22:00:00 Asia/Jakarta
Persistent=true
```

```ini
# /etc/systemd/system/sport-prediction-discovery.service
[Service]
Type=oneshot
User=sportapp
WorkingDirectory=/opt/sport-prediction/current/backend
ExecStart=/opt/sport-prediction/current/backend/.venv/bin/python -m app.workers.discovery
```

```ini
# /etc/systemd/system/sport-prediction-nightly.service
[Service]
Type=oneshot
User=sportapp
WorkingDirectory=/opt/sport-prediction/current/backend
ExecStart=/opt/sport-prediction/current/backend/.venv/bin/python -m app.workers.nightly
```

#### 2. Background Workers (Long-Running, Polling-Based)

Stage 2 dan Stage 4-5 workers berjalan sebagai long-running processes, polling setiap **60 detik**.

**Kenapa polling, bukan event-driven?**
- Engine lama sudah pakai polling 5 menit — 60 detik polling di database lebih sering tapi masih murah
- Tidak perlu external message queue (SQS/RabbitMQ/etc.)
- Worker crash = otomatis restart via systemd watchdog atau supervisor
- Skala: puluhan-ratusan match/hari = polling sekali per menit = <10,000 query/hari, trivial

**Job Registration (Stage 1 menulis ini):**
Saat Discovery worker menemukan match baru di Stage 1, dia menulis ke `pipeline_jobs`:

```python
# Stage 1 - Discovery
for match in discovered_matches:
    # Insert match, write predictions stub
    
    # Register Stage 2 job (T-2 hours)
    db.execute(pipeline_jobs.insert(), {
        "job_id": f"stage2:{match.match_id}",
        "stage": "stage2",
        "match_id": match.match_id,
        "scheduled_time": match.kickoff_wib - timedelta(hours=2),
        "status": "pending",
    })
    
    # Register Stage 4 job (T+duration)
    duration = SPORT_DURATIONS.get(match.sport, 150)  # minutes
    db.execute(pipeline_jobs.insert(), {
        "job_id": f"stage4:{match.match_id}",
        "stage": "stage4",
        "match_id": match.match_id,
        "scheduled_time": match.kickoff_wib + timedelta(minutes=duration + 15),
        "status": "pending",
    })
    # Stage 5 jobs are registered by stage4_worker after result capture
```

**Stage 2 Worker (T-2 jam):**
```python
async def stage2_worker():
    while True:
        now = datetime.now(WIB)
        jobs = db.fetch("""
            SELECT * FROM pipeline_jobs 
            WHERE stage = 'stage2' 
            AND status = 'pending' 
            AND scheduled_time <= %s
            ORDER BY scheduled_time ASC
            LIMIT 10
        """, (now,))
        
        for job in jobs:
            try:
                db.execute("UPDATE pipeline_jobs SET status='running', attempt_count=attempt_count+1 WHERE id=%s", (job.id,))
                await run_matrix_analysis(job.match_id)  # Stage 2 logic
                db.execute("UPDATE pipeline_jobs SET status='completed', completed_at=NOW() WHERE id=%s", (job.id,))
                await trigger_stage3(job.match_id)  # Stage 3 inline
            except Exception as e:
                handle_failure(job, e)
        
        await asyncio.sleep(60)
```

**Stage 4 Worker (T+duration+15 menit):**
```python
async def stage45_worker():
    while True:
        now = datetime.now(WIB)
        jobs = db.fetch("""
            SELECT * FROM pipeline_jobs 
            WHERE stage IN ('stage4', 'stage5')
            AND status = 'pending' 
            AND scheduled_time <= %s
            ORDER BY scheduled_time ASC
            LIMIT 10
        """, (now,))
        
        for job in jobs:
            try:
                if job.stage == 'stage4':
                    await run_result_capture(job.match_id)  # Fetch actual result
                    await run_win_reasoning(job.match_id)   # New field
                    # Register stage5 job
                    db.execute(pipeline_jobs.insert(), {
                        "job_id": f"stage5:{job.match_id}",
                        "stage": "stage5",
                        "match_id": job.match_id,
                        "scheduled_time": now,  # Immediate, same tick
                        "status": "pending",
                    })
                elif job.stage == 'stage5':
                    await run_validation(job.match_id)
                    await notification_service.send_result(job.match_id)
                
                db.execute("UPDATE pipeline_jobs SET status='completed', completed_at=NOW() WHERE id=%s", (job.id,))
            except Exception as e:
                handle_failure(job, e)
        
        await asyncio.sleep(60)
```

#### 3. Failure Handling

```python
def handle_failure(job, error):
    if job.attempt_count >= job.max_attempts:
        db.execute("""
            UPDATE pipeline_jobs 
            SET status='failed', last_error=%s, last_attempt_at=NOW()
            WHERE id=%s
        """, (str(error), job.id))
        # Alert via monitoring
    else:
        # Exponential backoff: 5min, 15min, 45min
        backoff_minutes = 5 * (3 ** job.attempt_count)
        db.execute("""
            UPDATE pipeline_jobs 
            SET status='pending', 
                last_error=%s,
                last_attempt_at=NOW(),
                scheduled_time=NOW() + INTERVAL '%s minutes'
            WHERE id=%s
        """, (str(error), backoff_minutes, job.id))
```

#### 4. Service Management

Workers berjalan sebagai systemd services:

```ini
# /etc/systemd/system/sport-prediction-workers.service
[Unit]
Description=Sport Prediction Pipeline Workers
After=network.target sport-prediction-backend.service

[Service]
Type=simple
User=sportapp
WorkingDirectory=/opt/sport-prediction/current/backend
ExecStart=/opt/sport-prediction/current/backend/.venv/bin/python -m app.workers
Restart=on-failure
RestartSec=10s
WatchdogSec=120s

[Install]
WantedBy=multi-user.target
```

Workers check-in via watchdog. Jika worker hang >120s tanpa progress, systemd restart.

---

## Consequences

### Positive

- **Relative triggers handled correctly**: T-2h dan T+15m dari kickoff, bukan fixed time
- **Debuggable**: pipeline_jobs table visibility untuk semua scheduled/running/failed jobs
- **Resilient**: worker crash → systemd restart; job failure → retry dengan backoff
- **Observable**: semua job state di-DB, query untuk monitoring dashboard
- **Simple**: tidak perlu MQ, tidak perlu external scheduler library

### Negative / Risks

**Risk #1 — Polling Overhead**
60-detik polling per worker × 2 workers = ~170 query/menit di DB. Acceptable untuk skala ini tapi perlu idx yang benar di `pipeline_jobs(scheduled_time) WHERE status='pending'`.

**Risk #2 — Clock Skew**
Jika server clock drift, scheduled_time vs NOW() bisa mismatch. Mitigasi: gunakan database server time (`NOW()` bukan application server time) untuk consistency.

**Risk #3 — Missed Jobs on Server Restart**
Jika server restart jam 23:55, discovery timer jam 00:00 besok akan catch-up via `Persistent=true`. Worker restart tidak miss jobs karena jobs di-database tetap ada.

**Risk #4 — Stage 3 Inline Call**
Stage 3 (Prediction Generation) dipanggil inline dari Stage 2 worker — inicoupling. Alternatif: Stage 2 tulis ke queue, Stage 3 worker separately polling. Chosen approach: inline karena Stage 3 harus run immediately setelah Stage 2, dan ini logically one pipeline.

**Risk #5 — Worker Concurrency**
Jika banyak match punya kickoff yang sama (misal: 02:00 WIB banyak football), Stage 2 worker akan lock + process sequentially dari polling loop. Mitigation: `LIMIT 10` per poll iteration + worker pool size 5 max concurrent.

---

## Alternatives Considered

### A. APScheduler atau Celery Beat

Gunakan library scheduler dengan interval scheduling builtin.

Rejected. Adds external dependency. Workers restart on crash but APScheduler state is in-memory — on restart jobs need re-registration. Database-backed scheduling (pipeline_jobs table) lebih robust untuk use case ini.

### B. Message Queue (RabbitMQ / SQS / Kafka)

Semua stage kirim pesan ke queue, worker berikutnya consume.

Rejected. Operational complexity tinggi untuk skala ini. Tidak butuh distributed processing — semua berjalan di satu LXC.

### C. systemd timer per match

Buat timer dynamically per match saat discovered.

Rejected. systemd tidak didesain untuk thousands of dynamic timers. Will overwhelm systemd daemon.

### D. cron setiap 5 menit (engine lama pattern)

Polling file-based state seperti engine lama.

Rejected. Pipeline_jobs di-database lebih observable dan avoids filesystem coupling.

---

## Configuration Constants

```python
# Pipeline configuration
STAGE2_LOOKAHEAD_HOURS = 2
STAGE4_LOOKAHEAD_MINUTES_AFTER_KICKOFF = 15  # after duration
WORKER_POLL_INTERVAL_SECONDS = 60
MAX_CONCURRENT_STAGE2_JOBS = 10
MAX_CONCURRENT_STAGE45_JOBS = 10
MAX_JOB_ATTEMPTS = 3
JOB_BACKOFF_FACTORS = [5, 15, 45]  # minutes

# Sport durations (minutes) — dari sports_v3_engine.py
SPORT_DURATIONS = {
    "football": 135,
    "tennis": 180,
    "motorsport": 150,
    "basketball": 150,
    "nfl": 240,
}
```

---

## Rollback Plan

Jika worker architecture gagal:

1. Stop workers: `systemctl stop sport-prediction-workers`
2. Keep timers disabled
3. Legacy cron jobs still exist and can be re-enabled (they were stopped, not deleted)
4. Restore by re-enabling cron jobs and stopping backend workers

---

## Observability

```sql
-- View pending jobs
SELECT stage, COUNT(*) FROM pipeline_jobs WHERE status='pending' GROUP BY stage;

-- View stuck jobs (>30 min running)
SELECT * FROM pipeline_jobs WHERE status='running' AND last_attempt_at < NOW() - INTERVAL '30 minutes';

-- View failed jobs
SELECT * FROM pipeline_jobs WHERE status='failed' ORDER BY created_at DESC LIMIT 20;

-- Pipeline throughput
SELECT DATE(scheduled_time) as date, stage, COUNT(*) 
FROM pipeline_jobs 
WHERE completed_at IS NOT NULL 
GROUP BY 1, 2 
ORDER BY 1 DESC;
```
