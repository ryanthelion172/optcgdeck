import type { Card, Deck } from '../types'

export const DECK_SIZE = 50
export const MAX_COPIES = 4

/** Cards whose text lets you run any number of copies. */
export const UNLIMITED_CARDS = new Set(['OP08-072', 'OP16-042'])

/** How many copies of a card a deck may hold. */
export function maxCopies(cardId: string): number {
  return UNLIMITED_CARDS.has(cardId) ? Infinity : MAX_COPIES
}

export type CardLookup = (id: string) => Card | undefined

export function newDeck(name = 'New deck'): Deck {
  return {
    id: crypto.randomUUID(),
    name,
    leaderId: null,
    cards: {},
  }
}

export function deckSize(deck: Deck): number {
  return Object.values(deck.cards).reduce((sum, n) => sum + n, 0)
}

/** True when the card shares at least one color with the Leader. */
export function matchesLeader(card: Card, leader: Card | undefined): boolean {
  if (!leader) return true
  return card.colors.some((c) => leader.colors.includes(c))
}

/** Returns a copy of the deck with `delta` copies of the card added or removed. */
export function changeCount(deck: Deck, card: Card, delta: number): Deck {
  if (card.category === 'Leader') {
    return { ...deck, leaderId: delta > 0 ? card.id : null }
  }
  const current = deck.cards[card.id] ?? 0
  const next = Math.max(0, Math.min(maxCopies(card.id), current + delta))
  const cards = { ...deck.cards }
  if (next === 0) delete cards[card.id]
  else cards[card.id] = next
  return { ...deck, cards }
}

export interface Problem {
  level: 'error' | 'warning'
  message: string
}

/** Checks the standard deck-building rules. An empty list means the deck is legal. */
export function validateDeck(deck: Deck, lookup: CardLookup): Problem[] {
  const problems: Problem[] = []
  const leader = deck.leaderId ? lookup(deck.leaderId) : undefined

  if (!deck.leaderId) problems.push({ level: 'error', message: 'Choose a Leader.' })
  else if (!leader) problems.push({ level: 'error', message: `Unknown Leader ${deck.leaderId}.` })

  const size = deckSize(deck)
  if (size !== DECK_SIZE) {
    const diff = DECK_SIZE - size
    problems.push({
      level: 'error',
      message:
        diff > 0
          ? `Deck has ${size} cards; add ${diff} more.`
          : `Deck has ${size} cards; remove ${-diff}.`,
    })
  }

  for (const [id, count] of Object.entries(deck.cards)) {
    const card = lookup(id)
    if (!card) {
      problems.push({ level: 'error', message: `Unknown card ${id}.` })
      continue
    }
    if (count > maxCopies(id)) {
      problems.push({ level: 'error', message: `${card.name} (${id}): max ${MAX_COPIES} copies.` })
    }
    if (card.category === 'Leader') {
      problems.push({ level: 'error', message: `${card.name} (${id}) is a Leader and can't be in the main deck.` })
    } else if (leader && !matchesLeader(card, leader)) {
      problems.push({
        level: 'error',
        message: `${card.name} (${id}) doesn't share a color with your Leader.`,
      })
    }
  }
  return problems
}

/** Number of cards at each cost, for the cost curve. Index 10 holds 10+. */
export function costCurve(deck: Deck, lookup: CardLookup): number[] {
  const curve = new Array(11).fill(0)
  for (const [id, count] of Object.entries(deck.cards)) {
    const cost = lookup(id)?.cost
    if (cost == null) continue
    curve[Math.min(cost, 10)] += count
  }
  return curve
}

export function countByCategory(deck: Deck, lookup: CardLookup): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [id, count] of Object.entries(deck.cards)) {
    const cat = lookup(id)?.category ?? 'Unknown'
    out[cat] = (out[cat] ?? 0) + count
  }
  return out
}

/**
 * Text decklist in the common "4xOP01-016" format, one card per line,
 * with the Leader first as "1x...".
 */
export function exportDecklist(deck: Deck): string {
  const lines: string[] = []
  if (deck.leaderId) lines.push(`1x${deck.leaderId}`)
  for (const id of Object.keys(deck.cards).sort()) lines.push(`${deck.cards[id]}x${id}`)
  return lines.join('\n')
}

export interface ImportResult {
  leaderId: string | null
  cards: Record<string, number>
  /** Lines that could not be understood or name unknown cards. */
  skipped: string[]
}

const CARD_ID = /\b([A-Z]{1,4}\d{0,2}-\d{3})\b/i
const COUNT = /^\s*(\d+)\s*x?\s*/i

/**
 * Parses a pasted decklist. Accepts "4xOP01-016", "4 OP01-016", "OP01-016 x4",
 * or lines with names such as "4 Nami (OP01-016)". The first Leader found
 * becomes the Leader.
 */
export function parseDecklist(text: string, lookup: CardLookup): ImportResult {
  const result: ImportResult = { leaderId: null, cards: {}, skipped: [] }
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#') || line.startsWith('//')) continue
    // Strip a leading count like "4x" first so it isn't read as part of the id.
    const lead = line.match(COUNT)
    const rest = lead ? line.slice(lead[0].length) : line
    const idMatch = rest.match(CARD_ID)
    if (!idMatch) {
      result.skipped.push(line)
      continue
    }
    const id = idMatch[1].toUpperCase()
    const card = lookup(id)
    if (!card) {
      result.skipped.push(line)
      continue
    }
    const trail = line.match(/x\s*(\d+)\s*$/i)
    const count = lead ? Number(lead[1]) : trail ? Number(trail[1]) : 1
    if (card.category === 'Leader') {
      if (!result.leaderId) result.leaderId = id
      continue
    }
    result.cards[id] = (result.cards[id] ?? 0) + count
  }
  return result
}
