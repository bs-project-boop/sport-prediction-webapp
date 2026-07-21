import { useState } from 'react'
import type { MatchItem, PredictionResponse } from '../../lib/api'
import { getValidationMeta } from '../../lib/validation'

interface MatchCardProps {
  match: MatchItem
  prediction?: PredictionResponse
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const OUTCOME_LABEL: Record<string, string> = {
  home_win: 'Home win',
  away_win: 'Away win',
  draw: 'Draw',
  over_35: 'Over 3.5 goals',
  under_35: 'Under 3.5 goals',
}

function resolveTeamName(outcome: string | null | undefined): string {
  if (!outcome) return '—'
  if (outcome in OUTCOME_LABEL) return OUTCOME_LABEL[outcome]
  return outcome
}

// ── Sub-components ───────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, { icon: string; label: string }> = {
  BENAR: { icon: '✓', label: 'Benar' },
  SEBAGIAN_BENAR: { icon: '◐', label: 'Sebagian benar' },
  SALAH: { icon: '×', label: 'Salah' },
  NO_PICK: { icon: '—', label: 'No pick' },
  NO_PREDICTION: { icon: '·', label: 'Belum ada prediksi' },
}

function MatchBadge({ status }: { status: string | null | undefined }) {
  const meta = getValidationMeta(status)
  const info = status ? STATUS_BADGE[status] : STATUS_BADGE.NO_PREDICTION
  return (
    <span
      className={`badge badge-${meta.tone}`}
      title={meta.description}
      aria-label={`Status: ${info.label}`}
    >
      <span aria-hidden="true">{info.icon}</span>
      <span>{info.label}</span>
    </span>
  )
}

interface ConfidenceBarProps {
  label: string
  value: number
  max?: number
}
function ConfidenceBar({ label, value, max = 100 }: ConfidenceBarProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div className="cb-row">
      <span className="cb-label">{label}</span>
      <div className="cb-track" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
        <div className="cb-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="cb-value">{value}</span>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export function MatchCard({ match, prediction }: MatchCardProps) {
  const [open, setOpen] = useState(false)

  const kickoffDate = match.kickoff_wib ?? match.date_wib
  const dateStr = kickoffDate
    ? new Date(kickoffDate).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' })
    : '—'
  const timeStr = kickoffDate
    ? new Date(kickoffDate).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })
    : ''

  // Team names from event or fallback to parsed team_a/team_b
  const teamA = match.team_a ?? match.event.split(' vs ')[0]?.trim() ?? '—'
  const teamB = match.team_b ?? match.event.split(' vs ')[1]?.trim() ?? '—'

  // Predicted outcome display
  const predictedTeam = prediction?.no_pick
    ? null
    : resolveTeamName(prediction?.predicted_outcome)
  const predictedScore = prediction?.predicted_score_or_result ?? null
  const hasPrediction = !prediction?.no_pick && predictedTeam && predictedTeam !== '—'

  // Actual outcome display
  const actualWinner = prediction?.actual_winner ?? null
  const actualResult = prediction?.actual_result ?? null
  const hasActual = Boolean(actualWinner || actualResult)

  // Reasoning items
  const reasoningItems: string[] = []
  if (prediction?.no_pick && prediction?.predicted_score_or_result) {
    reasoningItems.push(prediction.predicted_score_or_result)
  } else if (prediction?.predicted_score_or_result && !prediction?.no_pick) {
    reasoningItems.push(`Skor: ${prediction.predicted_score_or_result}`)
  }
  if (prediction?.confidence_percent != null) {
    reasoningItems.push(`Confidence: ${prediction.confidence_percent}%`)
  }

  // Confidence breakdown
  const breakdown = prediction?.confidence_breakdown ?? null

  // Data source badge
  const isDegraded = prediction?.DATA_SOURCE_DEGRADED ?? false
  const dataSource = isDegraded ? 'ESPN (degraded)' : 'ESPN'

  // Lesson learnt
  const lessonLearn = prediction?.lesson_learnt ?? null

  // Reasoning bullets (from raw reasoning array if available)
  const reasoningBullets: string[] = prediction?.reasoning ?? []
  if (!reasoningBullets.length && reasoningItems.length) {
    reasoningBullets.push(...reasoningItems)
  }

  return (
    <article className="mc-card">
      {/* ── Header row ── */}
      <div className="mc-row1">
        <div className="mc-meta">
          {timeStr && <span className="mc-time">{timeStr}</span>}
          <span className="mc-date">{dateStr}</span>
          <span className="mc-competition">{match.competition}</span>
        </div>
        <MatchBadge status={prediction?.validation_status} />
      </div>

      {/* ── Teams ── */}
      <p className="mc-teams">{teamA} <span className="mc-vs">vs</span> {teamB}</p>

      {/* ── Outcomes ── */}
      <div className="mc-outcomes">
        <div className="mc-outcome">
          <span className="mc-outcome-label">Prediksi</span>
          {hasPrediction ? (
            <span className="mc-outcome-value">
              {predictedTeam}
              {predictedScore ? `, ${predictedScore}` : ''}
            </span>
          ) : (
            <span className="mc-outcome-value mc-outcome-none">No pick</span>
          )}
        </div>
        <div className="mc-outcome">
          <span className="mc-outcome-label">Aktual</span>
          {hasActual ? (
            <span className="mc-outcome-value">
              {actualWinner ?? '—'}
              {actualResult ? `, ${actualResult}` : ''}
            </span>
          ) : (
            <span className="mc-outcome-value mc-outcome-none">
              {match.status === 'Scheduled' ? 'Belum selesai' : '—'}
            </span>
          )}
        </div>
      </div>

      {/* ── Expand toggle ── */}
      <button
        type="button"
        className="mc-expand"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? 'Sembunyikan analisa' : 'Lihat analisa'}
      >
        <span>{open ? 'Sembunyikan' : 'Lihat analisa'}</span>
        <span className={`mc-chevron${open ? ' up' : ''}`} aria-hidden="true">›</span>
      </button>

      {/* ── Collapsible detail panel ── */}
      <div
        className={`mc-reasoning${open ? ' open' : ''}`}
        aria-hidden={!open}
      >
        {/* Reasoning bullets */}
        {reasoningBullets.length > 0 && (
          <div className="mc-detail-section">
            <p className="mc-section-label">Analisa</p>
            <ul className="mc-reasoning-list">
              {reasoningBullets.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Confidence breakdown */}
        {breakdown && Object.keys(breakdown).length > 0 && (
          <div className="mc-detail-section">
            <p className="mc-section-label">Confidence Breakdown</p>
            <div className="mc-confidence-bars">
              {Object.entries(breakdown).map(([factor, value]) => (
                <ConfidenceBar
                  key={factor}
                  label={factor.replace(/_/g, ' ')}
                  value={typeof value === 'number' ? value : 0}
                />
              ))}
            </div>
          </div>
        )}

        {/* Data source badge */}
        <div className="mc-detail-section mc-source-row">
          <span className="mc-source-badge">
            {dataSource}
          </span>
          {isDegraded && (
            <span className="mc-degraded-badge" title="Data source degraded — confidence penalty applied">
              ⚠ Degraded
            </span>
          )}
        </div>

        {/* Lesson learnt */}
        {lessonLearn && (
          <div className="mc-detail-section">
            <p className="mc-section-label">Lesson Learnt</p>
            <p className="mc-lesson">{lessonLearn}</p>
          </div>
        )}

        {/* No reasoning available */}
        {!reasoningBullets.length && !breakdown && !lessonLearn && (
          <p className="mc-reasoning-placeholder">Tiada reasoning tersedia.</p>
        )}
      </div>
    </article>
  )
}
