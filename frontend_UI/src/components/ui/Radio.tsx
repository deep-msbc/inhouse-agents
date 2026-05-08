import type { InputHTMLAttributes } from 'react'

interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string
  tag?: string
}

export function Radio({ label, tag, className = '', ...rest }: RadioProps) {
  return (
    <label className={`flex items-center gap-3 cursor-pointer group ${rest.disabled ? 'opacity-50 cursor-not-allowed' : ''} ${className}`}>
      <span className="relative shrink-0 mt-px">
        <input type="radio" className="sr-only peer" {...rest} />
        <span className="flex h-4 w-4 items-center justify-center rounded-full border border-[var(--line-2)] bg-[var(--bg-3)] peer-checked:border-[var(--acc)] transition-all">
          <span className="h-2 w-2 rounded-full bg-[var(--acc)] opacity-0 peer-checked:opacity-100 transition-opacity" />
        </span>
      </span>
      <span className="flex-1 text-sm text-[var(--fg-2)] group-hover:text-[var(--fg)] transition-colors select-none">{label}</span>
      {tag && (
        <span className="shrink-0 text-[10px] font-mono text-[var(--fg-4)] border border-[var(--line)] bg-[var(--bg-3)] px-1.5 py-0.5 rounded">
          {tag}
        </span>
      )}
    </label>
  )
}
