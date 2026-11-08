import { useEffect, useRef, useState } from 'react'
import type { Card } from '../types'
import { scanPhoto, type ScanMode, type ScanResult } from '../lib/api'
import { defaultDeckName, maxCopies, type CardLookup } from '../lib/deck'
import { CardImage } from './CardImage'
import { Button, Modal } from './ui'

interface Props {
  lookup: CardLookup
  /** Names already used, so a default 'New deck N' doesn't repeat one. */
  deckNames: string[]
  onCreate: (name: string, leaderId: string | null, cards: Record<string, number>) => void
  onClose: () => void
}

type Row = { card: Card; count: number; confidence: string }

export function ScanModal({ lookup, deckNames, onCreate, onClose }: Props) {
  const [mode, setMode] = useState<ScanMode>('deck')
  const [photo, setPhoto] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ScanResult | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [name, setName] = useState('')
  // The unmatched card shown large, if any.
  const [zoomed, setZoomed] = useState<number | null>(null)
  // Counts scans, so a slow answer for an older photo is ignored.
  const scanId = useRef(0)

  useEffect(() => {
    if (!photo) return
    const url = URL.createObjectURL(photo)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [photo])

  const pick = (file: File | undefined) => {
    if (!file) return
    scanId.current++
    setBusy(false)
    setPhoto(file)
    setResult(null)
    setRows([])
    setError('')
  }

  const scan = async () => {
    if (!photo) return
    const id = ++scanId.current
    setBusy(true)
    setError('')
    try {
      const res = await scanPhoto(photo, mode)
      if (id !== scanId.current) return
      const found = res.cards.flatMap((c) => {
        const card = lookup(c.id)
        return card ? [{ card, count: c.count, confidence: c.confidence }] : []
      })
      setResult(res)
      setZoomed(null)
      setRows(found)
      setName(defaultDeckName(found.find((r) => r.card.category === 'Leader')?.card, deckNames))
    } catch (e) {
      if (id === scanId.current) setError((e as Error).message)
    } finally {
      if (id === scanId.current) setBusy(false)
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
    onCreate(name.trim() || defaultDeckName(leaderRow?.card, deckNames), leaderRow?.card.id ?? null, cards)
  }

  const modeButton = (m: ScanMode, label: string) => (
    <button
      type="button"
      role="radio"
      aria-checked={mode === m}
      disabled={busy}
      onClick={() => setMode(m)}
      className={`rounded-md px-3 py-1.5 text-sm font-medium ${
        mode === m ? 'bg-slate-600 text-white' : 'text-slate-400 hover:text-slate-200 disabled:opacity-50'
      }`}
    >
      {label}
    </button>
  )

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
    <Modal title="Create deck from photo" onClose={onClose} large>
      {!result && (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div role="radiogroup" aria-label="What's in the photo" className="flex w-fit gap-1 rounded-lg bg-slate-800 p-1">
            {modeButton('deck', 'Whole deck')}
            {modeButton('single', 'One card')}
          </div>
          <p className="text-sm text-slate-400">
            {mode === 'deck'
              ? 'Lay out one copy of each card, flat and not overlapping, on a plain background that stands out from the cards. Then take or choose a photo. You can set how many copies of each card after the scan.'
              : 'Take or choose a photo of one card. It can fill most of the photo. You can set how many copies after the scan.'}
          </p>
          <div className="flex gap-2">
            {fileButton('Take photo', true)}
            {fileButton('Choose photo', false)}
          </div>
          {preview ? (
            <img src={preview} alt="Photo to scan" className="min-h-0 w-full flex-1 rounded-lg object-contain" />
          ) : (
            <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-dashed border-slate-600 text-sm text-slate-500">
              Your photo will show here
            </div>
          )}
          {error && <p className="text-sm text-red-300">{error}</p>}
          <div className="flex justify-end">
            <Button variant="primary" onClick={scan} disabled={!photo || busy}>
              {busy ? 'Scanning…' : 'Scan photo'}
            </Button>
          </div>
        </div>
      )}

      {result && (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <p className="text-sm text-slate-400">
            Found {result.detected} card{result.detected === 1 ? '' : 's'}. Check the list, fix any counts, then
            create the deck. You can keep editing it afterwards.
          </p>
          <label className="flex shrink-0 flex-col gap-1 text-sm">
            <span className="text-slate-400">Deck name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              className="rounded-lg bg-slate-800 px-3 py-2"
            />
          </label>
          <p className="text-sm">
            Leader: <span className="font-semibold">{leaderRow ? leaderRow.card.name : 'none found, pick one after'}</span>
            <span className="ml-3 text-slate-400">{total} main-deck cards</span>
          </p>
          <ul className="min-h-0 flex-1 divide-y divide-slate-800 overflow-y-auto rounded-lg bg-slate-950">
            {mainRows.map((r) => (
              <li key={r.card.id} className="flex items-center gap-2 px-2 py-1.5">
                <CardImage card={r.card} className="!w-10 shrink-0" showText={false} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{r.card.name}</span>
                  <span className="text-xs text-slate-500">
                    {r.card.id}
                    {r.confidence !== 'High' && <span className="block text-amber-300">{r.confidence} confidence</span>}
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
            <div className="max-h-80 shrink-0 overflow-y-auto text-sm text-amber-300">
              Couldn't match {result.unmatched.length} card{result.unmatched.length === 1 ? '' : 's'}; add{' '}
              {result.unmatched.length === 1 ? 'it' : 'them'} by hand:
              <ul className="mt-2 flex flex-wrap gap-3 text-slate-400">
                {result.unmatched.map((u, i) => (
                  <li key={i} className={`flex flex-col gap-1 ${zoomed === i ? 'w-64' : 'w-24'}`}>
                    {u.image ? (
                      <button type="button" onClick={() => setZoomed(zoomed === i ? null : i)} title="Click to enlarge">
                        <img
                          src={u.image}
                          alt={`What the scan cut out for: ${u.label}`}
                          className="aspect-[63/88] w-full rounded border border-slate-700 bg-slate-950 object-contain"
                        />
                      </button>
                    ) : (
                      <div className="flex aspect-[63/88] w-full items-center justify-center rounded border border-dashed border-slate-700 p-1 text-center text-xs text-slate-500">
                        No card outline found
                      </div>
                    )}
                    <span className="text-xs leading-tight">{u.label}</span>
                  </li>
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
