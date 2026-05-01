"""
Unified Qdrant schema — single-collection architecture.

Collections
───────────
  rtk_unified_{model}_{dims}   — Code + Docs + Config (all content types in one collection)
  rtk_examples_{model}_{dims}  — Verified correct code examples (ConfigurableForm / ConfigurableDashboard)

Design decisions (from the schema design document):
  • One collection replaces the old 3-collection split.  ANN search + payload
    filtering on `content_type` gives comparable precision with simpler merging.
  • Rules are NOT stored — they are injected into every generation prompt.
  • Correct code examples live in a SEPARATE collection so they can be queried
    independently (e.g. "find me a form example with fileUpload").
"""

import re
import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    TextIndexParams,
    TokenizerType,
    VectorParams,
)

# ── Defaults ──────────────────────────────────────────────────────────────────
VECTOR_SIZE = 768
DISTANCE = Distance.COSINE

# Content types stored in the unified collection (rules excluded)
ContentType = Literal["code", "doc", "config"]

# Collection kind literals
CollectionKind = Literal["unified", "examples"]

_COLLECTION_PREFIXES: Dict[str, str] = {
    "unified":  "rtk_unified",
    "examples": "rtk_examples",
}


def _slugify(text: str) -> str:
    """Convert an arbitrary string into a safe Qdrant collection name segment."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()


def get_collection_name(
    model_name: str,
    dimensions: int,
    kind: CollectionKind = "unified",
) -> str:
    """
    Build a deterministic collection name.

    Examples
    --------
    ("nomic-ai/nomic-embed-text-v1.5", 768, "unified")
        → rtk_unified_nomic_ai_nomic_embed_text_v1_5_768
    """
    prefix = _COLLECTION_PREFIXES[kind]
    return f"{prefix}_{_slugify(model_name)}_{dimensions}"


def get_all_collection_names(
    model_name: str, dimensions: int
) -> Dict[str, str]:
    """Return {kind: collection_name} for both collections."""
    return {
        kind: get_collection_name(model_name, dimensions, kind)
        for kind in ("unified", "examples")
    }


def get_vector_config(dimensions: int = VECTOR_SIZE) -> VectorParams:
    """Return Qdrant VectorParams for a collection."""
    return VectorParams(size=dimensions, distance=DISTANCE)


# ── Payload indexes to create at collection setup ─────────────────────────────

def get_unified_payload_indexes() -> Dict[str, PayloadSchemaType]:
    """
    Keyword / integer indexes for the unified collection.
    These enable fast pre-filtering before ANN search.
    """
    return {
        # Universal
        "content_type":   PayloadSchemaType.KEYWORD,
        "repo_name":      PayloadSchemaType.KEYWORD,
        "namespace":      PayloadSchemaType.KEYWORD,
        "file_path":      PayloadSchemaType.KEYWORD,
        "language":       PayloadSchemaType.KEYWORD,
        # Code-specific
        "file_category":  PayloadSchemaType.KEYWORD,
        "symbol_name":    PayloadSchemaType.KEYWORD,
        "chunk_type":     PayloadSchemaType.KEYWORD,
        "module_path":    PayloadSchemaType.KEYWORD,
        "module_layer":   PayloadSchemaType.KEYWORD,
        # Doc-specific
        "doc_type":       PayloadSchemaType.KEYWORD,
        "heading_level":  PayloadSchemaType.INTEGER,
        "has_code_example": PayloadSchemaType.BOOL,
        # Config-specific
        "config_type":    PayloadSchemaType.KEYWORD,
        "schema_name":    PayloadSchemaType.KEYWORD,
    }


def get_unified_text_indexes() -> Dict[str, TextIndexParams]:
    """Text indexes (support partial/keyword matching)."""
    return {
        "section_title": TextIndexParams(
            type="text",
            tokenizer=TokenizerType.WORD,
            min_token_len=2,
            max_token_len=40,
            lowercase=True,
        ),
    }


def get_examples_payload_indexes() -> Dict[str, PayloadSchemaType]:
    """Keyword indexes for the correct_code_examples collection."""
    return {
        "example_pattern":  PayloadSchemaType.KEYWORD,   # "ConfigurableDashboard" | "ConfigurableForm"
        "file_role":        PayloadSchemaType.KEYWORD,   # "page_component" | "config" | "types" | "custom_component"
        "complexity":       PayloadSchemaType.KEYWORD,   # "simple" | "medium" | "complex"
        "language":         PayloadSchemaType.KEYWORD,
        "example_id":       PayloadSchemaType.KEYWORD,   # "Dashboard01", "Form08"
        "example_group":    PayloadSchemaType.KEYWORD,   # "Dashboard_Samples" | "Form_Samples"
        "is_verified":      PayloadSchemaType.BOOL,
        "has_custom_component": PayloadSchemaType.BOOL,
        "has_custom_validators": PayloadSchemaType.BOOL,
        "has_sections":     PayloadSchemaType.BOOL,
        "has_api_integration": PayloadSchemaType.BOOL,
    }


# ── Package → architecture layer mapping ──────────────────────────────────────

PACKAGE_LAYERS: Dict[str, str] = {
    "@msbc/react-toolkit":    "ui",
    "@msbc/utils":            "util",
    "@msbc/data-layer":       "data",
    "@msbc/config-ui":        "ui",
    "@msbc/config-app-shell": "app",
    "@msbc/import-utils":     "util",
    "dev-app":                "app",
    "monorepo-root":          "infra",
}


# ═════════════════════════════════════════════════════════════════════════════
# UNIFIED COLLECTION PAYLOAD
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class UnifiedChunkPayload:
    """
    Single payload schema for all content types in the unified collection.

    Fields for a content_type that doesn't apply are left at their default
    (empty string, empty list, 0, False).  Qdrant handles absent/empty
    payload fields natively.
    """

    # ── Universal (every chunk) ───────────────────────────────────────
    content_type: str               # "code" | "doc" | "config"
    repo_name: str                  # "react-toolkit" | "backend-services"
    namespace: str                  # "@msbc/react-toolkit" | "@msbc/utils"
    file_path: str                  # relative path from repo root
    file_name: str                  # "Button.tsx"
    file_id: str                    # SHA-256 of full file content
    chunk_id: str                   # deterministic SHA-256(file_path + chunk_index)
    chunk_index: int                # 0-based position within file
    total_chunks: int               # total chunks from this file
    language: str                   # "typescript" | "javascript" | "scss" | "markdown" | "json"
    summary: str = ""               # auto-generated one-liner

    # ── Sync ──────────────────────────────────────────────────────────
    text_hash: str = ""             # SHA-256 of chunk text (for incremental re-embedding)
    ingested_at: str = ""           # ISO-8601 UTC timestamp

    # ── Code-specific (content_type = "code") ─────────────────────────
    file_category: str = ""         # "component" | "hook" | "service" | "util" | "style" | ...
    chunk_type: str = ""            # "function" | "class" | "interface" | "module" | ...
    symbol_name: str = ""           # "Button" | "useApiRequest"
    module_path: str = ""           # "components/button" | "hooks"
    module_layer: str = ""          # "ui" | "logic" | "data" | "util" | "app" | "infra"
    parameters: List[str] = field(default_factory=list)   # prop/param names
    returns: str = ""               # return type string
    exports: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # resolved package names
    related_files: List[str] = field(default_factory=list)

    # ── Doc-specific (content_type = "doc") ───────────────────────────
    doc_type: str = ""              # "readme" | "tutorial" | "api_reference" | "usage_example" | ...
    section_title: str = ""
    heading_level: int = 0          # 1=H1, 2=H2, 3=H3, 0=non-heading
    section_path: str = ""          # "Components > Button > Props"
    has_code_example: bool = False
    code_language: str = ""         # dominant lang in fenced code blocks
    mentioned_symbols: List[str] = field(default_factory=list)
    mentioned_modules: List[str] = field(default_factory=list)

    # ── Config-specific (content_type = "config") ─────────────────────
    config_type: str = ""           # "interface" | "type_alias" | "enum" | "json_config" | ...
    schema_name: str = ""           # "ButtonProps" | "DashboardConfig"
    config_fields: List[str] = field(default_factory=list)  # property/attribute names
    extends: List[str] = field(default_factory=list)
    used_by_symbol: str = ""        # "Button" uses "ButtonProps"
    related_types: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to plain dict for Qdrant payload."""
        d = asdict(self)
        # Set ingested_at if not already set
        if not d.get("ingested_at"):
            d["ingested_at"] = datetime.now(timezone.utc).isoformat()
        return d


# ═════════════════════════════════════════════════════════════════════════════
# CORRECT CODE EXAMPLES COLLECTION PAYLOAD
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ExampleChunkPayload:
    """
    Payload for verified correct code examples (ConfigurableForm / ConfigurableDashboard).

    Each example folder (e.g. Dashboard01, Form08) is an "example set".
    Each file within the folder becomes one or more chunks.
    The metadata captures what pattern is demonstrated, complexity,
    and which toolkit features are showcased.
    """

    # ── Identity ──────────────────────────────────────────────────────
    file_path: str                  # "Dashboard_Samples/Dashboard01/dashboard1config.ts"
    file_name: str                  # "dashboard1config.ts"
    file_id: str                    # SHA-256 of full file content
    chunk_id: str                   # deterministic hash
    chunk_index: int
    total_chunks: int
    language: str                   # "typescript"

    # ── Example classification ────────────────────────────────────────
    example_id: str                 # "Dashboard01" | "Form08"
    example_group: str              # "Dashboard_Samples" | "Form_Samples"
    example_pattern: str            # "ConfigurableDashboard" | "ConfigurableForm"

    # ── File role within the example ──────────────────────────────────
    file_role: str                  # "page_component" | "config" | "types" | "custom_component"
    complexity: str                 # "simple" | "medium" | "complex"
    is_verified: bool = True        # all provided examples are human-verified

    # ── What this example demonstrates ────────────────────────────────
    use_case: str = ""              # "Basic dashboard with search and table"
    demonstrated_symbols: List[str] = field(default_factory=list)
    # e.g. ["ConfigurableDashboard", "DashboardConfig"]

    # ── Code semantics (same as unified code fields) ──────────────────
    symbol_name: str = ""           # top-level declaration name
    chunk_type: str = ""            # "function" | "module" | "interface" | ...
    exports: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    parameters: List[str] = field(default_factory=list)  # props for page components

    # ── @msbc package usage ───────────────────────────────────────────
    msbc_imports: List[str] = field(default_factory=list)
    # e.g. ["ConfigurableDashboard", "ConfigurableDashboardHandle"]
    msbc_packages: List[str] = field(default_factory=list)
    # e.g. ["@msbc/config-ui", "@msbc/react-toolkit"]

    # ── Dashboard-specific features (example_pattern = ConfigurableDashboard)
    has_search: bool = False
    has_filters: bool = False
    filter_types: List[str] = field(default_factory=list)       # ["select", "date_range"]
    has_actions: bool = False
    has_list_view: bool = False
    has_mode_switch: bool = False
    has_pagination: bool = False
    has_advance_filters: bool = False
    has_api_integration: bool = False
    has_row_selection: bool = False

    # ── Form-specific features (example_pattern = ConfigurableForm)
    field_types_used: List[str] = field(default_factory=list)
    # e.g. ["text", "email", "select", "custom", "fileUpload"]
    has_sections: bool = False
    has_nested_groups: bool = False
    has_custom_validators: bool = False
    custom_validator_names: List[str] = field(default_factory=list)
    has_custom_component: bool = False
    has_conditional_visibility: bool = False     # visibleIf
    has_conditional_validation: bool = False     # requiredIf
    has_dependent_fields: bool = False           # depends
    has_file_upload: bool = False

    # ── Config structure (for config files) ──────────────────────────
    config_type_name: str = ""      # "DashboardConfig" | "JSONFormSchema"
    config_fields: List[str] = field(default_factory=list)

    # ── Types info (for types files) ──────────────────────────────────
    type_names: List[str] = field(default_factory=list)     # exported type/interface names
    type_fields: List[str] = field(default_factory=list)    # all field names across types

    # ── Cross-references ──────────────────────────────────────────────
    related_files: List[str] = field(default_factory=list)  # sibling files in the example folder
    summary: str = ""               # auto-generated description

    # ── Sync ──────────────────────────────────────────────────────────
    text_hash: str = ""
    ingested_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("ingested_at"):
            d["ingested_at"] = datetime.now(timezone.utc).isoformat()
        return d


# ═════════════════════════════════════════════════════════════════════════════
# HELPER: Deterministic chunk ID
# ═════════════════════════════════════════════════════════════════════════════

def make_chunk_id(file_path: str, chunk_index: int) -> str:
    """SHA-256(file_path + chunk_index) → first 16 hex chars."""
    content = f"{file_path}::{chunk_index}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def make_point_id(chunk_id: str) -> str:
    """Convert a chunk_id into a UUID5 suitable for Qdrant point ID."""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))


def file_content_hash(content: str) -> str:
    """SHA-256 of file content for incremental sync."""
    return hashlib.sha256(content.encode()).hexdigest()


def text_hash(text: str) -> str:
    """SHA-256 of chunk text for chunk-level change detection."""
    return hashlib.sha256(text.encode()).hexdigest()
