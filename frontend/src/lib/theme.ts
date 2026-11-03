export type Theme = 'light' | 'dark'

const KEY = 'optcg.theme.v1'

/** The saved choice, or the device's setting if none was saved. */
export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // Storage blocked; fall through to the device setting.
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('light', theme === 'light')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f8fafc' : '#0f172a')
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // Not saved; the choice still applies until the page is closed.
  }
}
