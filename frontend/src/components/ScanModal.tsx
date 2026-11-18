import { useEffect, useRef, useState } from 'react'
import type { Card } from '../types'
import { scanPhoto, type ScanMode, type ScanResult } from '../lib/api'
import { defaultDeckName, maxCopies, type CardLookup } from '../lib/deck'
import { CardImage } from './CardImage'
import { CardSearch } from './CardSearch'
import { Button, Modal } from './ui'

interface Props {
  /** Every card, for searching by hand when the scan's guess is wrong. */
  cards: Card[]
  lookup: CardLookup
  /** Names already used, so a default 'New deck N' doesn't repeat one. */
  deckNames: string[]
  onCreate: (name: string, leaderId: string | null, cards: Record<string, number>) => void
  onClose: () => void
}

/** `printing`: the alternate art the scan matched (e.g. OP01-016_p1), shown instead of the base art. */
type Row = { card: Card; count: number; confidence: string; via: string[]; printing?: string }

export function ScanModal({ cards, lookup, deckNames, onCreate, onClose }: Props) {
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
  // What the user said about each unmatched card's closest-card guess, by its index.
  // The scanned photo shown full size, to compare against the counts.
  const [photoOpen, setPhotoOpen] = useState(false)
  const [answers, setAnswers] = useState<Record<number, 'yes' | 'no'>>({})
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
        return card ? [{ card, count: c.count, confidence: c.confidence, via: c.via ?? [], printing: c.printing }] : []
      })
      setResult(res)
      setZoomed(null)
      setPhotoOpen(false)
      setAnswers({})
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

  /** The user confirmed the closest card, or searched for the right one: add one copy of it to the deck. */
  const accept = (i: number, card: Card, via = 'confirmed by you', printing?: string) => {
    setAnswers((a) => ({ ...a, [i]: 'yes' }))
    setZoomed((z) => (z === i ? null : z))
    setRows((rs) => {
      const existing = rs.find((r) => r.card.id === card.id)
      if (!existing) return [...rs, { card, count: 1, confidence: 'High', via: [via], printing }]
      return rs.map((r) =>
        r === existing
          ? {
              ...r,
              printing: r.printing ?? printing,
              count: card.category === 'Leader' ? r.count : Math.min(maxCopies(card.id), r.count + 1),
              via: r.via.includes(via) ? r.via : [...r.via, via],
            }
          : r,
      )
    })
  }

  const misses = (result?.unmatched ?? []).map((u, i) => ({ ...u, i })).filter((u) => answers[u.i] !== 'yes')

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
          <div className="flex shrink-0 items-start gap-3">
            <p className="flex-1 text-sm text-slate-400">
              Found {result.detected} card{result.detected === 1 ? '' : 's'}. Check the list against your photo, fix
              any counts, then create the deck. You can keep editing it afterwards.
            </p>
            {preview && (
              <button
                type="button"
                onClick={() => setPhotoOpen((o) => !o)}
                aria-expanded={photoOpen}
                title={photoOpen ? 'Click to hide the large photo' : 'Click to enlarge your photo'}
                className="shrink-0 overflow-hidden rounded border border-slate-700 hover:border-slate-400"
              >
                <img src={preview} alt="Your scanned photo" className="h-16 w-24 bg-slate-950 object-contain" />
              </button>
            )}
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-3 sm:flex-row">
            {photoOpen && preview && (
              <button
                type="button"
                onClick={() => setPhotoOpen(false)}
                title="Click to make the photo small again"
                className="h-[25vh] shrink-0 cursor-zoom-out overflow-hidden rounded-lg bg-slate-950 sm:h-auto sm:w-1/2"
              >
                <img src={preview} alt="Your scanned photo, enlarged" className="h-full w-full object-contain" />
              </button>
            )}
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
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
                {leaderRow && leaderRow.via.length > 0 && (
                  <span className="ml-2 text-xs text-slate-500">via {leaderRow.via.join(', ')}</span>
                )}
                <span className="ml-3 text-slate-400">{total} main-deck cards</span>
              </p>
              <ul className="shrink-0 divide-y divide-slate-800 rounded-lg bg-slate-950">
                {mainRows.map((r) => (
                  <li key={r.card.id} className="flex items-center gap-2 px-2 py-1.5">
                    <CardImage card={r.card} printing={r.printing} className="!w-10 shrink-0" showText={false} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{r.card.name}</span>
                      <span className="text-xs text-slate-500">
                        {r.card.id}
                        {r.via.length > 0 && <span className="ml-2">via {r.via.join(', ')}</span>}
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
              {misses.length > 0 && (
                <div className="shrink-0 text-sm text-amber-300">
                  Couldn't match {misses.length} card{misses.length === 1 ? '' : 's'}. Confirm the closest card, or search for{' '}
                  {misses.length === 1 ? 'it' : 'them'}:
                  <ul className="mt-2 flex flex-wrap gap-3 text-slate-400">
                    {misses.map((u) => {
                      const i = u.i
                      const guess = u.closest && answers[i] !== 'no' ? lookup(u.closest) : undefined
                      const searching = !guess
                      return (
                        <li key={i} className={`flex gap-3 ${searching ? 'w-full flex-col sm:flex-row' : ''}`}>
                          <div className={`flex flex-col gap-1 ${zoomed === i ? 'w-64' : 'w-28'}`}>
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
                            {u.detail && <span className="text-xs leading-tight text-slate-500">{u.detail}</span>}
                            {guess && (
                              <div className="mt-1 flex flex-col gap-1 rounded border border-slate-700 bg-slate-900 p-1.5">
                                <span className="text-xs font-medium text-slate-200">Is this the card?</span>
                                <CardImage card={guess} printing={u.closestPrinting} showText={false} className="!rounded" />
                                <span className="text-xs leading-tight text-slate-300">
                                  {guess.name} <span className="text-slate-500">{guess.id}</span>
                                </span>
                                <div className="flex gap-2">
                                  <button
                                    type="button"
                                    aria-label={`Yes, it's ${guess.name}: add it to the deck`}
                                    title="Yes, add it to the deck"
                                    onClick={() => accept(i, guess, undefined, u.closestPrinting)}
                                    className="flex h-8 flex-1 items-center justify-center rounded bg-green-700 text-lg font-bold text-white hover:bg-green-600"
                                  >
                                    ✓
                                  </button>
                                  <button
                                    type="button"
                                    aria-label={`No, it's not ${guess.name}`}
                                    title="No, it's a different card"
                                    onClick={() => setAnswers((a) => ({ ...a, [i]: 'no' }))}
                                    className="flex h-8 flex-1 items-center justify-center rounded bg-red-700 text-lg font-bold text-white hover:bg-red-600"
                                  >
                                    ✗
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                          {searching && (
                            <div className="flex min-w-0 flex-1 flex-col gap-2 self-start rounded border border-slate-700 bg-slate-900 p-2">
                              <span className="text-sm font-medium text-slate-200">
                                {answers[i] === 'no' ? 'Which card is it? Search to add it:' : 'Search for the card to add it:'}
                              </span>
                              <CardSearch
                                cards={cards}
                                large
                                label={`Search for ${u.label}`}
                                onPick={(card) => accept(i, card, 'picked by you')}
                              />
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
            </div>
          </div>
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
