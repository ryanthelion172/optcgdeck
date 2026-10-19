import type { Card } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

export async function fetchCards(): Promise<Card[]> {
  const resp = await fetch(`${API_BASE}/api/cards`)
  if (!resp.ok) throw new Error(`Could not load cards (${resp.status})`)
  return resp.json()
}
