"""
Pydantic schemas for Phase 2: post-extraction artifact deduplication.

ArtifactSignature    — normalized representation of one extracted artifact instance.
DeduplicationDecision — result of comparing duplicate artifact signatures.

Used by:
  orchestration/utils/artifact_index.py   — builds ArtifactSignature catalogs
  orchestration/utils/deduplication.py    — produces DeduplicationDecision lists
  orchestration/nodes/node_definitions.py — artifact_index_node, global_deduplication_node
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ArtifactSignature(BaseModel):
    """
    Normalized representation of one extracted artifact across all modules.

    Created by build_artifact_index() in artifact_index.py from the raw LLM
    extraction output. Each artifact instance gets a unique artifact_id even if
    two modules define artifacts with the same name — deduplication happens later
    in global_deduplication_node.
    """

    artifact_id: str
    """Unique per-instance identifier: {artifact_type}__{module_key}__{discriminator}"""

    artifact_type: Literal[
        "api_endpoint",
        "db_model",
        "enum",
        "business_rule",
        "screen",
        "workflow",
    ]
    """Semantic category of this artifact."""

    module_key: str
    """snake_case key of the canonical module this artifact was extracted from."""

    name: str
    """Original artifact name as returned by the LLM."""

    normalized_name: str
    """Lowercased, slug/normalized form used for deduplication comparison."""

    method: str | None = None
    """HTTP method for api_endpoint artifacts (e.g. 'GET', 'POST'). None for other types."""

    path: str | None = None
    """Normalized URL path for api_endpoint artifacts (e.g. '/batches/{param}'). None for others."""

    table_name: str | None = None
    """Normalized table/model name for db_model artifacts. None for other types."""

    fields: list[dict] = Field(default_factory=list)
    """Field definitions for db_model artifacts (name, type, constraints, …)."""

    values: list[str] = Field(default_factory=list)
    """Enum value list. Populated only when artifact_type='enum'."""

    source_section_ids: list[str] = Field(default_factory=list)
    """Section IDs this artifact was derived from — for traceability back to the document."""

    raw: dict = Field(default_factory=dict)
    """Original raw artifact dict as extracted by the LLM. Preserved for downstream use."""


class DeduplicationDecision(BaseModel):
    """
    Result of comparing two or more artifact instances with the same effective identity.

    Produced by run_deduplication() in deduplication.py. One decision per duplicate
    group. When action='merge', merged_output carries the reconciled artifact dict.
    When action='conflict', needs_review=True and a human should inspect the artifacts.
    """

    artifact_type: str
    """Same as ArtifactSignature.artifact_type for the group."""

    canonical_artifact_id: str
    """artifact_id of the chosen canonical (winning) artifact for this group."""

    duplicate_artifact_ids: list[str]
    """artifact_ids of the duplicate artifacts (not including the canonical)."""

    action: Literal["merge", "keep_separate", "conflict"]
    """
    merge        — all duplicates are compatible; canonical_artifact_id is the single result.
    keep_separate — artifacts serve sufficiently distinct roles; all are retained.
    conflict      — incompatible definitions; needs_review=True, a human should resolve.
    """

    reason: str
    """Human-readable explanation of the deduplication decision."""

    confidence: float
    """0.0 – 1.0 confidence in the decision. Below 0.75 should be treated with caution."""

    merged_output: dict | None = None
    """
    The merged artifact dict when action='merge'.
    Contains union of fields/values/source_section_ids from all duplicates.
    None when action is 'keep_separate' or 'conflict'.
    """

    needs_review: bool = False
    """True when action='conflict' — a human analyst should review before code generation."""

    recommended_canonical: list[str] | None = None
    """
    Suggested canonical value set for enum conflicts.
    Union of all conflicting value sets, ordered alphabetically.
    Only populated for artifact_type='enum' conflicts.
    """
