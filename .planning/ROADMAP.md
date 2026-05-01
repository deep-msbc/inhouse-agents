# ROADMAP.md — InHouseAgents

## Project Summary

**Core value:** Given a requirement document, the system generates a deployable Django DRF project
with syntactically valid Python for every app.

**Milestone:** M1 — Stage 3 (Backend Code Gen) + Embedding Pipeline + Frontend UI Port

**Baseline:** Stages 1 and 2 are production-ready. All three open workstreams start from a
working foundation.

---

## Phases

- [ ] **Phase 1: Stage 3 Foundation** - CLI invoker, scaffold validator, ORM entity, schema contracts — hard prerequisites before any code generation
- [ ] **Phase 2: Code Generators** - All per-app code generators (models, serializers, views, urls), YAML prompt templates, and the syntax validator gate
- [ ] **Phase 3: Stage 3 Orchestration & API** - LangGraph flat graph with RAG retrieval, wired into FastAPI endpoint with job polling
- [ ] **Phase 4: Embedding Pipeline** - tree-sitter chunker, embedder, Qdrant store, toolkit and examples ingestors (Yug's workstream)
- [ ] **Phase 5: Frontend UI Port** - Vite + React + TypeScript SPA wired to all backend endpoints with job polling and file tree

---

## Phase Details

### Phase 1: Stage 3 Foundation
**Goal**: The entry-point contract for Stage 3 exists — djcli can be invoked, the scaffold can be verified, the ORM layer is ready to persist results, and schema contracts are in their canonical separate files
**Depends on**: Nothing (brownfield — Stages 1 & 2 already running)
**Requirements**: S3-01, S3-02, S3-13, S3-14
**Success Criteria** (what must be TRUE):
  1. Calling `CLIInvoker.run()` against a valid extraction triggers djcli with `--api` and never `--auth`, and the output path is honoured
  2. `ScaffoldValidator.validate()` returns success when the expected file tree is present and a structured error when any app file is missing
  3. A `BackendGeneration` row can be created and retrieved in the database via its repository; Alembic migration runs clean against both SQLite and Postgres
  4. Three separate schema contract files exist and none imports from the others — a deliberate merge attempt is rejected by module structure
**Plans**: 3 plans

Plans:
- [ ] 01-01-PLAN.md — Add output_path to CLIInvokerInput + S3-14 cross-import audit
- [ ] 01-02-PLAN.md — Build CLIInvoker (cli_invoker.py) and ScaffoldValidator (scaffold_validator.py)
- [ ] 01-03-PLAN.md — BackendGeneration ORM entity, BackendGenerationRepository, Alembic migration

### Phase 2: Code Generators
**Goal**: Every per-app Python file can be independently generated with LLM or Jinja2 as dictated by the architecture, and every generated file passes the syntax validator gate before proceeding
**Depends on**: Phase 1
**Requirements**: S3-03, S3-04, S3-05, S3-06, S3-07, S3-08
**Success Criteria** (what must be TRUE):
  1. `ModelsGenerator.generate(app)` returns a syntactically valid `models.py` string, validated by `ast.parse()` — on LLM syntax failure the error is appended to the prompt and retried up to 2 times
  2. `SerializersGenerator.generate(app)` produces a valid `serializers.py` via LLM with the same 2-retry ast gate
  3. `ViewsGenerator.generate(app)` uses LLM for custom views and Jinja2 for standard CRUD viewsets — swapping the two strategies causes a test assertion failure
  4. `UrlsGenerator.generate(app)` always uses Jinja2 and produces a valid `urls.py` — no LLM call is made regardless of input
  5. Every LLM prompt used by generators is loadable from a YAML file under `llm/prompts/templates/backend_agent/` — no inline prompt string exists in any generator Python file
**Plans**: TBD

### Phase 3: Stage 3 Orchestration & API
**Goal**: A single HTTP call triggers end-to-end Django DRF project generation — LangGraph orchestrates the full pipeline with RAG context, and job status is pollable until the project lands on disk
**Depends on**: Phase 2 (and Phase 4 preferred but not blocking — RAG retrieval gracefully handles empty Qdrant collection)
**Requirements**: S3-09, S3-10, S3-11, S3-12
**Success Criteria** (what must be TRUE):
  1. `POST /backend-generator/generate` with a valid `extraction_id` returns HTTP 202 with a `job_id` in under 500 ms
  2. `GET /backend-generator/jobs/{job_id}` transitions from `pending` → `processing` → `completed` and the response body contains a `PipelineOutput` with all generated files listed
  3. The LangGraph graph is flat (no nested subgraphs) and its node execution order is: CLI Invoke → Scaffold Validate → Code Generate (parallel per app) → Syntax Validate → Finalize
  4. Each app's code-gen node attempts Qdrant search against `examples_openai_large_1536` before its LLM call; if the collection is empty or Qdrant is unreachable, generation proceeds without RAG context (graceful degradation — not a hard failure)
**Notes**: Qdrant RAG retrieval is best-effort in v1. Full RAG quality requires Phase 4 (Embedding Pipeline) to be completed and both collections populated. Stage 3 must never block or fail if Qdrant returns zero results.
**Plans**: TBD
**UI hint**: yes

### Phase 4: Embedding Pipeline
**Goal**: Both Qdrant collections are populated and queryable — Stage 3 RAG retrieval gets real Django DRF examples, and Stage 2 gets real toolkit and frontend examples
**Depends on**: Nothing (self-contained — Yug's workstream, runs in parallel with Phases 1-3)
**Requirements**: EMB-01, EMB-02, EMB-03, EMB-04, EMB-05, EMB-06
**Success Criteria** (what must be TRUE):
  1. A TSX/TS or Python source file passed to the tree-sitter chunker produces a list of chunks, each with file path, language, symbol name, and character offsets as metadata
  2. Each chunk passed to the embedder returns a 1536-dimension float vector produced by `text-embedding-3-large`
  3. Upsert of 100 chunks to Qdrant and a similarity search for a known phrase returns the expected top result with cosine score above threshold
  4. Running the toolkit ingestor against the ReactToolkits monorepo populates `toolkit_openai_large_1536` with at least one point per TSX file found
  5. Running the examples ingestor against `correct_code_examples/` populates `examples_openai_large_1536` with Django DRF pattern chunks queryable by Stage 3
  6. `src/msbc/embedding/` contains exactly the 15 files defined in the spec and the module is importable with no circular imports
**Plans**: TBD

### Phase 5: Frontend UI Port
**Goal**: A developer can open the React SPA, upload a requirement document, watch Stage 1 and Stage 2 run to completion with live status, and see a file tree representing the generated project structure
**Depends on**: Phase 3 (Stage 3 endpoints must exist; Stage 2 endpoint already exists from baseline)
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, UI-06
**Success Criteria** (what must be TRUE):
  1. `npm run dev` starts the Vite dev server with zero TypeScript errors and the app loads in the browser
  2. The ported UI renders identically to the original Claude-designed app.jsx/styles.css layout — all original sections and styles are present
  3. Uploading a .docx or .pdf file triggers `POST /requirement-extractor/parse` and the returned `job_id` is stored in component state
  4. After Stage 1 completes, the `POST /frontend-planner/plan` call fires automatically with the `extraction_id` and the Stage 2 job begins
  5. The polling loop updates a visible progress indicator every 2 seconds until the job reaches a terminal status (`completed` or `failed`)
  6. A file tree panel renders the `SAMPLE_MODULES` mock structure without any live Stage 3 API call
**Plans**: TBD
**UI hint**: yes

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Stage 3 Foundation | 0/3 | Not started | - |
| 2. Code Generators | 0/? | Not started | - |
| 3. Stage 3 Orchestration & API | 0/? | Not started | - |
| 4. Embedding Pipeline | 0/? | Not started | - |
| 5. Frontend UI Port | 0/? | Not started | - |

---

## Coverage

| REQ-ID | Phase | Description |
|--------|-------|-------------|
| S3-01 | Phase 1 | CLI invoker — djcli subprocess wrapper |
| S3-02 | Phase 1 | Scaffold validator — file tree verification |
| S3-13 | Phase 1 | BackendGeneration ORM entity + Alembic migration |
| S3-14 | Phase 1 | Schema contracts in 3 separate files |
| S3-03 | Phase 2 | models_generator.py — LLM + ast.parse() |
| S3-04 | Phase 2 | serializers_generator.py — LLM + ast.parse() |
| S3-05 | Phase 2 | views_generator.py — LLM for custom, Jinja2 for CRUD |
| S3-06 | Phase 2 | urls_generator.py — Jinja2 always |
| S3-07 | Phase 2 | Syntax validator — ast.parse() gate on all files |
| S3-08 | Phase 2 | YAML prompt templates under backend_agent/ |
| S3-09 | Phase 3 | LangGraph flat graph orchestration |
| S3-10 | Phase 3 | RAG retrieval from examples_openai_large_1536 |
| S3-11 | Phase 3 | POST /backend-generator/generate endpoint |
| S3-12 | Phase 3 | GET /backend-generator/jobs/{job_id} endpoint |
| EMB-01 | Phase 4 | tree-sitter chunker |
| EMB-02 | Phase 4 | OpenAI text-embedding-3-large embedder |
| EMB-03 | Phase 4 | Qdrant store — upsert + similarity search |
| EMB-04 | Phase 4 | Toolkit ingestor — ReactToolkits monorepo |
| EMB-05 | Phase 4 | Examples ingestor — correct_code_examples/ |
| EMB-06 | Phase 4 | src/msbc/embedding/ 15-file module structure |
| UI-01 | Phase 5 | Vite + React + TypeScript scaffold |
| UI-02 | Phase 5 | Port app.jsx/styles.css to TypeScript |
| UI-03 | Phase 5 | Stage 1 endpoint wired with real API call |
| UI-04 | Phase 5 | Stage 2 endpoint wired with real API call |
| UI-05 | Phase 5 | Job polling with live status updates |
| UI-06 | Phase 5 | File tree display using SAMPLE_MODULES mock |

**Coverage: 26/26 v1 requirements mapped — 0 orphans**
