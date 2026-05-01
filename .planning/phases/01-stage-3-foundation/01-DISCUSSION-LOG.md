# Phase 1: Stage 3 Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-29
**Phase:** 01-stage-3-foundation
**Areas discussed:** Output path config, BackendGeneration entity

---

## Output path config

| Option | Description | Selected |
|--------|-------------|----------|
| Add to CLIInvokerInput | Add `output_path: str` to CLIInvokerInput — per-request, clean contract | ✓ |
| Env var in cli_invoker.py | Read DJANGO_PROJECTS_OUTPUT_PATH inside invoker, invisible to callers | |
| App config setting | Add DJANGO_OUTPUT_PATH to app/core/config.py, no per-request customization | |

**User's choice:** Add `output_path: str` to `CLIInvokerInput`
**Notes:** Clean per-request contract, easy to test.

---

### Follow-up: Directory creation

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — create it | cli_invoker.py calls os.makedirs(output_path, exist_ok=True) before subprocess | ✓ |
| No — caller's responsibility | Assume directory exists; djcli failure captured in errors | |

**User's choice:** Yes — invoker creates the directory
**Notes:** Caller doesn't need to pre-create directories.

---

## BackendGeneration entity

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — FK to requirement_extractions.id | Real DB-level FK constraint for relational integrity | ✓ |
| No — plain string extraction_id | Looser coupling, no FK cascade issues | |

**User's choice:** Real FK constraint
**Notes (verbatim from user):** "FK to requirement_extractions.id — proper relational integrity. Additional columns needed beyond the pattern shown: project_name: String (djcli project name, snake_case), output_path: String (final disk path where Django project landed), cli_stdout: Text (raw djcli stdout for debugging), cli_stderr: Text (raw djcli stderr for debugging), pipeline_output: JSON (full PipelineOutput.model_dump()). Follow exact same timestamp pattern as RequirementExtraction. No extra columns beyond these — keep it lean."

---

### Follow-up: Repository scope

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal — create + get_by_id only | Job lifecycle stays in JobRepository; BackendGeneration written once on completion | ✓ |
| Full lifecycle repo | Adds mark_processing/mark_completed/mark_failed | |

**User's choice:** Minimal
**Notes:** BackendGeneration is a result record, not a lifecycle entity.

---

## Claude's Discretion

- Alembic migration approach (autogenerate is the established pattern)
- `__repr__` format for BackendGeneration entity
- Exact timeout error message text

## Deferred Ideas

None raised during discussion.
