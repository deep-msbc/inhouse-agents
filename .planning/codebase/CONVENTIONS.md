# CONVENTIONS.md

## Naming Conventions

| Item | Convention | Example |
|---|---|---|
| Files | `snake_case.py` | `openai_client.py`, `toon_serializer.py` |
| Classes | `PascalCase` | `RequirementExtraction`, `BaseRepository` |
| Functions / methods | `snake_case` | `call_llm_with_schema`, `get_db` |
| Constants | `UPPER_SNAKE_CASE` | `TOTAL_INPUT_TOKEN_LIMIT`, `SCHEMA_VALIDATION_RETRIES` |
| Private helpers | `_leading_underscore` | `_bg_session()`, `_unwrap_components()` |
| Private schemas | `_PRIVATE_SCHEMA` | `_PRIVATE_SCHEMA` dict inside agent schema files |

---

## Import Organization

Order (top-to-bottom):
1. Standard library
2. Third-party (fastapi, sqlalchemy, langchain, pydantic...)
3. Internal `app.*` imports
4. Internal `src.msbc.*` imports

---

## Prompt System

**All prompts live in YAML files** under `src/msbc/llm/prompts/templates/<pipeline>/`.

**Never** inline prompt strings in Python code.

Use the `_fmt()` helper from `src/msbc/llm/prompts/loader.py` instead of Python's `.format()`:
```python
# Correct
prompt = _fmt(template, variable=value)

# Wrong — raw JSON braces in templates break .format()
prompt = template.format(variable=value)
```

---

## Pydantic Schema Patterns

**`_OpenModel` base class** (sets `ConfigDict(extra="allow")`): Used for all LLM output schemas so unexpected LLM-generated fields don't cause hard validation failures.

**Agent output schemas** use two-level pattern:
- `_PRIVATE_SCHEMA`: raw JSON Schema dict (Draft 2020-12) passed to `call_llm_with_schema`
- Public Pydantic model: typed Python model parsed after validation

All incoming API request/response models live in `src/msbc/models/schemas/`. Agent-specific schemas live in `src/msbc/agents/schemas/`.

---

## LLM Validation — 3-Layer Pattern

Every LLM call must go through all three layers:
1. `response_format={"type": "json_object"}` — structural enforcement at API level
2. JSON Schema in prompt — instructs the LLM on expected output
3. `jsonschema.Draft202012Validator` — programmatic validation with auto-retry on failure

Max retries: `SCHEMA_VALIDATION_RETRIES` (from `src/msbc/config.py`, currently `2`).

---

## Retry / Backoff Patterns

Three patterns in use — pick the right one:

| Pattern | Location | Use for |
|---|---|---|
| `async_retry()` decorator | `app/utils/retry_utils.py` | General async functions with transient failures |
| LLM schema retry loop | `openai_client.py` → `call_llm_with_schema` | JSON Schema validation failures (appends error to prompt) |
| `max_retries` config | `config/settings.yaml` | Agent-level retry budget |

---

## Error Handling

- Pipeline failures raise `RuntimeError` with descriptive messages
- Catch-log-reraise pattern: log the error at ERROR level, then let it propagate to the job runner which sets `Job.status = "failed"`
- Background tasks catch all exceptions to prevent silent failures — always update Job status in the `except` block

---

## Logging

Centralized factory in `app/core/logger.py`:
```python
from app.core.logger import get_logger
logger = get_logger(__name__)
```

Log level controlled by `LOG_LEVEL` env var (default `INFO`). Use `logger.info`, `logger.error`, `logger.debug` — no `print()` statements.

---

## LangGraph State Conventions

- State types are `TypedDict`
- Fields written by parallel `Send` nodes: `Annotated[list, operator.add]` — never a plain `list`
- All state files live alongside their graph: `state.py` next to `graph.py`

---

## Repository Pattern

All DB access goes through repository classes in `src/msbc/database/repositories/`. All inherit `BaseRepository[T]`. Never write raw SQLAlchemy queries directly in endpoints or nodes.

---

## Token Counting

Always count tokens with `tiktoken` before LLM calls. Use `TOTAL_INPUT_TOKEN_LIMIT` from `src/msbc/config.py` as the hard cap. Truncate — never let an oversized prompt silently fail downstream.
