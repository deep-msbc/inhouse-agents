"""
Smart AST-aware chunker for the embedding pipeline.

Improvements over the old db/chunker approach:
  • Token-envelope enforcement  — MIN 200 / MAX 800 tokens per chunk (merge + split passes).
  • Proper TS vs TSX grammar   — tree-sitter-typescript exposes two separate grammars.
  • File-level extraction      — imports/exports captured once, applied to every chunk.
  • Enriched embed text        — context header prepended before embedding so metadata
                                  travels inside the vector, not just as a side-car payload.
  • Example summary chunk      — synthetic natural-language entry-point per example folder.
  • No db/ dependency          — completely independent implementation.

Public API
──────────
  chunk_toolkit_file(...)          → list[ChunkResult]
  chunk_example_file(...)          → list[ChunkResult]
  build_example_summary_chunk(...) → ChunkResult
  build_embed_text(...)            → str   (convenience wrapper used by ingestors)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.msbc.embedding.schema import make_chunk_id, text_hash as _text_hash

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token-envelope constants
# ---------------------------------------------------------------------------

MIN_CHUNK_TOKENS: int = 200   # merge upward if a chunk is smaller than this
MAX_CHUNK_TOKENS: int = 800   # split at blank lines if a chunk is larger
SMALL_FILE_THRESHOLD: int = 500  # files under this token count → single chunk

# ---------------------------------------------------------------------------
# Known MSBC packages (used by msbc-import extraction)
# ---------------------------------------------------------------------------

_MSBC_PACKAGES: frozenset[str] = frozenset({
    "@msbc/react-toolkit",
    "@msbc/config-ui",
    "@msbc/data-layer",
    "@msbc/config-app-shell",
    "@msbc/import-utils",
    "@msbc/utils",
})

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# All import statements: captures the module specifier string
_ALL_IMPORT_RE = re.compile(
    r"""(?:import|from)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# Named imports from @msbc/* packages: captures {symbols} and package path
_MSBC_NAMED_IMPORT_RE = re.compile(
    r"""import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"](@msbc/[^'"]+)['"]""",
    re.MULTILINE,
)

# Default/namespace imports from @msbc/* packages
_MSBC_DEFAULT_IMPORT_RE = re.compile(
    r"""import\s+(?:type\s+)?(?:\*\s+as\s+\w+|\w+)\s+from\s+['"](@msbc/[^'"]+)['"]""",
    re.MULTILINE,
)

# Top-level export names (export const/function/class/type/interface/enum)
_EXPORT_SYMBOL_RE = re.compile(
    r"""^export\s+(?:default\s+)?(?:async\s+)?(?:const|let|var|function\*?|class|type|interface|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)""",
    re.MULTILINE,
)

# Re-export: export { A, B } or export { A as B }
_REEXPORT_RE = re.compile(
    r"""^export\s+\{([^}]+)\}""",
    re.MULTILINE,
)

# Dashboard feature detection
_HAS_SEARCH_RE = re.compile(r"hasSearch\s*:\s*true", re.IGNORECASE)
_FILTER_KEY_RE = re.compile(r"\bfilters\s*[=:]\s*[\[{]")
_ACTION_KEY_RE = re.compile(r"\bactions\s*[=:]\s*[\[{]")
_LIST_PROPS_RE = re.compile(r"\blistProps\b")
_MODE_SWITCH_RE = re.compile(r"\b(?:enableModeSwitch|modeSwitchProps)\b")
_PAGINATION_RE = re.compile(r"\bpaginationParams\b")
_ADVANCE_FILTER_RE = re.compile(r"\b(?:advanceFilterProps|advancedFilterProps)\b")
_API_OBJECT_RE = re.compile(r"\bapi\s*:", re.IGNORECASE)
_API_MAPPER_RE = re.compile(r"\bapiResponseMapper\b")
_ROW_SELECT_RE = re.compile(r"\browSelection\b")
_FILTER_SELECT_RE = re.compile(r"""type\s*:\s*['"]select['"]""")
_FILTER_DATE_RE = re.compile(r"""type\s*:\s*['"]date[_-]?range['"]|startDateKey\b""")
_FILTER_TEXT_RE = re.compile(r"""type\s*:\s*['"]text['"]""")
_FILTER_MULTISELECT_RE = re.compile(r"""type\s*:\s*['"]multi[_-]?select['"]""")

# Form feature detection
_SECTIONS_RE = re.compile(r"\bsections\s*[=:]\s*[\[{]")
_NESTED_GROUP_RE = re.compile(r"""type\s*:\s*['"]group['"]""")
_CUSTOM_VALIDATORS_RE = re.compile(r"\bcustomValidators\b")
_CUSTOM_COMPONENT_RE = re.compile(r"""type\s*:\s*['"]custom['"]""")
_VISIBLE_IF_RE = re.compile(r"\bvisibleIf\b")
_REQUIRED_IF_RE = re.compile(r"\brequiredIf\b")
_DEPENDS_RE = re.compile(r"\bdepends\s*[=:]\s*")
_FILE_UPLOAD_RE = re.compile(r"""type\s*:\s*['"]fileUpload['"]""")

# Field type extraction from form configs
_FIELD_TYPE_RE = re.compile(r"""type\s*:\s*['"](\w+)['"]""")
_KNOWN_FORM_FIELD_TYPES: frozenset[str] = frozenset({
    "text", "email", "number", "date", "select", "radio", "checkbox",
    "textarea", "password", "tel", "custom", "fileUpload", "file",
    "multiselect", "switch", "toggle", "datepicker", "autocomplete",
})

# Pattern + role detection
_DASHBOARD_INDICATOR_RE = re.compile(
    r"\b(?:ConfigurableDashboard|DashboardConfig|UserListConfig)\b"
)
_FORM_INDICATOR_RE = re.compile(
    r"\b(?:ConfigurableForm|JSONFormSchema|FormConfig)\b"
)

# Custom validator name extraction
_CV_BLOCK_RE = re.compile(r"customValidators\s*=?\s*\{([^}]+)\}", re.DOTALL)
_CV_NAME_RE = re.compile(r"(\w+)\s*:")

# ---------------------------------------------------------------------------
# ChunkResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChunkResult:
    """
    A single chunked segment produced by the chunker.

    Attributes
    ----------
    text          : Raw source code segment (stored in Qdrant payload for display).
    text_to_embed : Enriched text (context header + code) — what gets vectorised.
    chunk_id      : Deterministic ID from schema.make_chunk_id.
    chunk_index   : 0-based position within the file.
    symbol_name   : Primary symbol name extracted from the AST (empty for fallback chunks).
    chunk_type    : AST node kind: "function", "class", "interface", "type_alias",
                    "enum", "hook", "module", "summary".
    chunk_exports : Exported symbol names belonging specifically to this chunk.
    token_count   : Approximate token count (len(text) // 4).
    """

    text: str
    text_to_embed: str
    chunk_id: str
    chunk_index: int
    symbol_name: str = ""
    chunk_type: str = "module"
    chunk_exports: list[str] = field(default_factory=list)
    token_count: int = 0


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def count_tokens_approx(text: str) -> int:
    """Approximate token count: length divided by 4 (GPT-family rule of thumb)."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# File-level extraction helpers
# ---------------------------------------------------------------------------

def extract_file_imports(source: str) -> list[str]:
    """
    Return all unique import module specifiers found in *source*.

    Handles both ``import X from 'path'`` and bare ``from 'path'`` forms.
    Relative paths (./…) and absolute package paths are both captured.
    """
    seen: set[str] = set()
    results: list[str] = []
    for m in _ALL_IMPORT_RE.finditer(source):
        spec = m.group(1).strip()
        if spec and spec not in seen:
            seen.add(spec)
            results.append(spec)
    return results


def extract_msbc_imports(source: str) -> tuple[list[str], list[str]]:
    """
    Extract ``@msbc/*`` named symbols and package paths from *source*.

    Returns
    -------
    (symbols, packages)
        symbols  : Deduplicated list of imported symbol names, e.g. ``["ConfigurableForm"]``.
        packages : Deduplicated list of @msbc/* package paths, e.g. ``["@msbc/config-ui"]``.
    """
    symbols: set[str] = set()
    packages: set[str] = set()

    for m in _MSBC_NAMED_IMPORT_RE.finditer(source):
        raw = m.group(1)
        pkg = m.group(2).strip()
        packages.add(pkg)
        for sym in raw.split(","):
            cleaned = sym.strip().lstrip("type").strip()
            # Handle aliased imports: "ConfigurableForm as CF" → "ConfigurableForm"
            if " as " in cleaned:
                cleaned = cleaned.split(" as ")[0].strip()
            if cleaned:
                symbols.add(cleaned)

    for m in _MSBC_DEFAULT_IMPORT_RE.finditer(source):
        pkg = m.group(1).strip()
        packages.add(pkg)

    return sorted(symbols), sorted(packages)


def extract_file_exports(source: str) -> list[str]:
    """
    Return all top-level exported symbol names found in *source*.

    Covers:
    • ``export const/function/class/type/interface/enum Name``
    • ``export { A, B as C }`` re-export statements
    """
    seen: set[str] = set()
    results: list[str] = []

    for m in _EXPORT_SYMBOL_RE.finditer(source):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            results.append(name)

    for m in _REEXPORT_RE.finditer(source):
        for part in m.group(1).split(","):
            # Handle "A as B" — the exported name is the alias B
            part = part.strip()
            if " as " in part:
                name = part.split(" as ")[-1].strip()
            else:
                name = part
            if name and name not in seen:
                seen.add(name)
                results.append(name)

    return results


# ---------------------------------------------------------------------------
# Tree-sitter language loaders  (lazy, cached per process)
# ---------------------------------------------------------------------------

_TS_LANG_CACHE: dict[str, Any] = {}


def _get_ts_language(ext: str) -> Any:
    """
    Return the tree-sitter Language for the given extension.

    Uses ``language_typescript()`` for ``.ts`` files and ``language_tsx()``
    for ``.tsx`` files (and anything else as a safe fallback).
    """
    if ext in _TS_LANG_CACHE:
        return _TS_LANG_CACHE[ext]

    from tree_sitter import Language
    import tree_sitter_typescript as tsts

    lang = Language(tsts.language_typescript() if ext == ".ts" else tsts.language_tsx())
    _TS_LANG_CACHE[ext] = lang
    return lang


# ---------------------------------------------------------------------------
# AST declaration walker
# ---------------------------------------------------------------------------

def _walk_top_level_declarations(
    root: Any, source_bytes: bytes
) -> list[tuple[int, int, str, str]]:
    """
    Walk the root AST node's direct children and yield every named top-level
    declaration as ``(start_byte, end_byte, symbol_name, chunk_type)``.

    Handles transparent ``export_statement`` wrappers so callers never need
    to unwrap them separately.

    Recognised node kinds
    ---------------------
    function_declaration, class_declaration, interface_declaration,
    type_alias_declaration, enum_declaration, lexical_declaration (export const …),
    variable_declaration, export_statement (wrapping any of the above).
    """
    _DECL_KINDS = frozenset({
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "lexical_declaration",
        "variable_declaration",
    })

    declarations: list[tuple[int, int, str, str]] = []

    def _extract_from_node(node: Any, outer_start: int, outer_end: int) -> None:
        ntype = node.type

        if ntype in ("function_declaration",):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = source_bytes[name_node.start_byte: name_node.end_byte].decode()
                kind = "hook" if (name.startswith("use") and len(name) > 3 and name[3].isupper()) else "function"
                declarations.append((outer_start, outer_end, name, kind))

        elif ntype == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = source_bytes[name_node.start_byte: name_node.end_byte].decode()
                declarations.append((outer_start, outer_end, name, "class"))

        elif ntype == "interface_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = source_bytes[name_node.start_byte: name_node.end_byte].decode()
                declarations.append((outer_start, outer_end, name, "interface"))

        elif ntype == "type_alias_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = source_bytes[name_node.start_byte: name_node.end_byte].decode()
                declarations.append((outer_start, outer_end, name, "type_alias"))

        elif ntype == "enum_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = source_bytes[name_node.start_byte: name_node.end_byte].decode()
                declarations.append((outer_start, outer_end, name, "enum"))

        elif ntype in ("lexical_declaration", "variable_declaration"):
            for child in node.named_children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    val_node = child.child_by_field_name("value")
                    if name_node:
                        name = source_bytes[name_node.start_byte: name_node.end_byte].decode()
                        is_fn = val_node is not None and val_node.type in (
                            "arrow_function", "function_expression"
                        )
                        if is_fn:
                            kind = "hook" if (name.startswith("use") and len(name) > 3 and name[3].isupper()) else "function"
                        else:
                            kind = "variable"
                        declarations.append((outer_start, outer_end, name, kind))
                    break  # one declarator per lexical_declaration is typical

    for node in root.named_children:
        ntype = node.type
        if ntype in ("import_statement", "comment", "hash_bang_line"):
            continue

        if ntype == "export_statement":
            # Transparent unwrap: look for the inner declaration
            inner = None
            for child in node.named_children:
                if child.type in _DECL_KINDS:
                    inner = child
                    break
            if inner is not None:
                _extract_from_node(inner, node.start_byte, node.end_byte)
            # else: plain `export default X` or `export { X }` — not a new chunk
        elif ntype in _DECL_KINDS:
            _extract_from_node(node, node.start_byte, node.end_byte)

    return declarations


# ---------------------------------------------------------------------------
# Merge & split passes
# ---------------------------------------------------------------------------

def _merge_small_chunks(
    raw_chunks: list[tuple[str, str, str]],  # (text, symbol_name, chunk_type)
    import_prefix: str,
) -> list[tuple[str, str, str]]:
    """
    Merge consecutive chunks that are smaller than MIN_CHUNK_TOKENS into their
    next sibling.  The first chunk always keeps the full import prefix.

    The merged chunk inherits the symbol_name and chunk_type of the *last*
    segment in the merge group (more semantically meaningful).
    """
    if not raw_chunks:
        return raw_chunks

    merged: list[tuple[str, str, str]] = []
    pending_text, pending_name, pending_type = raw_chunks[0]

    for text, name, ctype in raw_chunks[1:]:
        if count_tokens_approx(pending_text) < MIN_CHUNK_TOKENS:
            # Merge: append current to pending
            pending_text = pending_text.rstrip() + "\n\n" + text
            pending_name = name  # inherit the latter symbol
            pending_type = ctype
        else:
            merged.append((pending_text, pending_name, pending_type))
            pending_text, pending_name, pending_type = text, name, ctype

    merged.append((pending_text, pending_name, pending_type))
    return merged


def _split_large_chunk(text: str, symbol_name: str, chunk_type: str) -> list[tuple[str, str, str]]:
    """
    Split a chunk that exceeds MAX_CHUNK_TOKENS at blank-line boundaries.
    Each resulting sub-chunk inherits the parent's symbol_name and chunk_type
    (since we don't re-parse, we can't determine sub-symbols reliably).
    """
    if count_tokens_approx(text) <= MAX_CHUNK_TOKENS:
        return [(text, symbol_name, chunk_type)]

    # Split at double newlines (blank lines)
    paragraphs = re.split(r"\n{2,}", text)
    result: list[tuple[str, str, str]] = []
    current_parts: list[str] = []

    for para in paragraphs:
        current_parts.append(para)
        current_text = "\n\n".join(current_parts)
        if count_tokens_approx(current_text) >= MIN_CHUNK_TOKENS:
            if count_tokens_approx(current_text) > MAX_CHUNK_TOKENS and len(current_parts) > 1:
                # Flush everything except the last paragraph, then start fresh
                flush_text = "\n\n".join(current_parts[:-1])
                result.append((flush_text, symbol_name, chunk_type))
                current_parts = [para]
            # else keep accumulating

    if current_parts:
        remainder = "\n\n".join(current_parts).strip()
        if remainder:
            result.append((remainder, symbol_name, chunk_type))

    return result if result else [(text, symbol_name, chunk_type)]


# ---------------------------------------------------------------------------
# TypeScript / TSX AST chunker
# ---------------------------------------------------------------------------

def _ast_chunk_typescript(
    source: str,
    file_path: str,
    ext: str,
    all_exports: list[str],
) -> list[tuple[str, str, str]]:
    """
    Parse *source* with tree-sitter and return
    ``(segment_text, symbol_name, chunk_type)`` tuples representing
    each top-level declaration.

    The first segment always includes the full import block for context.
    Subsequent segments include the import block as a minimal header to keep
    each chunk self-contained for retrieval.
    """
    from tree_sitter import Parser

    try:
        lang = _get_ts_language(ext)
        parser = Parser(lang)
    except Exception as exc:
        logger.warning("tree-sitter unavailable (%s). Using fallback chunker.", exc)
        return _fallback_chunk(source)

    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    # Collect import block text (prepended to chunks for self-containedness)
    import_lines: list[str] = [
        source_bytes[n.start_byte: n.end_byte].decode()
        for n in root.named_children
        if n.type == "import_statement"
    ]
    import_prefix = "\n".join(import_lines) + "\n\n" if import_lines else ""

    # Collect preamble (file-level comments + imports = everything before first decl)
    declarations = _walk_top_level_declarations(root, source_bytes)

    if not declarations:
        # No parseable declarations → return whole file as one chunk
        return [(source.strip(), Path(file_path).stem, "module")]

    first_start = declarations[0][0]
    preamble = source_bytes[:first_start].decode().rstrip()

    raw_chunks: list[tuple[str, str, str]] = []
    for idx, (start, end, name, ctype) in enumerate(declarations):
        segment = source_bytes[start:end].decode().strip()
        if not segment:
            continue

        if idx == 0:
            # First chunk: prepend full preamble (comments + imports)
            if preamble:
                segment = preamble + "\n\n" + segment
        else:
            # Subsequent chunks: prepend imports only for self-containedness
            if import_prefix:
                segment = import_prefix + segment

        raw_chunks.append((segment, name, ctype))

    return raw_chunks if raw_chunks else [(source.strip(), Path(file_path).stem, "module")]


# ---------------------------------------------------------------------------
# Fallback chunker (non-TS files and tree-sitter failures)
# ---------------------------------------------------------------------------

def _fallback_chunk(source: str) -> list[tuple[str, str, str]]:
    """
    Split *source* at blank-line boundaries and return
    ``(segment, "", "module")`` tuples.  Used for ``.scss``, ``.md``,
    ``.json`` and as a fallback when tree-sitter fails.
    """
    parts = [p.strip() for p in re.split(r"\n{2,}", source) if p.strip()]
    return [(p, "", "module") for p in parts] if parts else [(source.strip(), "", "module")]


# ---------------------------------------------------------------------------
# Build enriched embed text
# ---------------------------------------------------------------------------

def build_embed_text(
    chunk_text: str,
    chunk_type: str,
    symbol_name: str,
    namespace: str,
    file_category: str,
    file_name: str,
    msbc_imports: list[str],
    chunk_exports: list[str],
) -> str:
    """
    Build the enriched text string that will be vectorised.

    The context header placed before the code carries semantic metadata
    (type, namespace, package, file, imports, exports) so that queries like
    "ConfigurableForm component in config-ui" resolve correctly even when the
    code itself does not repeat these words.

    Format
    ------
    [{chunk_type}: {symbol_name}] [{namespace} / {file_category}]
    Package: {namespace} | File: {file_name}
    MSBC imports: {A, B, C}
    Exports: {X, Y}
    ---
    {chunk_text}
    """
    header_parts: list[str] = []

    label = f"{chunk_type}: {symbol_name}" if symbol_name else chunk_type
    header_parts.append(f"[{label}] [{namespace} / {file_category}]")
    header_parts.append(f"Package: {namespace} | File: {file_name}")

    if msbc_imports:
        header_parts.append(f"MSBC imports: {', '.join(msbc_imports[:8])}")
    if chunk_exports:
        header_parts.append(f"Exports: {', '.join(chunk_exports[:8])}")

    header = "\n".join(header_parts)
    return f"{header}\n---\n{chunk_text}"


# ---------------------------------------------------------------------------
# Determine which exports belong to a specific chunk segment
# ---------------------------------------------------------------------------

def _chunk_level_exports(segment: str, all_file_exports: list[str]) -> list[str]:
    """
    Return the subset of *all_file_exports* whose symbol name appears in the
    given *segment* text (cheap heuristic: if the name is in the text it was
    defined there).
    """
    return [sym for sym in all_file_exports if re.search(rf"\b{re.escape(sym)}\b", segment)]


# ---------------------------------------------------------------------------
# Public API: chunk_toolkit_file
# ---------------------------------------------------------------------------

def chunk_toolkit_file(
    source: str,
    file_path: str,
    file_name: str,
    namespace: str,
    file_category: str,
    module_layer: str,
    file_imports: list[str],
    msbc_imports: list[str],
    all_file_exports: list[str],
) -> list[ChunkResult]:
    """
    Chunk a toolkit source file and return a list of :class:`ChunkResult` objects
    ready to be embedded and upserted into the toolkit Qdrant collection.

    Strategy
    --------
    1. Files under ``SMALL_FILE_THRESHOLD`` tokens → single chunk (no parsing).
    2. TypeScript / TSX files → tree-sitter AST chunking.
    3. Other file types → blank-line split (fallback).
    4. Merge pass: chunks < ``MIN_CHUNK_TOKENS`` are merged with the next sibling.
    5. Split pass: chunks > ``MAX_CHUNK_TOKENS`` are split at blank-line boundaries.

    Parameters
    ----------
    source           : Raw file content (UTF-8 string).
    file_path        : Relative path from the monorepo root (forward-slashes).
    file_name        : Bare filename with extension.
    namespace        : @msbc/* package name, e.g. ``"@msbc/config-ui"``.
    file_category    : Coarse category, e.g. ``"component"``.
    module_layer     : Architecture layer, e.g. ``"ui"``.
    file_imports     : All import specifiers in the file (from extract_file_imports).
    msbc_imports     : @msbc/* symbols used in the file (from extract_msbc_imports).
    all_file_exports : All exported symbol names in the file (from extract_file_exports).
    """
    ext = Path(file_name).suffix.lower()
    total_tokens = count_tokens_approx(source)

    # ── Step 1: small file → one chunk ───────────────────────────────────────
    if total_tokens < SMALL_FILE_THRESHOLD:
        raw: list[tuple[str, str, str]] = [(source.strip(), Path(file_name).stem, "module")]
    # ── Step 2: TypeScript / TSX → AST chunking ──────────────────────────────
    elif ext in (".ts", ".tsx"):
        raw = _ast_chunk_typescript(source, file_path, ext, all_file_exports)
    # ── Step 3: other files → blank-line fallback ─────────────────────────────
    else:
        raw = _fallback_chunk(source)

    # ── Step 4: merge pass ────────────────────────────────────────────────────
    import_prefix = ""
    if ext in (".ts", ".tsx"):
        import_lines = [
            line for line in source.splitlines()
            if line.strip().startswith("import ")
        ]
        import_prefix = "\n".join(import_lines) + "\n\n" if import_lines else ""

    merged = _merge_small_chunks(raw, import_prefix)

    # ── Step 5: split pass ────────────────────────────────────────────────────
    final_raw: list[tuple[str, str, str]] = []
    for seg, name, ctype in merged:
        final_raw.extend(_split_large_chunk(seg, name, ctype))

    # ── Build ChunkResult objects ─────────────────────────────────────────────
    total = len(final_raw)
    results: list[ChunkResult] = []

    for idx, (seg_text, sym_name, ctype) in enumerate(final_raw):
        cid = make_chunk_id(file_path, idx)
        chunk_exports = _chunk_level_exports(seg_text, all_file_exports)

        embed_text = build_embed_text(
            chunk_text=seg_text,
            chunk_type=ctype,
            symbol_name=sym_name,
            namespace=namespace,
            file_category=file_category,
            file_name=file_name,
            msbc_imports=msbc_imports,
            chunk_exports=chunk_exports,
        )

        results.append(ChunkResult(
            text=seg_text,
            text_to_embed=embed_text,
            chunk_id=cid,
            chunk_index=idx,
            symbol_name=sym_name,
            chunk_type=ctype,
            chunk_exports=chunk_exports,
            token_count=count_tokens_approx(seg_text),
        ))

    return results


# ---------------------------------------------------------------------------
# Feature detection for correct_code_examples
# ---------------------------------------------------------------------------

def _detect_example_pattern(source: str, file_path: str) -> str:
    """
    Classify which MSBC pattern this example demonstrates.

    Returns ``"ConfigurableDashboard"``, ``"ConfigurableForm"``, or ``"unknown"``.
    Prefers content-based detection; falls back to path inference.
    """
    if _DASHBOARD_INDICATOR_RE.search(source):
        return "ConfigurableDashboard"
    if _FORM_INDICATOR_RE.search(source):
        return "ConfigurableForm"

    path_lower = file_path.lower()
    if "dashboard" in path_lower or "userlist" in path_lower:
        return "ConfigurableDashboard"
    if "form" in path_lower:
        return "ConfigurableForm"

    return "unknown"


def _detect_file_role(file_name: str, source: str) -> str:
    """
    Determine the functional role of a file within a correct_code_example folder.

    Returns one of: ``"page_component"``, ``"config"``, ``"types"``,
    ``"custom_component"``, ``"unknown"``.
    """
    name_lower = file_name.lower()

    if "types" in name_lower or name_lower.endswith(".types.ts"):
        return "types"

    if "config" in name_lower:
        return "config"

    # Custom component: uses @msbc/react-toolkit primitives but is NOT the main page
    if "@msbc/react-toolkit" in source and not _DASHBOARD_INDICATOR_RE.search(source) and not _FORM_INDICATOR_RE.search(source):
        return "custom_component"

    # Page component: renders ConfigurableForm or ConfigurableDashboard
    if _DASHBOARD_INDICATOR_RE.search(source) or _FORM_INDICATOR_RE.search(source):
        return "page_component"

    if file_name.endswith((".tsx", ".jsx")):
        return "page_component"

    return "unknown"


def _detect_dashboard_features(source: str) -> dict[str, Any]:
    """
    Return a dict of boolean feature flags for a ConfigurableDashboard example.

    Enhanced over the old approach:
    • Compiled regex constants (no per-call compilation).
    • Multi-select filter type detection.
    • Stricter boolean checks (avoids false positives from comments).
    """
    has_filters = bool(_FILTER_KEY_RE.search(source))
    has_actions = bool(_ACTION_KEY_RE.search(source))

    filter_types: list[str] = []
    if has_filters:
        if _FILTER_SELECT_RE.search(source):
            filter_types.append("select")
        if _FILTER_DATE_RE.search(source):
            filter_types.append("date_range")
        if _FILTER_TEXT_RE.search(source):
            filter_types.append("text")
        if _FILTER_MULTISELECT_RE.search(source):
            filter_types.append("multiselect")

    return {
        "has_search":           bool(_HAS_SEARCH_RE.search(source)),
        "has_filters":          has_filters,
        "has_actions":          has_actions,
        "has_list_view":        bool(_LIST_PROPS_RE.search(source)),
        "has_mode_switch":      bool(_MODE_SWITCH_RE.search(source)),
        "has_pagination":       bool(_PAGINATION_RE.search(source)),
        "has_advance_filters":  bool(_ADVANCE_FILTER_RE.search(source)),
        "has_api_integration":  bool(_API_OBJECT_RE.search(source) or _API_MAPPER_RE.search(source)),
        "has_row_selection":    bool(_ROW_SELECT_RE.search(source)),
        "filter_types":         filter_types,
    }


def _detect_form_features(source: str) -> dict[str, Any]:
    """
    Return a dict of boolean feature flags for a ConfigurableForm example.

    Enhanced over the old approach:
    • Extended ``_KNOWN_FORM_FIELD_TYPES`` with ``datepicker`` and ``autocomplete``.
    • Stricter custom-validator name extraction via pre-compiled regex.
    • Cleaner type de-duplication with a set.
    """
    has_custom_validators = bool(_CUSTOM_VALIDATORS_RE.search(source))

    custom_validator_names: list[str] = []
    if has_custom_validators:
        cv_match = _CV_BLOCK_RE.search(source)
        if cv_match:
            custom_validator_names = _CV_NAME_RE.findall(cv_match.group(1))

    raw_types = _FIELD_TYPE_RE.findall(source)
    field_types = sorted({t for t in raw_types if t in _KNOWN_FORM_FIELD_TYPES})

    return {
        "has_sections":               bool(_SECTIONS_RE.search(source)),
        "has_nested_groups":          bool(_NESTED_GROUP_RE.search(source)),
        "has_custom_validators":      has_custom_validators,
        "custom_validator_names":     custom_validator_names,
        "has_custom_component":       bool(_CUSTOM_COMPONENT_RE.search(source)),
        "has_conditional_visibility": bool(_VISIBLE_IF_RE.search(source)),
        "has_conditional_validation": bool(_REQUIRED_IF_RE.search(source)),
        "has_dependent_fields":       bool(_DEPENDS_RE.search(source)),
        "has_file_upload":            bool(_FILE_UPLOAD_RE.search(source)),
        "field_types_used":           field_types,
    }


def _detect_complexity(source: str, file_role: str, features: dict[str, Any]) -> str:
    """
    Classify example complexity as ``"simple"``, ``"medium"``, or ``"complex"``.

    Scoring approach:
    • Types files   — counted by the number of colon characters.
    • Config files  — each active feature flag adds 1 point.
    • Page/custom   — counts local state hooks and JSX depth as signals.
    """
    if file_role == "types":
        colon_count = source.count(":")
        if colon_count > 20:
            return "complex"
        if colon_count > 10:
            return "medium"
        return "simple"

    if file_role == "config":
        score = sum(1 for k, v in features.items() if isinstance(v, bool) and v)
        if score >= 4:
            return "complex"
        if score >= 2:
            return "medium"
        return "simple"

    if file_role in ("page_component", "custom_component"):
        has_state = "useState" in source
        has_effect = "useEffect" in source
        multiple_jsx = source.count("return (") > 1 or source.count("<div") > 5
        score = sum([has_state, has_effect, multiple_jsx])
        if score >= 2:
            return "medium"
        return "simple"

    return "simple"


def _generate_use_case(
    example_id: str,
    example_pattern: str,
    file_role: str,
    features: dict[str, Any],
    symbol_name: str = "",
) -> str:
    """
    Auto-generate a concise, human-readable ``use_case`` description.

    Enhanced: only appends feature labels when the flag is True, avoiding
    misleading use-case strings for files that don't directly use a feature.
    """
    parts: list[str] = []

    if example_pattern == "ConfigurableDashboard":
        parts.append("Dashboard")
        if features.get("has_search"):
            parts.append("with search")
        if features.get("has_filters"):
            ftypes = features.get("filter_types") or []
            parts.append(f"with {'/'.join(ftypes)} filters" if ftypes else "with filters")
        if features.get("has_advance_filters"):
            parts.append("with advanced filter modal")
        if features.get("has_actions"):
            parts.append("with bulk actions")
        if features.get("has_list_view"):
            parts.append("with card/list view toggle")
        if features.get("has_mode_switch"):
            parts.append("with table/grid mode switch")
        if features.get("has_pagination"):
            parts.append("with pagination")
        if features.get("has_row_selection"):
            parts.append("with row selection")
        if features.get("has_api_integration"):
            parts.append("with API integration")

    elif example_pattern == "ConfigurableForm":
        parts.append("Form")
        ftypes = features.get("field_types_used") or []
        if ftypes:
            parts.append(f"with {', '.join(ftypes[:4])} fields")
        if features.get("has_sections"):
            parts.append("with sections")
        if features.get("has_nested_groups"):
            parts.append("with nested group sections")
        if features.get("has_custom_validators"):
            names = features.get("custom_validator_names") or []
            parts.append(f"with custom validators ({', '.join(names[:3])})" if names else "with custom validators")
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

    role_prefix_map = {
        "page_component":   f"{example_id} page component: ",
        "config":           f"{example_id} config: ",
        "types":            f"{example_id} type definitions: ",
        "custom_component": f"{example_id} custom component ({symbol_name}): ",
        "summary":          f"{example_id}: ",
    }
    prefix = role_prefix_map.get(file_role, f"{example_id}: ")

    body = ", ".join(parts) if parts else example_pattern
    return prefix + body


# ---------------------------------------------------------------------------
# Public API: chunk_example_file
# ---------------------------------------------------------------------------

def chunk_example_file(
    source: str,
    file_path: str,
    file_name: str,
    example_id: str,
    example_group: str,
) -> list[ChunkResult]:
    """
    Chunk a single correct_code_examples file.

    Always returns **exactly one** :class:`ChunkResult` representing the whole
    file.  Example files are semantically atomic — splitting them would break
    the connection between config and component code.

    The feature-detection result is embedded in the enriched ``text_to_embed``
    so that high-level queries (e.g. "form with file upload") match correctly.
    """
    ext = Path(file_name).suffix.lower()
    example_pattern = _detect_example_pattern(source, file_path)
    file_role = _detect_file_role(file_name, source)
    msbc_symbols, msbc_packages = extract_msbc_imports(source)
    all_exports = extract_file_exports(source)

    features: dict[str, Any] = {}
    if example_pattern == "ConfigurableDashboard":
        features = _detect_dashboard_features(source)
    elif example_pattern == "ConfigurableForm":
        features = _detect_form_features(source)

    complexity = _detect_complexity(source, file_role, features)
    use_case = _generate_use_case(example_id, example_pattern, file_role, features)

    # Enriched embed text for examples: metadata header + full source
    feature_labels = [k for k, v in features.items() if isinstance(v, bool) and v]
    embed_lines = [
        f"[{example_id} / {file_role}] {example_pattern} example — {example_group}",
        f"File: {file_name} | Complexity: {complexity}",
        f"Use case: {use_case}",
    ]
    if feature_labels:
        embed_lines.append(f"Features: {', '.join(feature_labels)}")
    if msbc_symbols:
        embed_lines.append(f"MSBC imports: {', '.join(msbc_symbols[:8])}")
    embed_lines.append(f"Exports: {', '.join(all_exports[:8])}")
    embed_lines.append("---")
    embed_lines.append(source)
    embed_text = "\n".join(embed_lines)

    language: str
    if ext == ".tsx":
        language = "tsx"
    elif ext == ".ts":
        language = "typescript"
    else:
        language = "unknown"

    cid = make_chunk_id(file_path, 0)

    return [ChunkResult(
        text=source,
        text_to_embed=embed_text,
        chunk_id=cid,
        chunk_index=0,
        symbol_name=Path(file_name).stem,
        chunk_type="module",
        chunk_exports=all_exports,
        token_count=count_tokens_approx(source),
    )]


# ---------------------------------------------------------------------------
# Public API: build_example_summary_chunk
# ---------------------------------------------------------------------------

def build_example_summary_chunk(
    example_id: str,
    example_pattern: str,
    use_case: str,
    features: dict[str, Any],
    file_list: list[str],
    complexity: str,
) -> ChunkResult:
    """
    Build a synthetic *summary chunk* for an example folder.

    This chunk contains **no source code** — it is a natural-language
    description of the entire example set.  It serves as the semantic
    entry-point when agents run broad queries such as
    "show me a dashboard with search and advanced filters".

    The ``is_summary_chunk`` flag in :class:`ExampleChunkPayload` marks it
    so ingestors can handle it separately (e.g. skip file_hash comparison).

    Parameters
    ----------
    example_id      : Folder-level identifier, e.g. ``"Dashboard03"``.
    example_pattern : ``"ConfigurableDashboard"`` or ``"ConfigurableForm"``.
    use_case        : Human-readable description of what this example shows.
    features        : Feature dict from the config/page file in this folder.
    file_list       : All file names in this example folder.
    complexity      : ``"simple"``, ``"medium"``, or ``"complex"``.
    """
    active_features = [
        k.replace("has_", "").replace("_", " ")
        for k, v in features.items()
        if isinstance(v, bool) and v
    ]

    field_types = features.get("field_types_used") or []
    filter_types = features.get("filter_types") or []

    lines: list[str] = [
        f"[{example_id}] Complete {example_pattern} example",
        f"Use case: {use_case}",
        f"Complexity: {complexity}",
        f"Files in this example: {', '.join(file_list)}",
    ]

    if active_features:
        feature_bullets = "\n".join(f"  • {f}" for f in active_features)
        lines.append(f"Features:\n{feature_bullets}")

    if field_types:
        lines.append(f"Form field types: {', '.join(field_types)}")

    if filter_types:
        lines.append(f"Filter types: {', '.join(filter_types)}")

    summary_text = "\n".join(lines)

    # Synthetic chunk_id — use the example_id + sentinel index 9999
    # so it never collides with real file chunks
    cid = make_chunk_id(f"examples/{example_id}/__summary__", 9999)

    return ChunkResult(
        text=summary_text,
        text_to_embed=summary_text,  # no code — text IS the embed text
        chunk_id=cid,
        chunk_index=9999,
        symbol_name=example_id,
        chunk_type="summary",
        chunk_exports=[],
        token_count=count_tokens_approx(summary_text),
    )
