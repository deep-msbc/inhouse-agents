import type { HTMLAttributes } from 'react'

interface ChipProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'accent' | 'success' | 'warning' | 'error'
}

const variantClasses: Record<NonNullable<ChipProps['variant']>, string> = {
  default: 'bg-[var(--bg-3)] text-[var(--fg-3)] border-[var(--line)]',
  accent: 'bg-[var(--acc-soft)] text-[var(--acc)] border-[var(--acc-line)]',
  success: 'bg-emerald-950/40 text-emerald-400 border-emerald-900/40',
  warning: 'bg-amber-950/40 text-amber-400 border-amber-900/40',
  error: 'bg-red-950/40 text-red-400 border-red-900/40',
}

export function Chip({ variant = 'default', children, className = '', ...rest }: ChipProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full border font-mono ${variantClasses[variant]} ${className}`}
      {...rest}
    >
      {children}
    </span>
  )
}
