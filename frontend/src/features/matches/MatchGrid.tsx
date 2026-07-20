import type { MatchItem, PredictionResponse } from '../../lib/api'
import { groupMatchesBySport } from '../../lib/groupMatches'
import { MatchCard } from './MatchCard'

interface MatchGridProps {
  matches: MatchItem[]
  predictions: Map<string, PredictionResponse | undefined>
}

export function MatchGrid({ matches, predictions }: MatchGridProps) {
  const groups = groupMatchesBySport(matches)

  if (groups.length === 0) {
    return <div className="mc-empty">Tiada perlawanan dijumpai.</div>
  }

  return (
    <div className="sport-groups">
      {groups.map(({ sport, icon, items }) => (
        <section key={sport} className="sport-group" aria-label={`${sport} matches`}>
          <div className="sport-group-header">
            <span className="sport-icon" aria-hidden="true">{icon}</span>
            <h3 className="sport-name">{sport.charAt(0).toUpperCase() + sport.slice(1)}</h3>
            <span className="sport-count">{items.length} perlawanan</span>
          </div>
          <div className="match-grid">
            {items.map((match) => (
              <MatchCard
                key={match.match_id}
                match={match}
                prediction={predictions.get(match.match_id)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
