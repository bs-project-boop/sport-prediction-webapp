interface SportFilterBarProps {
  availableSports: string[]
  sport: string
  from: string
  to: string
  onSportChange: (sport: string) => void
  onFromChange: (from: string) => void
  onToChange: (to: string) => void
}

const SPORT_ICONS: Record<string, string> = {
  football: '⚽',
  basketball: '🏀',
  tennis: '🎾',
  default: '🏅',
}

function sportIcon(s: string) {
  return SPORT_ICONS[s.toLowerCase()] ?? SPORT_ICONS.default
}

export function SportFilterBar({
  availableSports,
  sport,
  from,
  to,
  onSportChange,
  onFromChange,
  onToChange,
}: SportFilterBarProps) {
  return (
    <div className="sport-filter-bar" role="group" aria-label="Dashboard filters">
      {/* Sport pills — generated dynamically */}
      <div className="sport-pills" role="radiogroup" aria-label="Filter by sport">
        <button
          type="button"
          role="radio"
          aria-checked={sport === 'all'}
          className={`sport-pill${sport === 'all' ? ' active' : ''}`}
          onClick={() => onSportChange('all')}
        >
          All
        </button>
        {availableSports.map((s) => (
          <button
            type="button"
            role="radio"
            key={s}
            aria-checked={sport === s}
            className={`sport-pill${sport === s ? ' active' : ''}`}
            onClick={() => onSportChange(s)}
          >
            <span aria-hidden="true">{sportIcon(s)}</span>
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Date range */}
      <div className="date-range">
        <label>
          <span>From</span>
          <input
            type="date"
            value={from}
            max={to}
            onChange={(e) => onFromChange(e.target.value)}
            aria-label="From date"
          />
        </label>
        <label>
          <span>To</span>
          <input
            type="date"
            value={to}
            min={from}
            onChange={(e) => onToChange(e.target.value)}
            aria-label="To date"
          />
        </label>
      </div>
    </div>
  )
}
