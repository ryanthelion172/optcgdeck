import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Deck } from '../types'
import { DeckSaver, type SaveStatus } from './deckSaver'

const deck = (id: string, name: string): Deck => ({ id, name, leaderId: null, cards: {} })

type Save = (deck: Deck, keepalive: boolean) => Promise<void>

function setup(save = vi.fn<Save>(async () => {})) {
  const remove = vi.fn(async (id: string) => void id)
  const statuses: SaveStatus[] = []
  const saver = new DeckSaver(save, remove, (s) => statuses.push(s), 100)
  return { saver, save, remove, statuses }
}

describe('DeckSaver', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('batches quick edits into one save of the newest version', async () => {
    const { saver, save, statuses } = setup()
    saver.schedule(deck('a', 'v1'))
    saver.schedule(deck('a', 'v2'))
    saver.schedule(deck('a', 'v3'))
    await vi.advanceTimersByTimeAsync(150)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save.mock.calls[0][0].name).toBe('v3')
    expect(statuses[statuses.length - 1]).toBe('saved')
  })

  it('never lets an older save finish after a newer one', async () => {
    const order: string[] = []
    let release!: () => void
    const save = vi.fn<Save>(async (d) => {
      if (d.name === 'v1') await new Promise<void>((r) => (release = r))
      order.push(d.name)
    })
    const { saver } = setup(save)
    saver.schedule(deck('a', 'v1'))
    await vi.advanceTimersByTimeAsync(150) // v1 is now in flight and stuck
    saver.schedule(deck('a', 'v2'))
    await vi.advanceTimersByTimeAsync(150)
    expect(order).toEqual([]) // v2 waits for v1
    release()
    await vi.runAllTimersAsync()
    expect(order).toEqual(['v1', 'v2'])
  })

  it('keeps failed saves for a retry', async () => {
    let fail = true
    const save = vi.fn<Save>(async () => {
      if (fail) throw new Error('offline')
    })
    const { saver, statuses } = setup(save)
    saver.schedule(deck('a', 'v1'))
    await vi.advanceTimersByTimeAsync(150)
    expect(statuses[statuses.length - 1]).toBe('error')
    fail = false
    await saver.retry()
    expect(save).toHaveBeenCalledTimes(2)
    expect(statuses[statuses.length - 1]).toBe('saved')
  })

  it('does not save a deck after it is deleted', async () => {
    const { saver, save, remove } = setup()
    saver.schedule(deck('a', 'v1'))
    await saver.delete('a')
    saver.schedule(deck('a', 'v2'))
    await vi.runAllTimersAsync()
    expect(save).not.toHaveBeenCalled()
    expect(remove).toHaveBeenCalledWith('a')
  })

  it('flush sends queued saves right away with keepalive', async () => {
    const { saver, save } = setup()
    saver.schedule(deck('a', 'v1'))
    saver.schedule(deck('b', 'v1'))
    await saver.flush(true)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save.mock.calls.every(([, keepalive]) => keepalive)).toBe(true)
  })
})
