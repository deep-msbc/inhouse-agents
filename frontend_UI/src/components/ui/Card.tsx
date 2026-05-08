import type { HTMLAttributes } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  selected?: boolean
  hoverable?: boolean
}

export function Card({ selected, hoverable = true, children, className = '', ...rest }: CardProps) {
  return (
    <div
      className={`rounded-[var(--r-lg)] border transition-all duration-150 ${
        selected
          ? 'border-[var(--acc-line)] bg-[var(--acc-soft)]'
          : 'border-[var(--line)] bg-[var(--bg-2)]'
      } ${hoverable ? 'hover:border-[var(--line-2)] cursor-pointer' : ''} ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}
