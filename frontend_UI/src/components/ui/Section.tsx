import type { HTMLAttributes, ReactNode } from 'react'

interface SectionProps extends HTMLAttributes<HTMLDivElement> {
  number?: string
  title: string
  subtitle?: string
  children: ReactNode
}

export function Section({ number, title, subtitle, children, className = '', ...rest }: SectionProps) {
  return (
    <div className={`flex flex-col gap-4 ${className}`} {...rest}>
      <div className="flex items-baseline gap-3">
        {number && (
          <span className="text-xs font-mono font-medium text-[var(--acc)] opacity-70 shrink-0">{number}</span>
        )}
        <div>
          <h3 className="text-sm font-semibold text-[var(--fg)]">{title}</h3>
          {subtitle && <p className="text-xs text-[var(--fg-4)] mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  )
}

interface SubBlockProps extends HTMLAttributes<HTMLDivElement> {
  label?: string
  children: ReactNode
}

export function SubBlock({ label, children, className = '', ...rest }: SubBlockProps) {
  return (
    <div className={`rounded-[var(--r)] bg-[var(--bg-2)] border border-[var(--line)] p-4 ${className}`} {...rest}>
      {label && <p className="text-xs text-[var(--fg-4)] mb-3 font-medium uppercase tracking-wider">{label}</p>}
      {children}
    </div>
  )
}
