import type { JobStatus } from '../../types/api'

interface StatusBadgeProps {
  status: JobStatus | 'idle'
  className?: string
}

const config: Record<string, { dot: string; text: string; label: string }> = {
  idle: { dot: 'bg-[var(--fg-4)]', text: 'text-[var(--fg-4)]', label: 'idle' },
  pending: { dot: 'bg-amber-400 animate-pulse', text: 'text-amber-400', label: 'pending' },
  processing: { dot: 'bg-[var(--acc)] animate-pulse', text: 'text-[var(--acc)]', label: 'processing' },
  completed: { dot: 'bg-emerald-400', text: 'text-emerald-400', label: 'completed' },
  failed: { dot: 'bg-red-400', text: 'text-red-400', label: 'failed' },
}

export function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const c = config[status] ?? config.idle
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-mono ${c.text} ${className}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
      {c.label}
    </span>
  )
}
