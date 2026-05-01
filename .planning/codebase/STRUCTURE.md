# STRUCTURE.md

## Root Layout

```
InHouseAgents/
├── main.py                     FastAPI app factory — wires app/ and src/msbc/ together
├── pyproject.toml              uv-managed dependencies
├── alembic.ini                 Alembic config (script_location = src/msbc/database/migrations)
├── config/settings.yaml        Default runtime values (overridden by env vars / .env)
├── scripts/                    One-off CLI scripts (check_jobs_schema, create_jobs_table)
├── app/                        Application shell (framework wiring)
└── src/msbc/                   Core domain package (all business logic)
```

---

## `app/` — Application Shell

```
app/
├── api/
│   └── main_router.py          Central APIRouter — imports and mounts all endpoint routers
├── core/
│   ├── config.py               Pydantic BaseSettings — ALL env vars live here
│   └── logger.py               get_logger(name) factory
├── dependencies.py             Shared FastAPI Depends() helpers
└── utils/
    └── retry_utils.py          async_retry() decorator — use this for any retry logic
```

`app/core/config.py` is the canonical settings object. Import `settings` from here everywhere.

---

## `src/msbc/` — Core Domain

### API Layer
```
src/msbc/api/v1/endpoints/
├── requirements.py             POST /requirement-extractor/parse  +  GET /jobs/{id}
└── frontend_planner.py         POST /frontend-planner/plan        +  GET /jobs/{id}
```
All endpoints follow the async-job pattern: validate → create Job → queue BackgroundTask → return 202.

### Orchestration (LangGraph)
```
src/msbc/orchestration/
├── graph.py                    Stage 1 graph — DO NOT MODIFY
├── state.py                    ExtractionState TypedDict — DO NOT MODIFY
├── nodes/
│   ├── node_definitions.py     Segmentation, extract_module, finalize nodes — DO NOT MODIFY
│   └── edge_logic.py           Conditional edge functions
└── planner/
    ├── graph.py                Stage 2 graph — DO NOT MODIFY
    ├── nodes.py                Prepare, plan_module, finalize_plan nodes — DO NOT MODIFY
    └── state.py                PlannerState TypedDict
```

### LLM & Agents
```
src/msbc/llm/
├── clients/
│   ├── base_client.py          Abstract base
│   └── openai_client.py        call_llm_with_schema() — tiktoken + jsonschema retry loop
├── prompts/
│   ├── loader.py               YAML loader + _fmt() helper (use instead of .format())
│   └── templates/
│       ├── requirement_extractor/   base_rules, frontend, backend, both, summary YAMLs
│       ├── frontend_planner/        plan_module.yaml
│       └── backend_agent/           (empty — Stage 3 prompts go here)
└── vector_db/
    ├── qdrant_client.py
    ├── embeddings.py
    └── retrievers.py

src/msbc/agents/
├── base_agent.py
├── schemas/
│   ├── requirement_extractor/  Pydantic output schemas: frontend, backend, combined, summary, unified, segmentation
│   └── frontend_planner/       schema.py
├── frontend_planner/
│   ├── toolkit_knowledge.py    PACKAGES dict — MSBC React component registry, injected into prompts
│   └── toon_serializer.py      TOON v3.0 compressor
└── backend/                    (to be created — Stage 3 agents)
```

### Models
```
src/msbc/models/
├── entities/
│   └── (base.py)               SQLAlchemy ORM: Job, RequirementExtraction, FrontendPlan
└── schemas/
    ├── requirement.py          Stage 1 Pydantic request/response models
    ├── frontend_plan.py        Stage 2 Pydantic request/response models
    └── backend_pipeline.py     Stage 3 contracts: CLIInvokerInput etc. (in progress)
```

### Database
```
src/msbc/database/
├── base.py                     DeclarativeBase + SQLAlchemy engine
├── session.py                  get_db() FastAPI dependency
├── migrations/
│   ├── env.py                  Alembic env — injects DATABASE_URL from settings
│   └── versions/
│       ├── 001_create_requirement_extractions.py
│       ├── 002_create_frontend_plans.py
│       └── 003_create_jobs.py
└── repositories/
    ├── base_repository.py      BaseRepository[T] — typed CRUD
    ├── requirement_repository.py
    ├── frontend_plan_repository.py
    └── job_repository.py
```

### Constants
```
src/msbc/config.py              TOTAL_INPUT_TOKEN_LIMIT=10000, SCHEMA_VALIDATION_RETRIES=2
```

---

## Where New Code Goes

| What | Where |
|---|---|
| New API endpoint | `src/msbc/api/v1/endpoints/<name>.py` + register in `app/api/main_router.py` |
| New LangGraph pipeline | `src/msbc/orchestration/<name>/graph.py` + `state.py` + `nodes.py` |
| New agent output schema | `src/msbc/agents/schemas/<pipeline>/schema.py` |
| New LLM prompt | `src/msbc/llm/prompts/templates/<pipeline>/<name>.yaml` |
| New ORM entity | `src/msbc/models/entities/<name>.py` + import in `main.py` noqa block |
| New Pydantic contract | `src/msbc/models/schemas/<name>.py` |
| New Alembic migration | `uv run alembic revision --autogenerate -m "description"` |
| Stage 3 backend agents | `src/msbc/agents/backend/` |
| Embedding pipeline | `src/msbc/embedding/` |
