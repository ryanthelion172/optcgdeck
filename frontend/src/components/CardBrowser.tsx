import { useMemo, useState } from 'react'
import type { Card, Color } from '../types'
import { filterCards, type Filters } from '../lib/search'
import { maxCopies } from '../lib/deck'
import { CardImage } from './CardImage'
import { COLOR_STYLES } from './colors'

const COLORS: Color[] = ['Red', 'Green', 'Blue', 'Purple', 'Black', 'Yellow']
const PAGE = 60

interface Props {
  cards: Card[]
  sets: string[]
  filters: Filters
  setFilters: (f: Filters) => void
  leader: Card | undefined
  counts: Record<string, number>
  onAdd: (card: Card) => void
  onOpen: (card: Card) => void
}

export function CardBrowser({ cards, sets, filters, setFilters, leader, counts, onAdd, onOpen }: Props) {
  const [limit, setLimit] = useState(PAGE)
  const results = useMemo(() => filterCards(cards, filters, !!leader), [cards, filters, leader])
  const pickingLeader = filters.leaders || !leader

  const update = (patch: Partial<Filters>) => {
    setLimit(PAGE)
    setFilters({ ...filters, ...patch })
  }
  const toggleColor = (c: Color) =>
    update({ colors: filters.colors.includes(c) ? filters.colors.filter((x) => x !== c) : [...filters.colors, c] })

  return (
    <section className="flex min-h-0 flex-col">
      <div className="space-y-2 border-b border-slate-800 p-3">
        {pickingLeader && (
          <div className="flex items-center justify-between rounded-lg bg-slate-900 px-3 py-2 text-sm">
            <span>Choose a Leader</span>
            {leader && (
              <button onClick={() => update({ leaders: false })} className="text-slate-400 hover:text-slate-200">
                Cancel
              </button>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-1.5">
          {COLORS.map((c) => (
            <button
              key={c}
              onClick={() => toggleColor(c)}
              aria-pressed={filters.colors.includes(c)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium ${
                filters.colors.includes(c) ? COLOR_STYLES[c] : 'bg-slate-800 text-slate-300'
              }`}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="Set"
            className="rounded-lg bg-slate-800 px-2 py-2 text-sm"
            value={filters.set}
            onChange={(e) => update({ set: e.target.value })}
          >
            <option value="">All sets</option>
            {sets.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <span className="text-xs text-slate-500">
            {results.length} {pickingLeader ? 'Leaders' : 'cards'}
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 xl:grid-cols-6">
          {results.slice(0, limit).map((card) => {
            const isLeaderCard = card.category === 'Leader'
            const count = isLeaderCard ? (leader?.id === card.id ? 1 : 0) : (counts[card.id] ?? 0)
            const full = !isLeaderCard && count >= maxCopies(card.id)
            return (
              <li key={card.id} className="relative">
                <button className="block w-full" onClick={() => onOpen(card)} aria-label={`Details for ${card.name}`}>
                  <CardImage card={card} />
                </button>
                {count > 0 && (
                  <span className="absolute left-1 top-1 rounded-md bg-black/80 px-1.5 text-sm font-bold">
                    {isLeaderCard ? 'L' : `${count}`}
                  </span>
                )}
                <button
                  onClick={() => onAdd(card)}
                  disabled={full}
                  aria-label={isLeaderCard ? `Use ${card.name} as Leader` : `Add ${card.name}`}
                  className="absolute bottom-1 right-1 flex h-9 w-9 items-center justify-center rounded-full bg-red-600 text-xl font-bold shadow-lg hover:bg-red-500 disabled:bg-slate-700"
                >
                  {isLeaderCard ? '★' : '+'}
                </button>
              </li>
            )
          })}
        </ul>
        {results.length > limit && (
          <button
            onClick={() => setLimit(limit + PAGE * 2)}
            className="mt-3 w-full rounded-lg bg-slate-800 py-2 text-sm hover:bg-slate-700"
          >
            Show more ({results.length - limit} left)
          </button>
        )}
      </div>
    </section>
  )
}
