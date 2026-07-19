import type { MetricsResponse } from '../../lib/api'

export function MetricsOverview({ metrics }: { metrics: MetricsResponse }) {
  const cards = [
    { label: 'Evaluated', value: metrics.evaluated_count, suffix: 'matches', tone: 'neutral' },
    { label: 'Strict accuracy', value: metrics.strict_accuracy_percent, suffix: '%', tone: 'green' },
    { label: 'Lenient accuracy', value: metrics.lenient_accuracy_percent, suffix: '%', tone: 'gold' },
    { label: 'Excluded', value: metrics.excluded_count, suffix: 'events', tone: 'muted' },
  ]
  return <section className="metric-grid" aria-label="Accuracy overview">
    {cards.map((card) => <article className={`metric-card ${card.tone}`} key={card.label}>
      <p>{card.label}</p><strong>{card.value ?? '—'}<small>{card.value === null ? '' : card.suffix}</small></strong>
    </article>)}
  </section>
}
