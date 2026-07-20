import type { MetricsResponse } from '../../lib/api'

interface KpiRowProps {
  metrics: MetricsResponse
}

interface KpiCard {
  label: string
  value: number | string
  suffix?: string
  tone: 'accent' | 'warning' | 'danger' | 'muted'
}

export function KpiRow({ metrics }: KpiRowProps) {
  const total = metrics.evaluated_count

  const cards: KpiCard[] = [
    {
      label: 'Evaluated',
      value: total,
      tone: 'muted',
    },
    {
      label: 'Strict accuracy',
      value: metrics.strict_accuracy_percent ?? '—',
      suffix: metrics.strict_accuracy_percent != null ? '%' : '',
      tone: 'accent',
    },
    {
      label: 'Lenient accuracy',
      value: metrics.lenient_accuracy_percent ?? '—',
      suffix: metrics.lenient_accuracy_percent != null ? '%' : '',
      tone: 'warning',
    },
    {
      label: 'Excluded',
      value: metrics.excluded_count,
      tone: 'muted',
    },
  ]

  return (
    <div className="kpi-row" role="list" aria-label="Key metrics">
      {cards.map((card) => (
        <div
          key={card.label}
          className={`kpi-card kpi-${card.tone}`}
          role="listitem"
          aria-label={`${card.label}: ${card.value}${card.suffix ?? ''}`}
        >
          <p className="kpi-label">{card.label}</p>
          <strong className="kpi-value">
            {card.value}
            {card.suffix && <small>{card.suffix}</small>}
          </strong>
        </div>
      ))}
    </div>
  )
}
