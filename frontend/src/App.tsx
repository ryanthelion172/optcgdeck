import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import type { Card, Deck } from './types'
import { deleteDeck as deleteDeckOnServer, fetchCards, fetchDecks, saveDeck } from './lib/api'
import { DeckSaver, type SaveStatus } from './lib/deckSaver'
import { changeCount, deckSize, matchesLeader, newDeck, validateDeck, DECK_SIZE } from './lib/deck'
import { emptyFilters, type Filters } from './lib/search'
import { applyTheme, initialTheme, type Theme } from './lib/theme'
import { CardBrowser } from './components/CardBrowser'
import { DeckPanel } from './components/DeckPanel'
import { CardDetail } from './components/CardDetail'
import { DecklistModal } from './components/DecklistModal'
import { ScanModal } from './components/ScanModal'
import { Button } from './components/ui'

function filtersFor(leader: Card | undefined): Filters {
  return { ...emptyFilters, colors: leader ? [...leader.colors] : [] }
}

const SAVE_LABELS: Record<SaveStatus, string> = { saved: 'Saved', saving: 'Saving…', error: 'Not saved' }

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  useEffect(() => applyTheme(theme), [theme])
  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  const [cards, setCards] = useState<Card[] | null>(null)
  const [decks, setDecks] = useState<Deck[] | null>(null)
  const [error, setError] = useState('')
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('saved')
  // The deck objects the server already has. Any deck in state that differs
  // from its entry here gets saved.
  const synced = useRef(new Map<string, Deck>())
  const [saver] = useState(() => new DeckSaver(saveDeck, deleteDeckOnServer, setSaveStatus))

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchCards(), fetchDecks()]).then(
      ([loadedCards, loadedDecks]) => {
        if (cancelled) return
        synced.current = new Map(loadedDecks.map((d) => [d.id, d]))
        // First visit: start with an empty deck (saved like any other change).
        setDecks(loadedDecks.length > 0 ? loadedDecks : [newDeck('My first deck')])
        setCards(loadedCards)
      },
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [])

  // Save every deck that changed since the last render.
  useEffect(() => {
    if (!decks) return
    for (const d of decks) if (synced.current.get(d.id) !== d) saver.schedule(d)
    synced.current = new Map(decks.map((d) => [d.id, d]))
  }, [decks, saver])

  // Send unsaved changes before the page is hidden or closed (e.g. switching apps on a phone).
  useEffect(() => {
    const flush = () => {
      if (document.visibilityState === 'hidden') void saver.flush(true)
    }
    const warn = (e: BeforeUnloadEvent) => {
      if (saveStatus !== 'saved') e.preventDefault()
    }
    document.addEventListener('visibilitychange', flush)
    window.addEventListener('pagehide', flush)
    window.addEventListener('beforeunload', warn)
    return () => {
      document.removeEventListener('visibilitychange', flush)
      window.removeEventListener('pagehide', flush)
      window.removeEventListener('beforeunload', warn)
    }
  }, [saver, saveStatus])

  if (error || !cards || !decks) {
    return (
      <div className="p-6">
        <h1 className="mb-3 text-base font-bold tracking-tight">
          <span className="text-red-500">OPTCG</span> Decks
        </h1>
        {error ? (
          <p className="text-red-300">
            {error}. Is the backend running? Start it with <code>uvicorn app.main:app</code> in the backend folder.
          </p>
        ) : (
          <p className="text-slate-400">Loading cards and decks…</p>
        )}
      </div>
    )
  }
  if (cards.length === 0) {
    return (
      <p className="p-6 text-slate-300">
        The card database is empty. Run <code>python scripts/import_cards.py</code> in the backend folder, then
        restart the backend.
      </p>
    )
  }
  return (
    <Builder
      cards={cards}
      decks={decks}
      setDecks={setDecks}
      saver={saver}
      saveStatus={saveStatus}
      theme={theme}
      onToggleTheme={toggleTheme}
    />
  )
}

function Builder({
  cards,
  decks,
  setDecks,
  saver,
  saveStatus,
  theme,
  onToggleTheme,
}: {
  cards: Card[]
  decks: Deck[]
  setDecks: Dispatch<SetStateAction<Deck[] | null>>
  saver: DeckSaver
  saveStatus: SaveStatus
  theme: Theme
  onToggleTheme: () => void
}) {
  const [currentId, setCurrentId] = useState(decks[0].id)
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [selected, setSelected] = useState<Card | null>(null)
  const [showList, setShowList] = useState(false)
  const [showScan, setShowScan] = useState(false)
  const [tab, setTab] = useState<'cards' | 'deck'>('cards')
  const [deleting, setDeleting] = useState(false)

  const byId = useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards])
  const lookup = useCallback((id: string) => byId.get(id), [byId])
  const sets = useMemo(() => [...new Set(cards.map((c) => c.set))].sort(), [cards])

  const deck = decks.find((d) => d.id === currentId) ?? decks[0]
  const leader = deck.leaderId ? lookup(deck.leaderId) : undefined
  const problems = useMemo(() => validateDeck(deck, lookup), [deck, lookup])

  // Every change is applied to the latest saved deck (not a copy from the last
  // render), so quick taps in a row can't overwrite each other.
  const modifyDeck = (id: string, fn: (d: Deck) => Deck) =>
    setDecks((all) => all && all.map((d) => (d.id === id ? fn(d) : d)))
  const addDeck = (d: Deck) => {
    setDecks((all) => all && [...all, d])
    setCurrentId(d.id)
  }
  const change = (card: Card, delta: number) => modifyDeck(deck.id, (d) => changeCount(d, card, delta))

  const createDeck = () => {
    addDeck(newDeck(`Deck ${decks.length + 1}`))
  }
  const createFromScan = (name: string, leaderId: string | null, scanned: Record<string, number>) => {
    const d = {
      ...newDeck(name),
      leaderId,
      cards: scanned,
    }
    addDeck(d)
    setShowScan(false)
    setTab('deck')
  }
  const renameDeck = () => {
    const name = prompt('Deck name', deck.name)?.trim()
    if (name) modifyDeck(deck.id, (d) => ({ ...d, name: name.slice(0, 100) }))
  }
  const deleteDeck = async () => {
    if (!confirm(`Delete "${deck.name}"?`)) return
    const id = deck.id
    setDeleting(true)
    try {
      await saver.delete(id)
    } catch (e) {
      alert(`${(e as Error).message}. The deck was not deleted.`)
      return
    } finally {
      setDeleting(false)
    }
    const rest = decks.filter((d) => d.id !== id)
    if (rest.length === 0) rest.push(newDeck('My first deck'))
    setDecks((all) => {
      const left = (all ?? []).filter((d) => d.id !== id)
      return left.length > 0 ? left : rest
    })
    setCurrentId(rest[0].id)
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
          onChange={(e) => setCurrentId(e.target.value)}
          className="min-w-0 max-w-[50vw] flex-1 rounded-lg bg-slate-800 px-2 py-2 text-sm sm:flex-none"
        >
          {decks.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <SaveIndicator status={saveStatus} onRetry={() => void saver.retry()} />
        <button
          onClick={onToggleTheme}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          className="ml-auto flex h-9 w-9 items-center sm:order-last justify-center rounded-lg bg-slate-800 text-lg hover:bg-slate-700"
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
        <div className="flex flex-wrap gap-1.5">
          <Button onClick={createDeck} title="New deck">New</Button>
          <Button onClick={renameDeck} title="Rename deck">Rename</Button>
          <Button onClick={() => setShowList(true)} title="Import or export a decklist">
            Decklist
          </Button>
          <Button variant="danger" onClick={() => void deleteDeck()} title="Delete deck" disabled={deleting}>
            Delete
          </Button>
          <Button variant="primary" onClick={() => setShowScan(true)}>
            Create deck from photo
          </Button>
        </div>
      </header>

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
      {showScan && (
        <ScanModal lookup={lookup} deckNames={decks.map((d) => d.name)} onCreate={createFromScan} onClose={() => setShowScan(false)} />
      )}
      {showList && (
        <DecklistModal
          deck={deck}
          lookup={lookup}
          onImport={(leaderId, imported) =>
            modifyDeck(deck.id, (d) => ({ ...d, leaderId: leaderId ?? d.leaderId, cards: imported }))
          }
          onClose={() => setShowList(false)}
        />
      )}
    </div>
  )
}

function SaveIndicator({ status, onRetry }: { status: SaveStatus; onRetry: () => void }) {
  if (status === 'error') {
    return (
      <button onClick={onRetry} className="text-xs text-red-400 underline" title="Try saving again">
        Not saved · Retry
      </button>
    )
  }
  return (
    <span className="text-xs text-slate-500" aria-live="polite">
      {SAVE_LABELS[status]}
    </span>
  )
}
