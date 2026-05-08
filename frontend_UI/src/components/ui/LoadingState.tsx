import { LoaderIcon } from '../icons/Icons'

interface LoadingStateProps {
  message?: string
  className?: string
}

export function LoadingState({ message = 'Processing…', className = '' }: LoadingStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 py-10 ${className}`}>
      <LoaderIcon className="h-6 w-6 text-[var(--acc)] animate-spin" />
      <p className="text-sm text-[var(--fg-3)]">{message}</p>
    </div>
  )
}
