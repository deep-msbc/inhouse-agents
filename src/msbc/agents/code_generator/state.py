import operator
from typing import Annotated, TypedDict


class CodeGenState(TypedDict):
    frontend_plan_id: str
    extraction_id: str
    output_dir: str
    module_filter: str | None

    plan_modules: list[dict]
    extraction_rules_index: dict[str, list[str]]

    current_module_idx: int
    current_screen_idx: int
    current_file_idx: int

    # Routing decision written by _advance_file_node and read by
    # _route_after_advance.  Stored in state so LangGraph can pass it
    # through conditional edges without needing an extra node.
    _next_node: str

    current_screen_context: Annotated[dict, lambda a, b: b]

    # Maps file_path → generated code for every file produced in the
    # current module.  The merge reducer means multiple parallel nodes
    # can each contribute their entry without clobbering the others.
    # Reset to {} at the start of each new module (see init_module).
    module_generated_files: Annotated[dict, lambda a, b: {**a, **b}]

    generated_files: Annotated[list, operator.add]
    all_errors: Annotated[list, operator.add]


class ValidatorState(TypedDict):
    generated_files: list[dict]
    plan_modules: list[dict]
    output_dir: str

    current_file_idx: int
    retry_count: int

    # Transient: populated by validate_file, consumed by decide_retry,
    # then overwritten on the next iteration.
    _check_errors: list[str]

    validated_files: Annotated[list, operator.add]
    all_validation_errors: Annotated[list, operator.add]
