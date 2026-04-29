"""
LangGraph workflow for the Frontend Planner Agent.

Graph topology:

  START
    │
    ▼
  prepare_node
    │  (conditional edge — fan_out_to_plan_modules returns N Send objects)
    ├──► plan_module_node (module 0)  ─┐
    ├──► plan_module_node (module 1)  ─┤  (all run in parallel)
    └──► plan_module_node (module N)  ─┘
                                       │
                                       ▼
                                  finalize_plan_node
                                  (pure-Python sort + usage merge)
                                       │
                                       ▼
                                      END

Entry point: run_frontend_planning(extraction_id, extracted_requirements, dependency_graph, parallel)

The function returns a PlannerOutput Pydantic model.
The caller (API endpoint) is responsible for:
  1. Loading the RequirementExtraction row from DB (to get extracted_requirements + dependency_graph).
  2. Passing them here.
  3. Persisting the returned PlannerOutput via FrontendPlanRepository.save_plan().
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.msbc.llm.clients.openai_client import merge_usage
from src.msbc.models.schemas.frontend_plan import ModulePlan, PlannerLLMUsage, PlannerOutput
from src.msbc.orchestration.planner.nodes import (
    fan_out_to_plan_modules,
    finalize_plan_node,
    plan_module_node,
    prepare_node,
)
from src.msbc.orchestration.planner.state import FrontendPlannerState

logger = logging.getLogger(__name__)


# ── Build and compile the graph once at import time ───────────────────────────

def _build_graph() -> Any:
    builder = StateGraph(FrontendPlannerState)

    # Nodes
    builder.add_node("prepare_node",       prepare_node)
    builder.add_node("plan_module_node",   plan_module_node)
    builder.add_node("finalize_plan_node", finalize_plan_node)

    # Edges
    builder.add_edge(START, "prepare_node")

    # Fan-out: prepare → N × plan_module_node (via Send)
    builder.add_conditional_edges(
        "prepare_node",
        fan_out_to_plan_modules,
        ["plan_module_node"],
    )

    # Fan-in: all plan_module_node results collected before finalize
    builder.add_edge("plan_module_node",   "finalize_plan_node")
    builder.add_edge("finalize_plan_node", END)

    return builder.compile()


_workflow = _build_graph()


# ── Public entry point ────────────────────────────────────────────────────────

async def run_frontend_planning(
    extraction_id: str,
    extracted_requirements: dict[str, Any],
    dependency_graph: dict[str, Any] | None = None,
    parallel: bool = True,
) -> PlannerOutput:
    """
    Run the full frontend planning workflow for a given extraction.

    Parameters
    ----------
    extraction_id:
        UUID of the source ``RequirementExtraction`` row.  Stored in state
        for logging; not used for any DB query here.
    extracted_requirements:
        The ``extracted_requirements`` JSON from the DB row.
        Must have ``"modules"`` at the top level (FrontendExtractionResult or
        BothExtractionResult shape).
    dependency_graph:
        The ``dependency_graph`` JSON from the DB row (may be None).
        Used to assign build-order priorities to modules.
    parallel:
        Stored in state for future use.  The graph always uses the Send
        fan-out pattern (LangGraph manages concurrency automatically).

    Returns
    -------
    PlannerOutput
        Validated Pydantic model containing:
          - modules: list[ModulePlan] — one per input module, sorted by priority
          - usage:   PlannerLLMUsage — aggregated token/cost across all calls
    """
    logger.info(
        "run_frontend_planning: start — extraction_id=%s, modules=%d.",
        extraction_id,
        len(extracted_requirements.get("modules", [])),
    )

    initial_state: FrontendPlannerState = {
        "extraction_id":          extraction_id,
        "extracted_requirements": extracted_requirements,
        "dependency_graph":       dependency_graph,
        "parallel":               parallel,
        # Populated by prepare_node
        "modules":          [],
        "shared_enums":     {},
        "shared_rules":     [],
        "dep_priority_map": {},
        # Populated by plan_module_node (reducer)
        "plan_results": [],
        # Populated by finalize_plan_node
        "final_plan": [],
        "all_usage":  [],
    }

    final_state: FrontendPlannerState = await _workflow.ainvoke(initial_state)

    # ── Aggregate usage ───────────────────────────────────────────────────────
    all_usage: list[dict[str, Any]] = final_state.get("all_usage", [])
    usage_summary = merge_usage(all_usage) if all_usage else {}
    llm_usage = PlannerLLMUsage(**usage_summary) if usage_summary else PlannerLLMUsage()

    # ── Validate final plan via Pydantic ──────────────────────────────────────
    raw_modules: list[dict[str, Any]] = final_state.get("final_plan", [])
    validated_modules: list[ModulePlan] = []
    for raw in raw_modules:
        try:
            validated_modules.append(ModulePlan.model_validate(raw))
        except Exception as exc:
            module_name = raw.get("module_name", "<unknown>")
            logger.warning(
                "run_frontend_planning: Pydantic validation warning for module '%s': %s. "
                "Keeping raw data with extra='allow'.",
                module_name, exc,
            )
            # ModulePlan uses extra="allow" so partial data is kept
            validated_modules.append(ModulePlan.model_validate(raw, strict=False))

    total_screens = sum(len(m.screens) for m in validated_modules)
    total_files   = sum(len(m.file_structure) for m in validated_modules)
    logger.info(
        "run_frontend_planning: complete — %d module(s), %d screen(s), %d file(s). "
        "Total tokens=%d, cost=$%.4f.",
        len(validated_modules),
        total_screens,
        total_files,
        llm_usage.total_tokens,
        llm_usage.total_cost_usd,
    )

    return PlannerOutput(modules=validated_modules, usage=llm_usage)
