import { useState } from 'react'
import type { MatchItem, PredictionResponse } from '../../lib/api'
import { getValidationMeta } from '../../lib/validation'

export function MatchCard({ match, prediction }: { match: MatchItem; prediction?: PredictionResponse }) {
  const [open, setOpen] = useState(false)
  const meta = getValidationMeta(prediction?.validation_status)
  return <article className="match-card">
    <div className="match-main">
      <div className="match-time"><span>{new Date(match.kickoff_wib ?? match.date_wib).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span><small>{match.sport}</small></div>
      <div className="teams"><strong>{match.team_a ?? match.event.split(' vs ')[0]}</strong><span>vs</span><strong>{match.team_b ?? match.event.split(' vs ')[1]}</strong><small>{match.competition}</small></div>
      <div className={`status-pill ${meta.tone}`} title={meta.description}><span aria-hidden="true">{meta.icon}</span>{meta.label}</div>
      <button className="expand-button" type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`${open ? 'Hide' : 'Show'} match details`}>
        {open ? '−' : '+'}
      </button>
    </div>
    {open && <div className="match-details">
      <div><span>Prediction</span><strong>{prediction?.predicted_outcome ?? 'Not available'}</strong></div>
      <div><span>Actual result</span><strong>{prediction?.actual_result ?? 'Pending'}</strong></div>
      <div><span>Confidence</span><strong>{prediction?.confidence_percent != null ? `${prediction.confidence_percent}%` : '—'}</strong></div>
      <p>{meta.description}</p>
    </div>}
  </article>
}
