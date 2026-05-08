import { useState, useEffect } from 'react'

/* Moon Icon */
function MoonIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

/* Sun Icon */
function SunIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="12" y1="21" x2="12" y2="23" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="1" y1="12" x2="3" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="21" y1="12" x2="23" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function TweaksPanel() {
  const [isDark, setIsDark] = useState(false)

  // Initialize theme from localStorage or system preference
  useEffect(() => {
    const saved = localStorage.getItem('theme')
    if (saved) {
      setIsDark(saved === 'dark')
      applyTheme(saved === 'dark')
    } else {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      setIsDark(prefersDark)
      applyTheme(prefersDark)
    }
  }, [])

  const applyTheme = (dark: boolean) => {
    const root = document.documentElement
    const body = document.body
    
    root.style.colorScheme = dark ? 'dark' : 'light'
    root.setAttribute('data-theme', dark ? 'dark' : 'light')
    body.setAttribute('data-theme', dark ? 'dark' : 'light')
    
    if (dark) {
      // Dark theme colors
      root.style.setProperty('--bg', '#0a0a0a')
      root.style.setProperty('--bg-1', '#0f0f0f')
      root.style.setProperty('--bg-2', '#1a1a1a')
      root.style.setProperty('--bg-3', '#2a2a2a')
      root.style.setProperty('--fg', '#f5f5f5')
      root.style.setProperty('--fg-2', '#d0d0d0')
      root.style.setProperty('--fg-3', '#a0a0a0')
      root.style.setProperty('--fg-4', '#707070')
      root.style.setProperty('--line', '#3a3a3a')
      root.style.setProperty('--line-2', '#2a2a2a')
      root.style.setProperty('--acc', '#8b85ff')
      root.style.setProperty('--acc-soft', 'rgba(139, 133, 255, 0.18)')
      root.style.setProperty('--acc-line', 'rgba(139, 133, 255, 0.35)')
      
      body.style.backgroundColor = '#0a0a0a'
      body.style.color = '#f5f5f5'
    } else {
      // Light theme colors
      root.style.setProperty('--bg', '#ffffff')
      root.style.setProperty('--bg-1', '#ffffff')
      root.style.setProperty('--bg-2', '#f8f8f8')
      root.style.setProperty('--bg-3', '#f0f0f0')
      root.style.setProperty('--fg', '#0f0f0f')
      root.style.setProperty('--fg-2', '#4a4a4a')
      root.style.setProperty('--fg-3', '#7a7a7a')
      root.style.setProperty('--fg-4', '#a0a0a0')
      root.style.setProperty('--line', '#e0e0e0')
      root.style.setProperty('--line-2', '#f0f0f0')
      root.style.setProperty('--acc', '#6366f1')
      root.style.setProperty('--acc-soft', 'rgba(99, 102, 241, 0.13)')
      root.style.setProperty('--acc-line', 'rgba(99, 102, 241, 0.33)')
      
      body.style.backgroundColor = '#ffffff'
      body.style.color = '#0f0f0f'
    }
  }

  const toggleTheme = () => {
    const newDark = !isDark
    setIsDark(newDark)
    applyTheme(newDark)
    localStorage.setItem('theme', newDark ? 'dark' : 'light')
  }

  return (
    <button
      onClick={toggleTheme}
      className="fixed bottom-5 right-5 z-50 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--bg-3)] border border-[var(--line-2)] text-[var(--fg-2)] hover:text-[var(--fg)] hover:border-[var(--acc-line)] hover:bg-[var(--bg-2)] transition-all duration-300 shadow-lg cursor-pointer"
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {isDark ? (
        <SunIcon className="h-5 w-5" />
      ) : (
        <MoonIcon className="h-5 w-5" />
      )}
    </button>
  )
}
