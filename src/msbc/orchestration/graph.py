"""
LangGraph workflow for the requirement extractor.

Graph topology (flat — no nested subgraphs):

  START
    │
    ▼
  document_chunker_node          ← NEW  (pure Python, no LLM — coarse chunks)
    │
    ▼
  module_inventory_node          ← NEW  (1 LLM call on chunk outline)
    │
    ▼
  module_normalizer_node         ← NEW  (Python merge rules + optional 1 LLM call)
    │
    ▼
  chunk_router_node              ← NEW  (pure Python deterministic routing)
    │
    ▼
  module_bundle_builder_node     ← UPDATED (reads chunks + routes instead of sections)
    │  (conditional edge — fan_out_to_modules returns N Send objects)
    ├──► extract_module_node (module 0)  ─┐
    ├──► extract_module_node (module 1)  ─┤  (all run in parallel)
    └──► extract_module_node (module N)  ─┘
                                          │  fan-in: runs ONCE after all N complete
                                          ▼
                                   artifact_index_node
                                          │
                                          ▼
                                   artifact_deduplication_node
                                          │
                                          ▼
                                     finalize_node
                                     (pure-Python collect + graph-builder LLM)
                                          │
                                          ▼
                                   quality_gate_node
                                     (deterministic quality gate, never blocks)
                                          │
                                          ▼
                                         END

LLM call count (new):
  document_chunker_node:     0  (pure Python)
  module_inventory_node:     1  (outline → module candidates)
  module_normalizer_node:    0-1 (Python first, LLM only for ambiguous)
  chunk_router_node:         0  (pure Python)
  extract_module_node × N:   N  (parallel — same as before)
  artifact_index_node:       0  (pure Python)
  artifact_deduplication_node: 0  (pure Python)
  finalize_node:             1  (graph builder)
  quality_gate_node:         0  (pure Python)
  ──────────────────────────────
  Total blocking calls:  1-2 sequential + N parallel
  (was: 5-6 sequential + N parallel)

Entry point: run_extraction(document_text, heading_hierarchy, mode)
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.msbc.llm.clients.openai_client import merge_usage
from src.msbc.orchestration.nodes.edge_logic import fan_out_to_modules
from src.msbc.orchestration.nodes.node_definitions import (
    artifact_deduplication_node,
    artifact_index_node,
    chunk_router_node,
    document_chunker_node,
    extract_module_node,
    finalize_node,
    module_bundle_builder_node,
    module_inventory_node,
    module_normalizer_node,
    quality_gate_node,
)
from src.msbc.orchestration.state import ExtractionState

logger = logging.getLogger(__name__)

# ── Build and compile the graph once at import time ───────────────────────────

def _build_graph():
    builder = StateGraph(ExtractionState)

    # Nodes
    builder.add_node("document_chunker_node",     document_chunker_node)
    builder.add_node("module_inventory_node",     module_inventory_node)
    builder.add_node("module_normalizer_node",    module_normalizer_node)
    builder.add_node("chunk_router_node",         chunk_router_node)
    builder.add_node("module_bundle_builder_node", module_bundle_builder_node)
    builder.add_node("extract_module_node",       extract_module_node)
    builder.add_node("artifact_index_node",       artifact_index_node)
    builder.add_node("artifact_deduplication_node", artifact_deduplication_node)
    builder.add_node("finalize_node",             finalize_node)
    builder.add_node("quality_gate_node",         quality_gate_node)

    # Linear pipeline before fan-out
    builder.add_edge(START,                       "document_chunker_node")
    builder.add_edge("document_chunker_node",     "module_inventory_node")
    builder.add_edge("module_inventory_node",     "module_normalizer_node")
    builder.add_edge("module_normalizer_node",    "chunk_router_node")
    builder.add_edge("chunk_router_node",         "module_bundle_builder_node")

    # Fan-out: module_bundle_builder → N × extract_module_node (via Send)
    builder.add_conditional_edges(
        "module_bundle_builder_node",
        fan_out_to_modules,
        ["extract_module_node"],
    )

    # Fan-in: all extract_module_node results accumulated → artifact_index_node runs once
    builder.add_edge("extract_module_node",        "artifact_index_node")
    builder.add_edge("artifact_index_node",        "artifact_deduplication_node")
    builder.add_edge("artifact_deduplication_node",  "finalize_node")
    builder.add_edge("finalize_node",              "quality_gate_node")
    builder.add_edge("quality_gate_node",          END)

    return builder.compile()


_workflow = _build_graph()


# ── Public entry point ────────────────────────────────────────────────────────

async def run_extraction(
    document_text: str,
    heading_hierarchy: list[dict],
    mode: str,
) -> dict[str, Any]:
    """
    Run the full requirement extraction workflow.

    Args:
        document_text:     Full plain-text content of the uploaded document.
        heading_hierarchy: List of {level: int, text: str} dicts from the extractor.
        mode:              "frontend" | "backend" | "both"

    Returns:
        {
            "extraction": <per-module requirements (pure-Python assembled)>,
            "graph":      <dependency graph JSON>,
            "usage":      <aggregated LLM usage/cost dict>,
        }
    """
    logger.info(
        "run_extraction: starting — mode=%s, doc_length=%d chars, headings=%d.",
        mode, len(document_text), len(heading_hierarchy),
    )

    initial_state: ExtractionState = {
        "document_text":      document_text,
        "heading_hierarchy":  heading_hierarchy,
        "mode":               mode,
        # Phase 1 fields
        "document_chunks":    [],
        "module_candidates":  [],
        "canonical_modules":  [],
        "chunk_routes":       [],
        "module_bundles":     [],
        # Fan-in accumulation
        "results":            [],
        # Phase 2
        "artifact_index":     {},
        "dedupe_report":      {},
        # Outputs
        "extraction":         {},
        "graph":              {},
        "quality_report":     {},
        "all_usage":          [],
    }

    final_state: ExtractionState = await _workflow.ainvoke(initial_state)

    # Aggregate all usage dicts collected across every node
    all_usage: list[dict[str, Any]] = final_state.get("all_usage", [])
    for result in final_state.get("results", []):
        all_usage.extend(result.get("usage", []))

    usage_summary = merge_usage(all_usage) if all_usage else {}

    total_modules = final_state.get("extraction", {}).get("total_modules", 0)
    logger.info(
        "run_extraction: complete — %d module(s), total tokens=%d, cost=$%.4f.",
        total_modules,
        usage_summary.get("total_tokens", 0),
        usage_summary.get("total_cost_usd", 0.0),
    )

    return {
        "extraction": final_state.get("extraction", {}),
        "graph":      final_state.get("graph",      {}),
        "usage":      usage_summary,
    }
