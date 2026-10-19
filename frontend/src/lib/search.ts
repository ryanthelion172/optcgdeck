import MiniSearch from 'minisearch'
import type { Card, Category, Color } from '../types'

export interface Filters {
  text: string
  colors: Color[]
  category: Category | ''
  cost: number | '' // 10 means 10+
  set: string
  /** Hide cards that can't go in a deck with the current Leader. */
  leaderOnly: boolean
}

export const emptyFilters: Filters = {
  text: '',
  colors: [],
  category: '',
  cost: '',
  set: '',
  leaderOnly: true,
}

export function buildIndex(cards: Card[]): MiniSearch<Card> {
  const index = new MiniSearch<Card>({
    fields: ['id', 'name', 'types', 'effect', 'trigger'],
    extractField: (doc, field) => {
      const value = (doc as unknown as Record<string, unknown>)[field]
      return Array.isArray(value) ? value.join(' ') : String(value ?? '')
    },
    searchOptions: { prefix: true, fuzzy: 0.15, boost: { name: 3, id: 3, types: 2 } },
  })
  index.addAll(cards)
  return index
}

export function filterCards(
  cards: Card[],
  index: MiniSearch<Card>,
  filters: Filters,
  leader: Card | undefined,
): Card[] {
  let pool = cards
  const text = filters.text.trim()
  if (text) {
    const byId = new Map(cards.map((c) => [c.id, c]))
    pool = index
      .search(text, { combineWith: 'AND' })
      .map((r) => byId.get(r.id as string))
      .filter((c): c is Card => !!c)
  }
  return pool.filter((c) => {
    if (filters.colors.length && !c.colors.some((col) => filters.colors.includes(col))) return false
    if (filters.category && c.category !== filters.category) return false
    if (filters.cost !== '') {
      if (c.cost == null) return false
      if (filters.cost === 10 ? c.cost < 10 : c.cost !== filters.cost) return false
    }
    if (filters.set && c.set !== filters.set) return false
    if (filters.leaderOnly && leader) {
      if (c.category === 'Leader') return false
      if (!c.colors.some((col) => leader.colors.includes(col))) return false
    }
    return true
  })
}
