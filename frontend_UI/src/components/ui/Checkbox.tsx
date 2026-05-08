import type { InputHTMLAttributes } from 'react'

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string
  tag?: string
  locked?: boolean
}

export function Checkbox({ label, tag, locked, className = '', ...rest }: CheckboxProps) {
  return (
    <label className={`flex items-center gap-3 cursor-pointer group ${rest.disabled ? 'opacity-50 cursor-not-allowed' : ''} ${className}`}>
      <span className="relative shrink-0 mt-px">
        <input type="checkbox" className="sr-only peer" {...rest} />
        <span className="flex h-4 w-4 items-center justify-center rounded border border-[var(--line-2)] bg-[var(--bg-3)] peer-checked:bg-[var(--acc)] peer-checked:border-[var(--acc)] transition-all">
          <svg className="h-2.5 w-2.5 text-white opacity-0 peer-checked:opacity-0 scale-0 peer-checked:scale-100 pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </span>
        {/* checkmark visible when checked — hack: use after pseudo via JS */}
      </span>
      <span className="flex-1 text-sm text-[var(--fg-2)] group-hover:text-[var(--fg)] transition-colors select-none">{label}</span>
      {tag && (
        <span className={`shrink-0 flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded border ${
          locked
            ? 'text-[var(--fg-4)] border-[var(--line)] bg-[var(--bg-3)]'
            : 'text-[var(--fg-4)] border-[var(--line)] bg-[var(--bg-3)]'
        }`}>
          {tag}
          {locked && <span className="text-[9px]">🔒</span>}
        </span>
      )}
    </label>
  )
}
