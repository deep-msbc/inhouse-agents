# CLAUDE.md — InHouseAgents Project Instructions

> This file is read by Claude Code on every session.
> Follow every rule here without exception. When in doubt, re-read this file before writing any code.

---

## 1. Who You Are Working With

**Deep (Tech Lead)** — The person running Claude Code sessions. He makes all final architecture
decisions. He is also doing Shrey's backend work directly via Claude Code.

**Yug (Frontend + AI)** — Owns Stage 1 (Requirement Extractor), Stage 2 (Frontend Planner),
Embedding Pipeline, and the React frontend port. Has his own instance.

**Shrey (Backend AI)** — Owns Stage 3 (Backend Code Generation). Deep runs Claude Code on
Shrey's behalf from this repo at `D:\shardi\InHouseAgents`.

---

## 2. Project: What This System Does

An enterprise-grade AI-powered Full-Stack Development Agent.

**Input:** User story document (.docx or .pdf)
**Output:** Structured requirements + module dependency graph + runnable Django DRF project
           + complete React frontend (components, configs, services, types)

**Pipeline:**
```
Stage 1 (Yug)    → Requirement Extractor   → ExtractionOutput JSON
Stage 2 (Yug)    → Frontend Planner        → FrontendPlan JSON
Stage 3 (Deep)   → Backend Code Generator  → Django DRF project on disk
Embedding (Yug)  → Qdrant + Kuzu           → RAG for Stage 2 planner
```

---

## 3. Repo Layout (Actual, as of today)

```
InHouseAgents/                          ← repo root, D:\shardi\InHouseAgents
│
├── CLAUDE.md                           ← THIS FILE
├── main.py                             ← FastAPI entry point (DevAgents app)
├── pyproject.toml                      ← uv-managed deps
├── alembic.ini
├── .gitignore
├── README.md
│
├── app/                                ← Application shell
│   ├── api/
│   │   └── main_router.py              ← Mounts all routers
│   ├── core/
│   │   ├── config.py                   ← Pydantic settings (DATABASE_URL etc.)
│   │   └── logger.py                   ← get_logger()
│   ├── dependencies.py
│   └── utils/
│       └── retry_utils.py              ← async_retry() — reuse this everywhere
│
├── config/                             ← Runtime YAML configs
├── scripts/                            ← CLI scripts (embed_toolkit, build_graph etc.)
│
└── src/
    └── msbc/                           ← Core domain package
        ├── config.py                   ← TOTAL_INPUT_TOKEN_LIMIT=10000, SCHEMA_VALIDATION_RETRIES=2
        │
        ├── models/
        │   ├── schemas/
        │   │   ├── requirement.py      ← Yug — Stage 1 output Pydantic models
        │   │   ├── frontend_plan.py    ← Yug — Stage 2 output Pydantic models
        │   │   └── backend_pipeline.py ← Deep/Shrey — Stage 3 contracts (CLIInvokerInput etc.)
        │   └── entities/
        │       └── base.py             ← SQLAlchemy: Job, RequirementExtraction, FrontendPlan
        │
        ├── database/
        │   ├── base.py                 ← DeclarativeBase + engine
        │   ├── session.py              ← get_db()
        │   ├── migrations/
        │   │   └── env.py              ← Alembic env
        │   └── repositories/
        │       ├── base.py             ← BaseRepository[T]
        │       ├── requirement_repository.py
        │       ├── frontend_plan_repository.py
        │       └── job_repository.py
        │
        ├── llm/
        │   ├── clients/
        │   │   ├── base_client.py
        │   │   └── openai_client.py    ← call_llm_with_schema() — tiktoken + jsonschema retry
        │   ├── vector_db/
        │   │   ├── qdrant_client.py
        │   │   ├── embeddings.py
        │   │   └── retrievers.py
        │   └── prompts/
        │       ├── loader.py           ← YAML loader — use _fmt(), NOT .format()
        │       └── templates/
        │           ├── requirement_extractor/   ← base_rules, frontend, backend, both, summary
        │           ├── frontend_planner/        ← plan_module.yaml
        │           └── backend_agent/           ← CREATE YAML HERE for Stage 3 prompts
        │
        ├── agents/
        │   ├── base_agent.py
        │   ├── schemas/
        │   │   ├── requirement_extractor/       ← frontend, backend, combined, summary, unified, segmentation
        │   │   └── frontend_planner/            ← schema.py
        │   ├── frontend_planner/
        │   │   ├── toolkit_knowledge.py         ← PACKAGES dict — source of truth for Kuzu nodes
        │   │   └── toon_serializer.py           ← TOON v3.0 serializer
        │   └── backend/                         ← CREATE THIS — Stage 3 implementation
        │       ├── cli_invoker.py               ← to build
        │       ├── scaffold_validator.py        ← to build
        │       ├── syntax_validator.py          ← to build
        │       └── code_generators/             ← to build
        │           ├── models_generator.py
        │           ├── serializers_generator.py
        │           ├── views_generator.py
        │           └── urls_generator.py
        │
        ├── orchestration/
        │   ├── graph.py                ← Stage 1 LangGraph — DO NOT TOUCH
        │   ├── state.py                ← ExtractionState TypedDict — DO NOT TOUCH
        │   ├── nodes/
        │   │   └── node_definitions.py ← extract_module_node — DO NOT TOUCH
        │   └── planner/
        │       ├── graph.py            ← Stage 2 LangGraph — DO NOT TOUCH
        │       └── nodes.py            ← plan_module_node — DO NOT TOUCH
        │
        ├── api/
        │   └── v1/
        │       └── endpoints/
        │           ├── requirements.py     ← POST /requirement-extractor/parse
        │           └── frontend_planner.py ← POST /frontend-planner/plan
        │
        ├── embedding/                  ← CREATE THIS — Yug's embedding pipeline
        │   ├── __init__.py
        │   ├── schema.py
        │   ├── chunker.py
        │   ├── embedder.py
        │   ├── store.py
        │   ├── graph_schema.py
        │   ├── graph_builder.py
        │   ├── graph_store.py
        │   └── ingestors/
        │       ├── __init__.py
        │       ├── scanner.py
        │       ├── toolkit_ingestor.py
        │       └── examples_ingestor.py
        │
        └── utils/
            └── extractors/
                ├── docx_extractor.py
                └── pdf_extractor.py
```

---

## 4. LOCKED Architecture Decisions — NEVER VIOLATE

These are immutable. No exceptions. No "but in this case...".

| # | Rule | Detail |
|---|------|--------|
| 1 | **Flat LangGraph only** | No nested subgraphs. EVER. All nodes in a single flat graph. |
| 2 | **Parallel reducer** | `Annotated[list, operator.add]` for any field written to by parallel nodes via Send API. |
| 3 | **Call C input = SUMMARIES ONLY** | The unify_requirements LLM call gets ONLY module summaries, never full extractions. Hard cap: 8192 tokens. |
| 4 | **3-layer JSON validation** | `response_format=json_object` + schema in prompt + `jsonschema Draft202012Validator`. Max 2 retries. |
| 5 | **All prompts in YAML** | Never inline prompt strings in Python. Every prompt lives in `llm/prompts/templates/`. |
| 6 | **tiktoken for token counting** | Truncate before EVERY LLM call. Import from `src/msbc/config.py` for limits. |
| 7 | **Django DRF only** | Backend generation target is always Django REST Framework. No FastAPI, no Flask. |
| 8 | **--auth: NEVER** | Never pass `--auth` to djcli. Not now, not ever. `use_auth = False` is locked in `CLIInvokerInput`. |
| 9 | **--api: ALWAYS** | Always pass `--api` explicitly to djcli. `use_api = True` is locked in `CLIInvokerInput`. |
| 10 | **No migration files** | Never generate migration files. No `0001_initial.py`. Nothing in `migrations/` except `__init__.py`. |
| 11 | **LLM generates: models, serializers, custom views** | These require understanding business logic — LLM handles them. |
| 12 | **Jinja2 generates: standard CRUD viewsets, urls.py** | Deterministic output — never use LLM for these. |
| 13 | **ast.parse() every generated file** | Python syntax validation. Max 2 retries on failure. |
| 14 | **CLI path from env var** | `os.environ["DJCLI_PATH"]` — never hardcode. |
| 15 | **djcli is a Python package** | Installed via pip from Nexus. NOT an .exe path. Do not use subprocess with .exe. |
| 16 | **No single contracts.py** | Schema files are split: requirement.py / frontend_plan.py / backend_pipeline.py. Never merge. |
| 17 | **YAML prompt loader uses _fmt()** | Never call `.format()` on prompt strings. Use the existing `_fmt()` helper in `loader.py`. |
| 18 | **OpenAI embedding model** | `text-embedding-3-large` @ 1536 dim. Never sentence-transformers for production embeddings. |
| 19 | **Qdrant collection names** | `toolkit_openai_large_1536` and `examples_openai_large_1536`. Exact strings, no deviation. |

---

## 5. Schema Contracts — Read Before Writing Any Stage 3 Code

**File:** `src/msbc/models/schemas/backend_pipeline.py`

Key types you will use constantly:

```python
CLIInvokerInput(
    project_name: str,
    framework: Framework.DJANGO,     # always django
    app_names: List[str],            # snake_case, sanitized
    module_names: List[str],         # originals pre-sanitization
    use_api: bool = True,            # LOCKED
    use_auth: bool = False,          # LOCKED
    command: "startproject"|"startapp"|"noop",
    existing_project_path: Optional[str]
)

GeneratedFile(
    app_name: str,
    file_type: "models"|"serializers"|"views"|"urls",
    file_path: str,                  # absolute path
    generation_method: "llm"|"jinja2",
    syntax_valid: bool,
    errors: List[str]
)

PipelineOutput(
    project_path: str,
    framework: Framework,
    generated_apps: List[str],
    generated_files: List[GeneratedFile],
    success: bool,
    errors: List[str]
)
```

**File:** `src/msbc/models/schemas/requirement.py` — read for `ExtractionOutput` shape.
**File:** `src/msbc/models/schemas/frontend_plan.py` — read for `FrontendPlan` shape.

---

## 6. Stage 3 — What to Build (Shrey/Deep's Work)

### Build order (strict):
1. `src/msbc/agents/backend/cli_invoker.py`
2. `src/msbc/agents/backend/scaffold_validator.py`
3. `src/msbc/agents/backend/code_generators/models_generator.py`
4. `src/msbc/agents/backend/code_generators/serializers_generator.py`
5. `src/msbc/agents/backend/code_generators/views_generator.py`
6. `src/msbc/agents/backend/code_generators/urls_generator.py`
7. `src/msbc/agents/backend/syntax_validator.py`
8. `src/msbc/orchestration/backend/graph.py` (flat LangGraph for Stage 3)
9. `src/msbc/api/v1/endpoints/backend_generator.py`

### cli_invoker.py rules:
- Use `subprocess.run()` with `timeout=60`
- Get djcli path from `os.environ["DJCLI_PATH"]`
- Command format: `python -m djcli startproject {project_name} {app1} {app2} --api`
- NEVER append `--auth`
- Capture stdout/stderr; map to `CLIInvokerOutput`
- On timeout: set `success=False`, error = "djcli timed out after 60s"

### scaffold_validator.py rules:
- After djcli runs, check these files exist for each app:
  `{app}/models.py`, `{app}/serializers.py`, `{app}/views.py`, `{app}/urls.py`
- Missing files → `ValidationResult(success=False, missing_files=[...])`

### code_generators rules:
- **models_generator.py**: LLM call. Read `ExtractionOutput.modules[n].entities`.
  Prompt in `llm/prompts/templates/backend_agent/models.yaml`.
- **serializers_generator.py**: LLM call. Read models output as context.
  Prompt in `llm/prompts/templates/backend_agent/serializers.yaml`.
- **views_generator.py**: 
  - If `endpoint.operation` in `{list, create, retrieve, update, destroy}` → Jinja2 CRUD template
  - If custom business logic → LLM call
  - Prompt (LLM path) in `llm/prompts/templates/backend_agent/views_custom.yaml`
- **urls_generator.py**: Jinja2 ALWAYS. No LLM.

### syntax_validator.py rules:
```python
import ast
def validate_python(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)
# Max 2 retries on failure — regenerate via LLM with error message in prompt
```

---

## 7. Embedding Pipeline — What to Build (Yug's Work / Reference)

**Spec:** See `plan.md` in repo root — follow it exactly.

Key decisions already locked:
- Model: `text-embedding-3-large`, `dimensions=1536`
- Chunker: tree-sitter (TypeScript/TSX). Fresh impl in `src/msbc/embedding/chunker.py`.
  The `db/` directory exists for reference ONLY — do not modify it.
- MIN_CHUNK_TOKENS=200, MAX_CHUNK_TOKENS=800
- Retry: reuse `app/utils/retry_utils.py`'s `async_retry()`
- OpenAI client pattern: reuse `src/msbc/llm/clients/openai_client.py`
- KUZU source of truth: `src/msbc/agents/frontend_planner/toolkit_knowledge.py` PACKAGES dict

**New config keys to add to `app/core/config.py`:**
```python
QDRANT_URL: str = "http://localhost:6333"
QDRANT_API_KEY: str = ""
OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
EMBEDDING_DIMENSIONS: int = 1536
RTK_MONOREPO_PATH: str = ""
EXAMPLES_DIR: str = "correct_code_examples"
KUZU_DB_PATH: str = "./data/toolkit_graph.kuzu"
```

---

## 8. API Patterns — How Existing Endpoints Work

All endpoints follow this async job pattern:

```python
# POST → returns job_id immediately (202 Accepted)
@router.post('/parse', status_code=202)
async def parse(body, background_tasks, db):
    job = job_repo.create_job(job_type='...')
    db.commit()
    background_tasks.add_task(_run_job, str(job.id), ...)
    return JobSubmitResponse(job_id=str(job.id), status='pending')

# GET /jobs/{job_id} → poll for result
```

When adding Stage 3 endpoint, follow the same pattern exactly.
File: `src/msbc/api/v1/endpoints/backend_generator.py`
Mount in: `app/api/main_router.py`

### Critical: Background Task DB Sessions

Background tasks CANNOT reuse the HTTP request's DB session — it closes when the request ends.
Always create a fresh session inside the background task function:

```python
from src.msbc.database.session import get_db
from contextlib import contextmanager
from sqlalchemy.orm import Session

# Pattern used in existing endpoints — copy exactly:
def _run_backend_generation_job(job_id: str, extraction_id: str, ...):
    with next(get_db()) as db:           # fresh session owned by this task
        job_repo = JobRepository(db)
        try:
            # ... do work ...
            job_repo.update_job(job_id, status="completed", result=output.model_dump())
            db.commit()
        except Exception as e:
            job_repo.update_job(job_id, status="failed", error=str(e))
            db.commit()
```

---

## 9. LLM Call Pattern — How to Call the LLM

Always use the existing wrapper. Never call `openai` directly.

```python
from src.msbc.llm.clients.openai_client import call_llm_with_schema

result = await call_llm_with_schema(
    system_prompt=system_text,
    user_prompt=user_text,
    schema=SCHEMA_DICT,          # jsonschema Draft 2020-12
    model="gpt-4.1-mini",        # default model
    max_retries=2                # SCHEMA_VALIDATION_RETRIES
)
```

Token counting before every call:
```python
import tiktoken
enc = tiktoken.encoding_for_model("gpt-4o")
token_count = len(enc.encode(text))
# Truncate if token_count > (TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS)
```

---

## 10. Prompt YAML Structure

Every prompt file follows this structure:

```yaml
# filename: backend_agent/models.yaml
system: |
  You are a senior Django developer. You will receive backend requirements
  for ONE module and generate a complete models.py file.
  {base_rules}
  Return JSON with key "code" containing the complete Python file as a string.

user_template: |
  Module: {module_name}
  Entities: {entities_json}
  Business rules: {business_rules}
  Generate models.py now.
```

Load via existing loader:
```python
from src.msbc.llm.prompts.loader import load_prompt
prompt = load_prompt("backend_agent/models.yaml")
system = prompt.system
user = prompt._fmt(prompt.user_template, module_name=..., entities_json=...)
```

---

## 11. Django CLI Tool (djcli) — Critical Facts

- **Package name:** `django_cli_tool` (installed from Nexus at `nexus.msbc-mainframe.lcl`)
- **Run via:** `python -m djcli` (NOT `djcli.exe`, NOT hardcoded path)
- **Path source:** `os.environ["DJCLI_PATH"]` if needed, but prefer module invocation
- **Subprocess timeout:** 60 seconds always

```python
import subprocess, os

cmd = [
    "python", "-m", "djcli", "startproject",
    project_name,
    *app_names,
    "--api",           # ALWAYS
    "--path", output_dir
    # NEVER --auth
]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
```

Generated project structure per app (validate these exist):
```
{project_name}/
├── {app_name}/
│   ├── __init__.py
│   ├── models.py        ← LLM will overwrite
│   ├── serializers.py   ← LLM will overwrite
│   ├── views.py         ← Jinja2 or LLM will overwrite
│   ├── urls.py          ← Jinja2 will overwrite
│   ├── admin.py
│   └── apps.py
├── {project_name}/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── manage.py
```

---

## 12. Token Budget

| Constant | Value | Location |
|----------|-------|----------|
| `TOTAL_INPUT_TOKEN_LIMIT` | 10000 | `src/msbc/config.py` |
| `PROMPT_MAX_TOKENS` | 4000 | `src/msbc/config.py` |
| Available for doc text | ~6000 | Computed: 10000 - 4000 |
| `SCHEMA_VALIDATION_RETRIES` | 2 | `src/msbc/config.py` |
| `API_RETRY_ATTEMPTS` | 3 | `src/msbc/config.py` |
| Default model | `gpt-4.1-mini` | env `LLM_MODEL` or hardcode |

---

## 13. Database — Repositories

Always use repository pattern. Never write raw SQLAlchemy queries in endpoint files.

```python
from src.msbc.database.repositories.job_repository import JobRepository
from src.msbc.database.session import get_db

# In endpoint:
db: Session = Depends(get_db)
job_repo = JobRepository(db)
job = job_repo.create_job(job_type="backend_generation")
```

Entity types: `Job`, `RequirementExtraction`, `FrontendPlan`
All in `src/msbc/models/entities/base.py`

---

## 14. Things Claude Must NEVER Do

- ❌ Create `contracts.py` at any level — split schemas stay split
- ❌ Add `--auth` flag anywhere in djcli invocations
- ❌ Generate migration files (`0001_initial.py` etc.)
- ❌ Nest LangGraph subgraphs inside other LangGraph graphs
- ❌ Write prompts as inline Python strings — YAML only
- ❌ Call `openai` SDK directly — use `call_llm_with_schema()`
- ❌ Hardcode the djcli path as a string or .exe path
- ❌ Use `sentence-transformers` for production embeddings
- ❌ Create a standalone `query.py` HTTP endpoint for embeddings — retrieval is via agent tools
- ❌ Modify `db/` directory — it is reference-only
- ❌ Touch `orchestration/graph.py`, `orchestration/nodes/`, `orchestration/planner/` — Stage 1 & 2 are complete
- ❌ Use `.format()` on prompt strings — use `_fmt()` from loader.py
- ❌ Add `kuzu` as pip dependency before confirming it's in pyproject.toml

---

## 15. Infrastructure Context

| Component | Detail |
|-----------|--------|
| Runtime | Python 3.12, FastAPI + Uvicorn |
| Package manager | `uv` (use `uv add` not `pip install` for new deps) |
| DB (app) | PostgreSQL via SQLAlchemy + Alembic |
| Vector DB | Qdrant (`qdrant-client` already in pyproject.toml) |
| Graph DB | Kuzu embedded (`pip install kuzu` / `uv add kuzu`) |
| LLM | OpenAI GPT-4.1-mini (`openai` SDK already in pyproject.toml) |
| Embeddings | OpenAI `text-embedding-3-large` |
| Internal PyPI | Nexus at `nexus.msbc-mainframe.lcl` |
| djcli package | `django_cli_tool-0.0.1-py3-none-any.whl` from Nexus |
| Deployment | Kubernetes on VM + Docker |

---

## 16. Running the Project

```bash
# Install deps
uv sync

# Run server
uv run uvicorn main:app --reload

# Run DB migrations
uv run alembic upgrade head

# Embed toolkit (once embedding pipeline is built)
uv run python scripts/embed_toolkit.py

# Build Kuzu graph
uv run python scripts/build_graph.py
```

Endpoints after server starts:
- `http://localhost:8000/health` — liveness
- `http://localhost:8000/docs` — Swagger UI
- `POST /api/v1/requirement-extractor/parse` — Stage 1
- `POST /api/v1/frontend-planner/plan` — Stage 2
- `POST /api/v1/backend-generator/generate` — Stage 3 (to build)
- `GET /api/v1/jobs/{job_id}` — poll job status

---

## 17. Current Work Status

| Component | Status | Owner |
|-----------|--------|-------|
| Stage 1 — Requirement Extractor | ✅ Complete | Yug |
| Stage 2 — Frontend Planner | ✅ Complete | Yug |
| Schema contracts (3 files) | ✅ Complete | All |
| Embedding pipeline | 🔄 In progress | Yug |
| Stage 3 — Backend Code Gen | 🔴 To build | Deep (Shrey) |
| Frontend UI (Vite+React+TS) | 🔴 To build | Yug |

**Current session focus:** Stage 3 backend code generation pipeline.
Start from `src/msbc/agents/backend/cli_invoker.py`.
Read `src/msbc/models/schemas/backend_pipeline.py` first — all types are defined there.