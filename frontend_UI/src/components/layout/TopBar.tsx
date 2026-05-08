import { ZapIcon } from '../icons/Icons'

interface TopBarProps {
  activeStep?: 'spec' | 'configure' | 'generate' | 'review'
  agentOnline?: boolean
  userInitials?: string
  onLogout?: () => void
}

const steps = ['spec', 'configure', 'generate', 'review'] as const

export function TopBar({ activeStep = 'configure', agentOnline = true, userInitials = 'AK', onLogout }: TopBarProps) {
  return (
    <header className="h-11 flex items-center px-5 border-b border-[var(--line)] bg-[var(--bg-1)] shrink-0 gap-4">
      {/* Brand */}
      <div className="flex items-center gap-2.5 shrink-0">
        <span className="flex h-6 w-6 items-center justify-center rounded bg-[var(--acc)]">
          <ZapIcon className="h-3.5 w-3.5 text-white" />
        </span>
        <span className="text-sm font-bold text-[var(--fg)] tracking-tight">
          scaffold<span className="text-[var(--fg-4)] font-normal">/</span>agent
        </span>
        <span className="text-[10px] font-mono text-[var(--fg-4)] border border-[var(--line-2)] rounded px-1.5 py-0.5 bg-[var(--bg-3)]">
          v0.4.2 · alpha
        </span>
      </div>

      {/* Pipeline steps — centered */}
      <div className="flex-1 flex items-center justify-center gap-1">
        {steps.map((step, i) => {
          const isActive = step === activeStep
          const stepIdx = steps.indexOf(step)
          const activeIdx = steps.indexOf(activeStep)
          const isPast = stepIdx < activeIdx
          return (
            <div key={step} className="flex items-center gap-1">
              <span
                className={`text-xs font-medium px-2.5 py-1 rounded-[var(--r)] transition-all ${
                  isActive
                    ? 'bg-[var(--acc)] text-white'
                    : isPast
                    ? 'text-[var(--fg-3)]'
                    : 'text-[var(--fg-4)]'
                }`}
              >
                {step}
              </span>
              {i < steps.length - 1 && (
                <span className="text-[var(--fg-4)] text-xs">→</span>
              )}
            </div>
          )
        })}
      </div>

      {/* Right side */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${agentOnline ? 'bg-emerald-400' : 'bg-red-400'}`} />
          <span className="text-xs text-[var(--fg-3)]">agent {agentOnline ? 'online' : 'offline'}</span>
        </div>
        <div
          onClick={onLogout}
          className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--bg-3)] border border-[var(--line-2)] text-xs font-semibold text-[var(--fg-2)] cursor-pointer hover:border-[var(--acc-line)] transition-colors"
          title="Logout"
        >
          {userInitials}
        </div>
      </div>
    </header>
  )
}
