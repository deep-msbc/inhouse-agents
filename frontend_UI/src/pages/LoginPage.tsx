import { useState } from 'react'
import { login, signup } from '../services/api'

interface LoginPageProps {
  onAuth: (token: string, name: string) => void
}

export function LoginPage({ onAuth }: LoginPageProps) {
  const [tab, setTab] = useState<'login' | 'signup'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = tab === 'login'
        ? await login({ email, password })
        : await signup({ name, email, password })
      localStorage.setItem('auth_token', res.token)
      localStorage.setItem('auth_user', res.user.name)
      onAuth(res.token, res.user.name)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center p-4"
      style={{
        background: 'radial-gradient(900px 600px at 50% 0%, color-mix(in oklab, var(--acc) 12%, transparent), transparent 60%), var(--bg)',
      }}
    >
      {/* Brand */}
      <div className="flex items-center gap-2.5 mb-8">
        <span
          className="flex h-7 w-7 items-center justify-center rounded-lg"
          style={{ background: 'var(--acc)' }}
        >
          <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
          </svg>
        </span>
        <span className="text-base font-bold" style={{ color: 'var(--fg)' }}>
          scaffold<span style={{ color: 'var(--fg-4)', fontWeight: 400 }}>/agent</span>
        </span>
        <span
          className="text-[10px] font-mono px-1.5 py-0.5 rounded border"
          style={{ color: 'var(--fg-4)', borderColor: 'var(--line-2)', background: 'var(--bg-3)' }}
        >
          v0.4.2 · alpha
        </span>
      </div>

      {/* Card */}
      <div
        className="w-full max-w-sm rounded-xl border p-6"
        style={{ borderColor: 'var(--line)', background: 'var(--bg-1)' }}
      >
        {/* Tabs */}
        <div
          className="flex rounded-lg p-0.5 mb-6"
          style={{ background: 'var(--bg-3)' }}
        >
          {(['login', 'signup'] as const).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setError(null) }}
              className="flex-1 py-1.5 text-xs font-semibold rounded-md transition-all capitalize"
              style={{
                background: tab === t ? 'var(--bg-1)' : 'transparent',
                color: tab === t ? 'var(--fg)' : 'var(--fg-4)',
                border: tab === t ? '1px solid var(--line-2)' : '1px solid transparent',
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {tab === 'signup' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium" style={{ color: 'var(--fg-3)' }}>Name</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Your name"
                required
                className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                style={{
                  background: 'var(--bg-2)',
                  border: '1px solid var(--line-2)',
                  color: 'var(--fg)',
                }}
                onFocus={e => (e.target.style.borderColor = 'var(--acc)')}
                onBlur={e => (e.target.style.borderColor = 'var(--line-2)')}
              />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: 'var(--fg-3)' }}>Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
              style={{
                background: 'var(--bg-2)',
                border: '1px solid var(--line-2)',
                color: 'var(--fg)',
              }}
              onFocus={e => (e.target.style.borderColor = 'var(--acc)')}
              onBlur={e => (e.target.style.borderColor = 'var(--line-2)')}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium" style={{ color: 'var(--fg-3)' }}>Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              required
              className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
              style={{
                background: 'var(--bg-2)',
                border: '1px solid var(--line-2)',
                color: 'var(--fg)',
              }}
              onFocus={e => (e.target.style.borderColor = 'var(--acc)')}
              onBlur={e => (e.target.style.borderColor = 'var(--line-2)')}
            />
          </div>

          {error && (
            <div
              className="text-xs px-3 py-2 rounded-lg"
              style={{ background: 'rgba(239,68,68,0.1)', color: '#f87171', border: '1px solid rgba(239,68,68,0.2)' }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg text-sm font-semibold mt-1 transition-all disabled:opacity-50"
            style={{ background: 'var(--acc)', color: '#fff' }}
          >
            {loading ? 'Please wait…' : tab === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </div>

      <p className="text-xs mt-4" style={{ color: 'var(--fg-4)' }}>
        InHouseAgents · MSBC Group
      </p>
    </div>
  )
}
