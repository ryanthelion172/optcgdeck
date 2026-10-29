import type { Deck } from '../types'

export type SaveStatus = 'saved' | 'saving' | 'error'

/**
 * Saves deck changes to the backend.
 *
 * - Changes are batched: a save goes out shortly after the last edit, not on every tap.
 * - Saves of one deck run one at a time and always send the newest version,
 *   so an older save can never land after a newer one.
 * - A deck being deleted gets no more saves, so a late save can't bring it back.
 */
export class DeckSaver {
  private pending = new Map<string, Deck>()
  private timers = new Map<string, ReturnType<typeof setTimeout>>()
  private running = new Map<string, Promise<void>>()
  private failed = new Set<string>()
  private deleted = new Set<string>()

  private save: (deck: Deck, keepalive: boolean) => Promise<void>
  private remove: (id: string) => Promise<void>
  private onStatus: (status: SaveStatus) => void
  private delay: number

  constructor(
    save: (deck: Deck, keepalive: boolean) => Promise<void>,
    remove: (id: string) => Promise<void>,
    onStatus: (status: SaveStatus) => void,
    delay = 600,
  ) {
    this.save = save
    this.remove = remove
    this.onStatus = onStatus
    this.delay = delay
  }

  /** Queues the latest version of a deck to be saved. */
  schedule(deck: Deck) {
    if (this.deleted.has(deck.id)) return
    this.pending.set(deck.id, deck)
    clearTimeout(this.timers.get(deck.id))
    this.timers.set(
      deck.id,
      setTimeout(() => void this.run(deck.id, false), this.delay),
    )
    this.report()
  }

  /** Sends every queued save now (used when the page is being hidden or closed). */
  flush(keepalive = false): Promise<void> {
    const ids = new Set([...this.timers.keys(), ...this.pending.keys()])
    return Promise.all([...ids].map((id) => this.run(id, keepalive))).then(() => undefined)
  }

  /** Tries failed saves again. */
  retry(): Promise<void> {
    return this.flush()
  }

  /** Stops saving a deck, waits for any save in progress, then deletes it on the server. */
  async delete(id: string): Promise<void> {
    this.deleted.add(id)
    clearTimeout(this.timers.get(id))
    this.timers.delete(id)
    this.pending.delete(id)
    this.failed.delete(id)
    await this.running.get(id)
    try {
      await this.remove(id)
    } catch (e) {
      this.deleted.delete(id)
      throw e
    } finally {
      this.report()
    }
  }

  private run(id: string, keepalive: boolean): Promise<void> {
    clearTimeout(this.timers.get(id))
    this.timers.delete(id)
    const previous = this.running.get(id) ?? Promise.resolve()
    const next = previous.then(async () => {
      const deck = this.pending.get(id)
      if (!deck || this.deleted.has(id)) return
      this.pending.delete(id)
      try {
        await this.save(deck, keepalive)
        this.failed.delete(id)
      } catch {
        // Keep it for a retry, unless a newer version is already waiting.
        if (!this.pending.has(id)) this.pending.set(id, deck)
        this.failed.add(id)
      }
    })
    this.running.set(id, next)
    this.report()
    return next.finally(() => {
      if (this.running.get(id) === next) this.running.delete(id)
      this.report()
    })
  }

  private report() {
    const busy = this.timers.size > 0 || this.running.size > 0
    this.onStatus(busy ? 'saving' : this.failed.size > 0 ? 'error' : 'saved')
  }
}
