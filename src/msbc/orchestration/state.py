"""
LangGraph state definitions for the requirement extractor workflow.

ExtractionState is the shared state dict that flows through every node.
`results` uses the Annotated[list, operator.add] reducer so parallel
`extract_module_node` invocations can each append their result without
overwriting one another.
"""

import operator
from typing import Annotated, Any, TypedDict


class ModuleSlice(TypedDict):
    """Input packet sent to extract_module_node via Send fan-out."""
    index:       int             # position in the modules list
    module_name: str             # name from segmentation
    module_text: str             # sliced document section for this module
    mode:        str             # frontend | backend | both


class ModuleResult(TypedDict):
    """Output of one extract_module_node execution."""
    module_name: str
    extraction:  dict[str, Any]  # validated extraction JSON
    summary:     dict[str, Any]  # validated summary JSON
    usage:       list[dict[str, Any]]


class ExtractionState(TypedDict):
    # ── Inputs ────────────────────────────────────────────────────────────────
    document_text:     str               # full plain-text document
    heading_hierarchy: list[dict]        # [{level, text}, ...]
    mode:              str               # frontend | backend | both

    # ── Segmentation output ───────────────────────────────────────────────────
    modules: list[dict[str, Any]]        # [{name, heading, level, description}]

    # ── Per-module results (parallel fan-in via reducer) ──────────────────────
    results: Annotated[list[ModuleResult], operator.add]

    # ── Post-processing outputs ───────────────────────────────────────────────
    extraction: dict[str, Any]           # output of finalize_node (pure-Python collect)
    graph:      dict[str, Any]           # output of graph_builder (inside finalize_node)

    # ── Aggregated LLM usage ──────────────────────────────────────────────────
    all_usage: list[dict[str, Any]]
