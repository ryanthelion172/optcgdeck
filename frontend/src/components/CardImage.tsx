import { useState } from 'react'
import type { Card } from '../types'

/**
 * Card art. The card's name and number sit underneath the image, so they show
 * while the image loads and stay visible if it can't be loaded.
 */
export function CardImage({ card, className = '' }: { card: Card; className?: string }) {
  const [failed, setFailed] = useState(false)
  return (
    <div className={`relative aspect-[5/7] w-full overflow-hidden rounded-lg bg-slate-800 ${className}`}>
      <div className="absolute inset-0 flex flex-col justify-between p-2 text-left text-xs">
        <span className="line-clamp-3 font-semibold">{card.name}</span>
        <span className="text-slate-400">{card.id}</span>
      </div>
      {card.image && !failed && (
        <img
          src={card.image}
          alt={`${card.name} (${card.id})`}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
    </div>
  )
}
