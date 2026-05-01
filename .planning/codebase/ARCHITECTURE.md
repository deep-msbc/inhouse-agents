# ARCHITECTURE.md

## System Overview

InHouseAgents is an async API-driven pipeline that transforms requirement documents (.docx/.pdf) into structured JSON requirements and executable React/Django project plans using LLM agents orchestrated by LangGraph.

---

## High-Level Data Flow

```
HTTP POST (file or extraction_id)
  └─► FastAPI endpoint (src/msbc/api/v1/endpoints/)
        ├─► Synchronous: validate input, extract document text
        ├─► Synchronous: create Job row (status=pending)
        └─► Queue BackgroundTask (returns 202 immediately)
              └─► Background worker runs LangGraph graph
                    ├─► Job status → processing
                    ├─► LangGraph nodes call LLM via openai_client.py
                    │     └─► 3-layer validation: json_object + schema prompt + jsonschema Draft202012
                    ├─► Results merged and saved (RequirementExtraction / FrontendPlan)
                    └─► Job status → completed | failed

HTTP GET /jobs/{job_id}   ← client polls until terminal status
```

---

## Async Job Pattern

All endpoints follow the same pattern:
1. Validate request synchronously
2. Create a `Job` ORM row with `status=pending`
3. Hand off to `BackgroundTasks` (returns HTTP 202)
4. Background function creates its **own** `Session` via `_bg_session()` — it cannot reuse the HTTP request session which is already closed
5. Job transitions: `pending → processing → completed | failed`
6. Client polls `GET /jobs/{job_id}` for result

---

## LangGraph Graphs

### Stage 1 — Requirement Extractor (`src/msbc/orchestration/graph.py`)

```
segmentation_node
  └─► fan_out_to_modules  [uses Send API — one invocation per module]
        └─► [extract_module_node] (all parallel)
              └─► finalize_node  (pure Python merge + dependency graph LLM call)
```

- `segmentation_node`: single LLM call to identify document modules from heading hierarchy
- `extract_module_node`: per module, fires frontend + backend + summary LLM calls via `asyncio.gather` (mode=`both`)
- `finalize_node`: aggregates parallel results; final LLM call builds topological dependency graph
- State: `ExtractionState` TypedDict in `src/msbc/orchestration/state.py`
  - Parallel-written fields use `Annotated[list, operator.add]` reducer

### Stage 2 — Frontend Planner (`src/msbc/orchestration/planner/graph.py`)

```
prepare_node
  └─► fan_out_to_plan_modules  [uses Send API]
        └─► [plan_module_node] (all parallel)
              └─► finalize_plan_node  (sort by priority, aggregate tokens)
```

- `prepare_node`: pure Python — extracts global rules, computes build order from dependency graph
- `plan_module_node`: LLM call using TOON-compressed input + toolkit_knowledge injection
- State: defined in `src/msbc/orchestration/planner/state.py`

**Locked rule**: No nested subgraphs — all nodes are in a single flat graph.

---

## LLM Client (`src/msbc/llm/clients/openai_client.py`)

`call_llm_with_schema(prompt, schema, model)`:
1. Counts tokens with `tiktoken`; truncates if over `TOTAL_INPUT_TOKEN_LIMIT` (from `src/msbc/config.py`)
2. Calls OpenAI with `response_format={"type": "json_object"}`
3. Validates response against JSON Schema (Draft 2020-12)
4. On validation failure: appends error to prompt and retries (max `SCHEMA_VALIDATION_RETRIES`)
5. Normalizers run before strict validation to fix common LLM hallucinations (uppercase keys, boolean casting)

---

## Database Layer

- **Engine**: `src/msbc/database/base.py` — `create_engine` from `app.core.config.settings.DATABASE_URL`
- **Session (HTTP requests)**: `src/msbc/database/session.py` — `get_db()` FastAPI dependency, yields transactional Session
- **Session (background tasks)**: `_bg_session()` defined inside endpoint files — creates a fresh Session outside the request lifecycle
- **Repositories**: `src/msbc/database/repositories/` — typed CRUD wrappers per entity, inherit `BaseRepository[T]`
- **Migrations**: Alembic, scripts in `src/msbc/database/migrations/versions/`

---

## Two-Tree Module Layout

The codebase has two parallel trees that are both imported by `main.py`:

| Tree | Role |
|---|---|
| `app/` | FastAPI wiring, global config, logger, DB engine, shared utilities |
| `src/msbc/` | All domain logic: API endpoints, LangGraph orchestration, LLM clients, agents, models |

`app/core/config.py` (`Settings`) is the single source of truth for all environment-driven configuration. `src/msbc/config.py` holds domain-level constants (token limits, retry counts).

---

## TOON Serialization

Before the Frontend Planner LLM call, `src/msbc/agents/frontend_planner/toon_serializer.py` compresses the full JSON extraction into TOON (Token-Oriented Object Notation v3.0) — an indentation-based format that significantly reduces token count and cost.

---

## Stage 3 — Backend Code Generator (Planned)

Target: Django DRF project generation. Location: `src/msbc/agents/backend/`. Not yet implemented. See CONCERNS.md for details.
