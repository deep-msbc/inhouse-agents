"""
Node implementations for the Frontend Planner LangGraph workflow.

Phases:
  1  — prepare_node        : pure-Python — parse extraction, build dep_priority_map
  2  — plan_module_node    : one focused LLM call per module (parallel via Send)
  3  — finalize_plan_node  : pure-Python — collect, sort by priority, merge usage
"""

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from src.msbc.agents.frontend_planner.toolkit_knowledge import build_toolkit_context
from src.msbc.agents.frontend_planner.toon_serializer import toon_single_module
from src.msbc.agents.schemas.frontend_planner import PLANNER_OUTPUT_SCHEMA
from src.msbc.llm.clients.openai_client import call_llm_with_schema, merge_usage
from src.msbc.orchestration.planner.state import (
    FrontendPlannerState,
    ModulePlanResult,
    ModulePlanSlice,
)

logger = logging.getLogger(__name__)

# ── Prompt loader (mirrors node_definitions.py) ───────────────────────────────

_PROMPTS_DIR = (
    Path(__file__).parent.parent.parent   # src/msbc/
    / "llm" / "prompts" / "templates" / "frontend_planner"
)


def _load_prompt(name: str) -> dict[str, str]:
    """Load a YAML prompt file and return {'system': ..., 'user_template': ...}."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fmt(template: str, **kwargs: str) -> str:
    """
    Safe prompt template substitution — uses str.replace so JSON examples
    inside the YAML (e.g. {key}) are never treated as Python format placeholders.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", value)
    return result


# ── Pre-built, shared system prompt (toolkit_context injected once) ───────────
# Built at import time — no I/O per call.
_TOOLKIT_CONTEXT: str = build_toolkit_context()


# ── Output normalizer ─────────────────────────────────────────────────────────

def _coerce_str_or_null(val: Any) -> Any:
    """
    Coerce a value that should be string-or-null.
    - None / False / "" → None
    - dict / list       → JSON string
    - anything else     → str(val)
    """
    if val is None or val is False or val == "":
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return str(val).lower() if isinstance(val, bool) else str(val)


def _coerce_str_or_null_keep_true(val: Any) -> Any:
    """Like _coerce_str_or_null but True → 'true' (not None)."""
    if val is None or val is False or val == "":
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return str(val).lower() if isinstance(val, bool) else str(val)


def _coerce_options(options: Any) -> list[str]:
    """Ensure every element of an options list is a string."""
    if not isinstance(options, list):
        return []
    return [str(o) if not isinstance(o, str) else o for o in options]


def _coerce_component(comp: dict) -> dict:
    """
    Coerce common LLM type mistakes inside one component dict.

    Handles:
      fields[].default_value   — boolean/number → string, False/None → null
      fields[].visible_when    — False/bool → null
      fields[].required_when   — False/bool → null
      fields[].disabled_when   — False/bool → null
      fields[].options         — non-string items → string
      filters[].default_value  — same as fields
      filters[].options        — non-string items → string
      columns[].color_logic    — dict/bool → JSON string or null
    """
    for field in comp.get("fields", []):
        field["default_value"] = _coerce_str_or_null(field.get("default_value"))
        field["visible_when"]  = _coerce_str_or_null(field.get("visible_when"))
        field["required_when"] = _coerce_str_or_null(field.get("required_when"))
        field["disabled_when"] = _coerce_str_or_null(field.get("disabled_when"))
        if "options" in field:
            field["options"] = _coerce_options(field["options"])

    for filt in comp.get("filters", []):
        filt["default_value"] = _coerce_str_or_null(filt.get("default_value"))
        if "options" in filt:
            filt["options"] = _coerce_options(filt["options"])

    for col in comp.get("columns", []):
        cl = col.get("color_logic")
        if cl is not None and not isinstance(cl, str):
            col["color_logic"] = (
                json.dumps(cl) if isinstance(cl, (dict, list))
                else (None if cl is False else str(cl))
            )
    return comp


def _coerce_module_plan(module: dict) -> dict:
    """
    Coerce common LLM type mistakes at every level of a module plan dict.

    Also fixes the 'module_name' missing issue: if the LLM drops module_name
    on a retry but keeps 'name', copy it over.
    """
    # Guard: ensure module_name is present.
    # LLM may use any of these keys on first call or when retrying under pressure.
    if not module.get("module_name"):
        for fallback in ("name", "module", "moduleName", "module_title", "title"):
            if module.get(fallback):
                module["module_name"] = module[fallback]
                break

    for screen in module.get("screens", []):
        for comp in screen.get("components", []):
            _coerce_component(comp)

    return module


def _normalise_plan_output(raw: Any) -> list[dict[str, Any]]:
    """
    Coerce LLM output into a list[ModulePlan] shape.

    Handles three response shapes the LLM may return:
      1. Correct: [{...}]                              — JSON array (expected)
      2. Wrapped: {"modules": [{...}]} / {"plan": [...]}
      3. Bare:    {...}                                 — object without array wrapper
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("modules", "plan", "data", "result", "plans"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        # Bare object — wrap it
        return [raw]
    raise RuntimeError(
        f"Unexpected planner LLM output type: {type(raw).__name__}. "
        "Expected a JSON array or object."
    )


def _normalise_and_validate(raw: Any) -> list[dict[str, Any]]:
    """
    Full normalizer passed to call_llm_with_schema.

    Runs BEFORE schema validation on every attempt so that:
      1. Shape is normalised (array / wrapped / bare).
      2. Common LLM type mismatches are coerced (False → null, 0 → "0", dict → JSON string).
      3. module_name is repaired from 'name' if missing.
    This eliminates wasted retries caused by coercible type mismatches.
    """
    plan_list = _normalise_plan_output(raw)
    return [_coerce_module_plan(m) for m in plan_list]


# ── Phase 1: prepare_node ─────────────────────────────────────────────────────

def prepare_node(state: FrontendPlannerState) -> dict[str, Any]:
    """
    Pure-Python node: parse ``extracted_requirements`` and ``dependency_graph``
    to build the per-module inputs needed for the parallel planning fan-out.

    Sets in state:
      modules          — flat list of module dicts
      shared_enums     — global enums dict (empty if not present)
      shared_rules     — global business rules list (empty if not present)
      dep_priority_map — {module_name: priority_int}
    """
    extraction: dict[str, Any] = state["extracted_requirements"]
    dep_graph:  dict[str, Any] | None = state.get("dependency_graph")

    # ── Extract modules ───────────────────────────────────────────────────────
    # Both FrontendExtractionResult and BothExtractionResult have top-level "modules"
    modules: list[dict[str, Any]] = extraction.get("modules", [])
    if not modules:
        logger.warning(
            "prepare_node: 'modules' is empty in extracted_requirements "
            "(extraction_id=%s). Nothing to plan.",
            state.get("extraction_id", "?"),
        )

    # ── Shared context (may be absent) ────────────────────────────────────────
    shared_enums: dict[str, Any] = extraction.get("global_enums", {})
    shared_rules: list[str] = extraction.get("global_business_rules", [])

    # ── Dependency priority map ───────────────────────────────────────────────
    dep_priority_map: dict[str, int] = {}
    if dep_graph:
        for node in dep_graph.get("nodes", []):
            name = node.get("name", "")
            priority = node.get("priority") or node.get("order") or 1
            if name:
                dep_priority_map[name] = int(priority)

    # Default priority: positional index if not in dep_graph
    for idx, module in enumerate(modules):
        name = module.get("name", "")
        if name and name not in dep_priority_map:
            dep_priority_map[name] = idx + 1

    logger.info(
        "prepare_node: %d module(s) ready for planning (extraction_id=%s).",
        len(modules), state.get("extraction_id", "?"),
    )

    return {
        "modules":          modules,
        "shared_enums":     shared_enums,
        "shared_rules":     shared_rules,
        "dep_priority_map": dep_priority_map,
        "plan_results":     [],
        "all_usage":        [],
    }


# ── Phase 2: plan_module_node (parallel via Send fan-out) ─────────────────────

async def plan_module_node(slice_input: ModulePlanSlice) -> dict[str, Any]:
    """
    Plan ONE frontend module with a focused LLM call.

    Invoked N times in parallel by the Send fan-out from fan_out_to_plan_modules.
    Each call appends one ModulePlanResult to state["plan_results"] via the reducer.

    The LLM returns a JSON array with exactly one ModulePlan element.
    """
    module_dict:  dict       = slice_input["module_dict"]
    dep_priority: int        = slice_input["dep_priority"]
    shared_enums: dict       = slice_input["shared_enums"]
    shared_rules: list[str]  = slice_input["shared_rules"]
    index:        int        = slice_input["index"]
    module_name:  str        = module_dict.get("name", f"module_{index}")

    logger.info("plan_module_node: planning '%s' (priority=%d).", module_name, dep_priority)

    # ── Build TOON input for this module ──────────────────────────────────────
    toon_input: str = toon_single_module(
        module_dict,
        dep_priority=dep_priority,
        shared_enums=shared_enums if shared_enums else None,
        shared_rules=shared_rules if shared_rules else None,
    )

    # ── Load prompt and inject toolkit context ────────────────────────────────
    prompt_data = _load_prompt("plan_module")
    system_prompt: str = _fmt(
        prompt_data["system"],
        toolkit_context=_TOOLKIT_CONTEXT,
    )
    user_prompt: str = _fmt(
        prompt_data["user_template"],
        toon_input=toon_input,
    )

    # ── Call LLM with schema validation + retry ───────────────────────────────
    # PLANNER_OUTPUT_SCHEMA has "type": "array" at root.
    # call_llm_with_schema validates the raw parsed value (list) against the
    # array schema via jsonschema — this works at runtime despite the dict
    # type annotation.
    result, usages = await call_llm_with_schema(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=PLANNER_OUTPUT_SCHEMA,
        schema_name=f"plan:{module_name}",
        normalizer=_normalise_and_validate,  # coerces array/object/bare shapes
    )

    # result is a list (the normaliser returned list); take the first element
    plan_list: list[dict[str, Any]] = result if isinstance(result, list) else [result]
    module_plan: dict[str, Any] = plan_list[0] if plan_list else {}

    # Ensure priority is stamped (LLM may omit it)
    if "priority" not in module_plan or not module_plan.get("priority"):
        module_plan["priority"] = dep_priority

    logger.info(
        "plan_module_node: '%s' done — %d screen(s), %d file(s).",
        module_name,
        len(module_plan.get("screens", [])),
        len(module_plan.get("file_structure", [])),
    )

    plan_result: ModulePlanResult = {
        "module_plan": module_plan,
        "usage":       merge_usage(usages) if usages else {},
    }
    return {"plan_results": [plan_result]}


# ── Phase 3: finalize_plan_node ───────────────────────────────────────────────

def finalize_plan_node(state: FrontendPlannerState) -> dict[str, Any]:
    """
    Pure-Python node: collect all plan_results, sort by module priority,
    and aggregate LLM usage across all parallel calls.
    """
    plan_results: list[ModulePlanResult] = state.get("plan_results", [])

    # Sort modules by their planned priority (ascending — 1 = build first)
    sorted_plans: list[dict[str, Any]] = sorted(
        [r["module_plan"] for r in plan_results],
        key=lambda m: (m.get("priority") or 999, m.get("module_name", "")),
    )

    # Collect one usage dict per parallel call
    all_usage: list[dict[str, Any]] = [
        r["usage"] for r in plan_results if r.get("usage")
    ]

    total_modules = len(sorted_plans)
    total_screens = sum(len(m.get("screens", [])) for m in sorted_plans)
    total_files   = sum(len(m.get("file_structure", [])) for m in sorted_plans)
    logger.info(
        "finalize_plan_node: %d module(s), %d screen(s), %d file(s) planned.",
        total_modules, total_screens, total_files,
    )

    return {
        "final_plan": sorted_plans,
        "all_usage":  all_usage,
    }


# ── Edge function: fan-out prepare → plan_module_node × N ─────────────────────

def fan_out_to_plan_modules(state: FrontendPlannerState) -> list[Any]:
    """
    Conditional-edge function called after prepare_node.

    Returns a list of Send objects (one per module) so LangGraph invokes
    plan_module_node in parallel for each module.
    """
    from langgraph.types import Send  # local import — avoids circular dependency

    modules:          list[dict[str, Any]] = state.get("modules", [])
    shared_enums:     dict[str, Any]       = state.get("shared_enums", {})
    shared_rules:     list[str]            = state.get("shared_rules", [])
    dep_priority_map: dict[str, int]       = state.get("dep_priority_map", {})

    sends: list[Send] = []
    for idx, module_dict in enumerate(modules):
        module_name  = module_dict.get("name", f"module_{idx}")
        dep_priority = dep_priority_map.get(module_name, idx + 1)

        slice_input: ModulePlanSlice = {
            "index":        idx,
            "module_dict":  module_dict,
            "dep_priority": dep_priority,
            "shared_enums": shared_enums,
            "shared_rules": shared_rules,
        }
        sends.append(Send("plan_module_node", slice_input))

    logger.info("fan_out_to_plan_modules: fanning out %d module(s).", len(sends))
    return sends
