/**
 * Date utilities — Asia/Jakarta (WIB, UTC+7) timezone helpers.
 *
 * Why hand-rolled: project has no luxon/date-fns-tz dep. Server-side data is
 * in WIB, so "today" must be WIB-today regardless of the user's local TZ
 * (otherwise a user browsing from UTC at 06:00 would see "yesterday").
 */

const WIB_OFFSET_MINUTES = 7 * 60 // +07:00, no DST

/**
 * Return YYYY-MM-DD for the current moment in WIB.
 */
export function todayWIB(now: Date = new Date()): string {
  // Convert to WIB by adding the offset, then read the date parts.
  const utcMs = now.getTime()
  const wibMs = utcMs + WIB_OFFSET_MINUTES * 60_000
  const wib = new Date(wibMs)
  const y = wib.getUTCFullYear()
  const m = String(wib.getUTCMonth() + 1).padStart(2, '0')
  const d = String(wib.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/**
 * Shift a YYYY-MM-DD string by N days in calendar terms (no TZ math needed).
 */
export function shiftDate(yyyyMmDd: string, days: number): string {
  const [y, m, d] = yyyyMmDd.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + days)
  const yy = dt.getUTCFullYear()
  const mm = String(dt.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(dt.getUTCDate()).padStart(2, '0')
  return `${yy}-${mm}-${dd}`
}