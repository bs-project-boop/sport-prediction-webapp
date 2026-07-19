import { describe, expect, it, vi } from 'vitest'
import { ApiClient, type MetricsResponse } from './api'

describe('ApiClient', () => {
  it('sends the PIN and returns the auth response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ authenticated: true }), { status: 200 }))
    const client = new ApiClient('/api', fetchMock)

    await expect(client.login('123456')).resolves.toEqual({ authenticated: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/pin', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ pin: '123456' }),
    }))
  })

  it('decodes the three-category accuracy response', async () => {
    const metrics: MetricsResponse = {
      evaluated_count: 7,
      correct_count: 3,
      partial_count: 1,
      incorrect_count: 3,
      excluded_count: 142,
      strict_accuracy_percent: 42.86,
      lenient_accuracy_percent: 57.14,
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(metrics), { status: 200 }))
    const client = new ApiClient('/api', fetchMock)

    await expect(client.getMetrics({ from: '2026-06-29', to: '2026-07-19' })).resolves.toEqual(metrics)
    expect(fetchMock.mock.calls[0][0]).toContain('/api/metrics/accuracy?from=2026-06-29&to=2026-07-19')
  })
})
