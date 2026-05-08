"""
Edge logic for the requirement extractor LangGraph workflow.

fan_out_to_modules is used as a conditional-edge function attached to
module_bundle_builder_node (Phase 1). It returns a list of Send objects —
one per canonical module bundle — causing LangGraph to invoke
extract_module_node in parallel for every bundle.
"""

from typing import Any

from langgraph.types import Send

from src.msbc.orchestration.state import ExtractionState


def fan_out_to_modules(state: ExtractionState) -> list[Any]:
    """
    Conditional-edge function: called after module_bundle_builder_node.

    Reads state["module_bundles"] (populated by module_bundle_builder_node)
    and returns a list of Send objects so LangGraph invokes
    extract_module_node in parallel for each canonical module.
    """
    bundles = state.get("module_bundles") or []
    return [
        Send(
            "extract_module_node",
            {
                "index":              i,
                "module_key":         bundle["module_key"],
                "module_name":        bundle["display_name"],
                "module_text":        bundle["combined_text"],
                "source_chunk_ids":   bundle["source_chunk_ids"],
                "mode":               state["mode"],
            },
        )
        for i, bundle in enumerate(bundles)
    ]
