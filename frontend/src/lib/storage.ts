import type { Deck } from '../types'

const DECKS_KEY = 'optcg.decks.v1'
const CURRENT_KEY = 'optcg.currentDeck.v1'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage can be full or blocked (private mode); the app keeps working in memory.
  }
}

export const loadDecks = () => read<Deck[]>(DECKS_KEY, [])
export const saveDecks = (decks: Deck[]) => write(DECKS_KEY, decks)
export const loadCurrentId = () => read<string | null>(CURRENT_KEY, null)
export const saveCurrentId = (id: string | null) => write(CURRENT_KEY, id)

/** Calls back with the latest decks when another tab or window saves them. */
export function onDecksChangedElsewhere(callback: (decks: Deck[]) => void): () => void {
  const listener = (e: StorageEvent) => {
    if (e.key === DECKS_KEY) callback(loadDecks())
  }
  window.addEventListener('storage', listener)
  return () => window.removeEventListener('storage', listener)
}
