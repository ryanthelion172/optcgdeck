import { useState } from 'react'
import type { Card } from '../types'
import { cardImageUrl } from '../lib/api'

/**
 * Card art. The card's name and number sit underneath the image, so they show
 * while the image loads and stay visible if it can't be loaded.
 */
export function CardImage({
  card,
  className = '',
  showText = true,
  printing,
}: {
  card: Card
  className?: string
  /** Show this printing's art (an alternate art's id, e.g. OP01-016_p1) instead of the base art. */
  printing?: string
  /** Turn off for small thumbnails, where the name won't fit. */
  showText?: boolean
}) {
  const [failed, setFailed] = useState(false)
  const [altFailed, setAltFailed] = useState(false)
  // If the alternate art can't be loaded, fall back to the base art.
  const art = printing && !altFailed ? printing : card.id
  return (
    <div className={`relative aspect-[5/7] w-full overflow-hidden rounded-lg bg-slate-800 ${className}`}>
      {showText && (
        <div className="absolute inset-0 flex flex-col justify-between p-2 text-left text-xs">
          <span className="line-clamp-3 font-semibold">{card.name}</span>
          <span className="text-slate-400">{card.id}</span>
        </div>
      )}
      {!failed && (
        <img
          src={cardImageUrl(art)}
          alt={`${card.name} (${art})`}
          loading="lazy"
          onError={() => (art !== card.id ? setAltFailed(true) : setFailed(true))}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
    </div>
  )
}
