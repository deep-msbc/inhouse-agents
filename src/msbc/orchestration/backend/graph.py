"""
LangGraph workflow for the Backend Code Generation Agent.

Graph topology:

  START
    │
    ▼
  prepare_backend_node
    │
    ▼
  backend_planner_node
    │
    ▼
  cli_strategy_node
    │
    ▼
  cli_invoker_node
    │
    ▼
  scaffold_validator_node
    │  (conditional edge — scaffold_valid=False → END, True → fan-out via Send)
    ├──► codegen_app_node (app 0) ─┐
    ├──► codegen_app_node (app 1) ─┤  (parallel)
    └──► codegen_app_node (app N) ─┘
                                   │
                                   ▼
                            collect_apps_node
                                   │
                                   ▼
                           project_settings_node
                                   │
                                   ▼
                          final_syntax_gate_node
                                   │
                                   ▼
                           assemble_output_node
                                   │
                                   ▼
                                  END

Entry point: run_backend_codegen(extraction_id, extracted_requirements, output_path, dependency_graph)
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.msbc.orchestration.backend.nodes import (
    _route_scaffold_to_codegen,
    assemble_output_node,
    backend_planner_node,
    cli_invoker_node,
    cli_strategy_node,
    codegen_app_node,
    collect_apps_node,
    final_syntax_gate_node,
    prepare_backend_node,
    project_settings_node,
    scaffold_validator_node,
)
from src.msbc.orchestration.backend.state import BackendCodegenState

logger = logging.getLogger(__name__)


def _build_graph() -> Any:
    builder = StateGraph(BackendCodegenState)

    builder.add_node("prepare_backend_node",    prepare_backend_node)
    builder.add_node("backend_planner_node",    backend_planner_node)
    builder.add_node("cli_strategy_node",       cli_strategy_node)
    builder.add_node("cli_invoker_node",        cli_invoker_node)
    builder.add_node("scaffold_validator_node", scaffold_validator_node)
    builder.add_node("codegen_app_node",        codegen_app_node)
    builder.add_node("collect_apps_node",       collect_apps_node)
    builder.add_node("project_settings_node",   project_settings_node)
    builder.add_node("final_syntax_gate_node",  final_syntax_gate_node)
    builder.add_node("assemble_output_node",    assemble_output_node)

    builder.add_edge(START,                      "prepare_backend_node")
    builder.add_edge("prepare_backend_node",     "backend_planner_node")
    builder.add_edge("backend_planner_node",     "cli_strategy_node")
    builder.add_edge("cli_strategy_node",        "cli_invoker_node")
    builder.add_edge("cli_invoker_node",         "scaffold_validator_node")

    # Conditional fan-out: scaffold valid → N parallel codegen_app_node; else → END
    builder.add_conditional_edges(
        "scaffold_validator_node",
        _route_scaffold_to_codegen,
    )

    # Fan-in: all parallel codegen_app_node results collected before collect_apps_node
    builder.add_edge("codegen_app_node",         "collect_apps_node")
    builder.add_edge("collect_apps_node",        "project_settings_node")
    builder.add_edge("project_settings_node",    "final_syntax_gate_node")
    builder.add_edge("final_syntax_gate_node",   "assemble_output_node")
    builder.add_edge("assemble_output_node",     END)

    return builder.compile()


_workflow = _build_graph()


async def run_backend_codegen(
    extraction_id: str,
    extracted_requirements: dict[str, Any],
    output_path: str,
    dependency_graph: dict[str, Any] | None = None,
    generation_mode: str = "startproject",
    existing_project_name: str = "",
) -> dict[str, Any]:
    """
    Run the full backend code generation workflow.

    Parameters
    ----------
    extraction_id:
        UUID of the source RequirementExtraction row.
    extracted_requirements:
        The extracted_requirements JSON from the DB row. Must have "modules".
    output_path:
        Absolute or relative directory where djcli writes the generated project.
    dependency_graph:
        The dependency_graph JSON from the DB row (may be None).

    Returns
    -------
    dict
        pipeline_output dict with keys: project_name, project_path, framework,
        generated_apps, generated_files, success, errors.
    """
    logger.info(
        "run_backend_codegen: start — extraction_id=%s modules=%d output_path=%r",
        extraction_id,
        len(extracted_requirements.get("modules", [])),
        output_path,
    )

    initial_state: BackendCodegenState = {
        "extraction_id":          extraction_id,
        "extracted_requirements": extracted_requirements,
        "dependency_graph":       dependency_graph,
        "output_path":            output_path,
        "generation_mode":        generation_mode,
        "existing_project_name":  existing_project_name,
        "modules":                [],
        "shared_enums":           {},
        "global_business_rules":  [],
        "dep_priority_map":       {},
        "backend_plan":           {},
        "cli_strategy":           {},
        "cli_output":             {},
        "scaffold_valid":         False,
        "app_results":            [],
        "generated_files":        [],
        "pipeline_output":        {},
        "all_errors":             [],
    }

    final_state: BackendCodegenState = await _workflow.ainvoke(initial_state)

    pipeline_output = final_state.get("pipeline_output")
    if not pipeline_output:
        pipeline_output = {
            "project_name":    "",
            "project_path":    "",
            "framework":       "django",
            "generated_apps":  [],
            "generated_files": [],
            "success":         False,
            "errors":          final_state.get("all_errors", ["Pipeline did not reach assemble_output_node"]),
        }

    logger.info(
        "run_backend_codegen: complete — success=%s apps=%d files=%d errors=%d",
        pipeline_output.get("success"),
        len(pipeline_output.get("generated_apps", [])),
        len(pipeline_output.get("generated_files", [])),
        len(pipeline_output.get("errors", [])),
    )

    return pipeline_output
