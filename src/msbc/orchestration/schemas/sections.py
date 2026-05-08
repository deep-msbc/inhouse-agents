"""
Pydantic schemas for the Phase 1 pre-extraction pipeline.

DocumentChunk  — coarse document slice produced by document_chunker_node.
ChunkRoute     — routing decision: chunk → canonical module(s).
CanonicalModule — a real business module (produced by module_normalizer_node).
ModuleBundle   — extraction input for extract_module_node.

DocumentSection and SectionClassification have been removed (belonged to the
old section_classifier_node batch approach).

JSON schemas for LLM calls are in:
  src/msbc/agents/schemas/requirement_extractor/module_inventory.py
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """
    One coarse slice of the source document.

    Built deterministically (no LLM) by document_chunker_node using
    document_chunking.py. Target: 3-10 chunks per document.
    """

    chunk_id: str
    """Stable identifier e.g. 'chunk_001'. Assigned sequentially."""

    title_hint: str | None = None
    """Top-level heading text for this chunk, if available."""

    text: str
    """Raw document text for this chunk (heading + body)."""

    start_char: int
    """Byte offset of chunk start in document_text (inclusive)."""

    end_char: int
    """Byte offset of chunk end in document_text (exclusive)."""

    local_headings: list[str] = Field(default_factory=list)
    """Sub-headings found inside this chunk. Used as evidence for module routing."""

    token_count: int
    """Approximate token count for this chunk's text."""


class ChunkRoute(BaseModel):
    """
    Routing decision: which canonical module(s) a DocumentChunk maps to.

    Produced by chunk_router_node. Most chunks resolve deterministically via
    evidence_chunk_ids set by module_inventory_node.
    """

    chunk_id: str
    """chunk_id of the DocumentChunk being routed."""

    module_keys: list[str]
    """One or more canonical module keys this chunk belongs to.
    Shared chunks have multiple keys and route_type='shared'."""

    route_type: Literal["primary", "shared", "unassigned"]
    """
    primary    — chunk maps to exactly one module.
    shared     — chunk content is relevant to multiple modules.
    unassigned — no deterministic match found.
    """

    reason: str
    """One-sentence explanation of how the routing decision was made."""

    confidence: float
    """0.0 - 1.0. Routes derived from evidence_chunk_ids score ~0.95."""


class CanonicalModule(BaseModel):
    """
    A real business module grouping one or more document chunks.

    Produced by module_normalizer_node. Only canonical modules are fanned
    out to extract_module_node — child concepts are never sent separately.
    """

    module_key: str
    """snake_case slug of display_name. e.g. 'material_consumption'."""

    display_name: str
    """Human-readable module name. e.g. 'Material Consumption'."""

    business_goal: str = ""
    """One-sentence description of the business problem this module solves."""

    primary_entities: list[str] = Field(default_factory=list)
    """Main data entities owned by this module."""

    main_actions: list[str] = Field(default_factory=list)
    """Core user actions in this module."""

    child_concepts: list[str] = Field(default_factory=list)
    """Sub-screens, forms, grids, workflows, rules that belong INSIDE this module.
    These are never sent as separate extract_module_node invocations."""

    evidence_chunk_ids: list[str] = Field(default_factory=list)
    """chunk_ids whose content primarily covers this module."""

    aliases: list[str] = Field(default_factory=list)
    """Original heading texts absorbed into this canonical module."""

    confidence: float = 0.8
    """0.0 - 1.0. Minimum confidence across constituent candidates."""

    merge_reason: str | None = None
    """Set when candidates were merged. Explains why."""


class ModuleBundle(BaseModel):
    """
    Complete extraction input for one canonical module.

    Produced by module_bundle_builder_node. combined_text contains all
    chunk texts joined in document order, formatted with chunk headers.
    """

    module_key: str
    display_name: str

    combined_text: str
    """All chunk texts concatenated with chunk headers, e.g.:

        # Canonical Module: Material Consumption

        Business Goal:
        Track raw material consumption against production jobs.

        Included Child Concepts:
        - Material Consumption Summary Grid
        - Add Consumption Entry
        - Consumption History

        Source Chunks:
        - chunk_005

        ## Source Content

        <chunk text here>
    """

    source_chunk_ids: list[str]
    """chunk_ids of all chunks included in combined_text, in document order."""
