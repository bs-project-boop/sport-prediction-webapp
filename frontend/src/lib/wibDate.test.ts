import { describe, it, expect } from 'vitest'
import { todayWIB, shiftDate } from './wibDate'

describe('todayWIB', () => {
  it('returns YYYY-MM-DD', () => {
    expect(todayWIB()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('uses UTC+7 boundary (UTC 16:00 = next WIB day)', () => {
    // 2026-07-21T16:00:00Z is 2026-07-21T23:00:00 WIB (still same day)
    const sameDay = new Date('2026-07-21T16:00:00Z')
    expect(todayWIB(sameDay)).toBe('2026-07-21')
    // 2026-07-21T17:00:00Z is 2026-07-22T00:00:00 WIB (next day)
    const nextDay = new Date('2026-07-21T17:00:00Z')
    expect(todayWIB(nextDay)).toBe('2026-07-22')
  })

  it('rolls back at the other boundary (UTC 16:59 → still 21st, 17:00 → 22nd)', () => {
    expect(todayWIB(new Date('2026-07-21T16:59:00Z'))).toBe('2026-07-21')
    expect(todayWIB(new Date('2026-07-21T17:00:00Z'))).toBe('2026-07-22')
  })
})

describe('shiftDate', () => {
  it('positive shift', () => {
    expect(shiftDate('2026-07-21', 1)).toBe('2026-07-22')
  })
  it('negative shift', () => {
    expect(shiftDate('2026-07-01', -1)).toBe('2026-06-30')
  })
  it('crosses month boundary', () => {
    expect(shiftDate('2026-01-31', 1)).toBe('2026-02-01')
  })
  it('crosses year boundary', () => {
    expect(shiftDate('2026-12-31', 1)).toBe('2027-01-01')
  })
})