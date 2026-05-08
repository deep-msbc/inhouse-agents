# CLAUDE.md — InHouseAgents Frontend UI Port
# Read this FULLY before writing any code.

---

## WHO YOU ARE

You are a Senior Frontend Engineer working on the **InHouseAgents** project at MSBC Group.
Your job is to port an existing Claude-designed UI (`app.jsx`, `styles.css`, `tweaks-panel.jsx`, `index.html`)
into a proper **Vite + React + TypeScript** project inside the `frontend/` folder.

---

## PROJECT CONTEXT

This frontend is the UI for an AI agent system that:
1. Takes a `.docx` or `.pdf` user story document as input
2. Calls a FastAPI backend to extract requirements (Stage 1)
3. Calls the backend to generate a frontend plan (Stage 2)
4. Shows the generated file tree and module list in the UI

The backend runs at `http://localhost:8000`.
The frontend runs at `http://localhost:5173` (Vite default).

---

## FOLDER LOCATION

Create everything inside:
```
InHouseAgents/
└── frontend/          ← ALL YOUR WORK GOES HERE
    ├── src/
    ├── public/
    ├── vite.config.ts
    ├── tsconfig.json
    └── package.json
```

DO NOT touch anything outside of `frontend/`. The backend lives in `src/msbc/` and `app/` — leave it alone.

---

## SOURCE DESIGN FILES (Already in repo root — READ ONLY)

These are the original Claude-designed files you must port FROM:

| File | What it contains |
|------|-----------------|
| `app.jsx` | Main App component, all UI logic, TreeNode, buildTree, TopBar, Section, SubBlock, Chip, Checkbox, Radio, Icons |
| `styles.css` | All CSS — dark theme, layout, components, animations |
| `tweaks-panel.jsx` | Floating tweaks panel — useTweaks hook, TweaksPanel, TweakSection, TweakToggle, TweakRadio, TweakColor, TweakSelect, TweakSlider |
| `index.html` | Entry HTML — Google Fonts (Inter, JetBrains Mono, IBM Plex Mono, Geist Mono, Fira Code) |

**MATCH THE DESIGN EXACTLY. Do not redesign anything.**

---

## TARGET FOLDER STRUCTURE

```
frontend/
├── public/
│   └── index.html (Vite entry)
├── src/
│   ├── main.tsx                      ← ReactDOM.createRoot entry
│   ├── App.tsx                       ← Root component (renders Generator page)
│   ├── styles/
│   │   └── global.css                ← Direct copy of styles.css (no changes)
│   ├── types/
│   │   └── api.ts                    ← All TypeScript interfaces
│   ├── services/
│   │   └── api.ts                    ← Axios wrapper for all backend calls
│   ├── hooks/
│   │   └── useJobPoller.ts           ← Polls /jobs/{id} every 2 seconds
│   ├── components/
│   │   ├── Icons.tsx                 ← All SVG icons from app.jsx Icon object
│   │   ├── TopBar.tsx                ← TopBar component
│   │   ├── TreeNode.tsx              ← TreeNode + buildTree logic
│   │   ├── Section.tsx               ← Section + SubBlock components
│   │   ├── Chip.tsx                  ← Chip component
│   │   ├── Checkbox.tsx              ← Checkbox component
│   │   ├── Radio.tsx                 ← Radio component
│   │   └── TweaksPanel.tsx           ← Full port of tweaks-panel.jsx
│   └── pages/
│       └── Generator.tsx             ← Main App component (port of App() from app.jsx)
├── vite.config.ts
├── tsconfig.json
└── package.json
```

---

## DESIGN SYSTEM — EXACT VALUES (from styles.css)

### CSS Variables (copy exactly into global.css)
```css
:root {
  --bg: #0a0a0a;
  --bg-1: #0d0d0d;
  --bg-2: #111213;
  --bg-3: #161618;
  --line: #1e1e1e;
  --line-2: #262628;
  --fg: #e9e9ea;
  --fg-2: #b6b6b8;
  --fg-3: #74747a;
  --fg-4: #4a4a4f;
  --acc: #6366f1;
  --acc-soft: #6366f122;
  --acc-line: #6366f155;
  --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
  --r: 8px;
  --r-lg: 12px;
}
```

### Google Fonts (copy into index.html)
```
Inter (400, 500, 600, 700)
JetBrains Mono (400, 500, 600)
IBM Plex Mono (400, 500, 600)
Geist Mono (400, 500, 600)
Fira Code (400, 500, 600)
```

---

## TYPESCRIPT TYPES (src/types/api.ts)

```typescript
export type JobStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface Job {
  id: string;
  status: JobStatus;
  created_at: string;
}

export interface ExtractionOutput {
  job_id: string;
  modules: string[];
  user_stories?: number;
  entity_diagrams?: number;
}

export interface PlanOutput {
  job_id: string;
  plan: Record<string, unknown>;
}

export type TreeNodeType = 'folder' | 'file';

export interface TreeNode {
  type: TreeNodeType;
  name: string;
  path: string;
  tag?: string;
  children?: TreeNode[];
}

export type ExtractionMode = 'frontend' | 'backend' | 'fullstack';
export type BackendAction = 'startproject' | 'startapp' | 'startservices';

export interface FeFlags {
  components: boolean;
  routing: boolean;
  flow: boolean;
  config: boolean;
}
```

---

## API SERVICE (src/services/api.ts)

Wire these 4 endpoints using axios:

```typescript
// 1. Upload document — multipart/form-data
POST http://localhost:8000/api/v1/requirement-extractor/parse
Body: FormData with file field

// 2. Poll Stage 1 job status
GET http://localhost:8000/api/v1/requirement-extractor/jobs/{job_id}

// 3. Start frontend planner — fires automatically after Stage 1 completes
POST http://localhost:8000/api/v1/frontend-planner/plan
Body: { extraction_id: string }

// 4. Poll Stage 2 job status
GET http://localhost:8000/api/v1/frontend-planner/jobs/{job_id}
```

Use axios with base URL `http://localhost:8000`. Add proxy in vite.config.ts:
```typescript
server: {
  proxy: {
    '/api': 'http://localhost:8000'
  }
}
```

---

## JOB POLLING HOOK (src/hooks/useJobPoller.ts)

```typescript
// Polls every 2000ms until status = 'completed' or 'failed'
// Stops automatically when done
// Returns: { status, data, error, isPolling }
```

---

## SAMPLE DATA (use in v1 — no real API data needed for tree)

```typescript
export const SAMPLE_MODULES = [
  "production_process_master",
  "job_production_tracking",
  "machine_telemetry",
  "operator_assignment",
  "quality_inspection",
];

export const FRONTEND_MODULES = [
  "ProductionProcess",
  "JobTracking",
  "MachineTelemetry",
  "OperatorAssignment",
  "QualityInspection",
];
```

---

## TWEAKS PANEL PORT RULES

The `tweaks-panel.jsx` uses `window.parent.postMessage` for host communication — skip this in the React port.
Instead:
- Use `useState` in `TweaksPanel` component directly
- `useTweaks(defaults)` hook returns `[values, setTweak]`
- Keep all controls: `TweakSection`, `TweakToggle`, `TweakRadio`, `TweakColor`, `TweakSelect`, `TweakSlider`
- Keep the draggable floating panel behavior (fixed bottom-right)
- Keep all CSS classes from `__TWEAKS_STYLE` — move them into `global.css`

---

## VITE CONFIG

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
```

---

## PACKAGE.JSON DEPENDENCIES

```json
{
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "axios": "^1.6.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.1",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0"
  }
}
```

---

## V1 SCOPE — 15 MAY DEMO (DO THESE ONLY)

### ✅ Must Have
1. Vite + React + TS scaffold running (`npm run dev` works)
2. UI matches `app.jsx` design exactly — same layout, same dark theme
3. File upload zone (drag + drop + browse) — wired to Stage 1 API
4. Extraction mode selector (Frontend / Backend / Full Stack cards)
5. Frontend + Backend sub-options (checkboxes, radio buttons)
6. Advanced section (collapsible) — parallel toggle, dep graph toggle, model selector
7. Generate button with progress animation
8. File tree on right side — using SAMPLE_MODULES mock data
9. Module rail on right side — showing SAMPLE_MODULES list
10. Chips (module count, file count, stack label)
11. Job polling hook — polls Stage 1 + Stage 2 every 2s
12. Auto-fire Stage 2 after Stage 1 completes
13. TopBar with brand, pipeline steps, status pill
14. TweaksPanel — floating bottom-right, draggable

### ❌ NOT in v1 (skip for now)
- Stage 3 backend wiring
- Real file tree from API (use SAMPLE_MODULES mock)
- Authentication
- Error toasts / notifications system

---

## STRICT RULES — NEVER VIOLATE

1. **Match app.jsx exactly** — same class names, same layout, same behavior
2. **Copy styles.css as-is** into `src/styles/global.css` — no Tailwind, no CSS modules
3. **No inline styles** except dynamic ones (accent color CSS vars) — use class names
4. **TypeScript strict mode** — no `any` types except where truly unavoidable
5. **No class components** — functional components + hooks only
6. **Axios only** — no fetch API calls
7. **No extra UI libraries** — no MUI, no Ant Design, no Chakra — design is already done
8. **One component per file** — no multiple exports in one file except index.ts barrel files
9. **Keep CSS variable names identical** to original (`--acc`, `--bg`, `--fg`, etc.)
10. **Do not touch backend files** — `src/msbc/`, `app/`, `main.py` are off limits

---

## HOW THE UI LOOKS (reference screenshot description)

- **Dark theme** — near-black background (#0a0a0a)
- **Left panel** — "Configure Your Generation" with 3 numbered sections
  - Section 01: Source Document upload zone
  - Section 02: Extraction Mode (FE / BE / FS cards)
  - Section 03: Advanced (collapsible)
- **Right panel** — "Generation Preview"
  - Chips row (module count, file count, stack label)
  - File tree window (terminal-style with dots bar)
  - Module rail sidebar (numbered list with progress bars)
- **TopBar** — `scaffold/agent` brand + pipeline steps (spec → configure → generate → review) + status pill
- **Tweaks panel** — floating bottom-right, light frosted glass style, draggable

---

## EXECUTION ORDER

Build in this exact order:

1. `npm create vite@latest . -- --template react-ts` in `frontend/`
2. Install axios: `npm install axios`
3. Copy `styles.css` → `src/styles/global.css`
4. Create `src/types/api.ts`
5. Create `src/components/Icons.tsx`
6. Create `src/components/Checkbox.tsx` + `Radio.tsx`
7. Create `src/components/TopBar.tsx`
8. Create `src/components/TreeNode.tsx` (includes buildTree logic)
9. Create `src/components/Section.tsx` + `SubBlock.tsx` + `Chip.tsx`
10. Create `src/components/TweaksPanel.tsx`
11. Create `src/hooks/useJobPoller.ts`
12. Create `src/services/api.ts`
13. Create `src/pages/Generator.tsx` (main App)
14. Update `src/main.tsx` + `src/App.tsx`
15. Update `vite.config.ts` with proxy
16. Test: `npm run dev` — UI should match screenshot exactly

---

## QUESTIONS TO ANSWER BEFORE CODING

If anything is unclear, assume:
- Backend is already running on `localhost:8000`
- Use SAMPLE_MODULES mock — don't wait for real API data for the tree
- If job polling returns error → show failed state, don't crash
- If file upload fails → show error state in the drop zone
