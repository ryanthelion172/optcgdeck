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
