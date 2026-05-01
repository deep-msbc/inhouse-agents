# InHouseAgents — Full-Stack Dev Agent

## What This Is

An enterprise-grade AI-powered Full-Stack Development Agent that takes a user story document (.docx or .pdf) and produces a runnable Django DRF backend project and a complete React frontend plan. Stages 1 and 2 (Requirement Extractor and Frontend Planner) are production-ready. The open work is Stage 3 (Backend Code Generator), the Embedding Pipeline that provides RAG context to both Stage 2 and Stage 3, and a React UI that wires everything together.

## Core Value

Given a requirement document, the system generates a deployable Django DRF project with syntactically valid Python for every app — that end-to-end code generation is the irreducible deliverable.

## Team

| Person | Role | What they own |
|---|---|---|
| **Deep** | Tech Lead | Stage 3 (Backend Code Gen), Frontend UI Port — runs Claude Code from this repo |
| **Yug** | Frontend + AI | Stage 1 & 2 (done), Embedding Pipeline, React frontend — separate Claude instance |

## Pipeline Architecture

```
Stage 1 (✓ done)   Requirement Extractor     → ExtractionOutput JSON
Stage 2 (✓ done)   Frontend Planner          → FrontendPlan JSON
Stage 3 (open)     Backend Code Generator    → Django DRF project on disk (configurable path)
Embedding (open)   Qdrant + Kuzu             → RAG context for Stage 2 & Stage 3
Frontend UI (open) React SPA                 → Wires all stages + job polling + file tree
```

### Embedding Collections
- `toolkit_openai_large_1536` — ReactToolkits monorepo TSX/TS → Stage 2 only
- `examples_openai_large_1536` — curated correct_code_examples/ → Stage 2 (frontend) + Stage 3 (Django DRF patterns)
- Kuzu graph layer: component relationship graph for Stage 2 planning

## Requirements

### Validated

- ✓ Document ingestion (.docx + .pdf) with heading hierarchy extraction — existing
- ✓ Async job pattern (create Job → BackgroundTask → poll /jobs/{id}) — existing
- ✓ Stage 1: Segmentation + parallel module extraction + dependency graph — existing
- ✓ Stage 2: Parallel frontend planning with TOON compression + toolkit injection — existing
- ✓ 3-layer LLM validation (json_object + schema prompt + jsonschema Draft202012) — existing
- ✓ PostgreSQL/SQLite ORM (Job, RequirementExtraction, FrontendPlan entities) — existing

### Active

**Stage 3 — Backend Code Generator (Deep, highest priority)**
- [ ] `cli_invoker.py` — subprocess wrapper for djcli (--api always, --auth never)
- [ ] `scaffold_validator.py` — verify expected file tree exists before generation
- [ ] `models_generator.py` — LLM generates models.py per app (ast.parse() validated, max 2 retries)
- [ ] `serializers_generator.py` — LLM generates serializers.py per app
- [ ] `views_generator.py` — LLM for custom views, Jinja2 for standard CRUD viewsets
- [ ] `urls_generator.py` — Jinja2 always (no LLM)
- [ ] `syntax_validator.py` — ast.parse() gate on every generated file
- [ ] Stage 3 LangGraph flat graph with RAG context retrieval node
- [ ] Stage 3 YAML prompt templates under `llm/prompts/templates/backend_agent/`
- [ ] Stage 3 FastAPI endpoint `POST /backend-generator/generate` + job polling
- [ ] `BackendGeneration` ORM entity + Alembic migration
- [ ] Schema contracts split across 3 separate files (never merged)

**Embedding Pipeline (Yug, parallel)**
- [ ] tree-sitter chunker for TSX/TS and Python source
- [ ] OpenAI text-embedding-3-large @ 1536 dim embedder
- [ ] Qdrant store (upsert, similarity search) for both collections
- [ ] Kuzu graph schema + builder + store for component relationships
- [ ] Toolkit ingestor (scans ReactToolkits monorepo)
- [ ] Examples ingestor (scans correct_code_examples/)
- [ ] `src/msbc/embedding/` module — 15 files per spec

**Frontend UI Port (Deep, after Stage 3)**
- [ ] Vite + React + TypeScript project scaffold
- [ ] Port existing Claude-designed app.jsx/styles.css
- [ ] Real API calls to Stage 1, 2, 3 endpoints
- [ ] Job polling with live status updates
- [ ] Live file tree from Stage 3 pipeline output

### Out of Scope

- Authentication / --auth flag — locked out of Django generation by architecture decision
- Django migration files — never generated (djcli constraint, locked)
- Nested LangGraph subgraphs — flat graphs only (locked)
- Test suite — not a priority for this sprint
- Deployment / containerization — not in scope for this milestone

## Context

- `src/msbc/models/schemas/backend_pipeline.py` already encodes all Stage 3 locked invariants as Pydantic models (CLIInvokerInput with use_api=True, use_auth=False; GeneratedFile with generation_method; PipelineOutput)
- `Framework` and `ExtractionMode` enums are currently duplicated in backend_pipeline.py and requirement.py — needs canonical home decision before Stage 3 build starts
- `OPENAI_API_KEY` has no startup validation — silent failure if missing; should be addressed
- `CORS_ORIGINS=["*"]` + `allow_credentials=True` is a security misconfiguration for non-local deploys
- Stage 3 agent will retrieve Django DRF examples from Qdrant `examples_openai_large_1536` (same collection Yug's embedding pipeline populates)

## Constraints

- **Django DRF only**: Backend generation target is always Django REST Framework — no Flask, no FastAPI-as-output
- **djcli flags**: `--api` always passed, `--auth` NEVER passed (locked architecture decision)
- **No migrations**: djcli must never generate migration files
- **LLM vs Jinja2**: LLM for models.py, serializers.py, custom views only. Jinja2 for standard CRUD viewsets and urls.py always.
- **Syntax validation**: ast.parse() on every generated Python file, max 2 retries before marking failed
- **Prompts in YAML**: Every LLM prompt lives in `llm/prompts/templates/` — no inline strings in Python
- **Flat LangGraph**: No nested subgraphs anywhere, ever
- **Schema contracts**: 3 separate files — never merged into a single contracts.py
- **Token limits**: tiktoken truncation before every LLM call using `TOTAL_INPUT_TOKEN_LIMIT` from `src/msbc/config.py`
- **Output path**: Django project output directory is a configurable runtime parameter

## Key Decisions

| Decision | Rationale | Outcome |
|---|---|---|
| LLM for models/serializers/custom views only | Standard CRUD is deterministic — no reason to burn tokens on Jinja2-able boilerplate | — Pending |
| ast.parse() with max 2 retries | Same retry budget as schema validation (SCHEMA_VALIDATION_RETRIES=2), keeps pipeline predictable | — Pending |
| Configurable output path for Django project | Different callers may want different output locations; avoids hardcoding | — Pending |
| Qdrant examples collection shared between Stage 2 & 3 | Single source of truth for curated examples; Stage 3 backend patterns added by Yug | — Pending |
| Schema contracts in 3 separate files | Avoids merge conflicts when Deep and Yug work in parallel on Stage 3 vs Embedding | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-29 after initialization*
