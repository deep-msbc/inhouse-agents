# REQUIREMENTS.md

## v1 Requirements

### Stage 3 — Backend Code Generator (Deep)

- [ ] **S3-01**: CLI invoker wraps djcli subprocess with `--api` always, `--auth` never, configurable output path
- [ ] **S3-02**: Scaffold validator confirms expected file tree exists for all apps before generation begins
- [ ] **S3-03**: `models_generator.py` calls LLM to generate models.py per app, validated by ast.parse() with max 2 retries
- [ ] **S3-04**: `serializers_generator.py` calls LLM to generate serializers.py per app, validated by ast.parse() with max 2 retries
- [ ] **S3-05**: `views_generator.py` uses LLM for custom views and Jinja2 for standard CRUD viewsets — never swapped
- [ ] **S3-06**: `urls_generator.py` uses Jinja2 always — LLM never used for URL conf
- [ ] **S3-07**: Syntax validator runs ast.parse() on every generated Python file; retries up to 2 times appending the parse error to the prompt
- [ ] **S3-08**: All Stage 3 LLM prompts stored as YAML files under `llm/prompts/templates/backend_agent/` — no inline strings
- [ ] **S3-09**: Stage 3 LangGraph flat graph orchestrates: CLI Invoke → Scaffold Validate → Code Generate (parallel per app) → Syntax Validate → Finalize
- [ ] **S3-10**: Stage 3 graph retrieves Django DRF examples from Qdrant `examples_openai_large_1536` before per-app code generation
- [ ] **S3-11**: FastAPI endpoint `POST /backend-generator/generate` accepts `extraction_id`, creates Job, queues BackgroundTask, returns job_id
- [ ] **S3-12**: `GET /backend-generator/jobs/{job_id}` returns job status + `PipelineOutput` on completion
- [ ] **S3-13**: `BackendGeneration` ORM entity persists PipelineOutput; Alembic migration created
- [ ] **S3-14**: Schema contracts split across 3 separate files — never merged into a single file

### Embedding Pipeline (Yug)

- [ ] **EMB-01**: tree-sitter chunker splits TSX/TS and Python source files into semantically meaningful chunks with metadata
- [ ] **EMB-02**: OpenAI text-embedding-3-large @ 1536 dimensions embedder generates vectors for each chunk
- [ ] **EMB-03**: Qdrant store supports upsert and similarity search for both collections
- [ ] **EMB-04**: Toolkit ingestor scans ReactToolkits monorepo and populates `toolkit_openai_large_1536` collection
- [ ] **EMB-05**: Examples ingestor scans `correct_code_examples/` and populates `examples_openai_large_1536` collection (frontend + Django DRF patterns)
- [ ] **EMB-06**: `src/msbc/embedding/` module structure matches 15-file spec from plan.md

### Frontend UI Port (Yug/Deep)

- [ ] **UI-01**: Vite + React + TypeScript project scaffolded
- [ ] **UI-02**: Existing Claude-designed app.jsx/styles.css ported to TypeScript components
- [ ] **UI-03**: Stage 1 endpoint (`POST /requirement-extractor/parse`) wired with real API call and file upload
- [ ] **UI-04**: Stage 2 endpoint (`POST /frontend-planner/plan`) wired with real API call
- [ ] **UI-05**: Job polling implemented — polls `GET /jobs/{job_id}` until terminal status, shows live progress
- [ ] **UI-06**: File tree display uses SAMPLE_MODULES mock data (Stage 3 wiring deferred to v2)

## v2 Requirements (Deferred)

- Kuzu graph layer for component relationships (EMB Phase 2 — Qdrant alone sufficient for v1)
- Stage 3 API wiring in Frontend UI (deferred until Stage 3 endpoint exists)
- Test suite (not a priority this sprint)
- Deployment / containerization

## Out of Scope

- `--auth` Django flag — locked out by architecture decision; NEVER generated
- Django migration files — djcli constraint, locked invariant
- Nested LangGraph subgraphs — flat graphs only, locked rule
- Flask / FastAPI as backend generation target — Django DRF only
- Authentication for the DevAgents web app itself — not in scope

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| S3-01 | Phase 1 | Pending |
| S3-02 | Phase 1 | Pending |
| S3-13 | Phase 1 | Pending |
| S3-14 | Phase 1 | Pending |
| S3-03 | Phase 2 | Pending |
| S3-04 | Phase 2 | Pending |
| S3-05 | Phase 2 | Pending |
| S3-06 | Phase 2 | Pending |
| S3-07 | Phase 2 | Pending |
| S3-08 | Phase 2 | Pending |
| S3-09 | Phase 3 | Pending |
| S3-10 | Phase 3 | Pending |
| S3-11 | Phase 3 | Pending |
| S3-12 | Phase 3 | Pending |
| EMB-01 | Phase 4 | Pending |
| EMB-02 | Phase 4 | Pending |
| EMB-03 | Phase 4 | Pending |
| EMB-04 | Phase 4 | Pending |
| EMB-05 | Phase 4 | Pending |
| EMB-06 | Phase 4 | Pending |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 5 | Pending |
| UI-03 | Phase 5 | Pending |
| UI-04 | Phase 5 | Pending |
| UI-05 | Phase 5 | Pending |
| UI-06 | Phase 5 | Pending |
