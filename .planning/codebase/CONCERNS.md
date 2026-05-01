# CONCERNS.md

## High Severity

| # | Concern | Detail |
|---|---------|--------|
| 1 | **Stage 3 pipeline entirely absent** | `src/msbc/agents/backend/` does not exist. Nine planned files (cli_invoker, scaffold_validator, syntax_validator, 4 code_generators) are missing. No Stage 3 LangGraph (`src/msbc/orchestration/backend/graph.py`) exists either. This is the primary open work item. |
| 2 | **Embedding pipeline entirely absent** | `src/msbc/embedding/` does not exist. Nine planned files (chunker, embedder, store, graph_builder, ingestors, etc.) are all missing. |
| 3 | **`OPENAI_API_KEY` not validated at startup** | `app/core/config.py` defaults `OPENAI_API_KEY` to `""`. No startup check raises an error if the key is missing — the app boots silently and fails only on first LLM call. |

---

## Medium Severity

| # | Concern | Detail |
|---|---------|--------|
| 4 | **`CORS_ORIGINS` defaults to `["*"]` with `allow_credentials=True`** | Wildcard origin + `allow_credentials=True` is rejected by browsers per CORS spec and is a security misconfiguration for any non-local deployment. |
| 5 | **No DB migration or ORM entity for Stage 3 results** | There is no `BackendGeneration` ORM entity or Alembic migration. Stage 3 has nowhere to persist its output. |
| 6 | **`alembic.ini` fallback URL hardcodes credentials** | `postgresql://user:password@localhost:5432/devagents` — safe only because `env.py` overrides it, but a misconfigured `env.py` would expose the fallback. |
| 7 | **`app/core/config.py` missing embedding/Qdrant config keys** | CLAUDE.md §7 (Embedding Pipeline) requires Qdrant URL, collection names, embedding model, etc. None are present in `Settings`. Stage 3 and embedding work will need these added before they can be configured via env vars. |
| 8 | **`call_llm_with_schema` token truncation not verified** | The CLAUDE.md locked rule requires tiktoken truncation before EVERY LLM call. If any call path bypasses `call_llm_with_schema`, truncation is silently skipped. |

---

## Low Severity

| # | Concern | Detail |
|---|---------|--------|
| 9 | **`job_type` is a free-form string** | `Job.job_type` has no enum validation at the ORM or Pydantic layer — typos silently create jobs with unknown types. |
| 10 | **Non-standard Alembic revision IDs** | Revisions use `"001"`, `"002"`, `"003"` strings instead of Alembic-generated hex IDs. Alembic can work with them but `--autogenerate` may create ordering issues. |
| 11 | **`scripts/check_jobs_schema.py` hardcodes SQLite** | The script uses a hardcoded SQLite URL, not the configured `DATABASE_URL`. It will not reflect the actual PostgreSQL schema. |
| 12 | **`updated_at` has no DB-level trigger** | `updated_at` relies on application-level updates. If a row is modified directly in the DB (e.g., during debugging), `updated_at` will not update. |

---

## Clean / No Concerns

- No `TODO`, `FIXME`, or `HACK` comments found anywhere in the codebase
- Enum duplication between `backend_pipeline.py` and other schema files is expected given Stage 3 is in early design
