import type { ButtonHTMLAttributes } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}

const variantClasses: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary:
    'bg-[var(--acc)] text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed',
  secondary:
    'bg-[var(--bg-3)] text-[var(--fg-2)] border border-[var(--line-2)] hover:border-[var(--acc-line)] hover:text-[var(--fg)] disabled:opacity-40 disabled:cursor-not-allowed',
  ghost:
    'bg-transparent text-[var(--fg-3)] hover:text-[var(--fg)] hover:bg-[var(--bg-2)] disabled:opacity-40 disabled:cursor-not-allowed',
  danger:
    'bg-red-900/20 text-red-400 border border-red-900/40 hover:bg-red-900/30 disabled:opacity-40 disabled:cursor-not-allowed',
}

const sizeClasses: Record<NonNullable<ButtonProps['size']>, string> = {
  sm: 'text-xs px-3 py-1.5 gap-1.5',
  md: 'text-sm px-4 py-2 gap-2',
  lg: 'text-sm px-5 py-2.5 gap-2',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled,
  children,
  className = '',
  ...rest
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center font-medium rounded-[var(--r)] transition-all duration-150 cursor-pointer select-none ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      {...rest}
    >
      {loading && (
        <svg className="animate-spin h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
}
