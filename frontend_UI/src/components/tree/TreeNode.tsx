import { useState } from 'react'
import { ChevronRightIcon, ChevronDownIcon } from '../icons/Icons'
import type { TreeNode as TreeNodeType } from '../../types/api'

const TAG_STYLES: Record<string, string> = {
  flow: 'bg-blue-900/50 text-blue-300 border-blue-700/40',
  routing: 'bg-indigo-900/50 text-indigo-300 border-indigo-700/40',
  config: 'bg-[var(--bg-3)] text-[var(--fg-4)] border-[var(--line-2)]',
  api: 'bg-[var(--bg-3)] text-[var(--fg-3)] border-[var(--line-2)] font-mono',
  auth: 'bg-emerald-900/40 text-emerald-400 border-emerald-800/40',
  module: 'bg-[var(--acc-soft)] text-[var(--acc)] border-[var(--acc-line)]',
}

const TAG_LABELS: Record<string, string> = {
  flow: 'FLOW',
  routing: 'ROUTING',
  config: 'CONFIG',
  api: '--API',
  auth: '--AUTH',
  module: 'module',
}

const EXT_COLOR: Record<string, string> = {
  tsx: 'text-sky-400',
  ts: 'text-blue-400',
  py: 'text-amber-400',
  md: 'text-[var(--fg-4)]',
  json: 'text-amber-300',
  css: 'text-pink-400',
}

function getExt(name: string) {
  return name.split('.').pop() ?? ''
}

function FolderSVG({ open }: { open: boolean }) {
  return open ? (
    <svg className="h-3.5 w-3.5 shrink-0 text-[var(--acc)]" viewBox="0 0 20 20" fill="currentColor">
      <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  ) : (
    <svg className="h-3.5 w-3.5 shrink-0 text-[var(--acc)] opacity-70" viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M2 6a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1H8a3 3 0 00-3 3v1.5a1.5 1.5 0 01-3 0V6z" />
      <path d="M6 12a2 2 0 012-2h8a2 2 0 012 2v2a2 2 0 01-2 2H2h2a2 2 0 002-2v-2z" />
    </svg>
  )
}

function FileSVG({ ext }: { ext: string }) {
  const color = EXT_COLOR[ext] ?? 'text-[var(--fg-4)]'
  return (
    <svg className={`h-3.5 w-3.5 shrink-0 ${color}`} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path d="M4 3a1 1 0 011-1h7l4 4v11a1 1 0 01-1 1H5a1 1 0 01-1-1V3z" />
      <path d="M11 2v4a1 1 0 001 1h4" />
    </svg>
  )
}

interface TreeNodeProps {
  node: TreeNodeType
  depth?: number
}

export function TreeNode({ node, depth = 0 }: TreeNodeProps) {
  const [open, setOpen] = useState(depth < 1)
  const isFolder = node.type === 'folder'
  const ext = getExt(node.name)
  const indent = depth * 14
  const nameColor = isFolder ? 'text-[var(--fg-2)]' : (EXT_COLOR[ext] ?? 'text-[var(--fg-3)]')

  return (
    <div>
      <div
        className="flex items-center h-6 hover:bg-[var(--bg-3)] transition-colors group cursor-pointer"
        style={{ paddingLeft: `${8 + indent}px`, paddingRight: '8px' }}
        onClick={() => isFolder && setOpen(o => !o)}
      >
        {/* Toggle */}
        <span className="w-4 h-4 flex items-center justify-center shrink-0 text-[var(--fg-4)]">
          {isFolder && (
            open ? <ChevronDownIcon className="h-3 w-3" /> : <ChevronRightIcon className="h-3 w-3" />
          )}
        </span>

        {/* Icon */}
        {isFolder ? <FolderSVG open={open} /> : <FileSVG ext={ext} />}

        {/* Name */}
        <span className={`ml-1.5 text-xs font-mono flex-1 truncate ${nameColor}`}>{node.name}</span>

        {/* Tag badge (right-aligned) */}
        {node.tag && (
          <span className={`ml-2 shrink-0 text-[10px] font-mono px-1.5 py-px rounded border leading-tight ${TAG_STYLES[node.tag] ?? TAG_STYLES.config}`}>
            {TAG_LABELS[node.tag] ?? node.tag.toUpperCase()}
          </span>
        )}
      </div>

      {isFolder && open && node.children && (
        <div>
          {node.children.map(child => (
            <TreeNode key={child.path} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

/* ─── Terminal Window Chrome ─── */
interface TreeWindowProps {
  root: string
  fileCount: number
  stackLabel: string
  moduleCount: number
  parallel?: boolean
  children: React.ReactNode
  command: string
}

export function TreeWindow({ root, fileCount, stackLabel, moduleCount, parallel, children, command }: TreeWindowProps) {
  const dotColor =
    stackLabel.toLowerCase().includes('frontend') && !stackLabel.toLowerCase().includes('backend')
      ? 'bg-indigo-500'
      : stackLabel.toLowerCase().includes('backend') && !stackLabel.toLowerCase().includes('frontend')
      ? 'bg-amber-500'
      : 'bg-violet-500'

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Mac chrome */}
      <div className="flex items-center px-4 py-2.5 border-b border-[var(--line)] bg-[var(--bg-2)] shrink-0">
        <div className="flex gap-1.5 mr-4">
          <span className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/80" />
        </div>
        <span className="text-xs font-mono text-[var(--fg-4)] flex-1">{root}</span>
        <span className="text-xs font-mono text-[var(--fg-4)]">{fileCount} files</span>
      </div>

      {/* Chip row */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--line)] bg-[var(--bg-2)] shrink-0 flex-wrap">
        <span className="text-xs font-medium px-2.5 py-1 rounded-full border border-[var(--line-2)] bg-[var(--bg-3)] text-[var(--fg-3)]">
          {moduleCount} Modules
        </span>
        <span className="text-xs font-medium px-2.5 py-1 rounded-full border border-[var(--line-2)] bg-[var(--bg-3)] text-[var(--fg-3)]">
          {fileCount} Files
        </span>
        <span className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border text-white ${dotColor} border-transparent`}>
          <span className="h-1.5 w-1.5 rounded-full bg-white/70" />
          {stackLabel}
        </span>
        {parallel && (
          <span className="text-xs font-medium px-2.5 py-1 rounded-full border border-[var(--line-2)] bg-[var(--bg-3)] text-[var(--fg-3)]">
            Parallel
          </span>
        )}
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto py-1 bg-[var(--bg-1)]">
        {children}
      </div>

      {/* Terminal command bar */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-t border-[var(--line)] bg-[var(--bg-2)] shrink-0">
        <span className="text-[var(--acc)] text-xs font-mono">$</span>
        <span className="text-xs font-mono text-[var(--fg-3)]">{command}</span>
        <span className="inline-block h-3.5 w-0.5 bg-[var(--fg-3)] animate-pulse ml-0.5" />
      </div>
    </div>
  )
}
