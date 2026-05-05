# CLAUDE.md — InHouseAgents

> Read this file completely before writing any code.
> Every rule here is verified against the actual codebase.
> Last verified: 2026-05-02 (Claude Code codebase scan)

---

## 1. Who You Are Working With

**Deep (Tech Lead / Sr. AI Engineer)** — Runs this Claude Code session.
Owns Stage 3 backend code generation. Makes all final decisions.
Communicate: direct, opinionated, no hedging. Challenge wrong assumptions.

**Yug (AI + Frontend Intern)** — Owns Stage 1, Stage 2, Embedding Pipeline.
Works from `C:\Users\yug.chauhan\Desktop\InHouseAgents`.

**Shrey (AI + Backend Intern)** — Owns Frontend UI port.
Uses shared Claude browser only (no Claude Code).

---

## 2. Project Summary

Enterprise AI-powered Full-Stack Development Agent.

**Input:** User story document (.docx or .pdf, 80-120 pages)
**Output:** Structured requirements JSON + dependency graph + Django DRF project on disk + React frontend plan

**Deployed:** Kubernetes on VM, Docker, FastAPI backend
**Package manager:** `uv` — ALWAYS `uv add`, NEVER `pip install`
**Run server:** `uv run uvicorn main:app --reload`
**Run migrations:** `uv run alembic upgrade head`

---

## 3. Actual Repository Structure (Verified 2026-05-02)

```
InHouseAgents/
├── main.py                          ← FastAPI entry point
├── CLAUDE.md                        ← THIS FILE
├── README.md                        ← Source of truth documentation
├── EMBEDDING_AND_GRAPH_GUIDE.md     ← Embedding + Kuzu run guide
├── requirements.txt                 ← pip requirements (uv managed)
├── pyproject.toml
├── alembic.ini
│
├── app/
│   ├── core/
│   │   ├── config.py                ← Pydantic settings (OPENAI_API_KEY, DATABASE_URL, LLM_MODEL etc.)
│   │   └── logger.py
│   ├── api/
│   │   └── main_router.py           ← Mounts all routers — ADD Stage 3 router here
│   ├── dependencies.py
│   └── utils/
│       └── retry_utils.py           ← async_retry() — reuse this
│
└── src/msbc/
    ├── config.py                    ← Token limits, timeouts, concurrency constants
    │
    ├── models/
    │   ├── schemas/
    │   │   ├── requirement.py       ← Stage 1 Pydantic models (DO NOT TOUCH)
    │   │   ├── frontend_plan.py     ← Stage 2 Pydantic models (DO NOT TOUCH)
    │   │   └── backend_pipeline.py  ← Stage 3 contracts (WORK HERE)
    │   └── entities/                ← ONE FILE PER ENTITY
    │       ├── __init__.py          ← re-exports all entities
    │       ├── job.py
    │       ├── requirement_extraction.py
    │       ├── frontend_plan.py
    │       └── backend_generation.py  ← CREATE (Plan 01-03)
    │
    ├── database/
    │   ├── base.py
    │   ├── session.py               ← get_db()
    │   ├── migrations/versions/
    │   └── repositories/
    │       ├── base_repository.py   ← BaseRepository[T] (NOT base.py)
    │       ├── job_repository.py
    │       ├── requirement_repository.py
    │       ├── frontend_plan_repository.py
    │       └── backend_generation_repository.py  ← CREATE (Plan 01-03)
    │
    ├── llm/
    │   ├── clients/
    │   │   └── openai_client.py     ← call_llm_with_schema() — ALWAYS use this
    │   └── prompts/
    │       ├── loader.py            ← _fmt() — NEVER .format()
    │       └── templates/
    │           ├── requirement_extractor/  ← DO NOT TOUCH
    │           ├── frontend_planner/       ← DO NOT TOUCH
    │           └── backend_agent/          ← CREATE YAML prompts here
    │
    ├── agents/
    │   ├── schemas/requirement_extractor/  ← DO NOT TOUCH
    │   ├── schemas/frontend_planner/       ← DO NOT TOUCH
    │   ├── frontend_planner/               ← DO NOT TOUCH
    │   └── backend/                        ← CREATE (Stage 3)
    │       ├── __init__.py
    │       ├── cli_invoker.py              ← Plan 01-02
    │       ├── scaffold_validator.py       ← Plan 01-02
    │       ├── syntax_validator.py         ← Phase 2
    │       └── code_generators/
    │           ├── models_generator.py
    │           ├── serializers_generator.py
    │           ├── views_generator.py
    │           └── urls_generator.py
    │
    ├── orchestration/
    │   ├── graph.py                 ← Stage 1 — DO NOT TOUCH
    │   ├── state.py                 ← Stage 1 — DO NOT TOUCH
    │   ├── nodes/edge_logic.py      ← fan_out_to_modules() — DO NOT TOUCH
    │   ├── nodes/node_definitions.py ← Stage 1 — DO NOT TOUCH
    │   ├── planner/graph.py         ← Stage 2 — DO NOT TOUCH
    │   ├── planner/nodes.py         ← Stage 2 — DO NOT TOUCH
    │   └── backend/                 ← CREATE (Phase 3)
    │       ├── graph.py
    │       ├── state.py             ← BackendCodegenState TypedDict
    │       └── nodes.py
    │
    ├── embedding/                   ← COMPLETE (Yug) — DO NOT TOUCH
    │   ├── chunker.py, embedder.py, store.py, schema.py
    │   ├── graph_schema.py, graph_builder.py, graph_store.py
    │   ├── code_graph_builder.py
    │   └── ingestors/scanner.py, toolkit_ingestor.py, examples_ingestor.py
    │
    ├── api/v1/endpoints/
    │   ├── requirements.py          ← DO NOT TOUCH
    │   ├── frontend_planner.py      ← DO NOT TOUCH
    │   └── backend_generator.py     ← CREATE (Phase 3)
    │
    └── utils/
        ├── validators.py
        └── extractors/docx_extractor.py, pdf_extractor.py
```

---

## 4. Token Budget & Concurrency (Verified from src/msbc/config.py)

| Constant | Actual Value |
|---|---|
| `TOTAL_INPUT_TOKEN_LIMIT` | **12000** |
| `PROMPT_MAX_TOKENS` | 4000 |
| `SCHEMA_VALIDATION_RETRIES` | 2 |
| `API_RETRY_ATTEMPTS` | 3 |
| `API_RETRY_BASE_DELAY` | 1.0s |
| `MODULE_EXTRACTION_TIMEOUT` | **900s** |
| `MODULE_BATCH_SIZE` | **3** |
| `LLM_MAX_CONCURRENCY` | **15** |

---

## 5. LOCKED Architecture Rules — NEVER VIOLATE

| # | Rule |
|---|---|
| 1 | **LangGraph FLAT graphs only** — no nested subgraphs, ever |
| 2 | **Parallel reducer** — `Annotated[list, operator.add]` on any field written by parallel Send nodes |
| 3 | **Call C = SUMMARIES ONLY** — finalize_node gets summaries never full extraction |
| 4 | **3-layer JSON validation** — json_object + schema in prompt + Draft202012Validator. Max 2 retries. |
| 5 | **All prompts in YAML** — never inline strings in Python |
| 6 | **`_fmt()` not `.format()`** — ALWAYS use `_fmt()` from loader.py |
| 7 | **`call_llm_with_schema()` only** — never call OpenAI SDK directly |
| 8 | **tiktoken for token counting** — truncate before every LLM call |
| 9 | **Django DRF only** — backend generation target always |
| 10 | **`--auth`: NEVER** — `use_auth = False` locked |
| 11 | **`--api`: ALWAYS** — `use_api = True` locked |
| 12 | **No Django migration files** — never generate |
| 13 | **LLM generates:** models.py, serializers.py, custom views only |
| 14 | **Jinja2 generates:** standard CRUD viewsets, urls.py ALWAYS |
| 15 | **`ast.parse()` every file** — max 2 retries on syntax failure |
| 16 | **Async subprocess** — `asyncio.to_thread(subprocess.run, ...)` — NEVER blocking in async |
| 17 | **`python -m djcli`** — never hardcoded .exe path |
| 18 | **3 separate schema files** — never merge into contracts.py |
| 19 | **Background tasks = own DB session** — `_bg_session()` pattern from existing endpoints |
| 20 | **Entities = separate files** — one file per entity, never consolidate to base.py |
| 21 | **`BackendCodegenState` first** — define TypedDict with reducer before any Stage 3 node |
| 22 | **`prepare_backend_node` pure Python** — no LLM, strips to summaries before BackendPlanner |
| 23 | **DO NOT TOUCH Stage 1/2** — orchestration/graph.py, nodes/, planner/ all locked |

---

## 6. Stage 3 Phase 1 — Build This Now

### GSD State: Phase 1, 3 plans ready, 0 executed
Plans: `.planning/phases/01-stage-3-foundation/`

### Wave 1 — Parallel:

**Plan 01-01** — `src/msbc/models/schemas/backend_pipeline.py`
Add `output_path: str` field to `CLIInvokerInput`. Caller-supplied, not from env var.
Also: verify no cross-imports between 3 schema files.

**Plan 01-03** — New ORM entity + repository + migration
```
src/msbc/models/entities/backend_generation.py   ← NEW file
src/msbc/database/repositories/backend_generation_repository.py  ← NEW file
src/msbc/database/migrations/versions/xxx_add_backend_generations.py
```

Entity — exact 9 columns (use _uuid_col() pattern from existing entities):
```python
id              # UUID PK
extraction_id   # String FK → requirement_extractions.id, indexed, not nullable
project_name    # String(255), not nullable
output_path     # String(1024), not nullable
cli_stdout      # Text, nullable
cli_stderr      # Text, nullable
pipeline_output # JSON, nullable
success         # Boolean, not nullable
created_at      # DateTime(timezone=True), server_default=func.now()
```

Repository — MINIMAL only:
```python
class BackendGenerationRepository(BaseRepository[BackendGeneration]):
    pass  # inherits create() + get_by_id() — no extra methods
```

### Wave 2 — After Wave 1:

**Plan 01-02** — `src/msbc/agents/backend/cli_invoker.py` + `scaffold_validator.py`

```python
# cli_invoker.py
from typing import NamedTuple

class CLIInvokerResult(NamedTuple):   # defined HERE not in backend_pipeline.py
    output: CLIInvokerOutput
    stdout: str
    stderr: str

class CLIInvoker:
    async def invoke(self, input: CLIInvokerInput) -> CLIInvokerResult:
        os.makedirs(input.output_path, exist_ok=True)
        cmd = [
            "python", "-m", "djcli", "startproject",
            input.project_name,
            *input.app_names,
            "--api",
            "--path", input.output_path
            # NEVER --auth
        ]
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd,
                capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired:
            return CLIInvokerResult(
                output=CLIInvokerOutput(success=False, errors=["djcli timed out after 60s"],
                    project_path="", framework=input.framework,
                    generated_apps=[], skipped_apps=[]),
                stdout="", stderr=""
            )

# scaffold_validator.py
# Check per app: models.py, serializers.py, views.py, urls.py, __init__.py
```

---

## 7. Stage 3 Full Architecture (Phase 2+3 Preview)

### BackendCodegenState (`orchestration/backend/state.py`):
```python
class AppCodegenResult(TypedDict):
    app_name: str
    generated_files: list[dict]
    errors: list[str]
    success: bool

class BackendCodegenState(TypedDict):
    extraction_id: str
    extracted_requirements: dict
    dependency_graph: dict | None
    output_path: str
    modules: list[dict]
    shared_enums: dict
    global_business_rules: list[str]
    dep_priority_map: dict[str, int]
    backend_plan: dict
    cli_strategy: dict
    cli_output: dict
    scaffold_valid: bool
    app_results: Annotated[list[AppCodegenResult], operator.add]  # reducer
    generated_files: list[dict]
    pipeline_output: dict
    all_errors: list[str]
```

### Flat LangGraph Node Order:
```
prepare_backend_node        [Pure Python]
    → backend_planner_node  [LLM — summaries + RAG examples_openai_large_1536]
    → cli_strategy_node     [Pure Python]
    → cli_invoker_node      [asyncio.to_thread]
    → scaffold_validator_node [Pure Python]
    → conditional_edge      [skip shared_enums if global_enums empty]
    → shared_enums_node     [Pure Python]
    → codegen_app_node × N  [Parallel Send — graph dependency order]
        internally: models → serializers → views → urls (one function)
    → collect_apps_node     [Pure Python reducer]
    → project_settings_node [Pure Python — INSTALLED_APPS + project urls.py]
    → final_syntax_gate_node [Pure Python — ast.parse all]
    → assemble_output_node  [Pure Python]
```

### Views Generator Decision:
```python
CRUD_OPERATIONS = {"list", "create", "retrieve", "update", "destroy"}

def _needs_custom_view(endpoint: dict) -> bool:
    operation = endpoint.get("operation", "").lower()
    has_business_logic = bool(endpoint.get("business_logic"))
    has_workflow = bool(endpoint.get("workflow_steps"))
    return operation not in CRUD_OPERATIONS or has_business_logic or has_workflow
# True → LLM with views_custom.yaml
# False → Jinja2 ModelViewSet template
```

---

## 8. LLM Call Pattern

```python
from src.msbc.llm.clients.openai_client import call_llm_with_schema, count_tokens

# Token check first
tokens = count_tokens(text)
budget = TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS  # ~8000
if tokens > budget:
    text = text[:budget * 4]  # approx chars

result = await call_llm_with_schema(
    system_prompt=system_text,
    user_prompt=user_text,
    schema=SCHEMA_DICT,
    schema_name="schema_name",
    model="gpt-4.1-mini",
    max_retries=2
)
```

---

## 9. Database Patterns

```python
# Entity pattern — look at job.py for _uuid_col() and DateTime pattern
# Repository pattern — look at base_repository.py for BaseRepository[T]
# Background session — copy _bg_session() from requirements.py endpoint
# API pattern — 202 + job_id + BackgroundTasks (copy from requirements.py)
```

---

## 10. Embedding Pipeline (Yug — Verified Complete)

Both Qdrant collections + both Kuzu graphs are built.
⚠️ Stage 2 → Qdrant/Kuzu wiring NOT done — similarity_query fields generated but not executed.

Collections: `toolkit_openai_large_1536`, `examples_openai_large_1536`
Run order: `build_graph.py` → `build_rtk_code_graph.py --rebuild` → `embed_toolkit.py` → `embed_examples.py`

---

## 11. NEVER DO

- ❌ `contracts.py` anywhere
- ❌ `--auth` flag in djcli
- ❌ Django migration files
- ❌ Nested LangGraph subgraphs
- ❌ Inline prompt strings in Python
- ❌ Direct OpenAI SDK calls
- ❌ Blocking `subprocess.run()` in async
- ❌ Hardcoded djcli path
- ❌ `sentence-transformers`
- ❌ Touch Stage 1/2 files
- ❌ Consolidate entities to base.py
- ❌ `.format()` on prompt strings