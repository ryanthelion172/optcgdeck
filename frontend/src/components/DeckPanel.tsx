import type { Card, Deck } from '../types'
import { costCurve, countByCategory, DECK_SIZE, deckSize, MAX_COPIES, type CardLookup, type Problem } from '../lib/deck'
import { CardImage } from './CardImage'
import { ColorDots } from './ui'

interface Props {
  deck: Deck
  lookup: CardLookup
  problems: Problem[]
  onChange: (card: Card, delta: number) => void
  onOpen: (card: Card) => void
  onPickLeader: () => void
}

const ORDER = ['Character', 'Event', 'Stage']

export function DeckPanel({ deck, lookup, problems, onChange, onOpen, onPickLeader }: Props) {
  const leader = deck.leaderId ? lookup(deck.leaderId) : undefined
  const size = deckSize(deck)
  const curve = costCurve(deck, lookup)
  const peak = Math.max(1, ...curve)
  const byCat = countByCategory(deck, lookup)

  const entries = Object.entries(deck.cards)
    .map(([id, count]) => ({ card: lookup(id), id, count }))
    .sort((a, b) => {
      const ca = ORDER.indexOf(a.card?.category ?? '')
      const cb = ORDER.indexOf(b.card?.category ?? '')
      if (ca !== cb) return ca - cb
      return (a.card?.cost ?? 0) - (b.card?.cost ?? 0) || a.id.localeCompare(b.id)
    })

  return (
    <section className="flex min-h-0 flex-col">
      <div className="space-y-3 border-b border-slate-800 p-3">
        {leader ? (
          <button onClick={() => onOpen(leader)} className="flex w-full items-center gap-3 rounded-xl bg-slate-900 p-2 text-left">
            <CardImage card={leader} className="!w-14 shrink-0" />
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-wide text-slate-400">Leader</p>
              <p className="truncate font-semibold">{leader.name}</p>
              <p className="flex items-center gap-2 text-xs text-slate-400">
                <ColorDots colors={leader.colors} /> {leader.id} · Life {leader.life} · {leader.power}
              </p>
            </div>
          </button>
        ) : (
          <button
            onClick={onPickLeader}
            className="w-full rounded-xl border border-dashed border-slate-600 p-4 text-sm text-slate-300 hover:bg-slate-900"
          >
            Pick a Leader to start
          </button>
        )}

        <div className="flex items-baseline justify-between">
          <p className={`text-2xl font-bold ${size === DECK_SIZE ? 'text-green-400' : ''}`}>
            {size}
            <span className="text-base font-normal text-slate-400">/{DECK_SIZE}</span>
          </p>
          <p className="text-xs text-slate-400">
            {ORDER.filter((c) => byCat[c]).map((c) => `${byCat[c]} ${c}${byCat[c] === 1 ? '' : 's'}`).join(' · ')}
          </p>
        </div>

        <div aria-label="Cost curve" className="flex h-16 items-end gap-1">
          {curve.map((n, cost) => (
            <div key={cost} className="flex flex-1 flex-col items-center gap-0.5">
              <span className="text-[10px] text-slate-400">{n || ''}</span>
              <div className="w-full rounded-t bg-red-500/80" style={{ height: `${(n / peak) * 36}px` }} />
              <span className="text-[10px] text-slate-500">{cost === 10 ? '10+' : cost}</span>
            </div>
          ))}
        </div>

        {problems.length > 0 ? (
          <ul className="space-y-1 text-xs text-amber-300">
            {problems.slice(0, 5).map((p) => (
              <li key={p.message}>• {p.message}</li>
            ))}
            {problems.length > 5 && <li>• and {problems.length - 5} more</li>}
          </ul>
        ) : (
          <p className="text-xs text-green-400">✓ Deck is legal</p>
        )}
      </div>

      <ul className="min-h-0 flex-1 divide-y divide-slate-800 overflow-y-auto">
        {entries.length === 0 && <li className="p-4 text-sm text-slate-400">No cards yet. Tap + on a card to add it.</li>}
        {entries.map(({ card, id, count }) => (
          <li key={id} className="flex items-center gap-2 px-3 py-1.5">
            {card ? (
              <button onClick={() => onOpen(card)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                <span className="w-6 shrink-0 rounded bg-slate-800 text-center text-sm font-semibold">{card.cost ?? '-'}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{card.name}</span>
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    <ColorDots colors={card.colors} /> {id}
                  </span>
                </span>
              </button>
            ) : (
              <span className="flex-1 text-sm text-red-300">Unknown card {id}</span>
            )}
            {card && (
              <div className="flex shrink-0 items-center gap-1">
                <button
                  aria-label={`Remove one ${card.name}`}
                  onClick={() => onChange(card, -1)}
                  className="h-8 w-8 rounded-full bg-slate-800 text-lg hover:bg-slate-700"
                >
                  −
                </button>
                <span className="w-5 text-center font-semibold">{count}</span>
                <button
                  aria-label={`Add one ${card.name}`}
                  onClick={() => onChange(card, 1)}
                  disabled={count >= MAX_COPIES}
                  className="h-8 w-8 rounded-full bg-slate-800 text-lg hover:bg-slate-700 disabled:opacity-40"
                >
                  +
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
