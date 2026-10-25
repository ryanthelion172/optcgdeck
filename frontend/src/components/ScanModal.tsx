import { useEffect, useState } from 'react'
import type { Card } from '../types'
import { scanPhoto, type ScanResult } from '../lib/api'
import { maxCopies, type CardLookup } from '../lib/deck'
import { CardImage } from './CardImage'
import { Button, Modal } from './ui'

interface Props {
  lookup: CardLookup
  onCreate: (leaderId: string | null, cards: Record<string, number>) => void
  onClose: () => void
}

type Row = { card: Card; count: number; confidence: string }

export function ScanModal({ lookup, onCreate, onClose }: Props) {
  const [photo, setPhoto] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ScanResult | null>(null)
  const [rows, setRows] = useState<Row[]>([])

  useEffect(() => {
    if (!photo) return
    const url = URL.createObjectURL(photo)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [photo])

  const pick = (file: File | undefined) => {
    if (!file) return
    setPhoto(file)
    setResult(null)
    setRows([])
    setError('')
  }

  const scan = async () => {
    if (!photo) return
    setBusy(true)
    setError('')
    try {
      const res = await scanPhoto(photo)
      setResult(res)
      setRows(
        res.cards.flatMap((c) => {
          const card = lookup(c.id)
          return card ? [{ card, count: c.count, confidence: c.confidence }] : []
        }),
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const leaderRow = rows.find((r) => r.card.category === 'Leader')
  const mainRows = rows.filter((r) => r.card.category !== 'Leader')
  const total = mainRows.reduce((n, r) => n + r.count, 0)

  const setCount = (id: string, count: number) =>
    setRows((rs) => rs.map((r) => (r.card.id === id ? { ...r, count: Math.max(0, Math.min(maxCopies(id), count)) } : r)))

  const create = () => {
    const cards: Record<string, number> = {}
    for (const r of mainRows) if (r.count > 0) cards[r.card.id] = r.count
    onCreate(leaderRow?.card.id ?? null, cards)
  }

  const fileButton = (label: string, capture: boolean) => (
    <label className="cursor-pointer rounded-lg bg-slate-800 px-3 py-2 text-sm font-medium hover:bg-slate-700">
      {label}
      <input
        type="file"
        accept="image/*"
        {...(capture ? { capture: 'environment' as const } : {})}
        className="hidden"
        onChange={(e) => pick(e.target.files?.[0])}
      />
    </label>
  )

  return (
    <Modal title="Create deck from photo" onClose={onClose}>
      {!result && (
        <div className="space-y-3">
          <p className="text-sm text-slate-400">
            Lay the cards out so each one is clearly visible, then take or choose a photo. Each scan uses one of
            your CardSight scans.
          </p>
          <div className="flex gap-2">
            {fileButton('Take photo', true)}
            {fileButton('Choose photo', false)}
          </div>
          {preview && <img src={preview} alt="Photo to scan" className="max-h-72 w-full rounded-lg object-contain" />}
          {error && <p className="text-sm text-red-300">{error}</p>}
          <div className="flex justify-end">
            <Button variant="primary" onClick={scan} disabled={!photo || busy}>
              {busy ? 'Scanning…' : 'Scan photo'}
            </Button>
          </div>
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <p className="text-sm text-slate-400">
            Found {result.detected} card{result.detected === 1 ? '' : 's'}. Check the list, fix any counts, then
            create the deck. You can keep editing it afterwards.
          </p>
          <p className="text-sm">
            Leader: <span className="font-semibold">{leaderRow ? leaderRow.card.name : 'none found, pick one after'}</span>
            <span className="ml-3 text-slate-400">{total} main-deck cards</span>
          </p>
          <ul className="max-h-[45vh] divide-y divide-slate-800 overflow-y-auto rounded-lg bg-slate-950">
            {mainRows.map((r) => (
              <li key={r.card.id} className="flex items-center gap-2 px-2 py-1.5">
                <CardImage card={r.card} className="!w-10 shrink-0" showText={false} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{r.card.name}</span>
                  <span className="text-xs text-slate-500">
                    {r.card.id}
                    {r.confidence !== 'High' && <span className="ml-2 text-amber-300">{r.confidence} confidence</span>}
                  </span>
                </span>
                <button
                  aria-label={`Remove one ${r.card.name}`}
                  onClick={() => setCount(r.card.id, r.count - 1)}
                  className="h-8 w-8 rounded-full bg-slate-800 hover:bg-slate-700"
                >
                  −
                </button>
                <span className="w-5 text-center font-semibold">{r.count}</span>
                <button
                  aria-label={`Add one ${r.card.name}`}
                  onClick={() => setCount(r.card.id, r.count + 1)}
                  className="h-8 w-8 rounded-full bg-slate-800 hover:bg-slate-700"
                >
                  +
                </button>
              </li>
            ))}
            {mainRows.length === 0 && <li className="p-3 text-sm text-slate-400">No main-deck cards recognised.</li>}
          </ul>
          {result.unmatched.length > 0 && (
            <div className="text-sm text-amber-300">
              Couldn't match {result.unmatched.length} card{result.unmatched.length === 1 ? '' : 's'}; add{' '}
              {result.unmatched.length === 1 ? 'it' : 'them'} by hand:
              <ul className="mt-1 list-disc pl-5 text-slate-400">
                {result.unmatched.map((u, i) => (
                  <li key={i}>{u.label}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button onClick={() => setResult(null)}>Scan another photo</Button>
            <Button variant="primary" onClick={create} disabled={!leaderRow && total === 0}>
              Create deck
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
