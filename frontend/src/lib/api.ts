import type { ValidationStatus } from './validation'

export interface AuthResponse { authenticated: boolean }
export interface MatchItem {
  match_id: string
  date_wib: string
  sport: string
  competition: string
  event: string
  kickoff_wib: string | null
  team_a: string | null
  team_b: string | null
  status: string
}
export interface MatchesResponse { items: MatchItem[]; total: number; limit: number; offset: number }
export interface PredictionResponse {
  match_id: string
  predicted_outcome: string | null
  predicted_score_or_result: string | null
  confidence_percent: number | null
  confidence_breakdown: Record<string, number> | null
  no_pick: boolean
  DATA_SOURCE_DEGRADED: boolean
  accuracy_excluded: boolean
  validation_status: ValidationStatus | null
  actual_result: string | null
  actual_winner: string | null
}
export interface MetricsResponse {
  evaluated_count: number
  correct_count: number
  partial_count: number
  incorrect_count: number
  excluded_count: number
  strict_accuracy_percent: number | null
  lenient_accuracy_percent: number | null
}
export interface AccuracyQuery { from?: string; to?: string; sport?: string; limit?: number; offset?: number }

type FetchLike = typeof fetch
const defaultFetch: FetchLike = (...args) => globalThis.fetch(...args)

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly fetchImpl: FetchLike

  constructor(baseUrl = '', fetchImpl: FetchLike = defaultFetch) {
    this.baseUrl = baseUrl
    this.fetchImpl = fetchImpl
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
    if (!response.ok) {
      throw new ApiError(response.status, 'Request failed')
    }
    return response.json() as Promise<T>
  }

  login(pin: string) {
    return this.request<AuthResponse>('/auth/pin', { method: 'POST', body: JSON.stringify({ pin }) })
  }

  logout() {
    return this.request<{ logged_out: boolean }>('/auth/logout', { method: 'POST' })
  }

  changePin(currentPin: string, newPin: string) {
    return this.request<{ pin_changed: boolean }>('/auth/pin', {
      method: 'PATCH',
      body: JSON.stringify({ current_pin: currentPin, new_pin: newPin }),
    })
  }

  getMatches(query: AccuracyQuery = {}) {
    return this.request<MatchesResponse>(`/matches?${this.toQuery(query)}`)
  }

  getPrediction(matchId: string) {
    return this.request<PredictionResponse>(`/predictions/${encodeURIComponent(matchId)}`)
  }

  getMetrics(query: AccuracyQuery = {}) {
    return this.request<MetricsResponse>(`/metrics/accuracy?${this.toQuery(query)}`)
  }

  healthReady() {
    return this.request<{ status: string }>('/health/ready')
  }

  private toQuery(query: AccuracyQuery) {
    return new URLSearchParams(Object.entries(query).filter((entry): entry is [string, string] => Boolean(entry[1]))).toString()
  }
}
