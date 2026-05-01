"""
Pydantic schemas for the embedding pipeline.

Two payload models:
  • ToolkitChunkPayload  — for the toolkit_openai_large_<dims> collection
  • ExampleChunkPayload  — for the examples_openai_large_<dims> collection

Plus helper functions for IDs, hashing, Qdrant payload index dicts, and
deterministic collection name generation.
"""

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

# ---------------------------------------------------------------------------
# Collection naming
# ---------------------------------------------------------------------------

_COLLECTION_PREFIXES: Dict[str, str] = {
    "toolkit":  "toolkit_openai_large",
    "examples": "examples_openai_large",
}


def get_collection_name(kind: Literal["toolkit", "examples"], dims: int) -> str:
    """
    Return the deterministic Qdrant collection name for a given kind and
    embedding dimension.

    Examples
    --------
    >>> get_collection_name("toolkit", 1536)
    'toolkit_openai_large_1536'
    >>> get_collection_name("examples", 1536)
    'examples_openai_large_1536'
    """
    prefix = _COLLECTION_PREFIXES[kind]
    return f"{prefix}_{dims}"


# ---------------------------------------------------------------------------
# ID & hash helpers
# ---------------------------------------------------------------------------

def make_chunk_id(file_path: str, index: int) -> str:
    """
    Build a deterministic, human-readable chunk ID.

    Format: ``<normalised_file_path>__chunk_<index>``

    The path separators are replaced with ``/`` and the drive letter is
    removed so IDs are consistent across operating systems.

    Examples
    --------
    >>> make_chunk_id("packages/config-ui/src/Form.tsx", 0)
    'packages/config-ui/src/Form.tsx__chunk_0'
    """
    normalised = file_path.replace("\\", "/").lstrip("/")
    return f"{normalised}__chunk_{index}"


def make_point_id(chunk_id: str) -> str:
    """
    Convert a chunk_id string into a UUID-v5 string suitable for Qdrant
    point IDs (which must be either unsigned 64-bit integers or UUIDs).

    Uses the DNS namespace as a stable, public namespace.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))


def file_hash(content: str) -> str:
    """Return the SHA-256 hex digest of *content* (used as file_id)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    """Return the SHA-256 hex digest of *text* (used as chunk text_hash)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Qdrant payload index definitions
# ---------------------------------------------------------------------------

def get_toolkit_payload_indexes() -> Dict[str, PayloadSchemaType]:
    """
    Return the Qdrant payload field → index type mapping for the toolkit
    collection.  Applied once during ``ensure_collection``.
    """
    return {
        "content_type":   PayloadSchemaType.KEYWORD,
        "namespace":      PayloadSchemaType.KEYWORD,
        "file_path":      PayloadSchemaType.KEYWORD,
        "file_name":      PayloadSchemaType.KEYWORD,
        "language":       PayloadSchemaType.KEYWORD,
        "file_category":  PayloadSchemaType.KEYWORD,
        "chunk_type":     PayloadSchemaType.KEYWORD,
        "symbol_name":    PayloadSchemaType.KEYWORD,
        "module_layer":   PayloadSchemaType.KEYWORD,
        "chunk_index":    PayloadSchemaType.INTEGER,
        "total_chunks":   PayloadSchemaType.INTEGER,
    }


def get_examples_payload_indexes() -> Dict[str, PayloadSchemaType]:
    """
    Return the Qdrant payload field → index type mapping for the examples
    collection.  Applied once during ``ensure_collection``.
    """
    return {
        "example_id":             PayloadSchemaType.KEYWORD,
        "example_group":          PayloadSchemaType.KEYWORD,
        "example_pattern":        PayloadSchemaType.KEYWORD,
        "file_role":              PayloadSchemaType.KEYWORD,
        "complexity":             PayloadSchemaType.KEYWORD,
        "language":               PayloadSchemaType.KEYWORD,
        "file_path":              PayloadSchemaType.KEYWORD,
        "file_name":              PayloadSchemaType.KEYWORD,
        "is_verified":            PayloadSchemaType.BOOL,
        "is_summary_chunk":       PayloadSchemaType.BOOL,
        "has_search":             PayloadSchemaType.BOOL,
        "has_filters":            PayloadSchemaType.BOOL,
        "has_actions":            PayloadSchemaType.BOOL,
        "has_list_view":          PayloadSchemaType.BOOL,
        "has_mode_switch":        PayloadSchemaType.BOOL,
        "has_pagination":         PayloadSchemaType.BOOL,
        "has_advance_filters":    PayloadSchemaType.BOOL,
        "has_api_integration":    PayloadSchemaType.BOOL,
        "has_row_selection":      PayloadSchemaType.BOOL,
        "has_sections":           PayloadSchemaType.BOOL,
        "has_nested_groups":      PayloadSchemaType.BOOL,
        "has_custom_validators":  PayloadSchemaType.BOOL,
        "has_custom_component":   PayloadSchemaType.BOOL,
        "has_conditional_visibility": PayloadSchemaType.BOOL,
        "has_conditional_validation": PayloadSchemaType.BOOL,
        "has_dependent_fields":   PayloadSchemaType.BOOL,
        "has_file_upload":        PayloadSchemaType.BOOL,
        "chunk_index":            PayloadSchemaType.INTEGER,
        "total_chunks":           PayloadSchemaType.INTEGER,
    }


# ---------------------------------------------------------------------------
# Qdrant vector config helper
# ---------------------------------------------------------------------------

def get_vector_config(dimensions: int) -> VectorParams:
    """Return a cosine-distance VectorParams for the given dimensionality."""
    return VectorParams(size=dimensions, distance=Distance.COSINE)


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------

class ToolkitChunkPayload(BaseModel):
    """
    Payload stored in Qdrant for every toolkit source-code chunk.

    All fields are stored alongside the embedding vector so they can be used
    for pre-filtering (payload indexes) or returned to the agent as context.
    """

    # ── Content classification ────────────────────────────────────────────────
    content_type: Literal["code", "style", "doc", "config"] = "code"
    """High-level type of the file this chunk came from."""

    # ── Source location ───────────────────────────────────────────────────────
    namespace: str
    """Package name, e.g. ``@msbc/config-ui``."""

    file_path: str
    """Relative path from the monorepo root (forward-slashes, no leading /)."""

    file_name: str
    """Bare filename with extension, e.g. ``ConfigurableForm.tsx``."""

    file_id: str
    """SHA-256 of the file contents — used for incremental sync."""

    # ── Chunk identity ────────────────────────────────────────────────────────
    chunk_id: str
    """Deterministic ID built by :func:`make_chunk_id`."""

    chunk_index: int
    """0-based position of this chunk within the file."""

    total_chunks: int
    """Total number of chunks produced from this file."""

    # ── Language & category ───────────────────────────────────────────────────
    language: Literal["typescript", "tsx", "scss", "markdown", "json", "unknown"] = "typescript"
    """Programming language / file type."""

    file_category: Literal[
        "component", "hook", "util", "service", "config", "type", "style", "doc", "unknown"
    ] = "unknown"
    """Coarse functional category inferred from naming conventions."""

    # ── AST-derived chunk metadata ────────────────────────────────────────────
    chunk_type: str = "module"
    """Kind of top-level symbol: function, class, interface, type_alias, etc."""

    symbol_name: str = ""
    """Name of the primary exported symbol in this chunk, if any."""

    module_layer: str = ""
    """Architecture layer derived from the package name, e.g. ``ui``, ``data``."""

    # ── File-level import / export metadata ───────────────────────────────────
    file_imports: List[str] = Field(default_factory=list)
    """All import specifiers found in the file (module paths)."""

    chunk_exports: List[str] = Field(default_factory=list)
    """Symbol names exported by this specific chunk."""

    msbc_imports: List[str] = Field(default_factory=list)
    """@msbc/* symbol names imported anywhere in the file."""

    # ── Quality / tracking ────────────────────────────────────────────────────
    text_hash: str = ""
    """SHA-256 of the text_to_embed string — detects stale vectors."""

    summary: str = ""
    """Optional one-sentence description (populated by a summariser agent later)."""

    ingested_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    """ISO-8601 UTC timestamp of when this point was upserted."""


class ExampleChunkPayload(BaseModel):
    """
    Payload stored in Qdrant for every correct_code_examples file chunk.

    One chunk per file plus one synthetic *summary chunk* per example folder.
    The summary chunk has ``is_summary_chunk=True`` and no raw source code.
    """

    # ── Source location ───────────────────────────────────────────────────────
    file_path: str
    """Relative path from the project root (forward-slashes, no leading /)."""

    file_name: str
    """Bare filename with extension, e.g. ``Form03.tsx``."""

    file_id: str
    """SHA-256 of the file contents.  Empty string for synthetic summary chunks."""

    # ── Chunk identity ────────────────────────────────────────────────────────
    chunk_id: str
    """Deterministic ID built by :func:`make_chunk_id`."""

    chunk_index: int = 0
    """Always 0 — examples produce exactly one chunk per file."""

    total_chunks: int = 1
    """Always 1 — examples produce exactly one chunk per file."""

    # ── Language ──────────────────────────────────────────────────────────────
    language: Literal["typescript", "tsx", "unknown"] = "tsx"

    # ── Example classification ────────────────────────────────────────────────
    example_id: str
    """Folder-level identifier, e.g. ``Dashboard03``."""

    example_group: str
    """Parent group, e.g. ``Dashboard_Samples`` or ``Form_Samples``."""

    example_pattern: Literal["ConfigurableDashboard", "ConfigurableForm", "unknown"] = "unknown"
    """Which MSBC pattern this example demonstrates."""

    file_role: Literal[
        "page_component", "config", "types", "custom_component", "summary", "unknown"
    ] = "unknown"
    """Functional role of this file within the example folder."""

    complexity: Literal["simple", "medium", "complex"] = "simple"
    """Subjective complexity rating."""

    is_verified: bool = True
    """True for all examples in ``correct_code_examples/`` — they are curated."""

    use_case: str = ""
    """Short human-readable description of what this example demonstrates."""

    # ── MSBC import metadata ──────────────────────────────────────────────────
    msbc_imports: List[str] = Field(default_factory=list)
    """@msbc/* symbol names used in this file."""

    msbc_packages: List[str] = Field(default_factory=list)
    """@msbc/* package paths used in this file."""

    # ── Dashboard feature flags ───────────────────────────────────────────────
    has_search: bool = False
    has_filters: bool = False
    has_actions: bool = False
    has_list_view: bool = False
    has_mode_switch: bool = False
    has_pagination: bool = False
    has_advance_filters: bool = False
    has_api_integration: bool = False
    has_row_selection: bool = False

    # ── Form feature flags ────────────────────────────────────────────────────
    has_sections: bool = False
    has_nested_groups: bool = False
    has_custom_validators: bool = False
    has_custom_component: bool = False
    has_conditional_visibility: bool = False
    has_conditional_validation: bool = False
    has_dependent_fields: bool = False
    has_file_upload: bool = False

    # ── Field type inventory ──────────────────────────────────────────────────
    field_types_used: List[str] = Field(default_factory=list)
    """Form field types used (e.g. ``["text", "select", "fileUpload"]``)."""

    # ── Summary chunk marker ──────────────────────────────────────────────────
    is_summary_chunk: bool = False
    """
    True for the one synthetic chunk per example folder that describes the
    *entire* example set in natural language.  Agents retrieve this chunk
    first when matching high-level queries such as
    "show me a dashboard with search and advanced filters".
    """

    # ── Quality / tracking ────────────────────────────────────────────────────
    summary: str = ""
    """Natural-language description of this file/example (populated by agent)."""

    text_hash: str = ""
    """SHA-256 of the text_to_embed string."""

    ingested_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    """ISO-8601 UTC timestamp of when this point was upserted."""
