import { useMemo, useState } from 'react'
import { useMutation, useQueries, useQuery } from '@tanstack/react-query'
import { ApiClient } from './lib/api'
import { PinLogin } from './features/auth/PinLogin'
import { AccuracyChart } from './features/metrics/AccuracyChart'
import { MetricsOverview } from './features/metrics/MetricsOverview'
import { MatchCard } from './features/matches/MatchCard'
import { getValidationMeta, VALIDATION_STATUSES } from './lib/validation'
import './App.css'

const api = new ApiClient(import.meta.env.VITE_API_BASE_URL ?? '/api')
const DEFAULT_FROM = '2026-06-29'
const DEFAULT_TO = '2026-07-19'

function App() {
  const [authenticated, setAuthenticated] = useState(false)
  const [loginError, setLoginError] = useState(false)
  const [from, setFrom] = useState(DEFAULT_FROM)
  const [to, setTo] = useState(DEFAULT_TO)
  const [sport, setSport] = useState('all')
  const login = useMutation({ mutationFn: (pin: string) => api.login(pin) })
  const submitLogin = async (pin: string) => {
    setLoginError(false)
    try {
      await login.mutateAsync(pin)
      setAuthenticated(true)
    } catch (error) {
      console.error('login failed', error)
      setLoginError(true)
    }
  }
  const query = { from, to, ...(sport === 'all' ? {} : { sport }) }
  const metrics = useQuery({ queryKey: ['metrics', query], queryFn: () => api.getMetrics(query), enabled: authenticated })
  const matches = useQuery({ queryKey: ['matches', query], queryFn: () => api.getMatches({ ...query, limit: 12 }), enabled: authenticated })
  const predictionQueries = useQueries({ queries: (matches.data?.items ?? []).map((match) => ({
    queryKey: ['prediction', match.match_id],
    queryFn: () => api.getPrediction(match.match_id),
    enabled: authenticated,
  })) })
  const predictions = useMemo(() => new Map(predictionQueries.map((item) => [item.data?.match_id, item.data])), [predictionQueries])

  if (!authenticated) return <PinLogin busy={login.isPending} error={loginError ? 'invalid' : null} onSubmit={submitLogin} />

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark small">SP</span><span>Sport<span className="brand-accent">/</span>Intel</span></div>
      <div className="topbar-actions"><span className="live-dot" /> Live data <button className="logout-button" type="button" onClick={() => { void api.logout(); setAuthenticated(false) }}>Lock</button></div>
    </header>
    <div className="dashboard-wrap">
      <section className="hero-row"><div><p className="eyebrow">PREDICTION DESK / 2026 SEASON</p><h1>Good evening, <span>analyst.</span></h1><p className="hero-sub">A clear view of what the model saw — and how it performed.</p></div><div className="date-chip"><span>Showing range</span><strong>{from} → {to}</strong></div></section>
      <section className="filter-bar" aria-label="Dashboard filters">
        <label>From <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label>To <input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
        <label>Sport <select value={sport} onChange={(event) => setSport(event.target.value)}><option value="all">All sports</option><option value="football">Football</option><option value="basketball">Basketball</option></select></label>
      </section>
      {metrics.isLoading ? <div className="loading">Loading signal…</div> : metrics.data && <MetricsOverview metrics={metrics.data} />}
      {metrics.data && <section className="analysis-grid"><article className="panel chart-panel"><div className="panel-heading"><div><p className="eyebrow">ACCURACY LENS</p><h2>Strict vs lenient</h2></div><span className="panel-note">Current range</span></div><AccuracyChart metrics={metrics.data} /></article><article className="panel read-panel"><p className="eyebrow">READ THE SIGNAL</p><h2>Partial wins<br /><span>still matter.</span></h2><p>Strict accuracy rewards only exact correctness. Lenient accuracy keeps partial outcomes visible, so calibration decisions have the full picture.</p><div className="legend-row"><span className="legend-dot green" /> Correct <span className="legend-dot gold" /> Partial <span className="legend-dot red" /> Incorrect</div></article></section>}
      <section className="matches-section"><div className="section-heading"><div><p className="eyebrow">EVENT LOG</p><h2>Recent matches</h2></div><span>{matches.data?.total ?? 0} total events</span></div>
        <div className="validation-key" aria-label="Validation status key">{VALIDATION_STATUSES.map((status) => { const meta = getValidationMeta(status); return <span className={`validation-key-item ${meta.tone}`} key={status}><span aria-hidden="true">{meta.icon}</span>{meta.label}</span> })}</div>
        {matches.isLoading && <div className="loading">Loading matches…</div>}
        {matches.isError && <div className="empty-state">We couldn&apos;t load match data. Check the backend connection.</div>}
        <div className="match-list">{matches.data?.items.map((match) => <MatchCard key={match.match_id} match={match} prediction={predictions.get(match.match_id)} />)}</div>
      </section>
    </div>
  </main>
}

export default App
