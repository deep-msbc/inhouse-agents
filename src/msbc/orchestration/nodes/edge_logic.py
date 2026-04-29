"""
Edge logic for the requirement extractor LangGraph workflow.

fan_out_to_modules is used as a conditional-edge function attached to
segmentation_node. It delegates to build_slices_node which returns a
list of Send objects — one per module — causing LangGraph to invoke
extract_module_node in parallel for every module.
"""

from typing import Any

from src.msbc.orchestration.nodes.node_definitions import build_slices_node
from src.msbc.orchestration.state import ExtractionState


def fan_out_to_modules(state: ExtractionState) -> list[Any]:
    """
    Conditional-edge function: called after segmentation_node.

    Returns a list of Send objects (one per module) so LangGraph
    invokes extract_module_node in parallel for each module slice.
    """
    return build_slices_node(state)
