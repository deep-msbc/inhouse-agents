import { useState, useMemo, useRef, useEffect } from 'react'
import { TopBar } from '../components/layout/TopBar'
import { TreeNode, TreeWindow } from '../components/tree/TreeNode'
import { TweaksPanel } from '../components/tweaks/TweaksPanel'
import { Checkbox } from '../components/ui/Checkbox'
import { Radio } from '../components/ui/Radio'
import { LoadingState } from '../components/ui/LoadingState'
import { EmptyState } from '../components/ui/EmptyState'
import { SparklesIcon, AlertIcon } from '../components/icons/Icons'
import { useJobPoller } from '../hooks/useJobPoller'
import { uploadDocument, getExtractionJob, startBackendGeneration, getBackendGenerationJob } from '../services/api'
// TEMP: uploadFile + generateCode commented out until /api/v1/uploads backend is ready
// import { uploadFile, generateCode, getExtractionJob } from '../services/api'
import {
  SAMPLE_MODULES, MOCK_STATS, FE_TREE, BE_TREE, FS_TREE,
  FILE_COUNTS, TREE_ROOTS, STACK_LABELS,
} from '../constants/modules'
import type { ExtractionMode, ExtractionOutput, JobStatus, BackendGenerationResult } from '../types/api'

/* ─── helpers ─── */
function getTree(mode: ExtractionMode) {
  return mode === 'frontend' ? FE_TREE : mode === 'backend' ? BE_TREE : FS_TREE
}

function getCommand(mode: ExtractionMode) {
  return `agent plan --stack ${mode === 'fullstack' ? 'fullstack' : mode}`
}

/* ─── File upload card ─── */
interface UploadZoneProps {
  file: File | null
  onFile: (f: File) => void
  onClear: () => void
  disabled?: boolean
  detected?: boolean
}

function UploadZone({ file, onFile, onClear, disabled, detected }: UploadZoneProps) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) onFile(f)
  }

  if (file) {
    return (
      <div className="rounded-[var(--r-lg)] border border-[var(--line-2)] bg-[var(--bg-2)] p-3 flex items-center gap-3">
        {/* Doc icon */}
        <div className="h-10 w-8 rounded border border-[var(--line-2)] bg-[var(--bg-3)] flex items-center justify-center shrink-0">
          <svg className="h-4 w-4 text-[var(--fg-4)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-[var(--fg)] truncate">{file.name}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-[var(--fg-4)]">{(file.size / 1024).toFixed(0)} KB</span>
            {detected && (
              <span className="flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--acc-soft)] text-[var(--acc)] border border-[var(--acc-line)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--acc)]" />
                User Story &nbsp;Detected
              </span>
            )}
          </div>
        </div>
        <button
          onClick={e => { e.stopPropagation(); onClear() }}
          className="shrink-0 h-6 w-6 flex items-center justify-center text-[var(--fg-4)] hover:text-[var(--fg)] transition-colors rounded cursor-pointer"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </button>
      </div>
    )
  }

  return (
    <div
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); if (!disabled) setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`flex flex-col items-center justify-center gap-2.5 rounded-[var(--r-lg)] border-2 border-dashed p-8 transition-all ${
        disabled ? 'opacity-50 cursor-not-allowed' :
        dragging ? 'border-[var(--acc)] bg-[var(--acc-soft)] cursor-copy' :
        'border-[var(--line-2)] bg-[var(--bg-2)] hover:border-[var(--acc-line)] hover:bg-[var(--bg-3)] cursor-pointer'
      }`}
    >
      <input ref={inputRef} type="file" accept=".docx,.pdf" className="sr-only" disabled={disabled} onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f) }} />
      <svg className="h-7 w-7 text-[var(--fg-4)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
      </svg>
      <p className="text-sm text-[var(--fg-3)]">Drop a spec to extract modules and user stories.</p>
    </div>
  )
}


/* ─── Mode card ─── */
interface ModeCardProps {
  id: ExtractionMode
  abbr: string
  label: string
  description: string
  selected: boolean
  onSelect: (id: ExtractionMode) => void
  disabled?: boolean
}

function ModeCard({ id, abbr, label, description, selected, onSelect, disabled }: ModeCardProps) {
  return (
    <button
      onClick={() => !disabled && onSelect(id)}
      disabled={disabled}
      className={`relative flex flex-col p-3 rounded-[var(--r-lg)] border text-left transition-all cursor-pointer ${
        selected
          ? 'border-[var(--acc)] bg-[var(--bg-2)]'
          : 'border-[var(--line)] bg-[var(--bg-2)] hover:border-[var(--line-2)]'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      {/* Abbreviation chip */}
      <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border self-start mb-2 ${
        selected
          ? 'bg-[var(--acc-soft)] text-[var(--acc)] border-[var(--acc-line)]'
          : 'bg-[var(--bg-3)] text-[var(--fg-4)] border-[var(--line)]'
      }`}>{abbr}</span>

      <span className={`text-sm font-semibold mb-1 ${selected ? 'text-[var(--fg)]' : 'text-[var(--fg-2)]'}`}>{label}</span>
      <span className="text-xs text-[var(--fg-4)] leading-snug">{description}</span>

      {/* Checkmark */}
      {selected && (
        <span className="absolute top-2.5 right-2.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--acc)]">
          <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </span>
      )}
    </button>
  )
}

/* ─── Section header ─── */
interface SectionHeadProps { number: string; title: string; subtitle?: string }
function SectionHead({ number, title, subtitle }: SectionHeadProps) {
  return (
    <div className="mb-3">
      <div className="flex items-center gap-2.5 mb-1">
        <span className="text-[10px] font-mono text-[var(--fg-4)] shrink-0">{number}</span>
        <span className="text-xs font-bold text-[var(--fg-2)] tracking-wider uppercase">{title}</span>
      </div>
      {subtitle && <p className="text-xs text-[var(--fg-4)] pl-7">{subtitle}</p>}
    </div>
  )
}

/* ─── Output label chip ─── */
function OutputLabel({ abbr, label }: { abbr: string; label: string }) {
  return (
    <div className="flex items-center gap-2 mb-2.5">
      <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border bg-[var(--acc-soft)] text-[var(--acc)] border-[var(--acc-line)]">{abbr}</span>
      <span className="text-xs text-[var(--fg-3)]">{label}</span>
    </div>
  )
}

/* ─── Module rail item ─── */
interface RailItemProps { index: number; name: string; count?: number; active?: boolean }
function RailItem({ index, name, count, active }: RailItemProps) {
  return (
    <div className={`flex items-center gap-2 py-2 border-b border-[var(--line)] last:border-0 ${active ? 'opacity-100' : 'opacity-60'}`}>
      <span className="text-[10px] font-mono text-[var(--fg-4)] w-4 shrink-0">{String(index).padStart(2, '0')}</span>
      <span className="text-xs font-mono text-[var(--fg-2)] flex-1 truncate">{name}</span>
      {count !== undefined && (
        <span className="text-[10px] font-mono text-[var(--fg-4)] shrink-0">{count}</span>
      )}
    </div>
  )
}

/* ─── Generate button ─── */
interface GenerateBtnProps { loading?: boolean; disabled?: boolean; done?: boolean; onClick: () => void }
function GenerateBtn({ loading, disabled, done, onClick }: GenerateBtnProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className="w-full flex items-center justify-center gap-2 py-2.5 rounded-[var(--r-lg)] bg-[var(--acc)] text-white text-sm font-semibold hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
    >
      {loading ? (
        <>
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Generating…
        </>
      ) : done ? (
        <>
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
          Regenerate
        </>
      ) : (
        <>
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3" /></svg>
          Generate Code
        </>
      )}
    </button>
  )
}

/* ─── Generator page ─── */
interface GeneratorProps {
  userName?: string
  onLogout?: () => void
}

export function Generator({ userName = 'AK', onLogout }: GeneratorProps) {
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<ExtractionMode>('frontend')
  const [feComponents, setFeComponents] = useState(true)
  const [feRouting, setFeRouting] = useState(true)
  const [feFlow, setFeFlow] = useState(true)
  const [feConfig, setFeConfig] = useState(true)
  const [beAction, setBeAction] = useState<'startproject' | 'startapp' | 'startservices'>('startproject')
  const [beAuth, setBeAuth] = useState(true)
  // const [parallel, setParallel] = useState(true)
  // const [advancedOpen, setAdvancedOpen] = useState(true)
  const [uploadError, setUploadError] = useState<string | null>(null)
  // TEMP: uploadId + uploadReady + isUploading unused until /uploads endpoint is ready
  // const [uploadId, setUploadId] = useState<string | null>(null)
  // const [uploadReady, setUploadReady] = useState(false)

  // Jobs
  const [stage1JobId, setStage1JobId] = useState<string | null>(null)
  const [stage3JobId, setStage3JobId] = useState<string | null>(null)
  // const [isUploading, setIsUploading] = useState(false)

  const stage1Poller = useMemo(
    () => stage1JobId ? () => getExtractionJob(stage1JobId) : null,
    [stage1JobId]
  )

  const stage3Poller = useMemo(
    () => stage3JobId ? () => getBackendGenerationJob(stage3JobId) : null,
    [stage3JobId]
  )

  // const { status: s1Status } = useJobPoller<ExtractionOutput>(stage1Poller)
  const {
  status: s1Status,
  data: extractionResult,
  error: pollError,
} = useJobPoller<ExtractionOutput>(stage1Poller)

  const { status: s3Status, error: s3PollError } = useJobPoller<BackendGenerationResult>(stage3Poller)



// -----------------------------------------------------------------------------------
  // TEMP: handleUpload (POST /uploads) commented out until backend /uploads endpoint is ready.
  // Restore this when the endpoint exists and remove the setFile(f) inline below.
  // const handleUpload = async (f: File) => {
  //   setFile(f)
  //   setUploadId(null)
  //   setUploadReady(false)
  //   setIsUploading(true)
  //   setUploadError(null)
  //   try {
  //     const res = await uploadFile(f, mode)
  //     setUploadId(res.upload_id)
  //     setUploadReady(true)
  //   } catch (e) {
  //     setUploadError(e instanceof Error ? e.message : 'Upload failed. Check the backend is running on localhost:8000.')
  //   } finally {
  //     setIsUploading(false)
  //   }
  // }

  // -------------------------------------------------------------------------------------------

  // const handleGenerate = async () => {
  //   if (!file) return
  //   setUploadError(null)
  //   setStage1JobId(null)
  //   try {
  //     // TEMP: Direct multipart POST to /requirement-extractor/parse until /uploads is ready
  //     const res = await uploadDocument(file)
  //     setStage1JobId(res.job_id)
  //   } catch (e) {
  //     setUploadError(e instanceof Error ? e.message : 'Generation failed.')
  //   }
  // }

  const handleFile = (f: File) => {
    const ext = f.name.toLowerCase().slice(f.name.lastIndexOf('.'))
    if (ext !== '.docx' && ext !== '.pdf') {
      setUploadError('Only .docx and .pdf files are supported.')
      return
    }
    if (f.size > 50 * 1024 * 1024) {
      setUploadError('File must be under 50 MB.')
      return
    }
    setUploadError(null)
    setFile(f)
  }

  const handleGenerate = async () => {
    if (!file) return

    setUploadError(null)
    setStage1JobId(null)
    setStage3JobId(null)

    try {
      const apiMode: 'frontend' | 'backend' | 'both' =
        mode === 'fullstack' ? 'both' : mode

      const res = await uploadDocument(file, apiMode)
      setStage1JobId(res.job_id)
    } catch (e) {
      setUploadError(
        e instanceof Error ? e.message : 'Generation failed. Check backend is running.'
      )
    }
  }

  useEffect(() => {
    if (
      s1Status !== 'completed' ||
      !extractionResult?.extraction_id ||
      (mode !== 'backend' && mode !== 'fullstack') ||
      stage3JobId !== null
    ) return

    const projectName = (file?.name ?? 'project')
      .replace(/\.[^.]+$/, '')
      .replace(/[^a-zA-Z0-9_-]/g, '_')

    startBackendGeneration({
      extraction_id: extractionResult.extraction_id,
      output_path: `./generated_projects/${projectName}`,
      backend_action: beAction,
    })
      .then(res => setStage3JobId(res.job_id))
      .catch(e => setUploadError(e instanceof Error ? e.message : 'Backend generation failed.'))
  }, [s1Status, extractionResult, mode, stage3JobId, file, beAction])



  const isRunning = (stage1JobId !== null) && (s1Status === 'pending' || s1Status === 'processing')
  const isStage3Running = stage3JobId !== null && (s3Status === 'pending' || s3Status === 'processing')
  const isAnyRunning = isRunning || isStage3Running
  const isDone = s1Status === 'completed' && (mode === 'frontend' || s3Status === 'completed')
  // const hasResult = !!stage1JobId
  const hasResult = isDone && !!extractionResult

  const s1Display: JobStatus | 'idle' = s1Status ?? 'idle'

  const activeStep =
    isDone ? 'review' :
    isAnyRunning ? 'generate' :
    file ? 'configure' : 'spec'

  const tree = getTree(mode)
  const fileCount = FILE_COUNTS[mode]!
  const treeRoot = TREE_ROOTS[mode]!
  const stackLabel = STACK_LABELS[mode]!
  const command = getCommand(mode)

  const moduleCounts: Record<string, number> = {
    production_process_master: 4,
    job_production_tracking: 5,
    machine_telemetry: 6,
    operator_assignment: 4,
    quality_inspection: 5,
  }

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] overflow-hidden">
      <TopBar
        activeStep={activeStep}
        agentOnline={true}
        userInitials={userName.slice(0, 2).toUpperCase()}
        onLogout={onLogout}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* ════ LEFT PANEL ════ */}
        <aside className="w-[430px] shrink-0 flex flex-col border-r border-[var(--line)] bg-[var(--bg-1)] overflow-y-auto">
          <div className="p-5 flex flex-col gap-5">

            {/* Panel title */}
            <div className="flex items-start gap-3">
              <div className="h-8 w-8 flex items-center justify-center rounded border border-[var(--line-2)] bg-[var(--bg-3)] shrink-0 mt-0.5">
                <svg className="h-4 w-4 text-[var(--fg-3)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                  <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
                </svg>
              </div>
              <div>
                <h2 className="text-base font-bold text-[var(--fg)]">Configure Your Generation</h2>
                <p className="text-xs text-[var(--fg-4)] mt-0.5">Upload a spec, pick a target, ship a scaffold.</p>
              </div>
            </div>

            <div className="h-px bg-[var(--line)]" />

            {/* 01 SOURCE DOCUMENT */}
            <div>
              <SectionHead number="01" title="Source Document" subtitle="Drop a spec to extract modules and user stories." />
              <UploadZone
                file={file}
                onFile={handleFile}
                onClear={() => { setFile(null); setUploadError(null) }}
                disabled={isAnyRunning}
                detected={!!file}
              />
              {file && !isAnyRunning && (
                <p className="text-xs text-center mt-2" style={{ color: '#22c55e' }}>
                  ✓ File selected. Click Generate Code when ready.
                </p>
              )}
              {uploadError && (
                <div className="flex items-center gap-2 text-xs text-red-400 bg-red-950/20 border border-red-900/30 rounded-[var(--r)] px-3 py-2 mt-2">
                  <AlertIcon className="h-3.5 w-3.5 shrink-0" />
                  {uploadError}
                </div>
              )}
            </div>

            <div className="h-px bg-[var(--line)]" />

            {/* 02 EXTRACTION MODE */}
            <div>
              <SectionHead number="02" title="Extraction Mode" subtitle="Choose what the agent should generate." />

              {/* Mode cards */}
              <div className="grid grid-cols-3 gap-2 mb-4">
                <ModeCard id="frontend" abbr="FE" label="Frontend Only" description="React + TS modules" selected={mode === 'frontend'} onSelect={setMode} disabled={isAnyRunning} />
                <ModeCard id="backend"  abbr="BE" label="Backend Only"  description="Django services"   selected={mode === 'backend'}  onSelect={setMode} disabled={isAnyRunning} />
                <ModeCard id="fullstack" abbr="FS" label="Full Stack" description="Both layers" selected={mode === 'fullstack'} onSelect={setMode} disabled={isAnyRunning} />
              </div>

              {/* FE sub-options */}
              {(mode === 'frontend' || mode === 'fullstack') && (
                <div className="rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--bg-2)] p-4 mb-3">
                  <OutputLabel abbr="FE" label="Frontend output" />
                  <div className="flex flex-col gap-2.5">
                    <Checkbox label="Include component file structure" tag="pages/, components/, services/" checked={feComponents} onChange={e => setFeComponents(e.target.checked)} disabled={isAnyRunning} />
                    <Checkbox label="Include screen routing" tag="routes.ts per module" checked={feRouting} onChange={e => setFeRouting(e.target.checked)} disabled={isAnyRunning} />
                    <Checkbox label="Include data flow mapping" tag="dataflow.md" checked={feFlow} onChange={e => setFeFlow(e.target.checked)} disabled={isAnyRunning} />
                    <Checkbox label="Generate dashboard config files" tag="dashboardConfig.ts" checked={feConfig} onChange={e => setFeConfig(e.target.checked)} disabled={isAnyRunning} />
                  </div>
                </div>
              )}

              {/* BE sub-options */}
              {(mode === 'backend' || mode === 'fullstack') && (
                <div className="rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--bg-2)] p-4">
                  <OutputLabel abbr="BE" label="Backend output" />
                  <div className="flex flex-col gap-2 mb-4">
                    <Radio label="Create New Project" name="beAction" value="startproject" checked={beAction === 'startproject'} onChange={() => setBeAction('startproject')} disabled={isAnyRunning} tag="startproject" />
                    <Radio label="Add Apps to Existing Project" name="beAction" value="startapp" checked={beAction === 'startapp'} onChange={() => setBeAction('startapp')} disabled={isAnyRunning} tag="startapp" />
                    <Radio label="Create Microservices" name="beAction" value="startservices" checked={beAction === 'startservices'} onChange={() => setBeAction('startservices')} disabled={isAnyRunning} tag="startservices" />
                  </div>
                  <div className="h-px bg-[var(--line)] mb-3" />
                  <div className="flex flex-col gap-2">
                    <Checkbox label="Include API layer" tag="--api" locked checked disabled className="opacity-60" onChange={() => {}} />
                    <Checkbox label="Include Auth module" tag="--auth" checked={beAuth} onChange={e => setBeAuth(e.target.checked)} disabled={isAnyRunning} />
                  </div>
                </div>
              )}
            </div>

            <div className="h-px bg-[var(--line)]" />


            {/* Generate button */}
            <GenerateBtn loading={isAnyRunning} disabled={!file || isAnyRunning} done={isDone} onClick={handleGenerate} />

            {/* Status indicators */}
            {s1Display !== 'idle' && (
              <div className="flex flex-col gap-1.5 text-xs font-mono text-[var(--fg-4)]">
                <div className="flex items-center justify-between">
                  <span>stage 1 extraction</span>
                  <span className={`${s1Display === 'completed' ? 'text-emerald-400' : s1Display === 'failed' ? 'text-red-400' : 'text-[var(--acc)]'}`}>{s1Display}</span>
                </div>
                {s3Status && (
                  <div className="flex items-center justify-between">
                    <span>stage 3 backend gen</span>
                    <span className={`${s3Status === 'completed' ? 'text-emerald-400' : s3Status === 'failed' ? 'text-red-400' : 'text-[var(--acc)]'}`}>{s3Status}</span>
                  </div>
                )}
              </div>
            )}

            {pollError && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-950/20 border border-red-900/30 rounded-[var(--r)] px-3 py-2 mt-2">
                <AlertIcon className="h-3.5 w-3.5 shrink-0" />
                {pollError}
              </div>
            )}

            {s3PollError && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-950/20 border border-red-900/30 rounded-[var(--r)] px-3 py-2 mt-2">
                <AlertIcon className="h-3.5 w-3.5 shrink-0" />
                {s3PollError}
              </div>
            )}
            
          </div>
        </aside>

        {/* ════ RIGHT PANEL ════ */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {/* Panel header */}
          <div className="flex items-start justify-between px-6 py-4 border-b border-[var(--line)] bg-[var(--bg-1)] shrink-0">
            <div>
              <h2 className="text-sm font-bold text-[var(--fg)]">Generation Preview</h2>
              <p className="text-xs text-[var(--fg-4)] mt-0.5">Updates live as configuration changes</p>
            </div>
          </div>

          {/* Content */}
          {isAnyRunning ? (
            <div className="flex-1 flex items-center justify-center">
              <LoadingState message={
                isStage3Running ? 'Generating backend code…' :
                s1Status === 'pending' || s1Status === 'processing' ? 'Extracting requirements…' :
                'Processing…'
              } />
            </div>
          ) : !hasResult ? (
            <div className="flex-1 flex items-center justify-center">
              <EmptyState
                icon={<SparklesIcon className="h-10 w-10" />}
                title="No generation yet"
                description="Upload a user story document and click Generate Code to start."
              />
            </div>
          ) : (
            /* Tree + module rail */
            <div className="flex flex-1 overflow-hidden">
              <TreeWindow
                root={treeRoot}
                fileCount={fileCount}
                stackLabel={stackLabel}
                moduleCount={MOCK_STATS.modules}
                // parallel={parallel}
                command={command}
              >
                {tree.map(node => (
                  <TreeNode key={node.path} node={node} depth={0} />
                ))}
              </TreeWindow>

              {/* Module rail */}
              <div className="w-52 shrink-0 flex flex-col border-l border-[var(--line)] bg-[var(--bg-1)] overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--line)] shrink-0">
                  <span className="text-[10px] font-mono font-bold text-[var(--fg-4)] uppercase tracking-widest">Detected Modules</span>
                  <span className="text-[10px] font-mono text-[var(--fg-4)] bg-[var(--bg-3)] border border-[var(--line)] rounded px-1.5 py-0.5">
                    {MOCK_STATS.modules}
                  </span>
                </div>
                <div className="flex-1 overflow-y-auto px-4">
                  {SAMPLE_MODULES.map((m, i) => (
                    <RailItem
                      key={m}
                      index={i + 1}
                      name={m}
                      count={moduleCounts[m]}
                      active={hasResult || file !== null}
                    />
                  ))}
                </div>
              </div>
                {/* Backend extraction result */}
                  <div className="w-[420px] shrink-0 flex flex-col border-l border-[var(--line)] bg-[var(--bg-1)] overflow-hidden">
                    <div className="px-4 py-3 border-b border-[var(--line)] shrink-0">
                      <p className="text-[10px] font-mono font-bold text-[var(--fg-4)] uppercase tracking-widest">
                         Backend Extraction Result
                      </p>
                      <p className="text-xs text-[var(--fg-4)] mt-1">
                       Extraction complete. Showing extracted requirement output from backend.
                      </p>
                    </div>

                <div className="flex-1 overflow-auto p-4">
                <div className="mb-3 text-xs text-[var(--fg-3)] space-y-1">
                <div>
                  <strong>Filename:</strong> {extractionResult?.filename}
                </div>
                <div>
                <strong>Mode:</strong> {extractionResult?.mode}
              </div>
                {extractionResult?.extraction_id && (
                <div>
                <strong>Extraction ID:</strong> {extractionResult.extraction_id}
              </div>
               )}
        </div>

          <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-words rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--bg-2)] p-3 text-[var(--fg-3)]">
            {JSON.stringify(
              {
                extraction: extractionResult?.extraction,
                graph: extractionResult?.graph,
                usage: extractionResult?.usage,
              },
              null,
              2
            )}
          </pre>
  </div>
</div>


            </div>
          )}
        </main>
      </div>

      <TweaksPanel />
    </div>
  )
}
