export type Color = 'Red' | 'Green' | 'Blue' | 'Purple' | 'Black' | 'Yellow'
export type Category = 'Leader' | 'Character' | 'Event' | 'Stage'

export interface Card {
  id: string
  name: string
  category: Category
  colors: Color[]
  cost: number | null
  life: number | null
  power: number | null
  counter: number | null
  attributes: string[]
  types: string[]
  effect: string
  trigger: string
  rarity: string | null
  set: string
  pack: string | null
  block: number | null
  image: string
  variants: { id: string; image: string }[]
}

export interface Deck {
  id: string
  name: string
  leaderId: string | null
  /** Main deck card counts by card id (Leader not included). */
  cards: Record<string, number>
}
