import { describe, it, expect } from 'vitest'
import { groupMatchesBySport, sportIcon } from './groupMatches'
import type { MatchItem } from './api'

const makeMatch = (overrides: Partial<MatchItem> = {}): MatchItem => ({
  match_id: 'm1',
  date_wib: '2026-07-20T12:00:00Z',
  sport: 'football',
  competition: 'Premier League',
  event: 'Team A vs Team B',
  kickoff_wib: '2026-07-20T12:00:00Z',
  team_a: 'Team A',
  team_b: 'Team B',
  status: 'completed',
  ...overrides,
}) as MatchItem

describe('groupMatchesBySport', () => {
  it('returns empty array for empty input', () => {
    expect(groupMatchesBySport([])).toEqual([])
  })

  it('groups matches by sport preserving order', () => {
    const matches = [
      makeMatch({ match_id: 'm1', sport: 'basketball' }),
      makeMatch({ match_id: 'm2', sport: 'football' }),
      makeMatch({ match_id: 'm3', sport: 'basketball' }),
      makeMatch({ match_id: 'm4', sport: 'tennis' }),
    ]
    const groups = groupMatchesBySport(matches)

    expect(groups).toHaveLength(3)
    expect(groups[0]).toMatchObject({ sport: 'basketball', items: [{ match_id: 'm1' }, { match_id: 'm3' }] })
    expect(groups[1]).toMatchObject({ sport: 'football', items: [{ match_id: 'm2' }] })
    expect(groups[2]).toMatchObject({ sport: 'tennis', items: [{ match_id: 'm4' }] })
  })

  it('sorts sports alphabetically', () => {
    const matches = [
      makeMatch({ match_id: 'm1', sport: 'tennis' }),
      makeMatch({ match_id: 'm2', sport: 'football' }),
      makeMatch({ match_id: 'm3', sport: 'basketball' }),
    ]
    const groups = groupMatchesBySport(matches)

    expect(groups.map((g) => g.sport)).toEqual(['basketball', 'football', 'tennis'])
  })

  it('handles unknown sport gracefully', () => {
    const matches = [makeMatch({ match_id: 'm1', sport: '' }), makeMatch({ match_id: 'm2', sport: 'football' })]
    const groups = groupMatchesBySport(matches)

    expect(groups).toHaveLength(2)
    expect(groups.find((g) => g.sport === '')).toBeDefined()
    expect(groups.find((g) => g.sport === 'football')).toBeDefined()
  })

  it('derives correct icons for known sports', () => {
    expect(sportIcon('football')).toBe('⚽')
    expect(sportIcon('basketball')).toBe('🏀')
    expect(sportIcon('tennis')).toBe('🎾')
    expect(sportIcon('volleyball')).toBe('🏐')
  })

  it('uses default icon for unknown sports', () => {
    expect(sportIcon('rugby')).toBe('🏅')
    expect(sportIcon('unknown')).toBe('🏅')
  })

  it('groups items as a plain array (not Set) so duplicates are preserved', () => {
    const matches = [
      makeMatch({ match_id: 'm1', sport: 'football' }),
      makeMatch({ match_id: 'm2', sport: 'football' }),
    ]
    const groups = groupMatchesBySport(matches)

    expect(groups[0].items).toHaveLength(2)
    expect(groups[0].items[0].match_id).toBe('m1')
    expect(groups[0].items[1].match_id).toBe('m2')
  })
})
