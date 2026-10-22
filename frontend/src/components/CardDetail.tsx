import type { Card } from '../types'
import { maxCopies } from '../lib/deck'
import { CardImage } from './CardImage'
import { Button, ColorDots, Modal } from './ui'

interface Props {
  card: Card
  count: number
  isLeader: boolean
  fitsLeader: boolean
  onChange: (delta: number) => void
  onClose: () => void
}

export function CardDetail({ card, count, isLeader, fitsLeader, onChange, onClose }: Props) {
  const stats = [
    card.category === 'Leader' ? ['Life', card.life] : ['Cost', card.cost],
    ['Power', card.power],
    ['Counter', card.counter],
  ].filter(([, v]) => v != null)

  return (
    <Modal title={card.name} onClose={onClose} large>
      <div className="flex shrink-0 flex-col gap-4 sm:min-h-0 sm:flex-1 sm:shrink sm:flex-row">
        <CardImage card={card} className="shrink-0 sm:h-full sm:!w-auto" />
        <div className="space-y-2 text-sm sm:min-h-0 sm:flex-1 sm:overflow-y-auto sm:text-base">
          <p className="flex items-center gap-2 text-slate-400">
            <ColorDots colors={card.colors} /> {card.id} · {card.category} · {card.rarity}
          </p>
          <div className="flex flex-wrap gap-2">
            {stats.map(([label, value]) => (
              <span key={label as string} className="whitespace-nowrap rounded bg-slate-800 px-2 py-1">
                <span className="text-slate-400">{label}</span> {value}
              </span>
            ))}
          </div>
          {card.types.length > 0 && <p className="text-slate-300">{card.types.join(' / ')}</p>}
          {card.attributes.length > 0 && <p className="text-slate-400">Attribute: {card.attributes.join(', ')}</p>}
          {card.effect && <p className="whitespace-pre-line leading-relaxed">{card.effect}</p>}
          {card.trigger && <p className="whitespace-pre-line text-amber-200">{card.trigger}</p>}
        </div>
      </div>
      <div className="mt-4 flex shrink-0 items-center justify-end gap-2">
        {card.category === 'Leader' ? (
          isLeader ? (
            <Button variant="danger" onClick={() => onChange(-1)}>
              Remove Leader
            </Button>
          ) : (
            <Button variant="primary" onClick={() => { onChange(1); onClose() }}>
              Use as Leader
            </Button>
          )
        ) : (
          <>
            {!fitsLeader && <span className="mr-auto text-xs text-amber-300">Doesn't match your Leader's colors</span>}
            <Button onClick={() => onChange(-1)} disabled={count === 0}>
              −
            </Button>
            <span className="whitespace-nowrap px-1 text-center">{count} in deck</span>
            <Button variant="primary" onClick={() => onChange(1)} disabled={count >= maxCopies(card.id)}>
              +
            </Button>
          </>
        )}
      </div>
    </Modal>
  )
}
