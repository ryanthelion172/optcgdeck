import { useEffect, useMemo, useRef, useState } from 'react'
import type { Card } from '../types'
import { searchCards } from '../lib/search'
import { CardImage } from './CardImage'

/**
 * A search box for picking one card by its name or card number.
 * `large` shows the matches as a grid of card pictures, big enough to tell
 * apart by their art (used when fixing a card the photo scan got wrong).
 */
/** How many matches the large grid shows; it has room to browse more than the small list. */
const LARGE_LIMIT = 60

export function CardSearch({
  cards,
  onPick,
  label,
  large = false,
}: {
  cards: Card[]
  onPick: (card: Card) => void
  label: string
  large?: boolean
}) {
  const [query, setQuery] = useState('')
  const limit = large ? LARGE_LIMIT : undefined
  const matches = useMemo(() => searchCards(cards, query, limit), [cards, query, limit])
  const box = useRef<HTMLDivElement>(null)
  const typed = query.trim() !== ''
  // The large search sits below the scan's card list: once there are results,
  // scroll so the search box is at the top and the results fill the space below.
  useEffect(() => {
    if (large && typed) box.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [large, typed])
  return (
    <div ref={box} className={`flex scroll-mt-2 flex-col ${large ? 'gap-2' : 'gap-1'}`}>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Card name or number, e.g. OP01-016"
        aria-label={label}
        autoFocus={large}
        className={`w-full rounded bg-slate-800 text-slate-100 ${large ? 'px-3 py-2.5 text-base' : 'px-2 py-1.5 text-xs'}`}
      />
      {typed &&
        (large ? (
          <div className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">
              {matches.length === 0
                ? 'No cards match.'
                : matches.length >= LARGE_LIMIT
                  ? `Showing the first ${LARGE_LIMIT} matches. Type more of the name or number to narrow it down.`
                  : `${matches.length} card${matches.length === 1 ? '' : 's'} match. Pick the one in your photo.`}
            </span>
            {matches.length > 0 && (
              <ul className="grid max-h-[60vh] grid-cols-2 gap-2 overflow-y-auto rounded border border-slate-700 bg-slate-950 p-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                {matches.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => onPick(c)}
                      title={`Add ${c.name} (${c.id})`}
                      className="flex w-full flex-col gap-1 rounded p-1 text-left hover:bg-slate-800 focus-visible:bg-slate-800"
                    >
                      <CardImage card={c} showText={false} className="!rounded" />
                      <span className="block truncate text-sm text-slate-200">{c.name}</span>
                      <span className="text-xs text-slate-500">{c.id}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
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
        ))}
    </div>
  )
}
