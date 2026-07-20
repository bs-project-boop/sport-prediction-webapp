import { useState } from 'react'
import type { MatchItem, PredictionResponse } from '../../lib/api'
import { getValidationMeta } from '../../lib/validation'

interface MatchCardProps {
  match: MatchItem
  prediction?: PredictionResponse
}

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
    <span className={`badge badge-${meta.tone}`} title={meta.description} aria-label={`Status: ${info.label}`}>
      <span aria-hidden="true">{info.icon}</span>
      <span>{info.label}</span>
    </span>
  )
}

export function MatchCard({ match, prediction }: MatchCardProps) {
  const [open, setOpen] = useState(false)

  const kickoffDate = match.kickoff_wib ?? match.date_wib
  const dateStr = kickoffDate ? new Date(kickoffDate).toLocaleDateString('id-ID', {
    day: '2-digit', month: 'short', year: 'numeric',
  }) : '—'
  const timeStr = kickoffDate ? new Date(kickoffDate).toLocaleTimeString('id-ID', {
    hour: '2-digit', minute: '2-digit',
  }) : ''
  const teamA = match.team_a ?? match.event.split(' vs ')[0] ?? '—'
  const teamB = match.team_b ?? match.event.split(' vs ')[1] ?? '—'

  return (
    <article className="mc-card">
      {/* Row 1: date/time + competition left, badge right */}
      <div className="mc-row1">
        <div className="mc-meta">
          {timeStr && <span className="mc-time">{timeStr}</span>}
          <span className="mc-date">{dateStr}</span>
          <span className="mc-competition">{match.competition}</span>
        </div>
        <MatchBadge status={prediction?.validation_status} />
      </div>

      {/* Match name */}
      <p className="mc-teams">{teamA} <span>vs</span> {teamB}</p>

      {/* Predicted + actual */}
      <div className="mc-outcomes">
        <div className="mc-outcome">
          <span className="mc-outcome-label">Prediksi</span>
          <span className="mc-outcome-value">{prediction?.predicted_outcome ?? '—'}</span>
        </div>
        <div className="mc-outcome">
          <span className="mc-outcome-label">Aktual</span>
          <span className="mc-outcome-value">{prediction?.actual_result ?? '—'}</span>
        </div>
      </div>

      {/* Expand toggle */}
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

      {/* Collapsible reasoning */}
      <div className={`mc-reasoning${open ? ' open' : ''}`} aria-hidden={!open}>
        {prediction?.predicted_score_or_result && (
          <p className="mc-reasoning-item">
            <strong>Score:</strong> {prediction.predicted_score_or_result}
          </p>
        )}
        {prediction?.confidence_percent != null && (
          <p className="mc-reasoning-item">
            <strong>Confidence:</strong> {prediction.confidence_percent}%
          </p>
        )}
        {prediction?.no_pick && (
          <p className="mc-reasoning-item"><em>Model tidak membuat pick untuk peristiwa ini.</em></p>
        )}
        {prediction?.accuracy_excluded && (
          <p className="mc-reasoning-item"><em>Entry ini dikecualikan dari metrik accuracy.</em></p>
        )}
        {!prediction?.predicted_score_or_result && !prediction?.no_pick && (
          <p className="mc-reasoning-item mc-reasoning-placeholder">Tiada reasoning tersedia.</p>
        )}
      </div>
    </article>
  )
}
