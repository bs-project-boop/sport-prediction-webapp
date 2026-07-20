import type { MatchItem } from './api'

export interface MatchGroup {
  sport: string
  icon: string
  items: MatchItem[]
}

const SPORT_ICONS: Record<string, string> = {
  football: '⚽',
  basketball: '🏀',
  tennis: '🎾',
  volleyball: '🏐',
  baseball: '⚾',
  hockey: '🏒',
  default: '🏅',
}

export function sportIcon(sport: string): string {
  return SPORT_ICONS[sport.toLowerCase()] ?? SPORT_ICONS.default
}

export function groupMatchesBySport(matches: MatchItem[]): MatchGroup[] {
  const map = new Map<string, MatchItem[]>()
  for (const match of matches) {
    const key = match.sport ?? 'unknown'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(match)
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([sport, items]) => ({ sport, icon: sportIcon(sport), items }))
}
