import type { Card, Deck } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

/** Card art is served by our backend, which downloads and caches it. */
export function cardImageUrl(cardId: string): string {
  return `${API_BASE}/api/cards/${encodeURIComponent(cardId)}/image`
}

/** Throws with the backend's own message (e.g. "Set DATABASE_URL…") when it gives one. */
async function check(resp: Response, what: string): Promise<Response> {
  if (resp.ok) return resp
  const detail = await resp.json().then(
    (d) => (typeof d.detail === 'string' ? d.detail : ''),
    () => '',
  )
  throw new Error(detail || `${what} (${resp.status})`)
}

export async function fetchCards(): Promise<Card[]> {
  const resp = await check(await fetch(`${API_BASE}/api/cards`), 'Could not load cards')
  return resp.json()
}

// Decks belong to a random owner key made on this device. It is the only thing
// the app keeps in the browser; the decks themselves live in the database, and
// the server stores only a hash of the key.
const OWNER_KEY = 'optcg.ownerKey.v1'

function makeKey(): string {
  // getRandomValues works on plain http too (e.g. a phone on your home network).
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

let ownerKey: string | null = null

export function getOwnerKey(): string {
  if (ownerKey) return ownerKey
  try {
    ownerKey = localStorage.getItem(OWNER_KEY)
    if (!ownerKey) {
      ownerKey = makeKey()
      localStorage.setItem(OWNER_KEY, ownerKey)
    }
  } catch {
    // Storage blocked (private mode): decks still save, but only for this visit.
    ownerKey ??= makeKey()
  }
  return ownerKey
}

const ownerHeaders = () => ({ 'X-Owner-Key': getOwnerKey() })

/** The decks saved for this device, most recently changed first. */
export async function fetchDecks(): Promise<Deck[]> {
  const resp = await check(await fetch(`${API_BASE}/api/decks`, { headers: ownerHeaders() }), 'Could not load decks')
  const decks: (Deck & { updatedAt?: string })[] = await resp.json()
  return decks.map(({ id, name, leaderId, cards }) => ({ id, name, leaderId, cards }))
}

/** Creates or replaces a deck. `keepalive` lets the save finish while the page closes. */
export async function saveDeck(deck: Deck, keepalive = false): Promise<void> {
  const { id, name, leaderId, cards } = deck
  await check(
    await fetch(`${API_BASE}/api/decks/${id}`, {
      method: 'PUT',
      headers: { ...ownerHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, leaderId, cards }),
      keepalive,
    }),
    'Could not save the deck',
  )
}

export async function deleteDeck(id: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/decks/${id}`, { method: 'DELETE', headers: ownerHeaders() })
  if (resp.status === 404) return // already gone (or never saved)
  await check(resp, 'Could not delete the deck')
}

export interface ScanResult {
  detected: number
  /** `via`: how the card was identified: 'set code', 'image match', 'name + image match' or 'name'; the scan results add 'confirmed by you' and 'picked by you'. */
  cards: { id: string; count: number; confidence: 'High' | 'Medium' | 'Low'; via?: string[] }[]
  /**
   * Cards found but not identified. `image` is the crop the square detection cut out, as a data: URL;
   * `detail` says what the number reader and image match saw; `closest` is the id of the
   * nearest card the image match found, offered to the user to confirm.
   */
  unmatched: { label: string; image?: string; detail?: string; closest?: string }[]
  /** How many card outlines OpenCV found in the photo (0 means the whole photo was read as one card). */
  cardsFound?: number
  /** What each step saw for each card, for debugging. */
  raw?: unknown
}

/** 'deck': a photo of many cards laid out. 'single': a photo of one card, which can fill the frame. */
export type ScanMode = 'deck' | 'single'

/** Sends a photo to the backend, which finds each card and identifies it. */
export async function scanPhoto(photo: File, mode: ScanMode = 'deck'): Promise<ScanResult> {
  const body = new FormData()
  body.append('photo', photo)
  body.append('mode', mode)
  const resp = await check(await fetch(`${API_BASE}/api/scan`, { method: 'POST', body }), 'Scan failed')
  const result: ScanResult = await resp.json()
  // Debugging aid: open the browser console (F12) to see what each step read for each card.
  console.log('Scan result:', result)
  return result
}
