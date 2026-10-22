import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Card, Deck } from './types'
import { fetchCards } from './lib/api'
import { changeCount, deckSize, matchesLeader, newDeck, validateDeck, DECK_SIZE } from './lib/deck'
import { emptyFilters, type Filters } from './lib/search'
import { loadCurrentId, loadDecks, saveCurrentId, saveDecks } from './lib/storage'
import { applyTheme, initialTheme, type Theme } from './lib/theme'
import { CardBrowser } from './components/CardBrowser'
import { DeckPanel } from './components/DeckPanel'
import { CardDetail } from './components/CardDetail'
import { DecklistModal } from './components/DecklistModal'
import { Button } from './components/ui'

function initialDecks(): { decks: Deck[]; currentId: string } {
  const decks = loadDecks()
  if (decks.length === 0) decks.push(newDeck('My first deck'))
  const saved = loadCurrentId()
  const currentId = decks.some((d) => d.id === saved) ? saved! : decks[0].id
  return { decks, currentId }
}

function filtersFor(leader: Card | undefined): Filters {
  return { ...emptyFilters, colors: leader ? [...leader.colors] : [] }
}

export default function App() {
  const [cards, setCards] = useState<Card[] | null>(null)
  const [error, setError] = useState('')
  const [{ decks, currentId }, setState] = useState(initialDecks)
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [selected, setSelected] = useState<Card | null>(null)
  const [showList, setShowList] = useState(false)
  const [tab, setTab] = useState<'cards' | 'deck'>('cards')
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => applyTheme(theme), [theme])

  useEffect(() => {
    fetchCards().then(setCards, (e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    saveDecks(decks)
    saveCurrentId(currentId)
  }, [decks, currentId])

  const byId = useMemo(() => new Map((cards ?? []).map((c) => [c.id, c])), [cards])
  const lookup = useCallback((id: string) => byId.get(id), [byId])
  const sets = useMemo(() => [...new Set((cards ?? []).map((c) => c.set))].sort(), [cards])

  const deck = decks.find((d) => d.id === currentId)!
  const leader = deck.leaderId ? lookup(deck.leaderId) : undefined
  const problems = useMemo(() => (cards ? validateDeck(deck, lookup) : []), [cards, deck, lookup])

  const updateDeck = (next: Deck) =>
    setState((s) => ({ ...s, decks: s.decks.map((d) => (d.id === next.id ? next : d)) }))
  const change = (card: Card, delta: number) => updateDeck(changeCount(deck, card, delta))

  const createDeck = () => {
    const d = newDeck(`Deck ${decks.length + 1}`)
    setState({ decks: [...decks, d], currentId: d.id })
  }
  const renameDeck = () => {
    const name = prompt('Deck name', deck.name)?.trim()
    if (name) updateDeck({ ...deck, name, updatedAt: Date.now() })
  }
  const deleteDeck = () => {
    if (!confirm(`Delete "${deck.name}"?`)) return
    const rest = decks.filter((d) => d.id !== deck.id)
    if (rest.length === 0) rest.push(newDeck('My first deck'))
    setState({ decks: rest, currentId: rest[0].id })
  }
  const pickLeader = () => {
    setFilters({ ...emptyFilters, leaders: true })
    setTab('cards')
  }
  const addFromBrowser = (card: Card) => {
    change(card, 1)
    // After choosing a Leader, show cards in its colors.
    if (card.category === 'Leader') setFilters(filtersFor(card))
  }

  // When the deck (or card data) changes, start from the Leader's colors.
  const leaderId = deck.leaderId
  useEffect(() => {
    setFilters(filtersFor(leaderId ? byId.get(leaderId) : undefined))
  }, [currentId, byId]) // eslint-disable-line react-hooks/exhaustive-deps

  const size = deckSize(deck)

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
        <h1 className="mr-2 text-base font-bold tracking-tight">
          <span className="text-red-500">OPTCG</span> Decks
        </h1>
        <select
          aria-label="Current deck"
          value={currentId}
          onChange={(e) => setState((s) => ({ ...s, currentId: e.target.value }))}
          className="min-w-0 max-w-[50vw] flex-1 rounded-lg bg-slate-800 px-2 py-2 text-sm sm:flex-none"
        >
          {decks.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <div className="flex gap-1.5">
          <Button onClick={createDeck} title="New deck">New</Button>
          <Button onClick={renameDeck} title="Rename deck">Rename</Button>
          <Button onClick={() => setShowList(true)} title="Import or export a decklist" disabled={!cards}>
            Decklist
          </Button>
          <Button variant="danger" onClick={deleteDeck} title="Delete deck">Delete</Button>
        </div>
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          className="ml-auto flex h-9 w-9 items-center justify-center rounded-lg bg-slate-800 text-lg hover:bg-slate-700"
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </header>

      {error ? (
        <p className="p-6 text-red-300">
          {error}. Is the backend running? Start it with <code>uvicorn app.main:app</code> in the backend folder.
        </p>
      ) : !cards ? (
        <p className="p-6 text-slate-400">Loading cards…</p>
      ) : (
        <main className="grid min-h-0 flex-1 lg:grid-cols-[1fr_380px]">
          <div className={`min-h-0 ${tab === 'cards' ? 'flex' : 'hidden'} flex-col lg:flex`}>
            <CardBrowser
              cards={cards}
              sets={sets}
              filters={filters}
              setFilters={setFilters}
              leader={leader}
              counts={deck.cards}
              onAdd={addFromBrowser}
              onOpen={setSelected}
            />
          </div>
          <div className={`min-h-0 ${tab === 'deck' ? 'flex' : 'hidden'} flex-col border-slate-800 lg:flex lg:border-l`}>
            <DeckPanel
              deck={deck}
              lookup={lookup}
              problems={problems}
              onChange={change}
              onOpen={setSelected}
              onPickLeader={pickLeader}
            />
          </div>
        </main>
      )}

      <nav className="grid grid-cols-2 border-t border-slate-800 pb-[env(safe-area-inset-bottom)] lg:hidden">
        {(['cards', 'deck'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`py-3 text-sm font-medium ${tab === t ? 'text-red-400' : 'text-slate-400'}`}
          >
            {t === 'cards' ? 'Cards' : `Deck ${size}/${DECK_SIZE}`}
          </button>
        ))}
      </nav>

      {selected && (
        <CardDetail
          card={selected}
          count={deck.cards[selected.id] ?? 0}
          isLeader={deck.leaderId === selected.id}
          fitsLeader={matchesLeader(selected, leader)}
          onChange={(delta) => change(selected, delta)}
          onClose={() => setSelected(null)}
        />
      )}
      {showList && cards && (
        <DecklistModal
          deck={deck}
          lookup={lookup}
          onImport={(leaderId, imported) =>
            updateDeck({ ...deck, leaderId: leaderId ?? deck.leaderId, cards: imported, updatedAt: Date.now() })
          }
          onClose={() => setShowList(false)}
        />
      )}
    </div>
  )
}
