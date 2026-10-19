import { useMemo, useState } from 'react'
import type MiniSearch from 'minisearch'
import type { Card, Category, Color } from '../types'
import { filterCards, type Filters } from '../lib/search'
import { MAX_COPIES } from '../lib/deck'
import { CardImage } from './CardImage'
import { COLOR_STYLES } from './colors'

const COLORS: Color[] = ['Red', 'Green', 'Blue', 'Purple', 'Black', 'Yellow']
const CATEGORIES: Category[] = ['Leader', 'Character', 'Event', 'Stage']
const PAGE = 60

interface Props {
  cards: Card[]
  index: MiniSearch<Card>
  sets: string[]
  filters: Filters
  setFilters: (f: Filters) => void
  leader: Card | undefined
  counts: Record<string, number>
  onAdd: (card: Card) => void
  onOpen: (card: Card) => void
}

export function CardBrowser({ cards, index, sets, filters, setFilters, leader, counts, onAdd, onOpen }: Props) {
  const [limit, setLimit] = useState(PAGE)
  const results = useMemo(() => filterCards(cards, index, filters, leader), [cards, index, filters, leader])

  const update = (patch: Partial<Filters>) => {
    setLimit(PAGE)
    setFilters({ ...filters, ...patch })
  }
  const toggleColor = (c: Color) =>
    update({ colors: filters.colors.includes(c) ? filters.colors.filter((x) => x !== c) : [...filters.colors, c] })

  const selectClass = 'rounded-lg bg-slate-800 px-2 py-2 text-sm'

  return (
    <section className="flex min-h-0 flex-col">
      <div className="space-y-2 border-b border-slate-800 p-3">
        <input
          type="search"
          value={filters.text}
          onChange={(e) => update({ text: e.target.value })}
          placeholder="Search name, type, effect or card number"
          className="w-full rounded-lg bg-slate-800 px-3 py-2 text-base placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500"
        />
        <div className="flex flex-wrap gap-1.5">
          {COLORS.map((c) => (
            <button
              key={c}
              onClick={() => toggleColor(c)}
              aria-pressed={filters.colors.includes(c)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                filters.colors.includes(c) ? COLOR_STYLES[c] : 'bg-slate-800 text-slate-300'
              }`}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Card type"
            className={selectClass}
            value={filters.category}
            onChange={(e) => update({ category: e.target.value as Category | '' })}
          >
            <option value="">All types</option>
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <select
            aria-label="Cost"
            className={selectClass}
            value={filters.cost}
            onChange={(e) => update({ cost: e.target.value === '' ? '' : Number(e.target.value) })}
          >
            <option value="">Any cost</option>
            {Array.from({ length: 11 }, (_, i) => (
              <option key={i} value={i}>
                Cost {i === 10 ? '10+' : i}
              </option>
            ))}
          </select>
          <select
            aria-label="Set"
            className={selectClass}
            value={filters.set}
            onChange={(e) => update({ set: e.target.value })}
          >
            <option value="">All sets</option>
            {sets.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {leader && (
            <label className="flex items-center gap-1.5 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={filters.leaderOnly}
                onChange={(e) => update({ leaderOnly: e.target.checked })}
                className="accent-red-500"
              />
              Only {leader.colors.join('/')}
            </label>
          )}
        </div>
        <p className="text-xs text-slate-500">
          {results.length} cards{!leader && ' · start by picking a Leader'}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 xl:grid-cols-6">
          {results.slice(0, limit).map((card) => {
            const count = card.category === 'Leader' ? (leader?.id === card.id ? 1 : 0) : (counts[card.id] ?? 0)
            const full = card.category !== 'Leader' && count >= MAX_COPIES
            return (
              <li key={card.id} className="relative">
                <button className="block w-full" onClick={() => onOpen(card)} aria-label={`Details for ${card.name}`}>
                  <CardImage card={card} />
                </button>
                {count > 0 && (
                  <span className="absolute left-1 top-1 rounded-md bg-black/80 px-1.5 text-sm font-bold">
                    {card.category === 'Leader' ? 'L' : `${count}`}
                  </span>
                )}
                <button
                  onClick={() => onAdd(card)}
                  disabled={full}
                  aria-label={card.category === 'Leader' ? `Use ${card.name} as Leader` : `Add ${card.name}`}
                  className="absolute bottom-1 right-1 flex h-9 w-9 items-center justify-center rounded-full bg-red-600 text-xl font-bold shadow-lg hover:bg-red-500 disabled:bg-slate-700"
                >
                  {card.category === 'Leader' ? '★' : '+'}
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
