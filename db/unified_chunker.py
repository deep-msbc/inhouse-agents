"""
Unified chunker for the single-collection RAG pipeline.

Re-uses the proven tree-sitter and regex strategies from chunker.py,
but outputs metadata aligned with the UnifiedChunkPayload and
ExampleChunkPayload schemas from unified_schema.py.

Public API
──────────
  chunk_for_unified()   — Chunk any file for the unified collection
  chunk_for_examples()  — Chunk correct_code_example files for the examples collection
"""

import json
import re
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Known package names (for mention extraction) ──────────────────────────────

_KNOWN_PACKAGES = {
    "@msbc/react-toolkit", "@msbc/config-ui", "@msbc/data-layer",
    "@msbc/config-app-shell", "@msbc/import-utils", "@msbc/utils",
}

# ── Re-export chunking from the existing chunker ─────────────────────────────
# We reuse the battle-tested tree-sitter code and markdown/style/interface/json
# chunkers as-is; only the metadata mapping changes.

from db.chunker import (
    Chunk,
    chunk_code_file,
    chunk_markdown_file,
    chunk_style_file,
    chunk_interfaces,
    chunk_json_config,
)


# ── Feature detection helpers for correct_code_examples ──────────────────────

_MSBC_IMPORT_RE = re.compile(
    r"""(?:import|from)\s+.*?['"](@msbc/[^'"]+)['"]""",
    re.MULTILINE,
)
_MSBC_SYMBOL_IMPORT_RE = re.compile(
    r"""import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"](@msbc/[^'"]+)['"]""",
    re.MULTILINE,
)
_COMPONENT_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")


def _extract_msbc_imports(source: str) -> Tuple[List[str], List[str]]:
    """Return (imported_symbols, package_names) from @msbc/* imports."""
    symbols: List[str] = []
    packages: set = set()
    for m in _MSBC_SYMBOL_IMPORT_RE.finditer(source):
        raw_symbols = m.group(1)
        pkg = m.group(2)
        packages.add(pkg)
        for s in raw_symbols.split(","):
            s = s.strip().replace("type ", "")
            if s:
                symbols.append(s)
    # Also catch default imports
    for m in _MSBC_IMPORT_RE.finditer(source):
        packages.add(m.group(1))
    return sorted(set(symbols)), sorted(packages)


def _detect_dashboard_features(source: str) -> Dict[str, Any]:
    """Detect dashboard config features from source text."""
    features: Dict[str, Any] = {}
    features["has_search"] = bool(re.search(r"hasSearch\s*:\s*true", source, re.IGNORECASE))
    features["has_filters"] = "filters:" in source or "filters :" in source
    features["has_actions"] = "actions:" in source or "actions :" in source
    features["has_list_view"] = "listProps" in source
    features["has_mode_switch"] = "enableModeSwitch" in source or "modeSwitchProps" in source
    features["has_pagination"] = "paginationParams" in source
    features["has_advance_filters"] = "advanceFilterProps" in source or "advancedFilterProps" in source
    features["has_api_integration"] = bool(re.search(r"\bapi\s*:", source)) or "apiResponseMapper" in source
    features["has_row_selection"] = "rowSelection" in source

    filter_types: List[str] = []
    if re.search(r"""type\s*:\s*['"]select['"]""", source):
        filter_types.append("select")
    if re.search(r"""type\s*:\s*['"]date[_-]?range['"]""", source) or "startDateKey" in source:
        filter_types.append("date_range")
    if re.search(r"""type\s*:\s*['"]text['"]""", source) and features["has_filters"]:
        filter_types.append("text")
    features["filter_types"] = filter_types

    return features


def _detect_form_features(source: str) -> Dict[str, Any]:
    """Detect form config features from source text."""
    features: Dict[str, Any] = {}
    features["has_sections"] = "sections:" in source or "sections :" in source
    features["has_nested_groups"] = bool(re.search(r"""type\s*:\s*['"]group['"]""", source))
    features["has_custom_validators"] = "customValidators" in source
    features["has_custom_component"] = bool(re.search(r"""type\s*:\s*['"]custom['"]""", source))
    features["has_conditional_visibility"] = "visibleIf" in source
    features["has_conditional_validation"] = "requiredIf" in source
    features["has_dependent_fields"] = "depends:" in source or "depends :" in source
    features["has_file_upload"] = bool(re.search(r"""type\s*:\s*['"]fileUpload['"]""", source))

    # Extract field types used
    field_type_re = re.compile(r"""type\s*:\s*['"](\w+)['"]""")
    raw_types = field_type_re.findall(source)
    # Filter to known form field types (exclude things like "group")
    known_field_types = {
        "text", "email", "number", "date", "select", "radio", "checkbox",
        "textarea", "password", "tel", "custom", "fileUpload", "file",
        "multiselect", "switch", "toggle",
    }
    field_types = sorted(set(t for t in raw_types if t in known_field_types))
    features["field_types_used"] = field_types

    # Extract custom validator function names
    validator_re = re.compile(r"""['"]?(\w+)['"]?\s*:\s*\(""")
    if features["has_custom_validators"]:
        # Look in customValidators object
        cv_match = re.search(r"customValidators\s*=?\s*\{([^}]+)\}", source, re.DOTALL)
        if cv_match:
            names = re.findall(r"(\w+)\s*:", cv_match.group(1))
            features["custom_validator_names"] = names
        else:
            features["custom_validator_names"] = []
    else:
        features["custom_validator_names"] = []

    return features


def _detect_example_pattern(source: str, file_path: str) -> str:
    """Detect whether this is a ConfigurableDashboard or ConfigurableForm example."""
    if "ConfigurableDashboard" in source or "DashboardConfig" in source:
        return "ConfigurableDashboard"
    if "ConfigurableForm" in source or "JSONFormSchema" in source:
        return "ConfigurableForm"
    # Infer from path
    path_lower = file_path.lower()
    if "dashboard" in path_lower or "userlist" in path_lower:
        return "ConfigurableDashboard"
    if "form" in path_lower:
        return "ConfigurableForm"
    return "unknown"


def _detect_file_role(file_name: str, source: str, example_pattern: str) -> str:
    """Classify file role within a correct_code_example folder."""
    name_lower = file_name.lower()
    stem = Path(file_name).stem.lower()

    # Types file
    if "types" in name_lower or name_lower.endswith(".types.ts"):
        return "types"

    # Config file
    if "config" in name_lower:
        return "config"

    # Custom component (not a page, not config, not types, has JSX and @msbc/react-toolkit)
    if "@msbc/react-toolkit" in source and "ConfigurableForm" not in source and "ConfigurableDashboard" not in source:
        return "custom_component"

    # Page component (uses ConfigurableForm or ConfigurableDashboard)
    if "ConfigurableForm" in source or "ConfigurableDashboard" in source:
        return "page_component"

    # Fallback: if it exports a React component, it's a page component
    if file_name.endswith((".tsx", ".jsx")):
        return "page_component"

    return "config"


def _detect_complexity(source: str, file_role: str, features: Dict[str, Any]) -> str:
    """Classify example complexity as simple/medium/complex."""
    if file_role == "types":
        # Types complexity based on field count
        field_count = source.count(":")
        if field_count > 15:
            return "complex"
        if field_count > 8:
            return "medium"
        return "simple"

    if file_role == "custom_component":
        return "medium"

    if file_role == "page_component":
        # Page components are usually simple unless they have local state/imperative logic
        has_state = "useState" in source
        has_ref = "useRef" in source
        has_multiple_components = source.count("<") > 6
        if has_state and has_multiple_components:
            return "medium"
        return "simple"

    if file_role == "config":
        complexity_score = 0
        # Dashboard features
        for key in ["has_filters", "has_actions", "has_list_view", "has_mode_switch",
                     "has_pagination", "has_advance_filters"]:
            if features.get(key):
                complexity_score += 1
        # Form features
        for key in ["has_sections", "has_nested_groups", "has_custom_validators",
                     "has_custom_component", "has_conditional_visibility",
                     "has_conditional_validation", "has_dependent_fields", "has_file_upload"]:
            if features.get(key):
                complexity_score += 1

        if complexity_score >= 3:
            return "complex"
        if complexity_score >= 1:
            return "medium"
        return "simple"

    return "simple"


def _generate_use_case(
    example_id: str,
    example_pattern: str,
    file_role: str,
    features: Dict[str, Any],
    symbol_name: str = "",
) -> str:
    """Auto-generate a use_case description for this example chunk."""
    parts = []

    if example_pattern == "ConfigurableDashboard":
        parts.append("Dashboard")
        if features.get("has_search"):
            parts.append("with search")
        if features.get("has_filters"):
            filter_types = features.get("filter_types", [])
            if filter_types:
                parts.append(f"with {'/'.join(filter_types)} filters")
            else:
                parts.append("with filters")
        if features.get("has_actions"):
            parts.append("with bulk actions")
        if features.get("has_list_view"):
            parts.append("with card/list view")
        if features.get("has_mode_switch"):
            parts.append("with table/grid mode switch")
        if features.get("has_pagination"):
            parts.append("with pagination")
        if features.get("has_advance_filters"):
            parts.append("with advanced filter modal")
        if features.get("has_api_integration"):
            parts.append("with API integration")
        if features.get("has_row_selection"):
            parts.append("with row selection")

    elif example_pattern == "ConfigurableForm":
        parts.append("Form")
        field_types = features.get("field_types_used", [])
        if field_types:
            parts.append(f"with {', '.join(field_types[:4])} fields")
        if features.get("has_sections"):
            parts.append("with sections")
        if features.get("has_nested_groups"):
            parts.append("with nested group sections")
        if features.get("has_custom_validators"):
            names = features.get("custom_validator_names", [])
            if names:
                parts.append(f"with custom validators ({', '.join(names[:3])})")
            else:
                parts.append("with custom validators")
        if features.get("has_custom_component"):
            parts.append("with custom rendered field")
        if features.get("has_conditional_visibility"):
            parts.append("with conditional visibility (visibleIf)")
        if features.get("has_conditional_validation"):
            parts.append("with conditional required (requiredIf)")
        if features.get("has_dependent_fields"):
            parts.append("with dependent fields")
        if features.get("has_file_upload"):
            parts.append("with file upload")

    if file_role == "page_component":
        prefix = f"{example_id} page component: "
    elif file_role == "config":
        prefix = f"{example_id} config: "
    elif file_role == "types":
        prefix = f"{example_id} type definitions: "
    elif file_role == "custom_component":
        prefix = f"{example_id} custom component ({symbol_name}): "
    else:
        prefix = f"{example_id}: "

    return prefix + ", ".join(parts) if parts else prefix + example_pattern


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API: chunk_for_examples
# ═════════════════════════════════════════════════════════════════════════════

def chunk_for_examples(
    source: str,
    file_path: str,
    file_name: str,
    example_id: str,
    example_group: str,
    related_files: Optional[List[str]] = None,
) -> List[Tuple[Chunk, Dict[str, Any]]]:
    """
    Chunk a correct_code_example file and return (Chunk, payload_dict) pairs
    ready for embedding into the examples collection.

    Uses tree-sitter for .ts/.tsx files, returns the full file as a single
    chunk for small files.
    """
    stem = Path(file_name).stem
    ext = Path(file_name).suffix.lower()

    # Detect pattern and file role
    example_pattern = _detect_example_pattern(source, file_path)
    file_role = _detect_file_role(file_name, source, example_pattern)

    # Extract @msbc imports
    msbc_symbols, msbc_packages = _extract_msbc_imports(source)

    # Detect features based on pattern and content
    features: Dict[str, Any] = {}
    if example_pattern == "ConfigurableDashboard":
        features = _detect_dashboard_features(source)
    elif example_pattern == "ConfigurableForm":
        features = _detect_form_features(source)

    # Chunk using tree-sitter (code files) or as-is (types files)
    if ext in (".ts", ".tsx"):
        if file_role == "types":
            # Use interface extraction for types files
            chunks = chunk_interfaces(source, file_path, stem)
            if not chunks:
                chunks = chunk_code_file(source, file_path, stem)
        else:
            chunks = chunk_code_file(source, file_path, stem)
    else:
        chunks = chunk_code_file(source, file_path, stem)

    # If no chunks were produced, create a single whole-file chunk
    if not chunks:
        from db.chunker import _make_chunk_id
        chunks = [Chunk(
            text=source.strip(),
            chunk_id=_make_chunk_id(file_path, 0, source),
            component_name=stem,
            chunk_type="module",
            chunk_index=0,
        )]

    total = len(chunks)
    complexity = _detect_complexity(source, file_role, features)

    results: List[Tuple[Chunk, Dict[str, Any]]] = []
    for chunk in chunks:
        # Collect demonstrated_symbols from chunk
        demonstrated = list(set(msbc_symbols))

        # Build use_case
        use_case = _generate_use_case(
            example_id, example_pattern, file_role, features,
            symbol_name=chunk.component_name,
        )

        # Type-specific metadata
        type_names: List[str] = []
        type_fields: List[str] = []
        if file_role == "types":
            type_names = [chunk.component_name] if chunk.component_name != stem else []
            type_fields = chunk.fields if hasattr(chunk, "fields") else []

        payload = {
            # Identity
            "file_path": file_path,
            "file_name": file_name,
            "file_id": hashlib.sha256(source.encode()).hexdigest(),
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "total_chunks": total,
            "language": "typescript" if ext in (".ts", ".tsx") else "javascript",
            # Example classification
            "example_id": example_id,
            "example_group": example_group,
            "example_pattern": example_pattern,
            # File role
            "file_role": file_role,
            "complexity": complexity,
            "is_verified": True,
            # What it demonstrates
            "use_case": use_case,
            "demonstrated_symbols": demonstrated,
            # Code semantics
            "symbol_name": chunk.component_name,
            "chunk_type": chunk.chunk_type,
            "exports": chunk.exports,
            "imports": chunk.imports,
            "parameters": chunk.props if chunk.props else [],
            # @msbc packages
            "msbc_imports": msbc_symbols,
            "msbc_packages": msbc_packages,
            # Dashboard features
            "has_search": features.get("has_search", False),
            "has_filters": features.get("has_filters", False),
            "filter_types": features.get("filter_types", []),
            "has_actions": features.get("has_actions", False),
            "has_list_view": features.get("has_list_view", False),
            "has_mode_switch": features.get("has_mode_switch", False),
            "has_pagination": features.get("has_pagination", False),
            "has_advance_filters": features.get("has_advance_filters", False),
            "has_api_integration": features.get("has_api_integration", False),
            "has_row_selection": features.get("has_row_selection", False),
            # Form features
            "field_types_used": features.get("field_types_used", []),
            "has_sections": features.get("has_sections", False),
            "has_nested_groups": features.get("has_nested_groups", False),
            "has_custom_validators": features.get("has_custom_validators", False),
            "custom_validator_names": features.get("custom_validator_names", []),
            "has_custom_component": features.get("has_custom_component", False),
            "has_conditional_visibility": features.get("has_conditional_visibility", False),
            "has_conditional_validation": features.get("has_conditional_validation", False),
            "has_dependent_fields": features.get("has_dependent_fields", False),
            "has_file_upload": features.get("has_file_upload", False),
            # Config structure
            "config_type_name": "",
            "config_fields": chunk.fields if hasattr(chunk, "fields") and chunk.fields else [],
            # Types info
            "type_names": type_names,
            "type_fields": type_fields,
            # Cross-references
            "related_files": related_files or [],
            "summary": use_case,
            # Sync
            "text_hash": hashlib.sha256(chunk.text.encode()).hexdigest(),
            "ingested_at": "",
        }

        # Detect config_type_name for config files
        if file_role == "config":
            if "DashboardConfig" in source:
                payload["config_type_name"] = "DashboardConfig"
            elif "JSONFormSchema" in source:
                payload["config_type_name"] = "JSONFormSchema"

        results.append((chunk, payload))

    return results
