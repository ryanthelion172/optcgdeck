import type { Card } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

/** Card art is served by our backend, which downloads and caches it. */
export function cardImageUrl(cardId: string): string {
  return `${API_BASE}/api/cards/${encodeURIComponent(cardId)}/image`
}

export async function fetchCards(): Promise<Card[]> {
  const resp = await fetch(`${API_BASE}/api/cards`)
  if (!resp.ok) throw new Error(`Could not load cards (${resp.status})`)
  return resp.json()
}

export interface ScanResult {
  detected: number
  cards: { id: string; count: number; confidence: 'High' | 'Medium' | 'Low' }[]
  unmatched: { label: string; confidence: string }[]
  /** CardSight's raw detections, for debugging. */
  raw?: unknown[]
}

/** Sends a photo to the backend, which identifies the cards with CardSight (one API call). */
export async function scanPhoto(photo: File): Promise<ScanResult> {
  const body = new FormData()
  body.append('photo', photo)
  const resp = await fetch(`${API_BASE}/api/scan`, { method: 'POST', body })
  if (!resp.ok) {
    const detail = await resp.json().then((d) => d.detail as string, () => '')
    throw new Error(detail || `Scan failed (${resp.status})`)
  }
  const result: ScanResult = await resp.json()
  // Debugging aid: open the browser console (F12) to see what CardSight returned.
  console.log('CardSight raw detections:', result.raw)
  console.log('Matched result:', { detected: result.detected, cards: result.cards, unmatched: result.unmatched })
  return result
}
