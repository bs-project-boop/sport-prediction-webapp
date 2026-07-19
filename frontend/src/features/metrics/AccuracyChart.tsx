import { Bar } from 'react-chartjs-2'
import { BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import type { MetricsResponse } from '../../lib/api'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend)

export function AccuracyChart({ metrics }: { metrics: MetricsResponse }) {
  return <div className="chart-wrap" aria-label="Strict and lenient accuracy comparison">
    <Bar
      data={{
        labels: ['Current range'],
        datasets: [
          { label: 'Strict', data: [metrics.strict_accuracy_percent ?? 0], backgroundColor: '#70d6a0', borderRadius: 8, barPercentage: 0.45 },
          { label: 'Lenient', data: [metrics.lenient_accuracy_percent ?? 0], backgroundColor: '#f5bd64', borderRadius: 8, barPercentage: 0.45 },
        ],
      }}
      options={{
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#9aa7b8', usePointStyle: true, boxWidth: 8 } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#77859a' } },
          y: { min: 0, max: 100, grid: { color: 'rgba(150, 170, 195, .1)' }, ticks: { color: '#77859a', callback: (value) => `${value}%` } },
        },
      }}
    />
  </div>
}
