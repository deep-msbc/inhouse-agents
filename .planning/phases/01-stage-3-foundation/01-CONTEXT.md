# Phase 1: Stage 3 Foundation - Context

**Gathered:** 2026-04-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the wiring prerequisites for Stage 3 backend code generation: the djcli subprocess wrapper (CLIInvoker), the scaffold file-tree verifier (ScaffoldValidator), the BackendGeneration ORM entity + Alembic migration, and confirmation that schema contracts live in three separate files with no cross-imports.

Code generation (models, serializers, views, urls) and LangGraph orchestration are NOT in scope — those are Phase 2 and Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Output path for generated Django projects

- **D-01:** Add `output_path: str` field to `CLIInvokerInput` in `backend_pipeline.py`. The caller specifies the target directory per-request — it is not read from an env var or app config inside the invoker.
- **D-02:** `cli_invoker.py` calls `os.makedirs(output_path, exist_ok=True)` before invoking djcli. The invoker is responsible for ensuring the directory exists — the caller does not need to pre-create it.

### BackendGeneration ORM entity

- **D-03:** Table name: `backend_generations`. Columns (exact set — no extras):
  - `id` — UUID PK (use same `_uuid_col()` SQLite/Postgres pattern as existing entities)
  - `extraction_id` — String, FK → `requirement_extractions.id`, not nullable, indexed
  - `project_name` — String(255), not nullable (snake_case djcli project name)
  - `output_path` — String(1024), not nullable (absolute disk path where Django project landed)
  - `cli_stdout` — Text, nullable (raw djcli stdout — debug aid)
  - `cli_stderr` — Text, nullable (raw djcli stderr — debug aid)
  - `pipeline_output` — JSON, nullable (full `PipelineOutput.model_dump()` — populated only on success)
  - `success` — Boolean, not nullable
  - `created_at` — DateTime(timezone=True), server_default=func.now() — follow RequirementExtraction exactly (no `updated_at` needed)
- **D-04:** FK constraint is a real DB-level FK for relational integrity (not a plain string column).
- **D-05:** `BackendGenerationRepository` is minimal — `create()` + `get_by_id()` only. Job lifecycle (pending → processing → completed → failed) stays in `JobRepository`. BackendGeneration is a result record written once at completion.

### Schema contracts

- **D-06:** `Framework` and `ExtractionMode` enums are already only defined in `backend_pipeline.py` — not duplicated in `requirement.py`. They stay in `backend_pipeline.py`. Anyone outside Stage 3 who needs them imports from there. No shared `enums.py` needed.
- **D-07:** S3-14 is already structurally satisfied (3 separate schema files with no cross-imports). The Phase 1 deliverable is a verification that no import merges have crept in — no code change needed unless the audit finds a violation.

### Claude's Discretion

- Alembic migration generation strategy (`--autogenerate` is the established pattern in this repo — follow it)
- `BackendGeneration.__repr__` format (follow existing entity style)
- Exact error message text on djcli timeout ("djcli timed out after 60s" is suggested in CLAUDE.md §6 — use it)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Schema contracts
- `src/msbc/models/schemas/backend_pipeline.py` — CLIInvokerInput (add output_path here), CLIInvokerOutput, ValidationResult, GeneratedFile, PipelineOutput — all locked types for Stage 3
- `src/msbc/models/schemas/requirement.py` — ExtractionOutput shape; BackendModuleItem structure that Stage 3 consumes

### ORM patterns to follow
- `src/msbc/models/entities/requirement_extraction.py` — Canonical ORM entity pattern: _uuid_col() helper, JSON columns, created_at only (no updated_at), mapped_column style
- `src/msbc/models/entities/job.py` — Job entity; shows FK-compatible UUID typing and _uuid_col() usage
- `src/msbc/database/repositories/job_repository.py` — Repository pattern: extend BaseRepository[T], method naming conventions

### Architecture rules
- `CLAUDE.md` §6 — cli_invoker.py build rules (subprocess.run, timeout=60, --api always, --auth never, stdout/stderr capture)
- `CLAUDE.md` §11 — djcli critical facts (python -m djcli, --path flag, never .exe)
- `CLAUDE.md` §8 — Background task DB session pattern (fresh session inside background task — CRITICAL)
- `CLAUDE.md` §13 — Repository pattern enforcement (no raw SQLAlchemy in endpoint files)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_uuid_col()` helper: copy the pattern from `requirement_extraction.py` — handles SQLite String(36) vs Postgres UUID(as_uuid=True)
- `BaseRepository[T]` in `src/msbc/database/repositories/base_repository.py` — extend this for BackendGenerationRepository
- `JobRepository.create_job()` — the `job_type` string for backend generation will be `"backend_generation"` (extend the accepted strings)
- `app/utils/retry_utils.py::async_retry()` — available if any Phase 1 code needs retry logic

### Established Patterns
- All ORM entities: UUID PK via `_uuid_col()`, `server_default=func.now()` for timestamps, JSON columns for payloads
- All repositories: extend `BaseRepository[T]`, constructor takes `Session`, named methods for domain operations
- Background tasks: fresh `Session` created inside the task function (HTTP request session is closed by then)

### Integration Points
- `BackendGeneration` entity must be imported in `src/msbc/models/entities/__init__.py` so Alembic's `env.py` picks it up via `import src.msbc.models.entities`
- `BackendGenerationRepository` goes in `src/msbc/database/repositories/backend_generation_repository.py` — no changes to existing repositories
- New `output_path: str` field in `CLIInvokerInput` is additive — no existing callers to update (Stage 3 endpoint doesn't exist yet)

</code_context>

<specifics>
## Specific Ideas

- "FK to requirement_extractions.id — proper relational integrity" (user's exact words)
- Column set for BackendGeneration specified verbatim by user — do not add columns beyond: id, extraction_id, project_name, output_path, cli_stdout, cli_stderr, pipeline_output, success, created_at

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-stage-3-foundation*
*Context gathered: 2026-04-29*
