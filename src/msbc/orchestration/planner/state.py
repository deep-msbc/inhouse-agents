"""
LangGraph state definitions for the Frontend Planner workflow.

FrontendPlannerState is the shared state dict that flows through every node.
plan_results uses Annotated[list, operator.add] so parallel plan_module_node
invocations each append their result without overwriting one another.
"""

import operator
from typing import Annotated, Any, TypedDict


class ModulePlanSlice(TypedDict):
    """
    Input packet sent to plan_module_node via Send fan-out.

    One slice = one module = one focused LLM call.
    """
    index:        int             # position in the modules list (for logging)
    module_dict:  dict            # one element from extracted_requirements["modules"]
    dep_priority: int             # build priority from the dependency graph (1 = first)
    shared_enums: dict            # global enums from the extraction (may be empty)
    shared_rules: list[str]       # global business rules from the extraction (may be empty)


class ModulePlanResult(TypedDict):
    """Output of one plan_module_node execution."""
    module_plan: dict[str, Any]   # one validated ModulePlan dict (LLM output[0])
    usage:       dict[str, Any]   # LLM token/cost usage for this call


class FrontendPlannerState(TypedDict):
    # ── Inputs (set by run_frontend_planning before ainvoke) ─────────────────
    extraction_id:           str
    extracted_requirements:  dict[str, Any]   # full JSON stored in the DB row
    dependency_graph:        dict[str, Any] | None
    parallel:                bool              # always parallel via Send fan-out

    # ── Parsed by prepare_node ────────────────────────────────────────────────
    modules:          list[dict[str, Any]]     # flat list of module dicts from extraction
    shared_enums:     dict[str, Any]           # global_enums (may be {})
    shared_rules:     list[str]                # global_business_rules (may be [])
    dep_priority_map: dict[str, int]           # {module_name → priority}

    # ── Per-module results (parallel fan-in via reducer) ──────────────────────
    plan_results: Annotated[list[ModulePlanResult], operator.add]

    # ── Set by finalize_plan_node ─────────────────────────────────────────────
    final_plan: list[dict[str, Any]]          # sorted array of ModulePlan dicts
    all_usage:  list[dict[str, Any]]          # one usage dict per plan_module_node call
