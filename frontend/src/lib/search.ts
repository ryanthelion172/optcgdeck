import type { Card, Color } from '../types'

export interface Filters {
  colors: Color[]
  set: string
  /** Show Leaders so one can be picked, instead of main-deck cards. */
  leaders: boolean
}

export const emptyFilters: Filters = { colors: [], set: '', leaders: false }

/**
 * Basic browsing: by set and color only. Leaders are shown while picking a
 * Leader (or when the deck has none yet); otherwise main-deck cards are shown.
 */
export function filterCards(cards: Card[], filters: Filters, hasLeader: boolean): Card[] {
  const pickingLeader = filters.leaders || !hasLeader
  return cards.filter((c) => {
    if ((c.category === 'Leader') !== pickingLeader) return false
    if (filters.colors.length && !c.colors.some((col) => filters.colors.includes(col))) return false
    if (filters.set && c.set !== filters.set) return false
    return true
  })
}

/** Lower case with spaces and dashes taken out, so "op01 016" finds "OP01-016". */
const squash = (s: string) => s.toLowerCase().replace(/[\s-]+/g, '')

/**
 * Cards whose name or card number (set code) contains the query, best matches
 * first: an exact number, then numbers and names that start with it, then the rest.
 */
export function searchCards(cards: Card[], query: string, limit = 30): Card[] {
  const q = query.trim().toLowerCase()
  const qs = squash(q)
  if (!qs) return []
  const scored: [number, Card][] = []
  for (const c of cards) {
    const id = squash(c.id)
    const name = c.name.toLowerCase()
    let rank: number
    if (id === qs) rank = 0
    else if (id.startsWith(qs)) rank = 1
    else if (name.startsWith(q)) rank = 2
    else if (name.includes(q)) rank = 3
    else if (id.includes(qs)) rank = 4
    else continue
    scored.push([rank, c])
  }
  scored.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name) || a[1].id.localeCompare(b[1].id))
  return scored.slice(0, limit).map(([, c]) => c)
}
