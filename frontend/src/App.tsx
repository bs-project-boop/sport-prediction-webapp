import { useMemo, useState } from 'react'
import { useMutation, useQueries, useQuery } from '@tanstack/react-query'
import { ApiClient, type PredictionResponse } from './lib/api'
import { PinLogin } from './features/auth/PinLogin'
import { Settings } from './features/auth/Settings'
import { SportFilterBar } from './features/matches/SportFilterBar'
import { KpiRow } from './features/matches/KpiRow'
import { MatchGrid } from './features/matches/MatchGrid'
import { useTheme } from './lib/ThemeProvider'
import './App.css'

const api = new ApiClient(import.meta.env.VITE_API_BASE_URL ?? '/api')
const DEFAULT_FROM = '2026-06-29'
const DEFAULT_TO = '2026-07-19'

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="5"/>
      <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
      <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  )
}

function App() {
  const [authenticated, setAuthenticated] = useState(false)
  const [loginError, setLoginError] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [from, setFrom] = useState(DEFAULT_FROM)
  const [to, setTo] = useState(DEFAULT_TO)
  const [sport, setSport] = useState('all')
  const { theme, toggle } = useTheme()

  const login = useMutation({ mutationFn: (pin: string) => api.login(pin) })
  const submitLogin = async (pin: string) => {
    setLoginError(false)
    try {
      await login.mutateAsync(pin)
      setAuthenticated(true)
    } catch {
      setLoginError(true)
    }
  }

  const query = { from, to, ...(sport === 'all' ? {} : { sport }) }
  const metrics = useQuery({ queryKey: ['metrics', query], queryFn: () => api.getMetrics(query), enabled: authenticated })
  const matches = useQuery({ queryKey: ['matches', query], queryFn: () => api.getMatches({ ...query, limit: 50 }), enabled: authenticated })
  const predictionQueries = useQueries({
    queries: (matches.data?.items ?? []).map((m) => ({
      queryKey: ['prediction', m.match_id],
      queryFn: () => api.getPrediction(m.match_id),
      enabled: authenticated,
    })),
  })

  const predictions = useMemo(() => {
    const entries: [string, PredictionResponse | undefined][] = predictionQueries
      .map((q) => [q.data?.match_id, q.data] as [string | undefined, PredictionResponse | undefined])
      .filter(([k]) => k != null) as [string, PredictionResponse | undefined][]
    return new Map(entries)
  }, [predictionQueries])

  // Dynamically derive available sports from loaded matches
  const availableSports = useMemo(() => {
    if (!matches.data?.items) return []
    const sports = [...new Set(matches.data.items.map((m) => m.sport).filter(Boolean))]
    return sports.sort()
  }, [matches.data?.items])

  const handlePinChanged = () => {
    setShowSettings(false)
    void api.logout()
    setAuthenticated(false)
  }

  if (!authenticated) {
    return <PinLogin busy={login.isPending} error={loginError ? 'invalid' : null} onSubmit={submitLogin} />
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark small">SP</span>
          <span>Sport<span className="brand-accent">/</span>Intel</span>
        </div>
        <div className="topbar-actions">
          <span className="live-dot" aria-label="Live data active" /> Live data
          <button
            type="button"
            className="icon-button theme-toggle"
            onClick={toggle}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
          </button>
          <button
            type="button"
            className="icon-button"
            title="Settings"
            onClick={() => setShowSettings((v) => !v)}
            aria-label="Settings"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
          </button>
          <button
            type="button"
            className="logout-button"
            onClick={() => { void api.logout(); setAuthenticated(false) }}
          >
            Lock
          </button>
        </div>
      </header>

      {showSettings && <Settings api={api} onPinChanged={handlePinChanged} />}

      <div className="dashboard-wrap">
        {/* Filter bar */}
        <SportFilterBar
          availableSports={availableSports}
          sport={sport}
          from={from}
          to={to}
          onSportChange={setSport}
          onFromChange={setFrom}
          onToChange={setTo}
        />

        {/* KPI row */}
        {metrics.isLoading && <div className="mc-loading">Memuat metrik…</div>}
        {metrics.data && <KpiRow metrics={metrics.data} />}

        {/* Match grid */}
        <div className="matches-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">EVENT LOG</p>
              <h2>Perlawanan</h2>
            </div>
            <span className="section-count">{matches.data?.total ?? 0} total</span>
          </div>

          {matches.isLoading && <div className="mc-loading">Memuat perlawanan…</div>}
          {matches.isError && <div className="mc-empty">Gagal memuat data. Sila semak sambungan backend.</div>}
          {matches.data && (
            <MatchGrid
              matches={matches.data.items}
              predictions={predictions}
            />
          )}
        </div>
      </div>
    </main>
  )
}

export default App
