import { describe, expect, it } from 'vitest'
import type { Card, Deck } from '../types'
import { changeCount, costCurve, exportDecklist, parseDecklist, validateDeck } from './deck'

function card(id: string, over: Partial<Card> = {}): Card {
  return {
    id,
    name: id,
    category: 'Character',
    colors: ['Red'],
    cost: 1,
    life: null,
    power: 1000,
    counter: 1000,
    attributes: [],
    types: [],
    effect: '',
    trigger: '',
    rarity: 'C',
    set: id.split('-')[0],
    pack: null,
    block: 1,
    image: '',
    variants: [],
    ...over,
  }
}

const leader = card('OP01-001', { category: 'Leader', colors: ['Red', 'Green'], cost: null, life: 5 })
const db: Record<string, Card> = { [leader.id]: leader }
for (let i = 10; i < 30; i++) db[`OP01-0${i}`] = card(`OP01-0${i}`, { cost: i % 8 })
db['OP02-050'] = card('OP02-050', { colors: ['Blue'] })
const lookup = (id: string) => db[id]

function legalDeck(): Deck {
  const cards: Record<string, number> = {}
  // 12 x 4 + 1 x 2 = 50
  for (let i = 10; i < 22; i++) cards[`OP01-0${i}`] = 4
  cards['OP01-022'] = 2
  return { id: 'd', name: 'Test', leaderId: leader.id, cards, updatedAt: 0 }
}

describe('validateDeck', () => {
  it('accepts a legal 50-card deck', () => {
    expect(validateDeck(legalDeck(), lookup)).toEqual([])
  })

  it('requires a Leader and exactly 50 cards', () => {
    const deck = { ...legalDeck(), leaderId: null, cards: { 'OP01-010': 4 } }
    const msgs = validateDeck(deck, lookup).map((p) => p.message)
    expect(msgs).toContain('Choose a Leader.')
    expect(msgs).toContain('Deck has 4 cards; add 46 more.')
  })

  it('flags cards that do not share a color with the Leader', () => {
    const deck = legalDeck()
    deck.cards['OP01-022'] = 1
    deck.cards['OP02-050'] = 1
    expect(validateDeck(deck, lookup).map((p) => p.message)).toEqual([
      "OP02-050 (OP02-050) doesn't share a color with your Leader.",
    ])
  })
})

describe('changeCount', () => {
  it('caps copies at 4 and removes at 0', () => {
    let deck = legalDeck()
    deck = changeCount(deck, db['OP01-010'], 1)
    expect(deck.cards['OP01-010']).toBe(4)
    deck = changeCount(deck, db['OP01-010'], -4)
    expect(deck.cards['OP01-010']).toBeUndefined()
  })

  it('sets the Leader instead of adding it to the deck', () => {
    const deck = changeCount({ ...legalDeck(), leaderId: null }, leader, 1)
    expect(deck.leaderId).toBe(leader.id)
  })
})

describe('decklist text', () => {
  it('round-trips through export and parse', () => {
    const deck = legalDeck()
    const parsed = parseDecklist(exportDecklist(deck), lookup)
    expect(parsed.leaderId).toBe(deck.leaderId)
    expect(parsed.cards).toEqual(deck.cards)
    expect(parsed.skipped).toEqual([])
  })

  it('understands other common formats and skips junk', () => {
    const text = '4 OP01-010\nop01-011 x3\n2 Some Name (OP01-012)\nhello\n1xZZ99-999'
    const parsed = parseDecklist(text, lookup)
    expect(parsed.cards).toEqual({ 'OP01-010': 4, 'OP01-011': 3, 'OP01-012': 2 })
    expect(parsed.skipped).toEqual(['hello', '1xZZ99-999'])
  })
})

it('builds a cost curve', () => {
  const curve = costCurve(legalDeck(), lookup)
  expect(curve.reduce((a, b) => a + b, 0)).toBe(50)
})
