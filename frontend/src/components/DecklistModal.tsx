import { useState } from 'react'
import type { Deck } from '../types'
import { exportDecklist, parseDecklist, type CardLookup } from '../lib/deck'
import { Button, Modal } from './ui'

interface Props {
  deck: Deck
  lookup: CardLookup
  onImport: (leaderId: string | null, cards: Record<string, number>) => void
  onClose: () => void
}

export function DecklistModal({ deck, lookup, onImport, onClose }: Props) {
  const [text, setText] = useState(() => exportDecklist(deck))
  const [note, setNote] = useState('')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(exportDecklist(deck))
      setNote('Copied to clipboard.')
    } catch {
      setNote('Could not copy. Select the text and copy it manually.')
    }
  }

  const doImport = () => {
    const result = parseDecklist(text, lookup)
    const total = Object.values(result.cards).reduce((a, b) => a + b, 0)
    if (!result.leaderId && total === 0) {
      setNote('No cards found. Use one card per line, like 4xOP01-016.')
      return
    }
    onImport(result.leaderId, result.cards)
    setNote(
      `Imported ${total} cards${result.leaderId ? ' and a Leader' : ''}.` +
        (result.skipped.length ? ` Skipped: ${result.skipped.join(', ')}` : ''),
    )
  }

  return (
    <Modal title="Decklist" onClose={onClose}>
      <p className="mb-2 text-sm text-slate-400">
        Copy this list to share it, or paste a list (one card per line, like <code>4xOP01-016</code>) and import it to
        replace this deck.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={12}
        spellCheck={false}
        className="w-full rounded-lg bg-slate-800 p-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
      />
      {note && <p className="mt-2 text-sm text-slate-300">{note}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <Button onClick={copy}>Copy decklist</Button>
        <Button variant="primary" onClick={doImport}>
          Import
        </Button>
      </div>
    </Modal>
  )
}
