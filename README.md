# DevAgents — AI-Powered Full-Stack Development Agent

> **Single source of truth for the entire InHouseAgents project.**  
> This document covers every component, design decision, data flow, folder, file, schema, algorithm, and configuration value in the system. It is intentionally exhaustive so that any AI tool or new engineer can reach full understanding from this file alone.

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [System Architecture — High Level](#2-system-architecture--high-level)
3. [Team Ownership Map](#3-team-ownership-map)
4. [Full Repository Structure](#4-full-repository-structure)
5. [Technology Stack](#5-technology-stack)
6. [Environment Variables & Configuration](#6-environment-variables--configuration)
7. [Application Entry Point — `main.py`](#7-application-entry-point--mainpy)
8. [Stage 1 — Requirement Extractor (Complete)](#8-stage-1--requirement-extractor-complete)
9. [Stage 2 — Frontend Planner (Complete)](#9-stage-2--frontend-planner-complete)
10. [Embedding Pipeline (Complete)](#10-embedding-pipeline-complete)
11. [KUZU Knowledge Graph (Complete)](#11-kuzu-knowledge-graph-complete)
12. [Database Layer](#12-database-layer)
13. [LLM Client Layer](#13-llm-client-layer)
14. [Utility Layers](#14-utility-layers)
15. [Pydantic Schema Contracts](#15-pydantic-schema-contracts)
16. [JSON-Schema Validation Layer](#16-json-schema-validation-layer)
17. [CLI Scripts](#17-cli-scripts)
18. [Stage 3 — Backend Code Generator (To Build)](#18-stage-3--backend-code-generator-to-build)
19. [Locked Architecture Decisions — Never Violate](#19-locked-architecture-decisions--never-violate)
20. [Token Budget & Concurrency Constants](#20-token-budget--concurrency-constants)
21. [Running the Project](#21-running-the-project)
22. [API Reference](#22-api-reference)
23. [Data Flow — End to End](#23-data-flow--end-to-end)
24. [Bug Fixes Applied (Latest Uncommitted Changes)](#24-bug-fixes-applied-latest-uncommitted-changes)
25. [What Is Planned Next](#25-what-is-planned-next)

---

## 1. What This System Does

**Input:** A user story document (`.docx` or `.pdf`) describing a business application.  
**Output (automated):**
- Structured JSON requirements (screens, fields, endpoints, business rules, enums, workflows)
- Module dependency graph (build order)
- A complete per-module frontend file-manifest plan (components, data hooks, routes, file structure)
- A fully runnable Django REST Framework project with models, serializers, views, and URLs

**Pipeline stages:**

```
User uploads document (.docx / .pdf)
              │
              ▼
 ┌─────────────────────────────┐
 │  Stage 1 — Requirement      │   Extracts structured requirements via LangGraph.
 │  Extractor                  │   Parallel per-module LLM calls. 3-layer JSON validation.
 │  POST /requirement-extractor│   Produces: ExtractionOutput JSON + DependencyGraph
 └─────────────┬───────────────┘
               │  extraction_id (UUID)
               ▼
 ┌─────────────────────────────┐
 │  Stage 2 — Frontend Planner │   Reads extraction from DB. Plans React component tree.
 │                             │   TOON-encodes requirements. Parallel per-module LLM calls.
 │  POST /frontend-planner/plan│   Produces: FrontendPlan JSON (file manifest + data hooks)
 └─────────────┬───────────────┘
               │  plan_id (UUID)
               ▼
 ┌─────────────────────────────┐
 │  Stage 3 — Backend Code Gen │   (To Build — owned by Deep/Shrey)
 │                             │   Invokes djcli scaffold. LLM generates models/serializers/
 │  POST /backend-generator/   │   custom views. Jinja2 generates urls + CRUD viewsets.
 │  generate                   │   Validates syntax with ast.parse(). Writes files to disk.
 └─────────────────────────────┘
```

The system also ships an **Embedding Pipeline** that indexes the internal ReactToolKits monorepo and curated code examples into Qdrant (vector search) and a KUZU graph database. The Frontend Planner uses these as retrieval sources to make toolkit-aware decisions.

---

## 2. System Architecture — High Level

```
┌──────────────────────────────────────────────────────────────────────┐
│                         FastAPI Application                          │
│  main.py → app/api/main_router.py                                    │
│                                                                      │
│  GET  /health                                                        │
│  POST /api/v1/requirement-extractor/parse        (Stage 1)           │
│  GET  /api/v1/requirement-extractor/jobs/{id}                        │
│  POST /api/v1/frontend-planner/plan              (Stage 2)           │
│  GET  /api/v1/frontend-planner/jobs/{id}                             │
│  POST /api/v1/backend-generator/generate         (Stage 3 — TODO)   │
│  GET  /api/v1/jobs/{id}                                              │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
   │  Stage 1     │  │  Stage 2     │  │  Embedding       │
   │  LangGraph   │  │  LangGraph   │  │  Pipeline        │
   │  (graph.py)  │  │  (planner/   │  │  (offline CLI)   │
   │              │  │   graph.py)  │  │                  │
   └──────┬───────┘  └──────┬───────┘  └──────┬───────────┘
          │                 │                  │
          ▼                 ▼                  ▼
   ┌──────────────────────────────────────────────────────┐
   │                OpenAI GPT-4.1-mini                   │
   │  call_llm_with_schema() — tiktoken + jsonschema      │
   └──────────────────────────────────────────────────────┘
          │                 │
          ▼                 ▼
   ┌──────────────────────────────┐     ┌────────────────┐
   │  PostgreSQL (SQLAlchemy ORM) │     │  Qdrant        │
   │  jobs, requirement_          │     │  (vector store) │
   │  extractions, frontend_plans │     │                │
   └──────────────────────────────┘     └────────┬───────┘
                                                  │
                                        ┌─────────┴──────┐
                                        │  KUZU           │
                                        │  (graph store)  │
                                        └─────────────────┘
```

---

## 3. Team Ownership Map

| Component | Owner | Status |
|-----------|-------|--------|
| Stage 1 — Requirement Extractor | Yug | ✅ Complete |
| Stage 2 — Frontend Planner | Yug | ✅ Complete |
| Embedding Pipeline (Qdrant + KUZU) | Yug | ✅ Complete |
| Stage 3 — Backend Code Generator | Deep (runs for Shrey) | 🔴 Not started |
| Frontend UI (Vite + React + TS) | Yug | 🔴 Not started |
| Schema contracts (3 files) | All | ✅ Complete |

Deep runs Claude Code sessions from `D:\shardi\InHouseAgents` on Shrey's behalf for Stage 3.  
Yug works from `C:\Users\yug.chauhan\Desktop\InHouseAgents`.

---

## 4. Full Repository Structure

```
InHouseAgents/                              ← repo root
│
├── main.py                                 ← FastAPI entry point — creates app, registers routers, _init_db()
├── alembic.ini                             ← Alembic migration config
├── CLAUDE.md                               ← AI session instructions (per-session read required)
├── EMBEDDING_AND_GRAPH_GUIDE.md            ← How to run the embedding pipeline
├── README.md                               ← THIS FILE — source of truth
├── requirements.txt                        ← Pip requirements (canonical managed via uv + pyproject.toml)
├── run_commands.md                         ← Quick reference for dev commands
│
├── app/                                    ← Application shell (framework-level concerns)
│   ├── __init__.py
│   ├── dependencies.py                     ← FastAPI shared dependencies (get_db re-exported)
│   ├── api/
│   │   ├── __init__.py
│   │   └── main_router.py                  ← Mounts requirement_extractor + frontend_planner routers
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                       ← Pydantic BaseSettings — ALL env vars live here
│   │   ├── logger.py                       ← get_logger() — structured logging setup
│   │   └── helpers/
│   │       └── message.py                  ← FILE_ERRORS, LLM_ERRORS string constants
│   └── utils/
│       ├── __init__.py
│       └── retry_utils.py                  ← async_retry() — exponential back-off, all LLM + HTTP calls use this
│
├── config/
│   └── settings.yaml                       ← Optional YAML overrides (env vars take precedence)
│
├── correct_code_examples/                  ← Curated hand-written React examples for embedding
│   ├── Dashboard_Samples/
│   │   ├── Dashboard03/  Dashboard04/  Dashboard07/  Dashboard08/  Dashboard09/
│   └── Form_Samples/
│       ├── Form03/  Form04/  Form05/  Form09/  Form10/  Form11/
│
├── data/                                   ← Runtime data files
│   ├── toolkit_graph.kuzu                  ← On-disk KUZU database directory (semantic graph)
│   └── pt_headings_test.json               ← Dev test fixture
│
├── db/                                     ← REFERENCE ONLY — old prototype embedding code. DO NOT MODIFY.
│   ├── chunker.py  embedder.py  enricher.py  query.py  scanner.py
│   └── unified_chunker.py  unified_ingest.py  unified_query.py  unified_schema.py
│
├── responses/                              ← Sample LLM extraction response JSON fixtures
│   ├── Job_Module_1.json  PO_Module_(1).json  Production_Tracking.json
│   └── Stock_Module_1.json  Stock_Module_2.json  Stock_Module_3.json
│
├── scripts/                                ← Standalone CLI scripts (offline use)
│   ├── embed_toolkit.py                    ← Sync RTK monorepo → Qdrant toolkit collection
│   ├── embed_examples.py                   ← Sync correct_code_examples → Qdrant examples collection
│   ├── build_graph.py                      ← Build/rebuild KUZU semantic knowledge graph
│   ├── build_rtk_code_graph.py             ← Build KUZU code-level graph (SourceFile/ExportedSymbol nodes)
│   ├── check_jobs_schema.py                ← Dev utility: inspect jobs table schema
│   ├── create_jobs_table.py                ← Dev utility: manually create jobs table
│   └── test_segmentation.py               ← Dev utility: test heading segmentation
│
├── SKELETON/                               ← Project bootstrap template — not active code
│
└── src/
    └── msbc/                               ← Core domain package
        ├── __init__.py
        ├── config.py                       ← Domain constants: token budgets, pricing, concurrency caps
        │
        ├── models/
        │   ├── __init__.py
        │   ├── schemas/
        │   │   ├── __init__.py
        │   │   ├── requirement.py          ← Pydantic models for Stage 1 output
        │   │   ├── frontend_plan.py        ← Pydantic models for Stage 2 output
        │   │   ├── backend_pipeline.py     ← Pydantic models for Stage 3 I/O contracts
        │   │   └── job.py                  ← JobSubmitResponse, JobStatusResponse
        │   └── entities/
        │       ├── __init__.py
        │       ├── job.py                  ← SQLAlchemy ORM: jobs table
        │       ├── requirement_extraction.py ← SQLAlchemy ORM: requirement_extractions table
        │       └── frontend_plan.py        ← SQLAlchemy ORM: frontend_plans table
        │
        ├── database/
        │   ├── __init__.py
        │   ├── base.py                     ← DeclarativeBase + create_engine (PostgreSQL/SQLite)
        │   ├── session.py                  ← get_db() dependency — yields Session
        │   ├── migrations/
        │   │   └── env.py                  ← Alembic env — imports all entities via Base.metadata
        │   └── repositories/
        │       ├── __init__.py             ← Re-exports all repository classes
        │       ├── base_repository.py      ← BaseRepository[T] — create/get/list/delete
        │       ├── job_repository.py       ← JobRepository — create_job, mark_processing/completed/failed
        │       ├── requirement_repository.py ← RequirementRepository — save_extraction, get_by_id
        │       └── frontend_plan_repository.py ← FrontendPlanRepository — save_plan, get_by_extraction_id
        │
        ├── llm/
        │   ├── __init__.py
        │   ├── clients/
        │   │   ├── __init__.py
        │   │   └── openai_client.py        ← call_llm(), call_llm_with_schema(), count_tokens(), merge_usage()
        │   └── prompts/
        │       ├── __init__.py
        │       └── templates/
        │           ├── requirement_extractor/
        │           │   ├── base_rules.yaml       ← Shared fidelity rules injected into every extraction prompt
        │           │   ├── segmentation.yaml     ← Module classification prompt (MODULE vs IGNORE)
        │           │   ├── frontend_extraction.yaml  ← Per-module frontend extraction prompt
        │           │   ├── backend_extraction.yaml   ← Per-module backend extraction prompt
        │           │   ├── both_extraction.yaml      ← Per-module frontend+backend extraction prompt
        │           │   ├── summary_extraction.yaml   ← Module summary prompt (1-2 sentence summaries)
        │           │   ├── unification.yaml          ← Unify N module summaries into global rules/enums
        │           │   └── graph_builder.yaml        ← Dependency graph generation prompt
        │           └── frontend_planner/
        │               └── plan_module.yaml      ← Full frontend plan prompt (component tree + file manifest)
        │
        ├── agents/
        │   ├── __init__.py
        │   ├── schemas/
        │   │   ├── __init__.py
        │   │   ├── requirement_extractor/
        │   │   │   ├── __init__.py           ← Re-exports all schema dicts
        │   │   │   ├── frontend.py           ← FRONTEND_SCHEMA (jsonschema Draft202012)
        │   │   │   ├── backend.py            ← BACKEND_SCHEMA
        │   │   │   ├── combined.py           ← COMBINED_SCHEMA (both mode)
        │   │   │   ├── summary.py            ← SUMMARY_SCHEMA
        │   │   │   ├── unified.py            ← UNIFIED_SCHEMA (global rules + enums)
        │   │   │   ├── segmentation.py       ← SEGMENTATION_SCHEMA + CLASSIFICATION_SCHEMA
        │   │   │   └── graph_output.py       ← GRAPH_OUTPUT_SCHEMA
        │   │   └── frontend_planner/
        │   │       ├── __init__.py
        │   │       └── schema.py             ← PLANNER_OUTPUT_SCHEMA
        │   └── frontend_planner/
        │       ├── __init__.py
        │       ├── toolkit_knowledge.py      ← PACKAGES dict — source of truth for all @msbc/* components
        │       └── toon_serializer.py        ← TOON v3.0 serializer — converts requirement JSON → compact string
        │
        ├── orchestration/
        │   ├── __init__.py
        │   ├── graph.py                      ← Stage 1 LangGraph — DO NOT TOUCH
        │   ├── state.py                      ← ExtractionState TypedDict — DO NOT TOUCH
        │   ├── nodes/
        │   │   ├── __init__.py
        │   │   ├── node_definitions.py       ← segmentation_node, extract_module_node, finalize_node
        │   │   └── edge_logic.py             ← fan_out_to_modules (Send fan-out)
        │   └── planner/
        │       ├── __init__.py
        │       ├── graph.py                  ← Stage 2 LangGraph — DO NOT TOUCH
        │       ├── state.py                  ← FrontendPlannerState TypedDict — DO NOT TOUCH
        │       └── nodes.py                  ← prepare_node, plan_module_node, finalize_plan_node
        │
        ├── api/
        │   └── v1/
        │       └── endpoints/
        │           ├── requirements.py       ← POST /requirement-extractor/parse + GET /jobs/{id}
        │           └── frontend_planner.py   ← POST /frontend-planner/plan + GET /jobs/{id}
        │
        ├── embedding/
        │   ├── __init__.py
        │   ├── schema.py                     ← ToolkitChunkPayload, ExampleChunkPayload, get_collection_name()
        │   ├── chunker.py                    ← tree-sitter AST chunker (200–800 token envelopes)
        │   ├── embedder.py                   ← OpenAIEmbedder — batched async embedding with retry
        │   ├── store.py                      ← QdrantStore — collection bootstrap, upsert, delete, diff
        │   ├── graph_schema.py               ← KUZU DDL constants (all CREATE TABLE / CREATE REL TABLE)
        │   ├── graph_builder.py              ← build_graph() / rebuild_graph() — populates KUZU from PACKAGES
        │   ├── graph_store.py                ← KuzuStore — read-only Cypher query interface
        │   ├── code_graph_builder.py         ← Builds SourceFile/ExportedSymbol code-level graph
        │   └── ingestors/
        │       ├── __init__.py
        │       ├── scanner.py                ← scan_toolkit() — walks RTK monorepo, returns FileRecord list
        │       ├── toolkit_ingestor.py       ← ingest_toolkit() — incremental Qdrant sync for toolkit
        │       └── examples_ingestor.py      ← ingest_examples() — incremental Qdrant sync for examples
        │
        └── utils/
            ├── __init__.py
            ├── validators.py                 ← validate_file_size(), validate_mode(), validate_uploaded_file()
            └── extractors/
                ├── __init__.py               ← Re-exports extract_text_from_file(), extract_heading_hierarchy()
                ├── docx_extractor.py         ← python-docx: extract_text(), extract_heading_hierarchy()
                └── pdf_extractor.py          ← PyMuPDF: extract_text(), extract_heading_hierarchy()
```

---

## 5. Technology Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Runtime | Python 3.12 | |
| Web framework | FastAPI + Uvicorn | |
| Package manager | `uv` | Use `uv add` not `pip install` |
| App DB | PostgreSQL (prod) / SQLite (dev) | SQLAlchemy ORM + Alembic migrations |
| ORM | SQLAlchemy 2.x (mapped_column style) | |
| Migrations | Alembic | `alembic upgrade head` |
| LLM | OpenAI GPT-4.1-mini (`gpt-4.1-mini`) | via LangChain ChatOpenAI |
| LLM token counting | tiktoken | `cl100k_base` fallback |
| LLM JSON validation | jsonschema Draft 2020-12 | `Draft202012Validator` |
| Workflow engine | LangGraph (flat graphs only) | Send API for parallel fan-out |
| Vector DB | Qdrant | `qdrant-client` |
| Graph DB | KUZU (embedded) | `kuzu` pip package |
| AST chunking | tree-sitter (`tree-sitter-typescript`) | TypeScript/TSX grammars |
| Retry | `app/utils/retry_utils.py` | exponential back-off |
| DOCX parsing | `python-docx` | |
| PDF parsing | PyMuPDF (`fitz`) | |
| Dependency injection | FastAPI `Depends` | |
| CORS | `starlette.middleware.cors` | |
| Settings | `pydantic-settings` (BaseSettings) | `.env` file support |

---

## 6. Environment Variables & Configuration

All environment variables are defined in `app/core/config.py` as a `pydantic-settings` `BaseSettings` class. They can be overridden via:
- `.env` file at project root
- System environment variables
- `config/settings.yaml` (optional)

### Full Settings Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_NAME` | `DevAgents` | Shown in Swagger UI and logs |
| `VERSION` | `0.1.0` | API version |
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` |
| `DEBUG` | `True` | FastAPI debug mode |
| `API_V1_PREFIX` | `/api/v1` | All routes prefixed with this |
| `HOST` | `0.0.0.0` | Uvicorn bind address |
| `PORT` | `8000` | Uvicorn port |
| `RELOAD` | `True` | Uvicorn hot-reload |
| `CORS_ORIGINS` | `["*"]` | Allowed CORS origins |
| `OPENAI_API_KEY` | _(required)_ | OpenAI secret key |
| `LLM_MODEL` | `gpt-4.1-mini` | Model for all LLM calls |
| `LLM_TIMEOUT` | `300` | Seconds per individual LLM call |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/devagents` | Supports `sqlite:///./dev.db` |
| `DATABASE_ECHO` | `False` | Log all SQL to stdout |
| `DATABASE_POOL_SIZE` | `10` | SQLAlchemy pool size |
| `DATABASE_MAX_OVERFLOW` | `5` | SQLAlchemy overflow |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server address |
| `QDRANT_API_KEY` | `""` | Qdrant API key (leave empty for local) |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` | Embedding model — never change |
| `EMBEDDING_DIMENSIONS` | `1536` | Matryoshka truncated dimension — never change |
| `RTK_MONOREPO_PATH` | `""` | Absolute path to ReactToolKits repo root |
| `EXAMPLES_DIR` | `correct_code_examples` | Relative path to curated examples dir |
| `KUZU_DB_PATH` | `./data/toolkit_graph.kuzu` | KUZU on-disk database directory |

### Domain Constants (`src/msbc/config.py`)

These are pure constants — not env vars. They are imported throughout the domain layer.

| Constant | Value | Purpose |
|----------|-------|---------|
| `TOTAL_INPUT_TOKEN_LIMIT` | `12000` | Hard cap: system+user+doc tokens per LLM call |
| `PROMPT_MAX_TOKENS` | `4000` | Reserved for prompt templates (system + user) |
| `API_RETRY_ATTEMPTS` | `3` | Total attempts (1 original + 2 retries) |
| `API_RETRY_BASE_DELAY` | `1.0` | First retry wait (doubles: 1→2→4s) |
| `SCHEMA_VALIDATION_RETRIES` | `2` | Extra attempts on JSON/schema mismatch |
| `MAX_FILE_SIZE_BYTES` | `20 MB` | Upload size limit |
| `ALLOWED_EXTENSIONS` | `{.docx, .pdf}` | Permitted upload types |
| `VALID_MODES` | `{frontend, backend, both}` | Extraction mode enum |
| `LLM_MAX_CONCURRENCY` | `15` (env: `LLM_MAX_CONCURRENCY`) | Global asyncio.Semaphore cap on simultaneous OpenAI calls |
| `MODULE_EXTRACTION_TIMEOUT` | `900` (env: `MODULE_EXTRACTION_TIMEOUT`) | Per-module async timeout in seconds |
| `MODULE_BATCH_SIZE` | `3` (env: `MODULE_BATCH_SIZE`) | Max parallel extract_module_node coroutines |

---

## 7. Application Entry Point — `main.py`

```
main.py
├── Creates FastAPI app with PROJECT_NAME, VERSION, DEBUG from settings
├── _init_db() — creates SQLite tables via create_all (SQLite dev mode only)
├── CORSMiddleware — allow_origins=* by default
├── Includes api_router at prefix "/api/v1"
└── GET /health → {"status": "ok", "project": ..., "version": ...}
```

`app/api/main_router.py` mounts:
- `requirement_extractor_router` from `src.msbc.api.v1.endpoints.requirements`
- `frontend_planner_router` from `src.msbc.api.v1.endpoints.frontend_planner`

---

## 8. Stage 1 — Requirement Extractor (Complete)

### Purpose
Takes a user story document and extracts fully structured requirements for every module: screens, fields, components, API endpoints, DB models, business rules, workflows, enums. Also builds a module dependency graph.

### API
```
POST /api/v1/requirement-extractor/parse   → 202 {job_id, status: "pending"}
GET  /api/v1/requirement-extractor/jobs/{job_id} → JobStatusResponse
```

The POST endpoint accepts `multipart/form-data`:
- `file`: `.docx` or `.pdf`
- `mode`: `frontend` | `backend` | `both`

### Complete Data Flow

```
1. FastAPI validates file (size ≤ 20MB, extension in {.docx, .pdf})
2. Extracts document text + heading hierarchy from the file
   ├── .docx → docx_extractor.extract_text() + extract_heading_hierarchy()
   └── .pdf  → pdf_extractor.extract_text() + extract_heading_hierarchy()
3. Creates Job record in DB (status="pending"), returns job_id
4. Fires BackgroundTasks._run_extraction_job(job_id, document_text, heading_hierarchy, mode, filename)
   ├── Marks job processing
   ├── Calls run_extraction(document_text, heading_hierarchy, mode)
   │   └── [LangGraph workflow — see below]
   ├── Saves RequirementExtraction record in DB
   ├── Marks job completed with result payload
   └── On error: marks job failed with error_message
```

### LangGraph Workflow (`src/msbc/orchestration/graph.py`)

**Topology (flat — no nested subgraphs):**

```
START → segmentation_node ──fan-out via Send──► extract_module_node (×N, parallel)
                                                        │
                                                  finalize_node → END
```

**ExtractionState TypedDict** (`src/msbc/orchestration/state.py`):
```python
{
  document_text:     str           # full plain-text content
  heading_hierarchy: list[dict]    # [{level, text}, ...]
  mode:              str           # frontend | backend | both
  modules:           list[dict]    # set by segmentation_node
  results:           Annotated[list[ModuleResult], operator.add]  # parallel reducer
  extraction:        dict          # set by finalize_node
  graph:             dict          # dependency graph set by finalize_node
  all_usage:         list[dict]    # aggregated across all nodes
}
```

**Node 1 — `segmentation_node`** (`node_definitions.py`):
1. Pre-cleans heading hierarchy: filters to levels 1–4, deduplicates, strips noise
2. Selects structural "container" heading candidates (headings with child sub-sections)
3. Makes ONE LLM call with `segmentation.yaml` prompt + CLASSIFICATION_SCHEMA
4. LLM classifies each candidate as `MODULE` or `IGNORE`
5. Returns list of identified modules with `{name, heading, level, description}`

**Fan-out — `fan_out_to_modules`** (`edge_logic.py`):
- Uses LangGraph `Send` API to dispatch one `ModuleSlice` per module to `extract_module_node`
- Respects `MODULE_BATCH_SIZE` — only N coroutines run simultaneously

**Node 2 — `extract_module_node`** (parallel, N instances, `node_definitions.py`):

For each module:
1. `_slice_module_text()` — extracts the document section for this module
   - Uses 3-pass heading search (exact → case-insensitive → whitespace-collapsed)
   - Falls back to full document if heading not found
2. Token counting via `count_tokens()` — truncates to `TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS` if over limit
3. Calls extraction LLM with mode-appropriate prompt:
   - `frontend` → `frontend_extraction.yaml` + `FRONTEND_SCHEMA`
   - `backend` → `backend_extraction.yaml` + `BACKEND_SCHEMA`
   - `both` → `both_extraction.yaml` + `COMBINED_SCHEMA` (two sequential calls: Phase A frontend, Phase B backend)
4. Normalizes component structure: uppercase `TOOLBAR`/`GRID` etc → lowercase `type` strings
5. Validates `opens_screen` references against known screen names
6. Calls summary LLM with `summary_extraction.yaml` + `SUMMARY_SCHEMA`
7. Returns `ModuleResult {module_name, extraction, summary, usage}`

**Node 3 — `finalize_node`** (`node_definitions.py`):
1. Pure-Python collection of all `ModuleResult` objects from the reducer
2. Makes ONE LLM call with `unification.yaml` prompt (SUMMARY ONLY — NOT full extractions)
   - Produces global enums and global business rules
3. Makes ONE LLM call with `graph_builder.yaml` prompt — builds dependency graph from module summaries
4. Assembles final `extraction` dict with `{modules, total_modules, mode, global_enums, global_business_rules}`
5. Returns `{extraction, graph, all_usage}`

### Document Extractors

**`docx_extractor.py`**:
- `extract_text()` — walks body elements in order (paragraphs + tables interleaved), applies Markdown-style markers (`#`, `##`, `  - `) for structure
- `extract_heading_hierarchy()` — dual-layer: style-based first (Heading 1–6 / Title), heuristic fallback (numbered patterns, ALL-CAPS short lines)

**`pdf_extractor.py`**:
- Uses PyMuPDF (`fitz`) — extracts text block by block
- Heading detection: font size comparison, bold detection, numbered patterns

### Heading-Finding Algorithm (`_find_heading` — Fixed)

A critical fix was applied to handle PDF/DOCX heading artifacts (extra whitespace, page numbers embedded in headings):

```python
def _find_heading(document_text, heading):
    # Pass 1: exact substring match
    # Pass 2: case-insensitive exact match
    # Pass 3: whitespace-collapsed case-insensitive match
    #   → normalises "Step 1        6 How PO is Created"
    #     to match "Step 1 How PO is Created"
    #   → walks original text to recover original character position
```

This fix eliminates the "Heading not found, using full document" fallback that was causing ~18k token inputs per module.

---

## 9. Stage 2 — Frontend Planner (Complete)

### Purpose
Takes an `extraction_id` (UUID of a saved `RequirementExtraction`) and produces a rich file-manifest plan for every frontend module: what React components to use, from which @msbc/* packages, which data hooks, routes, file structure, similarity search queries for RAG retrieval.

### API
```
POST /api/v1/frontend-planner/plan         → 202 {job_id, status: "pending"}
GET  /api/v1/frontend-planner/jobs/{job_id} → JobStatusResponse
```

POST body (JSON):
```json
{
  "extraction_id": "<UUID of a RequirementExtraction with mode=frontend or both>",
  "parallel": true
}
```

### LangGraph Workflow (`src/msbc/orchestration/planner/graph.py`)

**Topology (flat):**
```
START → prepare_node ──fan-out via Send──► plan_module_node (×N, parallel)
                                                    │
                                              finalize_plan_node → END
```

**FrontendPlannerState TypedDict** (`src/msbc/orchestration/planner/state.py`):
```python
{
  extraction_id:          str
  extracted_requirements: dict         # full JSON from DB
  dependency_graph:       dict | None
  parallel:               bool
  modules:                list[dict]   # set by prepare_node
  shared_enums:           dict         # global_enums
  shared_rules:           list[str]    # global_business_rules
  dep_priority_map:       dict[str, int]  # {module_name → priority}
  plan_results:           Annotated[list[ModulePlanResult], operator.add]
  final_plan:             list[dict]
  all_usage:              list[dict]
}
```

**Node 1 — `prepare_node`**:
- Reads `extracted_requirements.modules` from state
- Normalises both mode shapes (frontend-only and both) into a flat list
- Builds `dep_priority_map` from `dependency_graph.nodes[].build_order`
- Extracts `global_enums` and `global_business_rules`

**Node 2 — `plan_module_node`** (parallel, one per module):
1. TOON-encodes the module via `toon_single_module()` from `toon_serializer.py`
2. Builds toolkit context string from `build_toolkit_context()` in `toolkit_knowledge.py`
3. Calls LLM with `plan_module.yaml` prompt + `PLANNER_OUTPUT_SCHEMA`
4. Returns a `ModulePlan` dict

**Node 3 — `finalize_plan_node`**:
- Sorts `plan_results` by `dep_priority`
- Merges all usage dicts
- Returns `PlannerOutput(modules=[...], usage=PlannerLLMUsage(...))`

### TOON Serializer (`toon_serializer.py`)

TOON = Token-Oriented Object Notation v3.0. A compact, lossless, human-readable line-oriented format designed to reduce token count while preserving all structured data for the LLM.

- Objects: `key: value` per line, indented for nesting
- Primitive arrays: `key[N]: v1,v2,v3`
- Expanded list items: `- `
- Values are quoted only when necessary (contains special chars, reserved words, whitespace)

Both `frontend` and `both` extraction shapes are normalised to the same intermediate dict before TOON encoding.

### Toolkit Knowledge (`toolkit_knowledge.py`)

The `PACKAGES` dict is the **single source of truth** for the internal @msbc/* React toolkit. It describes every exported component with:
- `when_to_use` — list of usage conditions
- `do_not_use_when` — list of exclusion conditions
- `internally_uses` — composition dependencies
- `data_layer_hooks` — which hooks the component manages internally
- `key_props` — prop names and types
- Detailed config field descriptions

Packages covered:
- `@msbc/config-ui` → `ConfigurableDashboard`, `ConfigurableForm`
- `@msbc/react-toolkit` → atomic primitives (Button, Input, Dropdown, Table, List, Pagination, Modal, etc.)
- `@msbc/data-layer` → `useApiRequest`, `createApiSlice`, `apiClient`, `tokenManager`
- `@msbc/utils` → `classname`, `isEmpty`, `useDebounce`, etc.
- `@msbc/import-utils` → `ImportWizard`, `FieldMapper`
- `@msbc/config-app-shell` → `AppShell`, `LayoutRoute`, `ShellRoutes`

---

## 10. Embedding Pipeline (Complete)

The embedding pipeline is an **offline process** (CLI scripts). It indexes two data sources into Qdrant and exposes them to the Frontend Planner via vector similarity search.

### Collections

| Collection Name | Source | Purpose |
|----------------|--------|---------|
| `toolkit_openai_large_1536` | RTK monorepo `.ts`/`.tsx` files | Component source code + usage patterns |
| `examples_openai_large_1536` | `correct_code_examples/` folder | Curated reference implementations |

Collection names are generated deterministically by `get_collection_name(kind, dims)` in `schema.py`.

### Chunker (`src/msbc/embedding/chunker.py`)

Smart AST-aware chunker built from scratch (not the old `db/` prototype). Key details:
- Uses **tree-sitter** with TypeScript and TSX grammars (two separate grammars)
- Token envelope: **MIN 200 tokens / MAX 800 tokens** per chunk
  - Chunks below MIN are merged upward
  - Chunks above MAX are split at blank-line boundaries
- Files under `SMALL_FILE_THRESHOLD` (500 tokens) → single chunk
- **Enriched embed text** — prepended context header carries metadata inside the vector
- **Component guidance injection** — `when_to_use` / `do_not_use_when` from `PACKAGES` prepended to relevant chunks
- Feature detection functions (private but importable):
  - `_detect_complexity(content)` → `low | medium | high`
  - `_detect_dashboard_features(content)` → `set[str]`
  - `_detect_form_features(content)` → `set[str]`
  - `_detect_example_pattern(content)` → `dashboard | form | detail | ...`
  - `_detect_file_role(content)` → `config | component | hook | types | ...`
  - `_generate_use_case(pattern, features, imports)` → natural-language use case string

**Public API:**
```python
chunk_toolkit_file(file_path, content, namespace, module_layer) → list[ChunkResult]
chunk_example_file(file_path, content, example_id, group, pattern, role, features) → list[ChunkResult]
build_example_summary_chunk(example_id, group, files_info) → ChunkResult
build_embed_text(chunk_result) → str
```

### Embedder (`src/msbc/embedding/embedder.py`)

`OpenAIEmbedder` class:
- Model: `text-embedding-3-large`, dimensions: `1536`
- Batch size: **100 texts per API call** (OpenAI limit is 2048)
- Retry via `async_retry()` — retries on `RateLimitError`, `APIConnectionError`, `APITimeoutError`, `InternalServerError`
- Tracks per-call and cumulative token usage + USD cost (`$0.13 per 1M tokens`)

### QdrantStore (`src/msbc/embedding/store.py`)

`QdrantStore` class:
- Collection bootstrap — `create_collection()` if not exists, applies payload indexes
- Batched upsert — **64 points per call** (`UPSERT_BATCH_SIZE`)
- Filter-based delete by `file_path` (incremental sync)
- Full-collection scroll (`get_stored_file_hashes()`) — returns `{file_path: file_id}` map for diff

### Toolkit Ingestor (`ingestors/toolkit_ingestor.py`)

`ingest_toolkit(dry_run, full_sync)` — incremental sync algorithm:
1. Bootstrap Qdrant collection + indexes
2. Fetch stored `{file_path: file_id}` hashes from Qdrant
3. Scan monorepo via `scan_toolkit()` → list of `FileRecord`
4. Diff: ADD (new file), UPDATE (hash changed), DELETE (removed from disk)
5. DELETE removed files from Qdrant
6. For each ADD/UPDATE:
   - Extract imports/exports
   - Chunk with `chunk_toolkit_file()`
   - Embed with `OpenAIEmbedder`
   - Build `ToolkitChunkPayload` + `PointStruct`
   - Upsert to Qdrant
7. Log: added, updated, deleted, total tokens, estimated cost

### Examples Ingestor (`ingestors/examples_ingestor.py`)

`ingest_examples(dry_run, example_id, examples_dir)` — per-folder sync:
1. Bootstrap Qdrant examples collection
2. Walk `examples_dir/{group}/{example_id}/` (two levels)
3. Per folder: collect `.tsx`/`.ts` files + SHA-256 hashes
4. If any file changed or set changed → reprocess entire folder:
   - Feature detection per file
   - Build `ExampleChunkPayload` per chunk
   - Build synthetic **summary chunk** (`is_summary_chunk=True`)
   - Embed all texts in one batch call
   - Delete old Qdrant points, upsert new
5. Orphan cleanup: delete entries no longer on disk

### Scanner (`ingestors/scanner.py`)

`scan_toolkit(monorepo_path)` → `list[FileRecord]`:
- Walks 6 source directories mapped to `@msbc/*` namespaces:
  - `packages/react-toolkit/src` → `@msbc/react-toolkit`
  - `packages/config-ui/src` → `@msbc/config-ui`
  - `packages/data-layer/src` → `@msbc/data-layer`
  - `packages/config-app-shell/src` → `@msbc/config-app-shell`
  - `packages/import-utils/src` → `@msbc/import-utils`
  - `packages/utils/src` → `@msbc/utils`
- Skips: `node_modules/`, `dist/`, `.storybook/`, `__tests__/`, `*.test.*`, `*.spec.*`, `*.d.ts`, `*.stories.*`, empty files
- Returns `FileRecord(path, namespace, module_layer, content, sha256, ext)`

### Payload Schemas (`embedding/schema.py`)

```python
class ToolkitChunkPayload(BaseModel):
    chunk_id:       str       # "{normalised_path}__chunk_{index}"
    file_id:        str       # SHA-256 of file content
    file_path:      str       # relative path within monorepo
    namespace:      str       # "@msbc/react-toolkit" etc.
    module_layer:   str       # "atomic" | "ui" | "data" | "shell" | "utils"
    chunk_index:    int
    embed_text:     str       # text that was embedded (with context header)
    created_at:     datetime

class ExampleChunkPayload(BaseModel):
    chunk_id:       str
    file_id:        str
    file_path:      str
    example_id:     str       # e.g. "Dashboard03"
    group:          str       # e.g. "Dashboard_Samples"
    pattern:        str       # "dashboard" | "form" | "detail" | ...
    role:           str       # "config" | "component" | "hook" | ...
    features:       list[str] # detected feature flags
    complexity:     str       # "low" | "medium" | "high"
    is_summary_chunk: bool
    embed_text:     str
    created_at:     datetime
```

---

## 11. KUZU Knowledge Graph (Complete)

KUZU is an embedded graph database (like SQLite but for graphs). It provides structured, traversal-based retrieval that complements Qdrant vector search.

### Graph Schema (`embedding/graph_schema.py`)

**Semantic graph node tables:**

| Node Table | Primary Key | Description |
|-----------|-------------|-------------|
| `Package` | `name` | @msbc/* npm package |
| `Component` | `id` = `"{import_path}::{component_name}"` | React component or hook |
| `TypeDef` | `id` = `"{import_path}::{type_name}"` | TypeScript interface/type |
| `Feature` | `name` | Named capability flag (e.g. `has_search`) |
| `FieldType` | `name` | Form field type (e.g. `fileUpload`, `select`) |
| `Example` | `example_id` | One `correct_code_examples/{group}/{id}/` folder |
| `ExampleFile` | `file_path` | One source file within an Example |

**Semantic relationship tables:**

| Relationship | From → To | Meaning |
|-------------|-----------|---------|
| `BelongsTo` | Component → Package | Component is part of this package |
| `InternallyUses` | Component → Component | Composition/orchestration |
| `UsesType` | Component → TypeDef | Component accepts this type |
| `UsesHook` | Component → Component | Component depends on this hook |
| `ExhibitsFeature` | Component/Example → Feature | Has this capability |
| `SupportsFieldType` | Component → FieldType | Supports this field type |
| `DemonstratesComponent` | Example → Component | Example shows usage of component |
| `ExhibitsFieldType` | Example → FieldType | Example uses this field type |
| `HasFile` | Example → ExampleFile | Example contains this file |

**Code-graph node tables:**

| Node Table | Description |
|-----------|-------------|
| `SourceFile` | One `.ts`/`.tsx` file in the monorepo |
| `ExportedSymbol` | A named symbol exported by a SourceFile |

**Code-graph relationship tables:**

| Relationship | Description |
|-------------|-------------|
| `FileBelongsTo` | SourceFile → Package |
| `ImportsFrom` | SourceFile → SourceFile (intra-package) |
| `ImportsPackage` | SourceFile → Package (@msbc/* cross-package) |
| `ExportsSymbol` | SourceFile → ExportedSymbol |
| `ReExportsFrom` | SourceFile → SourceFile (export * from) |
| `SymbolLinkedToComponent` | ExportedSymbol → Component (code ↔ semantic bridge) |

### Graph Builder (`embedding/graph_builder.py`)

`build_graph(db_path)`:
1. Opens KUZU at `db_path`, runs all `ALL_DDL` statements (idempotent `IF NOT EXISTS`)
2. Iterates `PACKAGES` dict from `toolkit_knowledge.py`:
   - Creates `Package` nodes
   - Creates `Component` nodes with `when_to_use`/`do_not_use_when` as `STRING[]`
   - Creates `TypeDef`, `Feature`, `FieldType` nodes
   - Creates all relationship edges
3. Walks `correct_code_examples/` on disk:
   - Creates `Example`, `ExampleFile` nodes
   - Creates `HasFile`, `DemonstratesComponent`, `ExhibitsFeature`, `ExhibitsFieldType` edges

`rebuild_graph(db_path)`:
- Drops all tables in `DROP_ORDER` (reverse of dependency order)
- Then calls `build_graph()`

### KuzuStore (`embedding/graph_store.py`)

Read-only interface — writes only happen via `graph_builder`.

```python
store = KuzuStore()                      # opens data/toolkit_graph.kuzu
rows = store.query("MATCH (c:Component) WHERE c.name = 'ConfigurableDashboard' RETURN c")
# Returns: [{"c": {...}}]
```

High-level helper methods are thin wrappers around `query()`. Used by agent nodes inside LangGraph workflows for structured retrieval.

### Code Graph Builder (`embedding/code_graph_builder.py`)

`build_code_graph(db_path, monorepo_path)`:
- Scans every `.ts`/`.tsx` file in all 6 `SCAN_DIRS`
- For each file: creates `SourceFile` node
- Regex-parses `import` statements → `ImportsFrom` / `ImportsPackage` edges
- Regex-parses `export` statements → `ExportedSymbol` nodes + `ExportsSymbol` edges
- Regex-parses `export * from '...'` → `ReExportsFrom` edges
- For each `ExportedSymbol` matching an existing `Component.name` → `SymbolLinkedToComponent` edge

---

## 12. Database Layer

### Engine & Base (`database/base.py`)

```python
class Base(DeclarativeBase): ...  # all ORM models inherit this

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    pool_size=settings.DATABASE_POOL_SIZE,   # PostgreSQL only
    max_overflow=settings.DATABASE_MAX_OVERFLOW,  # PostgreSQL only
    pool_pre_ping=True,                       # PostgreSQL only
)
```

SQLite mode (detected by `startswith("sqlite")`): disables pool tunables and uses `String(36)` for UUID columns.

### Session (`database/session.py`)

```python
def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
```

Used as FastAPI `Depends(get_db)` in endpoints. **Background tasks create fresh sessions** via a `_bg_session()` context manager (same pattern) because the request session closes when the HTTP response is sent.

### ORM Entities

**`Job`** (table: `jobs`):
```
id           UUID / String(36) PK  — returned as job_id
job_type     String(50)            — "requirement_extraction" | "frontend_planning"
status       String(20)            — "pending" | "processing" | "completed" | "failed"
result       JSON nullable         — full result payload when completed
error_message Text nullable        — error description when failed
created_at   DateTime UTC          — auto-set
updated_at   DateTime UTC          — updated on every lifecycle change
```

**`RequirementExtraction`** (table: `requirement_extractions`):
```
id                      UUID PK
user_story_id           String(512)     — filename or caller-supplied ID
mode                    String(20)      — "frontend" | "backend" | "both"
extracted_requirements  JSON NOT NULL   — full structured requirements
dependency_graph        JSON nullable   — nodes/edges/entry_points
usage                   JSON NOT NULL   — {input_tokens, output_tokens, total_cost_usd, ...}
created_at              DateTime UTC
```

**`FrontendPlan`** (table: `frontend_plans`):
```
id             UUID PK
extraction_id  String — FK reference to RequirementExtraction.id
plan           JSON NOT NULL   — list[ModulePlan]
usage          JSON NOT NULL   — {input_tokens, output_tokens, total_cost_usd, ...}
created_at     DateTime UTC
```

### Repositories

All repositories follow the **Repository Pattern** — no raw queries in endpoints.

**`BaseRepository[T]`** (`base_repository.py`):
- `create(instance)` → flush + refresh
- `get_by_id(record_id)` → T | None
- `list_all(limit, offset)` → list[T]
- `delete(instance)` → flush

**`JobRepository`** (`job_repository.py`):
- `create_job(job_type)` → Job (status="pending")
- `mark_processing(job_id)` → Job
- `mark_completed(job_id, result)` → Job
- `mark_failed(job_id, error_message)` → Job
- `get_by_job_id(job_id)` → Job | None

**`RequirementRepository`** (`requirement_repository.py`):
- `save_extraction(user_story_id, mode, extracted_requirements, dependency_graph, usage)` → RequirementExtraction
- `get_by_id(record_id)` → RequirementExtraction | None

**`FrontendPlanRepository`** (`frontend_plan_repository.py`):
- `save_plan(extraction_id, plan, usage)` → FrontendPlan
- `get_by_extraction_id(extraction_id)` → FrontendPlan | None

---

## 13. LLM Client Layer

### `openai_client.py` — The Only Way to Call the LLM

**Never call `openai` SDK directly.** Always use `call_llm_with_schema()`.

#### Global Concurrency Semaphore

```python
_llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)  # default: 15
```

Lazily initialized. Caps simultaneous OpenAI API calls globally across all background jobs.

#### `call_llm(system_prompt, user_prompt)` → `(str, usage_dict)`

- Builds `ChatOpenAI` with:
  - `model`: `settings.LLM_MODEL`
  - `temperature`: `0.1`
  - `timeout`: `settings.LLM_TIMEOUT`
  - `response_format`: `{"type": "json_object"}` (for supported model prefixes)
- Acquires semaphore before each call
- Exponential-backoff retry: up to `API_RETRY_ATTEMPTS` (3) total attempts
- Base delay: `API_RETRY_BASE_DELAY` = 1.0s (doubles: 1→2→4)
- Returns `(content_string, usage_dict)`

#### `call_llm_with_schema(system_prompt, user_prompt, schema, model, max_retries)` → `dict`

Adds **3-layer JSON validation** on top of `call_llm()`:
1. `response_format={"type": "json_object"}` — forces the model to output JSON
2. Schema embedded in the prompt itself — LLM is told exactly what to produce
3. `jsonschema.Draft202012Validator(schema).validate(parsed_json)` — validates after parsing

On schema validation failure: retries up to `SCHEMA_VALIDATION_RETRIES` (2) additional times with the validation error appended to the user prompt.

#### Token Counting

```python
count_tokens(text: str) -> int
# Uses tiktoken encoding_for_model(settings.LLM_MODEL), fallback: cl100k_base
```

Every node counts tokens before building the prompt and truncates document text if over `TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS` (~8000 tokens available for doc text).

#### Cost Tracking

```python
_calculate_cost(model, input_tokens, output_tokens) -> dict
# Returns: {input_tokens, output_tokens, total_tokens, input_cost_usd, output_cost_usd, total_cost_usd, model}

merge_usage(usages: list[dict]) -> dict
# Sums all usage dicts and returns a combined total
```

Pricing table in `src/msbc/config.py` (`MODEL_PRICING`) covers `gpt-4.1-mini`, `gpt-4.1`, `gpt-4.1-nano`, `gpt-4o-mini`, `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`.

---

## 14. Utility Layers

### `app/utils/retry_utils.py` — `async_retry()`

Universal exponential back-off wrapper for any async callable.

```python
result = await async_retry(
    func,
    *args,
    exception_types=(openai.RateLimitError, ...),
    retryable_status_codes={429, 500, 502, 503, 504},
    max_attempts=3,
    base_delay=1.0,
    **kwargs,
)
```

- Inspects `exc.response.status_code` to decide if an HTTP error is retryable
- Non-retryable HTTP codes raise immediately (no retry)
- Logs each retry with attempt number, error type, and delay

### `src/msbc/utils/validators.py`

```python
validate_file_size(file_bytes) → None  # raises HTTPException 413 if > MAX_FILE_SIZE_BYTES
validate_mode(mode) → None             # raises HTTPException 400 if mode not in VALID_MODES
validate_uploaded_file(file) → None    # checks extension and content-type
```

### `src/msbc/utils/extractors/`

**`docx_extractor.py`**:
- `extract_text(file_bytes) → str` — full text with Markdown structural markers
- `extract_heading_hierarchy(file_bytes) → list[dict]`
  - Layer 1: Word heading styles (Title, Heading 1–6)
  - Layer 2: Heuristic fallback (numbered patterns `1.`, `1.1`, ALL-CAPS short lines)

**`pdf_extractor.py`**:
- `extract_text(file_bytes) → str`
- `extract_heading_hierarchy(file_bytes) → list[dict]`
  - Font size analysis: lines significantly larger than median → heading
  - Bold detection
  - Numbered prefix patterns

### `app/core/logger.py`

```python
get_logger(name: str) → logging.Logger
# Returns a configured logger. Level from settings.LOG_LEVEL.
```

---

## 15. Pydantic Schema Contracts

### `src/msbc/models/schemas/requirement.py`

Top-level response type: `ParseResponse`

```
ParseResponse
├── extraction : ExtractionResult  (discriminated union on "mode")
│   ├── FrontendExtractionResult  mode="frontend"
│   │   └── modules: list[FrontendModuleItem]
│   │       ├── name, order, description
│   │       ├── screens: list[FrontendScreen]
│   │       │   ├── components: list[FrontendComponent]
│   │       │   ├── field_groups: list[FrontendFieldGroup]
│   │       │   │   └── fields: list[FrontendField]
│   │       │   ├── actions: list[FrontendScreenAction]
│   │       │   └── behaviors: list[FrontendBehavior]
│   │       ├── enums: list[EnumItem]
│   │       ├── business_rules: list[str]
│   │       └── workflows: list[FrontendWorkflow]
│   ├── BackendExtractionResult   mode="backend"
│   │   └── modules: list[BackendModuleItem]
│   │       ├── api_endpoints: list[ApiEndpoint]
│   │       │   ├── request_params: BackendRequestParams
│   │       │   ├── response_body: BackendResponseBody
│   │       │   └── error_responses: list[BackendErrorResponse]
│   │       ├── models: list[DbModel]
│   │       │   ├── fields: list[DbField]
│   │       │   └── relationships: list[DbRelationship]
│   │       ├── business_logic: list[BusinessLogicItem]
│   │       └── workflows: list[BackendWorkflow]
│   └── BothExtractionResult      mode="both"
│       └── modules: list[BothModuleItem]
│           ├── frontend: BothFrontendSection
│           └── backend: BothBackendSection
├── graph: DependencyGraph
│   ├── nodes: list[GraphNode]  (name, description, build_order)
│   ├── edges: list[GraphEdge]  (from_module, to_module, dependency_type)
│   ├── entry_points: list[str]
│   └── metadata: GraphMetadata
└── usage: LLMUsage
    ├── input_tokens, output_tokens, total_tokens
    ├── input_cost_usd, output_cost_usd, total_cost_usd
    └── model
```

All sub-models use `ConfigDict(extra="allow")` — unknown LLM fields are preserved, never rejected.

### `src/msbc/models/schemas/frontend_plan.py`

```
PlannerOutput
└── modules: list[ModulePlan]
    ├── module_name, description, priority
    ├── similarity_query
    ├── business_rules: list[str]
    ├── screens: list[ScreenPlan]
    │   ├── screen_name, type, route, opens_as, priority
    │   ├── similarity_query
    │   ├── components: list[ComponentPlan]
    │   │   ├── component_name, type, toolkit_mapping
    │   │   ├── similarity_query
    │   │   ├── actions: list[ActionPlan]
    │   │   ├── columns: list[ColumnDef]     (grids)
    │   │   ├── fields: list[FieldDef]       (forms)
    │   │   ├── filters: list[FilterDef]     (filter panels)
    │   │   └── data_hook: str
    │   ├── user_interactions: list[UserInteraction]
    │   └── data_flow: DataFlow
    │       ├── state: list[StateItem]
    │       └── api_calls: list[ApiCall]
    ├── shared_components: list[SharedComponent]
    └── file_structure: list[FilePlan]
```

Coercion validators normalise LLM type mistakes:
- `dict` → JSON string for `color_logic`, `default_value` fields
- `int/float/bool` → `str` for string fields

### `src/msbc/models/schemas/backend_pipeline.py`

Contracts for Stage 3 (to build):

```python
CLIInvokerInput:
    project_name: str
    framework: Framework.DJANGO         # always
    app_names: list[str]               # snake_case, sanitised
    module_names: list[str]            # originals pre-sanitisation
    use_api: bool = True               # LOCKED — always True
    use_auth: bool = False             # LOCKED — never True
    command: "startproject"|"startapp"|"noop"
    existing_project_path: str | None

CLIInvokerOutput:
    project_path: str
    framework: Framework
    generated_apps: list[str]
    skipped_apps: list[str]
    success: bool
    errors: list[str]

ValidationResult:
    success: bool
    project_path: str
    missing_files: list[str]   # "app_name/models.py" relative format
    errors: list[str]

GeneratedFile:
    app_name: str
    file_type: "models"|"serializers"|"views"|"urls"
    file_path: str             # absolute path
    generation_method: "llm"|"jinja2"
    syntax_valid: bool
    errors: list[str]

PipelineOutput:
    project_path: str
    framework: Framework
    generated_apps: list[str]
    generated_files: list[GeneratedFile]
    success: bool
    errors: list[str]
```

### `src/msbc/models/schemas/job.py`

```python
JobSubmitResponse:
    job_id: str
    status: str = "pending"
    message: str

JobStatusResponse:
    job_id: str
    job_type: str
    status: str            # "pending" | "processing" | "completed" | "failed"
    result: Any | None
    error_message: str | None
    created_at: str | None
    updated_at: str | None
```

---

## 16. JSON-Schema Validation Layer

Every LLM call passes through a `jsonschema` Draft 2020-12 validator in `call_llm_with_schema()`. The schema is also injected into the prompt so the model knows exactly what to produce.

Schema files live in `src/msbc/agents/schemas/`:

| Schema Dict | File | Used By |
|------------|------|---------|
| `SEGMENTATION_SCHEMA` | `segmentation.py` | segmentation_node candidate classification |
| `CLASSIFICATION_SCHEMA` | `segmentation.py` | segmentation_node module identification |
| `FRONTEND_SCHEMA` | `frontend.py` | extract_module_node (frontend mode) |
| `BACKEND_SCHEMA` | `backend.py` | extract_module_node (backend mode) |
| `COMBINED_SCHEMA` | `combined.py` | extract_module_node (both mode) |
| `SUMMARY_SCHEMA` | `summary.py` | extract_module_node summary call |
| `UNIFIED_SCHEMA` | `unified.py` | finalize_node global rules/enums call |
| `GRAPH_OUTPUT_SCHEMA` | `graph_output.py` | finalize_node graph builder call |
| `PLANNER_OUTPUT_SCHEMA` | `frontend_planner/schema.py` | plan_module_node |

---

## 17. CLI Scripts

All scripts in `scripts/` prepend the project root to `sys.path` before importing from `src.*` or `app.*`.

### `scripts/embed_toolkit.py`
```bash
python scripts/embed_toolkit.py [--dry-run] [--full-sync]
```
- Requires `RTK_MONOREPO_PATH` and `OPENAI_API_KEY` to be set
- `--dry-run`: preview without writing to Qdrant
- `--full-sync`: re-embed every file, ignore stored hashes
- Exit codes: 0=success, 1=config error, 2=runtime error

### `scripts/embed_examples.py`
```bash
python scripts/embed_examples.py [--dry-run] [--example-id <id>] [--examples-dir <path>]
```
- `--example-id`: process only one specific example folder (e.g. `Dashboard03`)

### `scripts/build_graph.py`
```bash
python scripts/build_graph.py [--rebuild] [--db-path <path>] [--examples-dir <path>]
```
- `--rebuild`: drops all tables, rebuilds from scratch (use when PACKAGES dict changes)
- Without `--rebuild`: idempotent MERGE / IF NOT EXISTS

### `scripts/build_rtk_code_graph.py`
```bash
python scripts/build_rtk_code_graph.py [--rebuild] [--db-path PATH] [--monorepo-path PATH]
```
- Builds code-level SourceFile/ExportedSymbol graph from monorepo source

---

## 18. Stage 3 — Backend Code Generator (To Build)

**Owner:** Deep (runs Claude Code sessions on Shrey's behalf)  
**Working directory:** `D:\shardi\InHouseAgents`

### Build Order (strict)

1. `src/msbc/agents/backend/cli_invoker.py`
2. `src/msbc/agents/backend/scaffold_validator.py`
3. `src/msbc/agents/backend/code_generators/models_generator.py`
4. `src/msbc/agents/backend/code_generators/serializers_generator.py`
5. `src/msbc/agents/backend/code_generators/views_generator.py`
6. `src/msbc/agents/backend/code_generators/urls_generator.py`
7. `src/msbc/agents/backend/syntax_validator.py`
8. `src/msbc/orchestration/backend/graph.py` (flat LangGraph for Stage 3)
9. `src/msbc/api/v1/endpoints/backend_generator.py`

### `cli_invoker.py` Rules

```python
import subprocess, os

cmd = [
    "python", "-m", "djcli", "startproject",
    project_name, *app_names,
    "--api",           # ALWAYS — LOCKED
    "--path", output_dir
    # NEVER --auth
]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
# On timeout: success=False, error="djcli timed out after 60s"
```

- `python -m djcli` (module invocation — NOT a hardcoded .exe path)
- Path from `os.environ["DJCLI_PATH"]` if needed for Python executable discovery
- Package: `django_cli_tool` installed via pip from Nexus (`nexus.msbc-mainframe.lcl`)

### Generated Project Structure (validate these exist)

```
{project_name}/
├── {app_name}/
│   ├── __init__.py
│   ├── models.py        ← LLM will overwrite
│   ├── serializers.py   ← LLM will overwrite
│   ├── views.py         ← Jinja2 OR LLM will overwrite
│   ├── urls.py          ← Jinja2 ALWAYS overwrites
│   ├── admin.py
│   └── apps.py
├── {project_name}/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── manage.py
```

### Generation Method per File Type

| File | Method | Reason |
|------|--------|--------|
| `models.py` | LLM | Requires business logic understanding |
| `serializers.py` | LLM | Requires field/relationship context |
| Standard CRUD views | Jinja2 | Deterministic — no LLM needed |
| Custom business logic views | LLM | Requires non-trivial logic |
| `urls.py` | Jinja2 ALWAYS | Fully deterministic |

### Syntax Validator

```python
import ast
def validate_python(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)
# Max 2 retries — regenerate via LLM with error message appended to prompt
```

### Prompt Files to Create

- `src/msbc/llm/prompts/templates/backend_agent/models.yaml`
- `src/msbc/llm/prompts/templates/backend_agent/serializers.yaml`
- `src/msbc/llm/prompts/templates/backend_agent/views_custom.yaml`

### API Endpoint Pattern (follow exactly)

```python
@router.post('/generate', status_code=202)
async def generate(body, background_tasks, db):
    job = job_repo.create_job(job_type='backend_generation')
    db.commit()
    background_tasks.add_task(_run_backend_generation_job, str(job.id), ...)
    return JobSubmitResponse(job_id=str(job.id), status='pending')
```

Background task MUST create its own DB session:
```python
from sqlalchemy.orm import Session
from src.msbc.database.base import engine

with Session(engine) as db:  # never reuse the HTTP request session
    ...
```

---

## 19. Locked Architecture Decisions — Never Violate

| # | Rule | Detail |
|---|------|--------|
| 1 | **Flat LangGraph only** | No nested subgraphs. All nodes in a single flat graph. |
| 2 | **Parallel reducer** | `Annotated[list, operator.add]` for parallel node fan-in. |
| 3 | **Call C input = SUMMARIES ONLY** | `unify_requirements` LLM call gets module summaries only. Hard cap: 8192 tokens. |
| 4 | **3-layer JSON validation** | `json_object` + schema in prompt + `Draft202012Validator`. Max 2 retries. |
| 5 | **All prompts in YAML** | Never inline prompt strings in Python. Every prompt in `llm/prompts/templates/`. |
| 6 | **tiktoken for token counting** | Truncate before EVERY LLM call. Import limits from `src/msbc/config.py`. |
| 7 | **Django DRF only** | Backend generation target is always Django REST Framework. |
| 8 | **--auth: NEVER** | Never pass `--auth` to djcli. `use_auth = False` locked. |
| 9 | **--api: ALWAYS** | Always pass `--api` to djcli. `use_api = True` locked. |
| 10 | **No migration files** | Never generate `0001_initial.py` or anything in `migrations/`. |
| 11 | **LLM generates: models, serializers, custom views** | |
| 12 | **Jinja2 generates: CRUD viewsets, urls.py** | |
| 13 | **ast.parse() every generated file** | Max 2 retries on syntax failure. |
| 14 | **CLI path from env var** | `os.environ["DJCLI_PATH"]` — never hardcode. |
| 15 | **djcli is Python package** | `python -m djcli`. NOT `.exe`. NOT hardcoded path. |
| 16 | **No single contracts.py** | Schema files stay split: `requirement.py` / `frontend_plan.py` / `backend_pipeline.py`. |
| 17 | **YAML prompt loader uses `_fmt()`** | Never call `.format()` on prompt strings. Use `_fmt()` which does `str.replace()`. |
| 18 | **OpenAI embedding model** | `text-embedding-3-large` @ 1536 dim. Never `sentence-transformers` for production. |
| 19 | **Qdrant collection names** | `toolkit_openai_large_1536` and `examples_openai_large_1536`. Exact strings. |

---

## 20. Token Budget & Concurrency Constants

### Token Budget per LLM Call

```
TOTAL_INPUT_TOKEN_LIMIT = 12000   (total: system + user + document text)
PROMPT_MAX_TOKENS       = 4000    (reserved for system + user prompt templates)
Available for doc text  ≈ 8000    (12000 − 4000)
SCHEMA_VALIDATION_RETRIES = 2     (extra attempts when JSON fails validation)
```

### Concurrency Architecture

Three independent caps at different granularities:

| Cap | Value | Scope | Config |
|-----|-------|-------|--------|
| `LLM_MAX_CONCURRENCY` | 15 | Global asyncio semaphore on ALL OpenAI calls | `LLM_MAX_CONCURRENCY` env var |
| `MODULE_BATCH_SIZE` | 3 | Max parallel `extract_module_node` coroutines (LangGraph Send fan-out) | `MODULE_BATCH_SIZE` env var |
| `MODULE_EXTRACTION_TIMEOUT` | 900s | Async timeout per `extract_module_node` coroutine | `MODULE_EXTRACTION_TIMEOUT` env var |

**Why 15 for `LLM_MAX_CONCURRENCY`:** A typical job has 5 modules × 3 LLM calls each = 15 calls. Setting to 15 allows a full single job to run fully in parallel without queuing. Multi-job overlap protection relies on OpenAI's own rate-limiter (returns 429, which is already retried).

---

## 21. Running the Project

### Prerequisites

- Python 3.12
- PostgreSQL (or SQLite for dev)
- Qdrant (for embedding pipeline, `docker run -p 6333:6333 qdrant/qdrant`)
- `uv` package manager (`pip install uv`)
- `.env` file with at minimum `OPENAI_API_KEY`

### Install & Run

```bash
# Install all dependencies
uv sync

# Apply DB migrations
uv run alembic upgrade head

# Start the FastAPI server (dev mode with hot-reload)
uv run uvicorn main:app --reload

# Or use the main.py uvicorn invocation directly:
uv run python main.py
```

### One-time Embedding Setup (requires RTK_MONOREPO_PATH)

```bash
# Build the KUZU semantic knowledge graph from toolkit_knowledge.py
uv run python scripts/build_graph.py

# Build the KUZU code-level graph from monorepo source files
uv run python scripts/build_rtk_code_graph.py

# Embed RTK monorepo source files into Qdrant (full first-time run)
uv run python scripts/embed_toolkit.py --full-sync

# Embed curated examples into Qdrant
uv run python scripts/embed_examples.py --full-sync
```

### Incremental Embedding Updates

```bash
# Preview what changed (no writes)
uv run python scripts/embed_toolkit.py --dry-run

# Apply updates (only changed files re-embedded)
uv run python scripts/embed_toolkit.py

# Rebuild graph from scratch (after PACKAGES dict changes)
uv run python scripts/build_graph.py --rebuild
```

### SQLite Dev Mode

Set `DATABASE_URL=sqlite:///./dev.db` in `.env`. Tables are auto-created via `_init_db()` on startup. Alembic is not needed for SQLite dev.

---

## 22. API Reference

### Health Check
```
GET /health
→ 200 {"status": "ok", "project": "DevAgents", "version": "0.1.0"}
```

### Stage 1 — Requirement Extractor

```
POST /api/v1/requirement-extractor/parse
Content-Type: multipart/form-data
Body:
  file: <.docx or .pdf upload>
  mode: "frontend" | "backend" | "both"

→ 202 {
    "job_id": "<UUID>",
    "status": "pending",
    "message": "Job submitted. Poll the status endpoint with job_id."
  }
```

```
GET /api/v1/requirement-extractor/jobs/{job_id}

→ 200 {
    "job_id": "<UUID>",
    "job_type": "requirement_extraction",
    "status": "pending" | "processing" | "completed" | "failed",
    "result": {                    # present only when completed
      "extraction": { "modules": [...], "total_modules": N, "mode": "..." },
      "graph": { "nodes": [...], "edges": [...], "entry_points": [...] },
      "usage": { "total_tokens": N, "total_cost_usd": 0.0, "model": "..." },
      "extraction_id": "<UUID>"
    },
    "error_message": "...",        # present only when failed
    "created_at": "2026-...",
    "updated_at": "2026-..."
  }
```

### Stage 2 — Frontend Planner

```
POST /api/v1/frontend-planner/plan
Content-Type: application/json
Body:
  { "extraction_id": "<UUID>", "parallel": true }

→ 202 {"job_id": "<UUID>", "status": "pending", "message": "..."}
```

```
GET /api/v1/frontend-planner/jobs/{job_id}

→ 200 {
    "job_id": "<UUID>",
    "job_type": "frontend_planning",
    "status": "pending" | "processing" | "completed" | "failed",
    "result": {
      "plan_id": "<UUID>",
      "extraction_id": "<UUID>",
      "modules": [
        {
          "module_name": "...",
          "priority": 1,
          "screens": [
            {
              "screen_name": "...",
              "type": "dashboard | form | detail | popup",
              "route": "/...",
              "components": [...],
              "file_structure": [...]
            }
          ]
        }
      ],
      "usage": { "total_tokens": N, "total_cost_usd": 0.0 }
    }
  }
```

### Stage 3 — Backend Generator (To Build)

```
POST /api/v1/backend-generator/generate    (planned endpoint)
Content-Type: application/json
Body: { "extraction_id": "<UUID>" }
→ 202 {"job_id": "<UUID>", "status": "pending"}

GET /api/v1/backend-generator/jobs/{job_id}
→ 200 { "status": "...", "result": { "project_path": "...", "generated_files": [...] } }
```

---

## 23. Data Flow — End to End

### Stage 1 Full Flow

```
Upload .docx → bytes
    ↓
docx_extractor.extract_text(bytes) → document_text (str)
docx_extractor.extract_heading_hierarchy(bytes) → [{level, text}, ...]
    ↓
Job.create(job_type="requirement_extraction") → job_id
    ↓ (background)
run_extraction(document_text, heading_hierarchy, mode)
    ↓
[LangGraph]
    segmentation_node:
        _pre_clean_headings() → filter levels 1-4, dedupe
        _select_module_candidates() → pick structural container headings
        call_llm_with_schema(segmentation.yaml, CLASSIFICATION_SCHEMA)
        → modules: [{name, heading, level, description}, ...]
    ↓ fan-out via Send (MODULE_BATCH_SIZE=3 at a time)
    extract_module_node (parallel, one per module):
        _slice_module_text(doc, module_heading, next_heading)
            → _find_heading() with 3-pass search (exact / CI / whitespace-collapsed)
        count_tokens(module_text) → truncate if over 8000
        call_llm_with_schema(frontend_extraction.yaml, FRONTEND_SCHEMA)
        normalize_component_structure() → fix uppercase → lowercase types
        _validate_opens_screen_refs() → warn on broken refs
        call_llm_with_schema(summary_extraction.yaml, SUMMARY_SCHEMA)
        → ModuleResult {module_name, extraction, summary, usage}
    ↓ fan-in reducer (operator.add)
    finalize_node:
        call_llm_with_schema(unification.yaml, UNIFIED_SCHEMA) [SUMMARIES ONLY]
        call_llm_with_schema(graph_builder.yaml, GRAPH_OUTPUT_SCHEMA) [SUMMARIES ONLY]
        assemble extraction dict
        → {extraction, graph, all_usage}
    ↓
RequirementExtraction.save(user_story_id, mode, extracted_requirements, dependency_graph, usage)
    ↓
Job.mark_completed(result={extraction, graph, usage, extraction_id})
```

### Stage 2 Full Flow

```
POST /frontend-planner/plan {extraction_id}
    ↓
RequirementRepository.get_by_id(extraction_id) → RequirementExtraction
validate mode in {"frontend", "both"} (reject "backend")
    ↓
Job.create(job_type="frontend_planning") → job_id
    ↓ (background)
run_frontend_planning(extraction_id, extracted_requirements, dependency_graph)
    ↓
[LangGraph]
    prepare_node:
        parse extraction.modules → flat list
        build dep_priority_map from dependency_graph.nodes[].build_order
        extract global_enums, global_business_rules
    ↓ fan-out via Send
    plan_module_node (parallel, one per module):
        toon_single_module(module_dict) → TOON string (~40% token reduction)
        build_toolkit_context() → toolkit component registry string
        call_llm_with_schema(plan_module.yaml, PLANNER_OUTPUT_SCHEMA)
        coerce_str_or_null() on nullable string fields
        → ModulePlan dict
    ↓ fan-in reducer
    finalize_plan_node:
        sort plan_results by dep_priority
        merge_usage()
        → PlannerOutput(modules=[...], usage=...)
    ↓
FrontendPlanRepository.save_plan(extraction_id, plan, usage)
    ↓
Job.mark_completed(result={plan_id, extraction_id, modules, usage})
```

---

## 24. Bug Fixes Applied (Latest Uncommitted Changes)

These changes have been implemented but are not yet committed to git:

### Fix 1 — Heading Normalization (`node_definitions.py`)

**Problem:** PDF/DOCX extractors sometimes produce heading text with embedded whitespace artifacts or stray page numbers, e.g.:
```
"Step 1        6 How Purchase Order is Created"
```
The original `_slice_module_text` used only exact and case-insensitive `str.find()`. This caused 4 of 5 modules in certain documents to fall back to the full 75,453-char document text (~18k tokens per LLM call).

**Fix:** Added a third pass in `_find_heading()` using whitespace-collapsed comparison:
1. Normalise both document and heading with `re.sub(r'\s+', ' ', text)` → shadow strings
2. `str.find()` on shadow strings
3. Walk original characters to recover the match position in the original document

**Impact:** Eliminates "Heading not found; using full text" warnings on affected documents. Module text is now correctly scoped to the relevant section.

### Fix 2 — Token Truncation Enforcement (`node_definitions.py`)

**Problem:** `TOTAL_INPUT_TOKEN_LIMIT` existed in `src/msbc/config.py` but was never actually applied. Module text was sent raw to the LLM regardless of size.

**Fix:** After `_slice_module_text()` runs, count tokens via `count_tokens(module_text)`. If count exceeds `TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS` (~8000), truncate the text by approximating a character cutoff (tokens ≈ chars / 4) and log a warning.

### Fix 3 — Global LLM Concurrency Cap (`openai_client.py`)

**Problem:** With 5 modules × 3 LLM calls = 15 concurrent API calls per job, two overlapping jobs = 30+ simultaneous calls → rate limit cascade → timeouts on the second job.

**Fix:** Added a module-level `asyncio.Semaphore(LLM_MAX_CONCURRENCY)` (default: 15) that is acquired inside `call_llm()` before each API call. Added `LLM_MAX_CONCURRENCY` constant to `src/msbc/config.py`, configurable via env var.

### Fix 4 — `MODULE_EXTRACTION_TIMEOUT` Raised to 900s (`src/msbc/config.py`)

**Problem:** The previous 120s per-call timeout × 3 attempts + sleep ≈ 363s total was less than the time for a large document with multiple modules. Second-job modules were timing out before their LLM calls even got a chance to run.

**Fix:** `MODULE_EXTRACTION_TIMEOUT` raised from 120 to 900 seconds. Configurable via `MODULE_EXTRACTION_TIMEOUT` env var.

### Fix 5 — `MODULE_BATCH_SIZE` Cap Added (`src/msbc/config.py`, `edge_logic.py`)

**Problem:** The LangGraph `Send` fan-out fires all N modules simultaneously. For large documents this could mean 8-10 modules all racing for LLM calls at once.

**Fix:** `MODULE_BATCH_SIZE = 3` — the `fan_out_to_modules` function processes modules in batches of `MODULE_BATCH_SIZE`, preventing the rate-limit cascade.

---

## 25. What Is Planned Next

### Immediate (Stage 3 — Backend Code Generator)

1. Build `src/msbc/agents/backend/cli_invoker.py` — subprocess wrapper for `python -m djcli`
2. Build `src/msbc/agents/backend/scaffold_validator.py` — checks djcli output files exist
3. Build code generators: `models_generator.py`, `serializers_generator.py`, `views_generator.py`, `urls_generator.py`
4. Build `src/msbc/agents/backend/syntax_validator.py` — `ast.parse()` with 2-retry loop
5. Build `src/msbc/orchestration/backend/graph.py` — flat LangGraph for Stage 3
6. Build `src/msbc/api/v1/endpoints/backend_generator.py` — POST + GET endpoint
7. Create YAML prompt files: `backend_agent/models.yaml`, `serializers.yaml`, `views_custom.yaml`
8. Mount the new router in `app/api/main_router.py`

### Frontend UI (Vite + React + TypeScript)

A separate Vite+React+TS frontend to drive the pipeline visually:
- Upload user story document
- Configure extraction mode
- Poll job status with live progress
- View/browse the structured extraction output
- Trigger the frontend planner
- Browse the per-module component plan
- Download the generated Django project

### Retrieval Integration (Planner → Qdrant/KUZU)

Connect the Frontend Planner's `similarity_query` fields to actual Qdrant search and KUZU traversal at generation time. Currently the planner outputs queries but does not execute them.

---

## Infrastructure Reference

| Component | Detail |
|-----------|--------|
| Runtime | Python 3.12, FastAPI + Uvicorn |
| Package manager | `uv` (use `uv add`, never `pip install` for new deps) |
| App DB | PostgreSQL via SQLAlchemy + Alembic |
| Vector DB | Qdrant (`qdrant-client`) — `http://localhost:6333` |
| Graph DB | KUZU embedded (`kuzu`) — `./data/toolkit_graph.kuzu` |
| LLM | OpenAI GPT-4.1-mini |
| Embeddings | OpenAI `text-embedding-3-large` @ 1536 dim |
| Internal PyPI | Nexus at `nexus.msbc-mainframe.lcl` |
| djcli package | `django_cli_tool-0.0.1-py3-none-any.whl` from Nexus |
| Deployment | Kubernetes on VM + Docker |