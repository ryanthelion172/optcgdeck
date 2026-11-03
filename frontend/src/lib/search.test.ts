import { expect, it } from 'vitest'
import type { Card } from '../types'
import { emptyFilters, filterCards } from './search'

const mk = (id: string, category: Card['category'], colors: Card['colors']) =>
  ({ id, category, colors, set: id.split('-')[0] }) as Card
const cards = [
  mk('OP01-001', 'Leader', ['Red']),
  mk('OP01-016', 'Character', ['Red']),
  mk('OP02-050', 'Character', ['Blue']),
  mk('OP02-001', 'Leader', ['Green']),
]
const ids = (cs: Card[]) => cs.map((c) => c.id)

it('shows Leaders until one is chosen', () => {
  expect(ids(filterCards(cards, emptyFilters, false))).toEqual(['OP01-001', 'OP02-001'])
})

it('shows main-deck cards filtered by color and set once a Leader is chosen', () => {
  expect(ids(filterCards(cards, emptyFilters, true))).toEqual(['OP01-016', 'OP02-050'])
  expect(ids(filterCards(cards, { ...emptyFilters, colors: ['Blue'] }, true))).toEqual(['OP02-050'])
  expect(ids(filterCards(cards, { ...emptyFilters, set: 'OP01' }, true))).toEqual(['OP01-016'])
})

it('shows Leaders again when changing Leader', () => {
  expect(ids(filterCards(cards, { ...emptyFilters, leaders: true }, true))).toEqual(['OP01-001', 'OP02-001'])
})
