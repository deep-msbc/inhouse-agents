import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  className?: string
}

export function EmptyState({ icon, title, description, className = '' }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 py-10 text-center ${className}`}>
      {icon && <div className="text-[var(--fg-4)] mb-1">{icon}</div>}
      <p className="text-sm font-medium text-[var(--fg-3)]">{title}</p>
      {description && <p className="text-xs text-[var(--fg-4)] max-w-xs">{description}</p>}
    </div>
  )
}
