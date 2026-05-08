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
    module_name: str             # display name from canonical_modules
    module_text: str             # combined chunk text for this module
    mode:        str             # frontend | backend | both
    module_key:          str | None   # snake_case slug from module_normalizer_node
    source_chunk_ids:    list[str]    # chunk_ids bundled into module_text


class ModuleResult(TypedDict):
    """Output of one extract_module_node execution."""
    module_name: str
    extraction:  dict[str, Any]  # validated extraction JSON
    summary:     dict[str, Any]  # validated summary JSON
    usage:       list[dict[str, Any]]
    module_key:          str | None
    source_chunk_ids:    list[str]


class ExtractionState(TypedDict):
    # ── Inputs ────────────────────────────────────────────────────────────────
    document_text:     str               # full plain-text document
    heading_hierarchy: list[dict]        # [{level, text}, ...]
    mode:              str               # frontend | backend | both

    # ── Phase 1: chunk-based pipeline ─────────────────────────────────────────
    document_chunks:   list[dict[str, Any]]  # DocumentChunk dicts (document_chunker_node)
    module_candidates: list[dict[str, Any]]  # raw candidates (module_inventory_node)
    canonical_modules: list[dict[str, Any]]  # CanonicalModule dicts (module_normalizer_node)
    chunk_routes:      list[dict[str, Any]]  # ChunkRoute dicts (chunk_router_node)
    module_bundles:    list[dict[str, Any]]  # ModuleBundle dicts, ready for fan-out

    # ── Per-module results (parallel fan-in via reducer) ──────────────────────
    results: Annotated[list[ModuleResult], operator.add]

    # ── Phase 2: artifact deduplication ───────────────────────────────────────
    artifact_index: dict[str, Any]       # grouped ArtifactSignature dicts, keyed by type
    dedupe_report:  dict[str, Any]       # merge decisions + conflicts + self-edges removed

    # ── Post-processing outputs ───────────────────────────────────────────────
    extraction: dict[str, Any]           # output of finalize_node (pure-Python collect)
    graph:      dict[str, Any]           # output of graph_builder (inside finalize_node)

    # ── Phase 3: quality gate ─────────────────────────────────────────────────
    quality_report: dict[str, Any]       # deterministic lint results, never blocks pipeline

    # ── Aggregated LLM usage ──────────────────────────────────────────────────
    all_usage: list[dict[str, Any]]
