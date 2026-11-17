import { useMemo, useState } from 'react'
import type { Card } from '../types'
import { searchCards } from '../lib/search'
import { CardImage } from './CardImage'

/** A search box for picking one card by its name or card number. */
export function CardSearch({ cards, onPick, label }: { cards: Card[]; onPick: (card: Card) => void; label: string }) {
  const [query, setQuery] = useState('')
  const matches = useMemo(() => searchCards(cards, query), [cards, query])
  return (
    <div className="flex flex-col gap-1">
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Card name or number, e.g. OP01-016"
        aria-label={label}
        className="w-full rounded bg-slate-800 px-2 py-1.5 text-xs text-slate-100"
      />
      {query.trim() && (
        <ul className="max-h-56 overflow-y-auto rounded border border-slate-700 bg-slate-950">
          {matches.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onPick(c)}
                className="flex w-full items-center gap-2 px-1.5 py-1 text-left hover:bg-slate-800"
              >
                <CardImage card={c} showText={false} className="!w-8 shrink-0 !rounded" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs text-slate-200">{c.name}</span>
                  <span className="text-xs text-slate-500">{c.id}</span>
                </span>
              </button>
            </li>
          ))}
          {matches.length === 0 && <li className="p-2 text-xs text-slate-500">No cards match.</li>}
        </ul>
      )}
    </div>
  )
}
