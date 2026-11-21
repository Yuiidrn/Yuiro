import { ref, watchEffect } from 'vue'

const STORAGE_KEY = 'yuiro-theme'
type Theme = 'light' | 'dark'

const theme = ref<Theme>('light')

function applyTheme(t: Theme): void {
  document.documentElement.setAttribute('data-theme', t)
  document.documentElement.classList.toggle('dark', t === 'dark')
}

function detectSystemTheme(): Theme {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function loadStored(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch { /* localStorage unavailable */ }
  return null
}

/**
 * 跨窗口同步：调试台「UI」页可以改桌宠主题，写入的是同一个 localStorage 键。
 * storage 事件只在「别的窗口」触发，所以这里监听即可即时应用，无需重启。
 */
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== STORAGE_KEY) return
    if (e.newValue === 'light' || e.newValue === 'dark') theme.value = e.newValue
  })
}

export function useTheme() {
  if (theme.value === 'light') {
    const stored = loadStored()
    const initial = stored ?? detectSystemTheme()
    theme.value = initial
    applyTheme(initial)
  }

  watchEffect(() => {
    applyTheme(theme.value)
    try { localStorage.setItem(STORAGE_KEY, theme.value) } catch { /* ignore */ }
  })

  function toggleTheme(): void {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  return { theme, toggleTheme }
}
