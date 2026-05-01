# External Integrations

**Analysis Date:** 2026-04-29

## APIs & External Services

**LLM (Primary):**
- OpenAI Chat Completions API - Requirement extraction, frontend planning, all LLM calls
  - SDK/Client: `langchain-openai` `ChatOpenAI` (wraps `openai` SDK)
  - Implementation: `src/msbc/llm/clients/openai_client.py`
  - Auth: `OPENAI_API_KEY` environment variable
  - Default model: `gpt-4.1-mini` (configurable via `LLM_MODEL` env var)
  - JSON mode enabled for supported models (gpt-4.1*, gpt-4o*, gpt-4-turbo, gpt-3.5-turbo-1106/0125)

**Embeddings:**
- Voyage AI Embeddings API - External embedding generation
  - SDK/Client: `voyageai` >=0.3.7
  - Auth: Voyage AI API key (env var name not yet surfaced in codebase — check `.env`)
- HuggingFace Hub - Model downloads for local inference
  - SDK/Client: `huggingface-hub` >=1.9.0
  - Auth: `HUGGING_FACE_HUB_TOKEN` (standard HuggingFace env var convention)

## Data Storage

**Primary Database:**
- PostgreSQL
  - Connection: `DATABASE_URL` env var
  - Default: `postgresql://postgres:postgres@localhost:5432/devagents`
  - Client/ORM: SQLAlchemy >=2.0.0 (`src/msbc/database/base.py`)
  - Session management: `src/msbc/database/session.py` — `get_db()` FastAPI dependency
  - Pool settings: `DATABASE_POOL_SIZE` (default 10), `DATABASE_MAX_OVERFLOW` (default 5), `pool_pre_ping=True`
  - Echo SQL: `DATABASE_ECHO` (default False)

**Development Database Alternative:**
- SQLite — auto-detected when `DATABASE_URL` starts with `sqlite://`
  - Tables created via `Base.metadata.create_all()` on startup (`main.py:_init_db`)

**Vector Store:**
- Qdrant — vector database for embeddings
  - Client: `qdrant-client` >=1.17.1
  - Connection config: Not yet surfaced in `app/core/config.py` — likely in `.env`

**File Storage:**
- Local filesystem only — uploaded documents processed in-memory, not persisted to disk

**Caching:**
- None detected

## Authentication & Identity

**Auth Provider:**
- None — no user authentication layer detected; the API is unauthenticated

## Database Migrations

**Tool:** Alembic >=1.13.0
- Config: `alembic.ini`
- Script location: `src/msbc/database/migrations/`
- Versions directory: `src/msbc/database/migrations/versions/`
- Existing migrations:
  - `001_create_requirement_extractions.py`
  - `002_create_frontend_plans.py`
  - `003_create_jobs.py`
- `DATABASE_URL` injected at runtime via `src/msbc/database/migrations/env.py` from `app.core.config.settings`
- Run migrations: `alembic upgrade head`

## Monitoring & Observability

**Error Tracking:**
- None detected (no Sentry, Datadog, etc.)

**Logs:**
- Python `logging` module with a custom root configuration in `app/core/logger.py`
- Format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- Level controlled by `LOG_LEVEL` env var (default: `INFO`)
- Noisy third-party loggers silenced at WARNING: `httpx`, `httpcore`, `openai`, `urllib3`

## CI/CD & Deployment

**Hosting:**
- Not specified in codebase

**CI Pipeline:**
- Not detected

## Environment Configuration

**Required env vars:**
- `OPENAI_API_KEY` — OpenAI API key (required for all LLM calls; no default)
- `DATABASE_URL` — PostgreSQL connection string (default: `postgresql://postgres:postgres@localhost:5432/devagents`)

**Optional env vars:**
- `LLM_MODEL` — OpenAI model name (default: `gpt-4.1-mini`)
- `LLM_TIMEOUT` — Seconds per LLM call (default: `120`)
- `DATABASE_ECHO` — Log SQL statements (default: `False`)
- `DATABASE_POOL_SIZE` — SQLAlchemy pool size (default: `10`)
- `DATABASE_MAX_OVERFLOW` — SQLAlchemy overflow connections (default: `5`)
- `LOG_LEVEL` — Logging verbosity (default: `INFO`)
- `HOST` — API bind address (default: `0.0.0.0`)
- `PORT` — API port (default: `8000`)
- `RELOAD` — Uvicorn hot-reload (default: `True`)
- `CORS_ORIGINS` — Allowed CORS origins (default: `["*"]`)
- `ENVIRONMENT` — deployment environment label (default: `development`)
- `DEBUG` — FastAPI debug mode (default: `True`)

**Secrets location:**
- `.env` file in project root (loaded by `pydantic-settings`; must not be committed)
- `app/core/config.py` — Settings class definition (`SettingsConfigDict(env_file=".env")`)

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## API Endpoints

**Requirement Extractor:**
- `POST /api/v1/requirement-extractor/parse` — Upload `.docx`/`.pdf`, returns `job_id` (HTTP 202, async)
- `GET /api/v1/requirement-extractor/jobs/{job_id}` — Poll job status and results

**Frontend Planner:**
- Registered via `src/msbc/api/v1/endpoints/frontend_planner.py` (prefix and routes defined there)

**Health:**
- `GET /health` — Returns `{"status": "ok", ...}`

**OpenAPI Docs:**
- `GET /api/v1/openapi.json`

---

*Integration audit: 2026-04-29*
