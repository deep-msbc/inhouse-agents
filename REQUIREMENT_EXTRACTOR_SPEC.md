# Requirement Extractor — Full Implementation Specification

> This document describes the complete working implementation of Stage 1 (Requirement Extractor) across all three extraction modes: `frontend`, `backend`, and `both`.
> Every file path is relative to the repo root `InHouseAgents/`.

---

## 1. Entry Point — API Endpoint

**File:** `src/msbc/api/v1/endpoints/requirements.py`

The router is mounted under `/api/v1/requirement-extractor` via `app/api/main_router.py`.

### POST `/requirement-extractor/parse`

- Accepts: multipart form — `file` (.docx or .pdf), `mode` (string)
- Returns: HTTP 202 with `{ job_id, status: "pending" }`
- Validation: file type, file size (max 20 MB), and mode string are validated before job is created
- The heavy LLM work runs in a background task (`BackgroundTasks`) so the HTTP response returns immediately

**File validators:**
- `src/msbc/utils/validators.py` — `validate_file_size()`, `validate_mode()`, `validate_uploaded_file()`

**File extractors:**
- `src/msbc/utils/extractors/docx_extractor.py` — extracts plain text + heading hierarchy from `.docx`
- `src/msbc/utils/extractors/pdf_extractor.py` — extracts plain text + heading hierarchy from `.pdf`

### GET `/requirement-extractor/jobs/{job_id}`

- Polls job status: `pending` → `processing` → `completed` | `failed`
- Returns the full structured JSON result once `completed`

### Background Task DB Session Pattern

Background tasks cannot reuse the HTTP request's DB session (it closes when the request ends). A standalone `_bg_session()` context manager (defined in the same endpoint file) creates a fresh `sqlalchemy.orm.Session` tied to the task's lifetime.

---

## 2. Constants and Configuration

**File:** `src/msbc/config.py`

| Constant | Value | Purpose |
|---|---|---|
| `TOTAL_INPUT_TOKEN_LIMIT` | 12000 | Hard cap: system + user prompt + doc text per LLM call |
| `PROMPT_MAX_TOKENS` | 4000 | Reserved for fixed prompt templates |
| `SCHEMA_VALIDATION_RETRIES` | 2 | Max extra attempts when LLM JSON fails schema validation |
| `API_RETRY_ATTEMPTS` | 3 | 1 original + 2 retries on transient API failures |
| `API_RETRY_BASE_DELAY` | 1.0s | Doubles each retry: 1 → 2 → 4 seconds |
| `MODULE_EXTRACTION_TIMEOUT` | 600s | Hard deadline for one `extract_module_node` coroutine |
| `MODULE_BATCH_SIZE` | 3 | Max concurrent modules in the fan-out (concurrency semaphore) |
| `LLM_MAX_CONCURRENCY` | 15 | Max simultaneous OpenAI calls globally |
| `VALID_MODES` | `{"frontend", "backend", "both"}` | Accepted mode values |
| `MAX_FILE_SIZE_BYTES` | 20 MB | Upload limit |

App-level settings (env vars like `OPENAI_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT`) live in `app/core/config.py`.

---

## 3. LangGraph Workflow

**File:** `src/msbc/orchestration/graph.py`

The graph is compiled once at import time. Entry point: `run_extraction(document_text, heading_hierarchy, mode)`.

### Graph Topology (flat — no nested subgraphs)

```
START
  │
  ▼
segmentation_node          (1 LLM call — classifies headings)
  │
  │  conditional edge — fan_out_to_modules() returns N Send objects
  │
  ├──► extract_module_node (module 0)  ─┐
  ├──► extract_module_node (module 1)  ─┤  all run concurrently, capped by MODULE_BATCH_SIZE
  └──► extract_module_node (module N)  ─┘
                                         │
                                         ▼
                                    finalize_node   (pure-Python collect + 1 graph-builder LLM call)
                                         │
                                         ▼
                                        END
```

**State type:** `src/msbc/orchestration/state.py` → `ExtractionState` (TypedDict)

The `results` field uses `Annotated[list, operator.add]` so parallel `extract_module_node` invocations each append without overwriting.

**Edge logic:** `src/msbc/orchestration/nodes/edge_logic.py` → `fan_out_to_modules()` calls `build_slices_node()` which returns one `langgraph.types.Send` object per module.

**Node implementations:** `src/msbc/orchestration/nodes/node_definitions.py`

---

## 4. Pipeline Phases — Detailed

All node logic lives in one file: `src/msbc/orchestration/nodes/node_definitions.py`

### Phase 0 — `segmentation_node`

**Goal:** Identify the top-level modules from the uploaded document's heading structure.

**Steps (in order):**

1. **Python pre-clean** (`_pre_clean_headings`): Remove blank headings, headings > 150 chars, emoji-prefixed decorative headings, and field-label headings (e.g. "Module Name: X"). Keep only the three shallowest heading levels. Deduplicate by exact text.

2. **Structural candidate selection** (`_select_module_candidates`): From the cleaned headings, keep only structural "container" headings — the shallowest level with 2–25 entries, or (when overcrowded) only headings at that level that have ≥ 4 direct sub-headings. Reduces 100–200 headings to 3–25 candidates so the LLM receives a small, accurate input.

3. **LLM classification call**: Each candidate heading is classified as `MODULE` | `SUB_SECTION` | `UI` | `IGNORE`.
   - Prompt: `src/msbc/llm/prompts/templates/requirement_extractor/segmentation.yaml`
   - Schema: `src/msbc/agents/schemas/requirement_extractor/segmentation.py` → `CLASSIFICATION_SCHEMA`

4. **Python filter**: Keep only `type == "MODULE"` results. Enrich each with level and description. Sort by original document position.

5. **Fallback**: If no MODULE headings found, treat the whole document as a single module named "Application".

**Output added to state:** `modules: list[dict]` — each dict has `name`, `heading`, `level`, `description`.

---

### Phase 0.5 — `build_slices_node` (fan-out prep)

**Goal:** Slice the document text per module and create `Send` objects for parallel dispatch.

For each module, `_slice_module_text()` extracts the document section from that module's heading up to the next module's heading (or end of document). The heading-to-text locator uses three passes: exact match → case-insensitive → whitespace-collapsed search (handles PDF/docx artifacts).

Each `Send` carries a `ModuleSlice` TypedDict: `{ index, module_name, module_text, mode }`.

**The `mode` from the API request is propagated here to every module slice.** This is the mechanism by which `frontend`, `backend`, or `both` controls all downstream LLM calls.

---

### Phase 1 — `extract_module_node` (parallel, one per module)

**File:** `src/msbc/orchestration/nodes/node_definitions.py`

Each invocation is throttled by `_get_module_semaphore()` (capped at `MODULE_BATCH_SIZE`, default 3). The actual logic runs in `_extract_module_body()`.

#### 4a. Token budget and chunking

The prompt overhead (system + fixed user template rendered with empty `module_text`) is counted with `count_tokens()` (tiktoken). The remaining budget is:

```
token_budget = max(TOTAL_INPUT_TOKEN_LIMIT - actual_overhead, 1000)
```

If `module_text` fits within `token_budget`, it is processed as a single chunk. If it exceeds the budget, `_split_module_into_chunks()` splits it at:
1. Markdown heading boundaries
2. Numbered-section boundaries (e.g. `8.1 Sub-section`)
3. Blank-line paragraph boundaries (fallback)

Chunks are capped at 10 (`max_chunks`). Tiny trailing chunks (< 300 tokens) are merged into the previous chunk. Each chunk is prefixed with `[Part N/Total of module 'X']` so the LLM knows it sees a partial view.

#### 4b. LLM calls — mode-specific behaviour

**Summary extraction** runs on the first chunk only, regardless of mode:
- Prompt: `src/msbc/llm/prompts/templates/requirement_extractor/summary_extraction.yaml`
- Schema: `src/msbc/agents/schemas/requirement_extractor/summary.py` → `SUMMARY_SCHEMA`
- Output: `{ module_summary: { name, purpose, key_entities, key_flows, dependencies, shared_enums, cross_module_validations } }`
- Used exclusively by the graph-builder in Phase 2 — never returned to the end user directly.

---

#### mode = `"frontend"`

- **LLM calls per chunk:** 1 (frontend extraction + summary in parallel via `asyncio.gather`)
- **Prompt:** `src/msbc/llm/prompts/templates/requirement_extractor/frontend_extraction.yaml`
- **Schema:** `src/msbc/agents/schemas/requirement_extractor/frontend.py` → `FRONTEND_SCHEMA`
- **Normalizer applied before validation:** `_normalize_extraction()` — unwraps components in UPPERCASE named-key format that the LLM sometimes emits, and strips enums with empty `values` arrays.
- **Output shape per module:**
  ```json
  {
    "module": {
      "name": "...",
      "description": "...",
      "screens": [
        {
          "name": "...",
          "screen_type": "dashboard | form",
          "opens_as": "page | modal | drawer | popup",
          "purpose": "...",
          "components": [...],
          "field_groups": [...],
          "actions": [...],
          "validations": [...],
          "behaviors": [...]
        }
      ],
      "enums": [{ "name": "...", "values": [...] }],
      "business_rules": ["..."],
      "workflows": [{ "name": "...", "steps": [...], "screens_involved": [...] }]
    }
  }
  ```

---

#### mode = `"backend"`

- **LLM calls per chunk:** 1 (backend extraction + summary in parallel via `asyncio.gather`)
- **Prompt:** `src/msbc/llm/prompts/templates/requirement_extractor/backend_extraction.yaml`
- **Schema:** `src/msbc/agents/schemas/requirement_extractor/backend.py` → `BACKEND_SCHEMA`
- **Endpoint retry guard:** After extraction, if `models` is non-empty but `api_endpoints` is empty (LLM truncation), a targeted retry is fired with an explicit warning appended to the user prompt.
- **Output shape per module:**
  ```json
  {
    "module": {
      "name": "...",
      "description": "...",
      "api_endpoints": [
        {
          "path": "...",
          "method": "GET | POST | PUT | PATCH | DELETE",
          "summary": "...",
          "request_params": { "path": [...], "query": [...], "body": [...] },
          "response_body": { "success_status": 200, "shape": "...", "fields": [...] },
          "authentication": "...",
          "authorization": "...",
          "validations": ["..."],
          "error_responses": [{ "status": 400, "condition": "..." }]
        }
      ],
      "models": [
        {
          "name": "...",
          "fields": [{ "name": "...", "type": "...", "required": true }],
          "relationships": [{ "type": "...", "target": "..." }]
        }
      ],
      "business_logic": [{ "rule": "...", "trigger": "...", "action": "..." }],
      "workflows": [{ "name": "...", "steps": [...] }]
    }
  }
  ```

---

#### mode = `"both"`

- **LLM calls per chunk:** 2 (frontend + backend — fired in two sequential phases to halve peak concurrency)

  **Phase A** (all FE extractions across all chunks + summary, in parallel):
  - Uses `frontend_extraction.yaml` + `FRONTEND_SCHEMA`
  - Normalizer applied: `_normalize_extraction()`

  **Phase B** (all BE extractions across all chunks, in parallel, with remaining timeout budget):
  - Uses `backend_extraction.yaml` + `BACKEND_SCHEMA`
  - Endpoint retry guard applied after merge (same as `backend` mode)

- After Phase A and Phase B, results are stitched per-chunk into the unified `both` structure.
- **Output shape per module:**
  ```json
  {
    "module": {
      "name": "...",
      "description": "...",
      "frontend": {
        "screens": [...],
        "enums": [...],
        "business_rules": [...],
        "workflows": [...]
      },
      "backend": {
        "api_endpoints": [...],
        "models": [...],
        "business_logic": [...],
        "workflows": [...]
      }
    }
  }
  ```

---

#### Multi-chunk merge (`_merge_chunk_extractions`)

When a module is split into N chunks, the N extraction dicts are merged:

| Field | Deduplication key |
|---|---|
| `screens` | `name` |
| `enums` | `name` |
| `models` | `name` |
| `api_endpoints` | `(method.upper(), path)` |
| `business_rules` / `business_logic` / `workflows` | exact string / first string value in dict |

For `both` mode the merge keeps `frontend.*` and `backend.*` sub-trees separate throughout.

---

#### Cross-validation (`_cross_validate_module`)

For `frontend` and `both` modes, after extraction any `opens_screen` references inside toolbar actions and grid row actions are checked against the set of screen names extracted from the same module. Mismatches are logged as warnings (not errors).

---

### Phase 2 — `finalize_node`

**Goal:** Assemble all module results and build the dependency graph.

**Step 1 — Pure-Python merge** (`_python_merge_results`):
- Results are sorted by their original segmentation order (using `order_map`).
- Produces the final `ExtractionOutput` dict:
  ```json
  {
    "mode": "frontend | backend | both",
    "total_modules": N,
    "modules": [
      { "name": "...", "order": 1, ...extraction fields... }
    ]
  }
  ```
- No LLM call — instant.

**Step 2 — Graph builder LLM call**:
- Input: only the `module_summary` objects from each module (small context, no full extractions).
- Valid node IDs are derived as `snake_case` of each module name and passed explicitly to the LLM so it cannot invent phantom nodes.
- Prompt: `src/msbc/llm/prompts/templates/requirement_extractor/graph_builder.yaml`
- Schema: `src/msbc/agents/schemas/requirement_extractor/graph_output.py` → `GRAPH_OUTPUT_SCHEMA`
- Post-processing: phantom nodes (IDs not in the extracted set) are filtered out; any extracted module missing from the LLM's node list is added back; edges whose endpoints are not valid IDs are dropped; `entry_points` are recomputed.
- **Graph output shape:**
  ```json
  {
    "graph": {
      "nodes": [{ "id": "...", "label": "...", "type": "feature|auth|data|...", "description": "...", "external_dependencies": [...] }],
      "edges": [{ "from": "...", "to": "...", "relation": "depends_on|calls|triggers|...", "data_shared": [...] }],
      "entry_points": ["module_id_1"],
      "metadata": { "total_modules": N, "mode": "...", "total_edges": M }
    }
  }
  ```

---

## 5. LLM Client

**File:** `src/msbc/llm/clients/openai_client.py`

Function: `call_llm_with_schema(system_prompt, user_prompt, schema, schema_name, normalizer=None)`

Implements **3-layer JSON validation**:
1. `response_format={"type": "json_object"}` — forces JSON mode on supported models
2. Schema embedded in the user prompt — LLM sees the shape it must follow
3. `jsonschema.Draft202012Validator` — validates the parsed JSON against the schema

On schema validation failure: retries up to `SCHEMA_VALIDATION_RETRIES` (2) times.
On transient API errors (HTTP 429, 500–504): retries up to `API_RETRY_ATTEMPTS` (3) with exponential backoff.

A global `asyncio.Semaphore` (size `LLM_MAX_CONCURRENCY = 15`) gates all simultaneous OpenAI calls.

---

## 6. JSON Schemas

All schemas are in `src/msbc/agents/schemas/requirement_extractor/`.

| File | Schema constant | Used by |
|---|---|---|
| `segmentation.py` | `CLASSIFICATION_SCHEMA` | `segmentation_node` |
| `frontend.py` | `FRONTEND_SCHEMA` | `extract_module_node` (frontend + both Phase A) |
| `backend.py` | `BACKEND_SCHEMA` | `extract_module_node` (backend + both Phase B) |
| `combined.py` | `COMBINED_SCHEMA` | Not used directly — imports from frontend.py + backend.py |
| `summary.py` | `SUMMARY_SCHEMA` | `extract_module_node` (all modes, first chunk only) |
| `graph_output.py` | `GRAPH_OUTPUT_SCHEMA` | `finalize_node` graph builder call |

The `__init__.py` in this package re-exports all constants so node_definitions.py imports them from one place.

---

## 7. Prompt YAML Files

All prompts are in `src/msbc/llm/prompts/templates/requirement_extractor/`.

| File | Used in phase | Purpose |
|---|---|---|
| `segmentation.yaml` | Phase 0 | Heading classification — MODULE vs IGNORE |
| `base_rules.yaml` | Phase 1 (all modes) | Shared extraction rules injected into every extraction prompt via `{base_rules}` |
| `frontend_extraction.yaml` | Phase 1 (frontend, both Phase A) | Screen/component/field/workflow extraction |
| `backend_extraction.yaml` | Phase 1 (backend, both Phase B) | Endpoint/model/business-logic extraction |
| `both_extraction.yaml` | Reference only | Not used directly — both mode fires fe + be prompts separately |
| `summary_extraction.yaml` | Phase 1 (all modes, first chunk) | Inter-module dependency summary |
| `graph_builder.yaml` | Phase 2 | Dependency graph from summaries |

**Prompt loader:** `src/msbc/llm/prompts/loader.py`
- Loads YAML files as `{ system, user_template }` dicts.
- Template substitution uses `_fmt()` (plain `str.replace()`), never Python's `.format()`, so JSON example braces inside prompts are never misinterpreted.

---

## 8. Output Pydantic Schemas

**File:** `src/msbc/models/schemas/requirement.py`

Defines the typed Pydantic response models returned by the API. Structure:

```
ParseResponse
├── extraction : ExtractionResult  (discriminated union on "mode")
│   ├── FrontendExtractionResult   mode="frontend"
│   │   └── modules: list[FrontendModuleItem]
│   │       ├── screens: list[FrontendScreen]  → components, field_groups, actions, behaviors
│   │       ├── enums, business_rules, workflows
│   ├── BackendExtractionResult    mode="backend"
│   │   └── modules: list[BackendModuleItem]
│   │       ├── api_endpoints, models, business_logic, workflows
│   └── BothExtractionResult       mode="both"
│       └── modules: list[BothModuleItem]
│           ├── frontend: BothFrontendSection
│           └── backend: BothBackendSection
├── graph : DependencyGraph
│   ├── nodes, edges, entry_points, metadata
└── usage : LLMUsage
```

---

## 9. Database

**Entities:** `src/msbc/models/entities/base.py` — `Job`, `RequirementExtraction`

**Repositories:**
- `src/msbc/database/repositories/job_repository.py` — `JobRepository`: `create_job()`, `mark_processing()`, `mark_completed()`, `mark_failed()`
- `src/msbc/database/repositories/requirement_repository.py` — `RequirementRepository`

**Session:** `src/msbc/database/session.py` → `get_db()` (FastAPI dependency)

---

## 10. Complete File Map

```
src/msbc/
├── config.py                                    ← token limits, timeouts, valid modes, pricing
│
├── orchestration/
│   ├── graph.py                                 ← _build_graph(), run_extraction() entry point
│   ├── state.py                                 ← ExtractionState, ModuleSlice, ModuleResult
│   └── nodes/
│       ├── edge_logic.py                        ← fan_out_to_modules()
│       └── node_definitions.py                  ← ALL node logic: segmentation, extract, finalize
│
├── llm/
│   ├── clients/
│   │   └── openai_client.py                     ← call_llm_with_schema(), count_tokens()
│   └── prompts/
│       ├── loader.py                            ← _load_prompt(), _fmt()
│       └── templates/requirement_extractor/
│           ├── base_rules.yaml                  ← shared extraction rules
│           ├── segmentation.yaml                ← Phase 0 heading classification
│           ├── frontend_extraction.yaml         ← Phase 1 frontend-mode extraction
│           ├── backend_extraction.yaml          ← Phase 1 backend-mode extraction
│           ├── both_extraction.yaml             ← reference only
│           ├── summary_extraction.yaml          ← Phase 1 summary (all modes)
│           └── graph_builder.yaml               ← Phase 2 graph builder
│
├── agents/schemas/requirement_extractor/
│   ├── __init__.py                              ← re-exports all schema constants
│   ├── segmentation.py                          ← CLASSIFICATION_SCHEMA
│   ├── frontend.py                              ← FRONTEND_SCHEMA
│   ├── backend.py                               ← BACKEND_SCHEMA
│   ├── combined.py                              ← COMBINED_SCHEMA (imports fe+be)
│   ├── summary.py                               ← SUMMARY_SCHEMA
│   └── graph_output.py                          ← GRAPH_OUTPUT_SCHEMA
│
├── models/schemas/
│   └── requirement.py                           ← Pydantic response models (ParseResponse etc.)
│
├── models/entities/
│   └── base.py                                  ← SQLAlchemy: Job, RequirementExtraction
│
├── database/
│   ├── session.py                               ← get_db()
│   └── repositories/
│       ├── job_repository.py
│       └── requirement_repository.py
│
├── utils/
│   └── extractors/
│       ├── docx_extractor.py                    ← text + heading hierarchy from .docx
│       └── pdf_extractor.py                     ← text + heading hierarchy from .pdf
│
└── api/v1/endpoints/
    └── requirements.py                          ← FastAPI router, background task, _bg_session()
```

---

## 11. Key Invariants (Never Violate)

| # | Rule |
|---|---|
| 1 | **Flat LangGraph only** — no nested subgraphs, ever |
| 2 | **`results` uses `Annotated[list, operator.add]`** — parallel fan-in reducer |
| 3 | **Graph builder receives SUMMARIES ONLY** — never full extraction JSON |
| 4 | **3-layer JSON validation** — json_object mode + schema in prompt + Draft202012Validator |
| 5 | **All prompts in YAML** — never inline strings in Python |
| 6 | **tiktoken for token counting** — truncate before every LLM call |
| 7 | **`_fmt()` for template substitution** — never `.format()` on prompt strings |
| 8 | **`call_llm_with_schema()` only** — never call OpenAI SDK directly |
| 9 | **`both` mode fires FE and BE as separate prompts** — `both_extraction.yaml` is not used as a combined prompt |
| 10 | **Summary runs on first chunk only** — not on every chunk of a multi-chunk module |
