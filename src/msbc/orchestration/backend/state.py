"""
LangGraph state definitions for the Backend Code Generation workflow.

BackendCodegenState is the shared state dict that flows through every node.
app_results uses Annotated[list, operator.add] so parallel codegen_app_node
invocations each append their AppCodegenResult without overwriting one another.
"""

import operator
from typing import Annotated, Any, TypedDict


class AppCodegenResult(TypedDict):
    """Output of one codegen_app_node execution."""
    app_name: str
    generated_files: list[dict]
    errors: list[str]
    success: bool


class AppPlanSlice(TypedDict):
    """Input packet sent to codegen_app_node via Send fan-out."""
    app_plan: dict[str, Any]          # one app dict from backend_plan["apps"]
    dep_priority: int                 # build priority (1 = first)
    shared_enums: dict[str, Any]      # global enums from extraction
    global_business_rules: list[str]  # global rules from extraction
    project_path: str                 # djcli-generated project root on disk
    generation_mode: str              # passed through for path resolution in codegen_app_node


class BackendCodegenState(TypedDict):
    # ── Inputs (set by run_backend_codegen before ainvoke) ───────────────────
    extraction_id: str
    extracted_requirements: dict[str, Any]
    dependency_graph: dict[str, Any] | None
    output_path: str
    generation_mode: str        # "startproject" | "startapp" | "startservices"
    existing_project_name: str  # only used when generation_mode == "startapp"

    # ── Parsed by prepare_backend_node ───────────────────────────────────────
    modules: list[dict[str, Any]]
    shared_enums: dict[str, Any]
    global_business_rules: list[str]
    dep_priority_map: dict[str, int]

    # ── Set by backend_planner_node ───────────────────────────────────────────
    backend_plan: dict[str, Any]

    # ── Set by cli_strategy_node ──────────────────────────────────────────────
    cli_strategy: dict[str, Any]

    # ── Set by cli_invoker_node ───────────────────────────────────────────────
    cli_output: dict[str, Any]

    # ── Set by scaffold_validator_node ────────────────────────────────────────
    scaffold_valid: bool

    # ── Per-app codegen results (parallel fan-in via reducer) ─────────────────
    app_results: Annotated[list[AppCodegenResult], operator.add]

    # ── Set by collect_apps_node ──────────────────────────────────────────────
    generated_files: list[dict[str, Any]]

    # ── Set by assemble_output_node ───────────────────────────────────────────
    pipeline_output: dict[str, Any]

    # ── Error accumulator (extended by any node that detects errors) ──────────
    all_errors: list[str]
