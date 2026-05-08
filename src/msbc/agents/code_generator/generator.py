"""
agents/code_generator/generator.py
────────────────────────────────────
Phase 3 — Generation Graph.

Flat LangGraph that generates frontend files in dependency order.

Graph topology:
  START → init_module → retrieve_screen → generate_file → advance_file → END

Entry point: run_code_generation(request, kuzu_store, qdrant_store)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.msbc.agents.code_generator.retriever import retrieve_for_screen
from src.msbc.agents.code_generator.spec_normalizer import normalize_screen
from src.msbc.agents.code_generator.state import CodeGenState
from src.msbc.llm.clients.openai_client import call_llm_with_schema, count_tokens
from src.msbc.llm.prompts.loader import load_prompt
from src.msbc.models.schemas.code_generator import (
    CodeGeneratorOutput,
    GeneratedFile,
    GenerateRequest,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FILE_TYPE_ORDER: dict[str, int] = {
    "types": 0,
    "config": 1,
    "service": 2,
    "page": 3,
    "form": 4,
    "component": 5,
    "hook": 6,
    "index": 7,
}

# ---------------------------------------------------------------------------
# Token budget constants
# ---------------------------------------------------------------------------
# gpt-4.1 / gpt-4.1-mini context windows are large (128k–1M tokens), so we
# set a generous hard cap that still leaves ~8k tokens for the model's output.
# The code generator NEVER truncates sibling files or screen plans — those are
# the two most critical inputs and cutting them causes the LLM to invent type
# names.  Only the optional reference sections (toolkit examples, external
# example files) are trimmed when a call would exceed the cap.

# Maximum tokens we will send in (system + user) combined.
# Leaves ~8k tokens headroom for the model to write a complete source file.
CODEGEN_MAX_INPUT_TOKENS: int = 120_000

# Priority order for trimming when the prompt exceeds CODEGEN_MAX_INPUT_TOKENS.
# Items at the END of this list are trimmed first (lowest priority).
# sibling_files_text and screen_plan_json are NOT in this list — they are never
# trimmed because they are the source of truth the LLM must not invent around.
_TRIM_PRIORITY: list[str] = [
    "example_files_text",    # trimmed first — nice-to-have patterns
    "toolkit_files_text",    # trimmed second — reference code
    "component_graph_json",  # trimmed third — structural metadata
    "business_rules_text",   # trimmed last among optionals
]

_GENERATE_FILE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["code"],
    "properties": {
        "code": {"type": "string"},
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_output_path(output_dir: str, relative_file_path: str) -> Path:
    root = Path(output_dir).resolve()
    target = (root / relative_file_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(
            f"Unsafe generated path outside output_dir: {relative_file_path}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------
# Context helpers — no arbitrary character truncation
# ---------------------------------------------------------------------------

def _format_file_blocks(files: list[dict]) -> str:
    """Render a list of file dicts as labelled code blocks. No truncation."""
    parts: list[str] = []
    for f in files:
        header = f"// --- {f.get('file_path', 'unknown')} ---\n"
        content = f.get("content", "")
        parts.append(header + content + "\n")
    return "\n".join(parts)


def _trim_optional_sections(
    slots: dict[str, str],
    system_tokens: int,
) -> dict[str, str]:
    """
    If (system_tokens + total user-section tokens) would exceed
    CODEGEN_MAX_INPUT_TOKENS, trim the lowest-priority optional sections
    in _TRIM_PRIORITY order until the prompt fits.

    Sections NOT in _TRIM_PRIORITY (sibling_files_text, screen_plan_json,
    module_file_structure_json) are NEVER trimmed — they are the ground-truth
    context the LLM must see complete to avoid inventing type names.
    """
    total = system_tokens + sum(count_tokens(v) for v in slots.values())
    headroom = CODEGEN_MAX_INPUT_TOKENS - total

    if headroom >= 0:
        return slots  # already fits — nothing to trim

    result = dict(slots)
    for key in _TRIM_PRIORITY:
        if headroom >= 0:
            break
        text = result.get(key, "")
        if not text or text == "(none)":
            continue
        # How many tokens does this section cost?
        section_tokens = count_tokens(text)
        # How many tokens do we need to free up?
        to_free = -headroom
        if section_tokens <= to_free:
            # Drop the entire section
            result[key] = "(none — trimmed to fit token budget)"
            headroom += section_tokens
        else:
            # Trim to just enough chars (rough approximation: 1 token ≈ 4 chars)
            keep_tokens = section_tokens - to_free - 10
            keep_chars = max(200, keep_tokens * 4)
            result[key] = text[:keep_chars] + "\n... [trimmed to fit token budget]"
            headroom += section_tokens - count_tokens(result[key])
        logger.debug(
            "[generator] trimmed '%s' to free %d tokens (headroom now %d)",
            key, to_free, headroom,
        )

    if headroom < 0:
        logger.warning(
            "[generator] prompt still %d tokens over budget after trimming all "
            "optional sections — sending anyway (model context window is large).",
            -headroom,
        )

    return result


# ---------------------------------------------------------------------------
# Example role filtering
# ---------------------------------------------------------------------------

# Maps each file type to the example file roles that are relevant context.
# Roles that don't match are dropped before the budget is consumed, so the
# LLM sees the most targeted examples possible.
# Falls back to the full example set when nothing matches (see _filter_examples_by_role).
_FILE_TYPE_TO_EXAMPLE_ROLES: dict[str, list[str]] = {
    "types":     ["types"],
    "config":    ["config", "dashboard_config", "form_config"],
    "service":   ["service", "hook"],
    "page":      ["page", "page_component", "dashboard_page", "detail_page", "component"],
    "form":      ["form", "form_component", "form_page", "component"],
    "component": ["component", "page", "page_component"],
    "hook":      ["hook", "service"],
}


def _filter_examples_by_role(
    example_files: list[dict],
    file_type: str,
) -> list[dict]:
    """
    Return only the example files whose ``file_role`` matches the roles
    relevant to ``file_type``.

    Falls back to the full list when nothing matches (e.g. an unknown
    file type or an empty example set) so the LLM always gets some
    reference code.
    """
    allowed_roles = _FILE_TYPE_TO_EXAMPLE_ROLES.get(file_type, [])
    if not allowed_roles:
        return example_files
    filtered = [
        f for f in example_files
        if f.get("file_role", "") in allowed_roles
    ]
    return filtered if filtered else example_files


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

async def init_module(state: CodeGenState) -> dict[str, Any]:
    """
    Node 1 — Prepare the module/screen/file work queue.

    Reads plan_modules (list of raw ModulePlan dicts), applies module_filter,
    sorts screens by priority, and sorts files inside each module by
    FILE_TYPE_ORDER.  Resets all cursor indexes to 0.
    """
    modules: list[dict] = state["plan_modules"]
    module_filter = state.get("module_filter")

    if module_filter:
        modules = [m for m in modules if m.get("module_name") == module_filter]
        if not modules:
            logger.warning(
                "[generator] module_filter='%s' matched 0 modules.", module_filter
            )

    # Sort modules by priority (ascending — lower number = build first)
    modules = sorted(modules, key=lambda m: m.get("priority", 1))

    # Sort screens inside each module by priority
    for m in modules:
        m["screens"] = sorted(
            m.get("screens", []), key=lambda s: s.get("priority", 1)
        )
        # Sort file_structure by FILE_TYPE_ORDER
        m["file_structure"] = sorted(
            m.get("file_structure", []),
            key=lambda f: FILE_TYPE_ORDER.get(f.get("type", "component"), 99),
        )

    logger.info(
        "[generator] init_module: %d module(s) queued.", len(modules)
    )

    return {
        "plan_modules": modules,
        "current_module_idx": 0,
        "current_screen_idx": 0,
        "current_file_idx": 0,
        "module_generated_files": {},
        "generated_files": [],
        "all_errors": [],
    }


async def retrieve_screen(
    state: CodeGenState, config: RunnableConfig = None
) -> dict[str, Any]:
    """
    Node 2 — Build ScreenContext for the current screen via Phase 2 retriever.

    Reads the current module and screen from the cursor indexes, calls
    retrieve_for_screen(), and stores the result in current_screen_context.
    """
    modules = state["plan_modules"]
    mod_idx = state["current_module_idx"]
    scr_idx = state["current_screen_idx"]

    current_module = modules[mod_idx]
    screens = current_module.get("screens", [])
    current_screen_raw = screens[scr_idx]

    # Extract business rules from extraction_rules_index keyed by module name
    module_name: str = current_module.get("module_name", "")
    rules_index: dict[str, list[str]] = state.get("extraction_rules_index") or {}
    business_rules: list[str] = rules_index.get(module_name, [])

    # Retrieve kuzu_store and qdrant_store from config (injected by the graph runner)
    cfg = config or {}
    kuzu_store = cfg.get("configurable", {}).get("kuzu_store")
    qdrant_store = cfg.get("configurable", {}).get("qdrant_store")

    # Build a lightweight screen_plan proxy that supports attribute access
    screen_proxy = _DictProxy(current_screen_raw)

    try:
        context = await retrieve_for_screen(
            screen_plan=screen_proxy,
            module_name=module_name,
            business_rules=business_rules,
            kuzu_store=kuzu_store,
            qdrant_store=qdrant_store,
        )
        return {"current_screen_context": context.model_dump()}
    except Exception as exc:
        logger.warning(
            "[generator] retrieve_screen failed for %s/%s: %s",
            module_name,
            current_screen_raw.get("screen_name", "?"),
            exc,
        )
        # Return empty context so generation can still proceed (may produce less accurate code)
        from src.msbc.models.schemas.code_generator import ScreenContext
        fallback = ScreenContext(
            screen_name=current_screen_raw.get("screen_name", "unknown"),
            module_name=module_name,
            toolkit_files=[],
            example_files=[],
            component_graph=[],
            business_rules=business_rules,
            screen_plan=current_screen_raw,
        )
        return {"current_screen_context": fallback.model_dump()}


async def generate_file(
    state: CodeGenState, config: RunnableConfig = None
) -> dict[str, Any]:
    """
    Node 3 — Generate one file using the LLM.

    Builds the prompt from the current FilePlan + ScreenContext, calls
    call_llm_with_schema(), and writes the file to disk.
    """
    modules = state["plan_modules"]
    mod_idx = state["current_module_idx"]
    file_idx = state["current_file_idx"]

    current_module = modules[mod_idx]
    module_name: str = current_module.get("module_name", "")
    file_plans = current_module.get("file_structure", [])
    file_plan = file_plans[file_idx]

    context = state.get("current_screen_context") or {}
    screen_name: str = context.get("screen_name", "")

    file_path: str = file_plan.get("path", "")
    file_type: str = file_plan.get("type", "component")

    # ── Load prompt + resolve per-file-type instructions ──────────────────────

    prompt = load_prompt("code_generator/generate_file.yaml")
    system_text = prompt.system
    file_type_instructions_dict: dict = prompt.get("file_type_instructions") or {}
    file_type_instructions: str = file_type_instructions_dict.get(file_type, "")

    # ── Normalize screen plan (planner vocab → toolkit-accepted vocab) ─────────

    screen_plan_raw: dict = context.get("screen_plan", {})
    screen_plan_normalized: dict = normalize_screen(screen_plan_raw)

    # types and service files need ALL screens as context so they can produce
    # exhaustive type definitions / hook coverage for the whole module.
    # No truncation — these are the ground-truth inputs the LLM must see fully.
    if file_type in ("types", "service"):
        all_screens_normalized = [
            normalize_screen(s) for s in current_module.get("screens", [])
        ]
        screen_plan_json = json.dumps(all_screens_normalized, indent=2)
    else:
        screen_plan_json = json.dumps(screen_plan_normalized, indent=2)

    # ── Module file structure (tells the LLM what files exist to import from) ──
    # No truncation — the LLM needs the full list to know valid import paths.

    file_structure_summary = [
        {
            "path": f.get("path", ""),
            "type": f.get("type", ""),
            "description": f.get("description", ""),
            "belongs_to_screen": f.get("belongs_to_screen", ""),
        }
        for f in current_module.get("file_structure", [])
    ]
    module_file_structure_json = json.dumps(file_structure_summary, indent=2)

    # ── Sibling files (already-generated code in this module) ─────────────────
    # No truncation — the LLM must see the complete types file to avoid
    # inventing type names. This is the single most important context slot.

    module_generated: dict[str, str] = state.get("module_generated_files") or {}
    if module_generated:
        sibling_parts: list[str] = []
        for sib_path, sib_code in module_generated.items():
            sibling_parts.append(f"// --- {sib_path} ---\n{sib_code}\n")
        sibling_files_text = "\n".join(sibling_parts)
    else:
        sibling_files_text = "(none — this is the first file in the module)"

    # ── Component graph ───────────────────────────────────────────────────────

    component_graph_json = json.dumps(context.get("component_graph", []), indent=2)

    # ── Toolkit files + role-filtered example files ───────────────────────────
    # These are optional reference sections; they will be trimmed if the prompt
    # is too long, but the required sections above will never be touched.

    toolkit_files_text = _format_file_blocks(context.get("toolkit_files", []))
    raw_example_files: list[dict] = context.get("example_files", [])
    role_filtered_examples = _filter_examples_by_role(raw_example_files, file_type)
    example_files_text = _format_file_blocks(role_filtered_examples)

    # ── Business rules ────────────────────────────────────────────────────────

    business_rules_list: list[str] = context.get("business_rules", [])
    business_rules_text = (
        "\n".join(f"- {r}" for r in business_rules_list) or "(none)"
    )

    # ── Token-aware trimming of optional sections ─────────────────────────────
    # Build the full slot dict, then trim only the optional sections if needed.

    optional_slots: dict[str, str] = {
        "toolkit_files_text":  toolkit_files_text or "(none)",
        "example_files_text":  example_files_text or "(none)",
        "component_graph_json": component_graph_json,
        "business_rules_text": business_rules_text,
    }
    system_tokens = count_tokens(system_text)
    # Account for the fixed (non-trimmable) slots too
    fixed_tokens = count_tokens(
        file_type_instructions + screen_plan_json + module_file_structure_json
        + sibling_files_text + file_path + file_type + module_name
    )
    trimmed_slots = _trim_optional_sections(optional_slots, system_tokens + fixed_tokens)

    logger.info(
        "[generator] %s/%s — system=%d fixed=%d optional=%d tokens",
        module_name, file_path,
        system_tokens, fixed_tokens,
        sum(count_tokens(v) for v in trimmed_slots.values()),
    )

    # ── Assemble user prompt ──────────────────────────────────────────────────

    user_text = prompt._fmt(
        prompt.user_template,
        file_type_instructions=file_type_instructions,
        file_path=file_path,
        file_type=file_type,
        module_name=module_name,
        module_file_structure_json=module_file_structure_json,
        screen_plan_json=screen_plan_json,
        component_graph_json=trimmed_slots["component_graph_json"],
        sibling_files_text=sibling_files_text,
        toolkit_files_text=trimmed_slots["toolkit_files_text"],
        example_files_text=trimmed_slots["example_files_text"],
        business_rules_text=trimmed_slots["business_rules_text"],
    )

    # ── LLM call ─────────────────────────────────────────────────────────────

    errors: list[str] = []
    content = ""
    prompt_tokens = 0
    completion_tokens = 0

    try:
        result, usages = await call_llm_with_schema(
            system_prompt=system_text,
            user_prompt=user_text,
            schema=_GENERATE_FILE_SCHEMA,
            schema_name="generate_file",
        )
        content = result.get("code", "")
        if usages:
            prompt_tokens = usages[-1].get("input_tokens", 0)
            completion_tokens = usages[-1].get("output_tokens", 0)
    except Exception as exc:
        msg = f"LLM generation failed for {file_path}: {exc}"
        logger.error("[generator] %s", msg)
        errors.append(msg)

    # ── Write file to disk ────────────────────────────────────────────────────

    if content:
        try:
            out_path = _safe_output_path(state["output_dir"], file_path)
            out_path.write_text(content, encoding="utf-8")
            logger.info("[generator] wrote %s", out_path)
        except Exception as exc:
            msg = f"Disk write failed for {file_path}: {exc}"
            logger.error("[generator] %s", msg)
            errors.append(msg)

    # ── Build GeneratedFile record ────────────────────────────────────────────

    generated = GeneratedFile(
        module_name=module_name,
        screen_name=screen_name,
        file_path=file_path,
        file_type=file_type,
        content=content,
        validation_passed=False,
        validation_errors=[],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    return {
        "generated_files": [generated.model_dump()],
        # Merge this file into the per-module sibling cache so subsequent
        # files in the same module can see it as an already-generated sibling.
        "module_generated_files": {file_path: content} if content else {},
        "all_errors": errors,
    }


async def _advance_file_node(state: CodeGenState) -> dict[str, Any]:
    """Thin async wrapper — updates cursor state and stores routing decision."""
    modules = state["plan_modules"]
    mod_idx = state["current_module_idx"]
    scr_idx = state["current_screen_idx"]
    file_idx = state["current_file_idx"]

    current_module = modules[mod_idx]
    screens = current_module.get("screens", [])
    file_plans = current_module.get("file_structure", [])

    current_screen_name = (
        screens[scr_idx].get("screen_name", "") if scr_idx < len(screens) else ""
    )
    screen_files = [
        i for i, f in enumerate(file_plans)
        if f.get("belongs_to_screen", "") == current_screen_name
        or f.get("belongs_to_screen", "") == ""
    ]

    try:
        pos = screen_files.index(file_idx)
    except ValueError:
        pos = len(screen_files) - 1

    updates: dict[str, Any] = {}

    if pos + 1 < len(screen_files):
        updates["current_file_idx"] = screen_files[pos + 1]
        updates["_next_node"] = "generate_file"
    elif scr_idx + 1 < len(screens):
        next_scr_name = screens[scr_idx + 1].get("screen_name", "")
        new_screen_files = [
            i for i, f in enumerate(file_plans)
            if f.get("belongs_to_screen", "") == next_scr_name
            or f.get("belongs_to_screen", "") == ""
        ]
        updates["current_screen_idx"] = scr_idx + 1
        updates["current_file_idx"] = new_screen_files[0] if new_screen_files else 0
        updates["_next_node"] = "retrieve_screen"
    elif mod_idx + 1 < len(modules):
        updates["current_module_idx"] = mod_idx + 1
        updates["current_screen_idx"] = 0
        updates["current_file_idx"] = 0
        # Clear the sibling cache — new module, fresh slate.
        updates["module_generated_files"] = {}
        # Route directly to retrieve_screen for the first screen of the next
        # module.  Routing back to init_module would reset current_module_idx
        # to 0 and loop over the first module forever.
        updates["_next_node"] = "retrieve_screen"
    else:
        updates["_next_node"] = "__end__"

    return updates


def _route_after_advance(state: CodeGenState) -> str:
    return state.get("_next_node", "__end__")


# ---------------------------------------------------------------------------
# Attribute-access proxy (wraps raw screen dict for retriever compatibility)
# ---------------------------------------------------------------------------

class _DictProxy:
    """Wraps a plain dict so attribute access works (for retriever functions)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, item: str) -> Any:
        try:
            return self._data[item]
        except KeyError:
            return None

    def model_dump(self) -> dict[str, Any]:
        return self._data


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    builder = StateGraph(CodeGenState)

    builder.add_node("init_module", init_module)
    builder.add_node("retrieve_screen", retrieve_screen)
    builder.add_node("generate_file", generate_file)
    builder.add_node("advance_file", _advance_file_node)

    builder.add_edge(START, "init_module")
    builder.add_edge("init_module", "retrieve_screen")
    builder.add_edge("retrieve_screen", "generate_file")
    builder.add_edge("generate_file", "advance_file")

    builder.add_conditional_edges(
        "advance_file",
        _route_after_advance,
        {
            "generate_file": "generate_file",
            "retrieve_screen": "retrieve_screen",
            "__end__": END,
        },
    )

    return builder.compile()


_workflow = _build_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_code_generation(
    request: GenerateRequest,
    plan_modules: list[dict],
    extraction_rules_index: dict[str, list[str]],
    kuzu_store: Any,
    qdrant_store: Any,
) -> CodeGeneratorOutput:
    """
    Run the full code generation graph for a frontend plan.

    Parameters
    ----------
    request
        GenerateRequest containing frontend_plan_id, extraction_id, output_dir,
        and optional module_filter.
    plan_modules
        List of raw ModulePlan dicts from the FrontendPlan DB row.
    extraction_rules_index
        Dict mapping module_name → list of business rule strings from
        ExtractionOutput.
    kuzu_store
        KuzuStore instance (passed through to retrieve_screen node).
    qdrant_store
        QdrantStore instance (passed through to retrieve_screen node).

    Returns
    -------
    CodeGeneratorOutput
    """
    logger.info(
        "[generator] run_code_generation start — plan_id=%s, modules=%d.",
        request.frontend_plan_id,
        len(plan_modules),
    )

    initial_state: CodeGenState = {
        "frontend_plan_id": request.frontend_plan_id,
        "extraction_id": request.extraction_id,
        "output_dir": request.output_dir,
        "module_filter": request.module_filter,
        "plan_modules": plan_modules,
        "extraction_rules_index": extraction_rules_index,
        "current_module_idx": 0,
        "current_screen_idx": 0,
        "current_file_idx": 0,
        "_next_node": "",
        "current_screen_context": {},
        "module_generated_files": {},
        "generated_files": [],
        "all_errors": [],
    }

    config = {
        "configurable": {
            "kuzu_store": kuzu_store,
            "qdrant_store": qdrant_store,
        }
    }

    final_state: CodeGenState = await _workflow.ainvoke(initial_state, config=config)

    generated = [
        GeneratedFile.model_validate(f)
        for f in final_state.get("generated_files", [])
    ]
    errors: list[str] = final_state.get("all_errors", [])

    passed = sum(1 for f in generated if f.validation_passed)
    validation_summary = {
        "total": len(generated),
        "passed": passed,
        "failed": len(generated) - passed,
    }

    success = len(errors) == 0 and len(generated) > 0

    logger.info(
        "[generator] run_code_generation complete — files=%d, errors=%d.",
        len(generated),
        len(errors),
    )

    return CodeGeneratorOutput(
        frontend_plan_id=request.frontend_plan_id,
        output_dir=request.output_dir,
        generated_files=generated,
        validation_summary=validation_summary,
        success=success,
        errors=errors,
    )
