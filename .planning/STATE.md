---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: planning
last_updated: "2026-04-29T00:00:00.000Z"
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 3
  completed_plans: 0
---

# STATE.md — InHouseAgents

## Project Reference

**Core value**: Given a requirement document, generate a deployable Django DRF project with
syntactically valid Python for every app.

**Milestone**: M1 — Stage 3 (Backend Code Gen) + Embedding Pipeline + Frontend UI Port

**Roadmap**: 5 phases, 26 requirements

---

## Current Position

**Phase**: 1 — Stage 3 Foundation
**Plan**: 3 plans ready (01-01, 01-02, 01-03)
**Status**: Ready to execute

```
Progress: [----------] 0/5 phases complete
```

---

## Phase Status

| Phase | Status | Started | Completed |
|-------|--------|---------|-----------|
| 1. Stage 3 Foundation | Ready to execute (3 plans) | 2026-04-29 | - |
| 2. Code Generators | Not started | - | - |
| 3. Stage 3 Orchestration & API | Not started | - | - |
| 4. Embedding Pipeline | Not started | - | - |
| 5. Frontend UI Port | Not started | - | - |

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Requirements total | 26 |
| Requirements completed | 0 |
| Phases completed | 0/5 |
| Plans completed | 0/3 |

---

## Accumulated Context

### Architecture Decisions (Locked)

- `--api` always passed to djcli, `--auth` NEVER passed
- Django DRF only — no Flask, no FastAPI as output target
- LLM for models.py, serializers.py, custom views only; Jinja2 for CRUD viewsets and urls.py always
- ast.parse() on every generated Python file, max 2 retries
- All LLM prompts in YAML under `llm/prompts/templates/` — no inline strings
- Flat LangGraph only — no nested subgraphs, ever
- Schema contracts in 3 separate files — never merged
- tiktoken truncation before every LLM call using `TOTAL_INPUT_TOKEN_LIMIT`
- Django project output directory is a configurable runtime parameter

### Known Pre-Work Items (Before Phase 1 Plans)

- `Framework` and `ExtractionMode` enums are duplicated in `backend_pipeline.py` and `requirement.py` — canonical home decision needed before Stage 3 build begins
- `OPENAI_API_KEY` has no startup validation — silent failure if missing; address early
- `CORS_ORIGINS=["*"]` + `allow_credentials=True` is a security misconfiguration for non-local deploys

### Parallelization Notes

- Phase 4 (Embedding Pipeline) is fully independent of Phases 1-3 — Yug can run concurrently
- Phase 3 has a soft dependency on Phase 4 (RAG context); Stage 3 graph should handle empty Qdrant collection gracefully so Phase 3 can be completed before Phase 4 finishes
- Within Phase 2, generators (S3-03 through S3-06) are independently implementable — all four can be planned and executed in parallel

### Blockers

None at start.

### Todos

- [ ] Resolve enum duplication (Framework, ExtractionMode) before Phase 1 plans run
- [ ] Add OPENAI_API_KEY startup validation (can be done in Phase 1)

---

## Session Continuity

**Last updated**: 2026-04-29 — Phase 1 planning complete (3 plans verified)

**Next action**: Run `/gsd-execute-phase 1` to execute Phase 1 plans

**Context for next session**:

- Stages 1 and 2 are production-ready — do not touch `src/msbc/orchestration/graph.py`,
  `src/msbc/orchestration/planner/graph.py`, or any Stage 1/2 nodes

- `src/msbc/models/schemas/backend_pipeline.py` already exists with Pydantic models for
  CLIInvokerInput (use_api=True, use_auth=False), GeneratedFile, PipelineOutput — read this
  before writing any Phase 1 code

- All new Stage 3 code goes under `src/msbc/agents/backend/`
- All new embedding code goes under `src/msbc/embedding/`
- New endpoint files go in `src/msbc/api/v1/endpoints/` and must be registered in
  `app/api/main_router.py`
