"""
Multi-strategy chunker for the 3-collection RAG pipeline.

Strategies
──────────
  chunk_code_file()      — TypeScript/JSX AST chunking via tree-sitter (→ code collection)
  chunk_markdown_file()  — Heading-aware doc chunking with mention extraction (→ docs collection)
  chunk_style_file()     — CSS / SCSS at-rule + selector chunking (→ code collection)
  chunk_interfaces()     — Per-interface / per-type extraction (→ config collection)
  chunk_json_config()    — JSON schema chunking (→ config collection)
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

# ── Chunk dataclass ───────────────────────────────────────────────────────────

@dataclass
class Chunk:
    text: str
    chunk_id: str
    component_name: str
    chunk_type: str                     # "function_component" | "hook" | "interface" | "section" | …
    chunk_index: int = 0
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    props: List[str] = field(default_factory=list)
    # ── doc-chunk extras ──
    heading_level: int = 0
    parent_section: str = ""
    section_path: str = ""
    has_code_example: bool = False
    code_language: str = ""
    example_count: int = 0
    mentioned_components: List[str] = field(default_factory=list)
    mentioned_packages: List[str] = field(default_factory=list)
    # ── config-chunk extras ──
    config_type: str = ""               # "interface" | "type_alias" | "enum" | "json_schema"
    schema_name: str = ""
    fields: List[str] = field(default_factory=list)
    field_count: int = 0
    extends: List[str] = field(default_factory=list)


def _make_chunk_id(file_path: str, index: int, text: str) -> str:
    """Stable, deterministic SHA-256-based ID (first 16 hex chars)."""
    content = f"{file_path}::{index}::{text}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _determine_chunk_type(name: str, keyword: str) -> str:
    if keyword == "class":
        return "class"
    if keyword == "interface":
        return "interface"
    if keyword == "type_alias":
        return "type_alias"
    if keyword == "enum":
        return "enum"
    if name.startswith("use") and len(name) > 3 and name[3].isupper():
        return "hook"
    if name and name[0].isupper():
        return "function_component"
    return "utility"


# ── Tree-sitter based parsing (primary) ──────────────────────────────────────

# ── Tree-sitter language helpers ──────────────────────────────────────────────

def _get_ts_language():
    """Return the tree-sitter TypeScript+TSX language (parses JSX too)."""
    from tree_sitter import Language
    import tree_sitter_typescript as tsts
    return Language(tsts.language_tsx())


def _get_js_language():
    """Fallback: plain JavaScript grammar."""
    from tree_sitter import Language
    import tree_sitter_javascript as tsjs
    return Language(tsjs.language())


def _extract_props(params_node) -> List[str]:
    """Extract prop names from formal_parameters or object_pattern node."""
    if params_node is None:
        return []
    target = params_node
    if params_node.type == "formal_parameters":
        for child in params_node.named_children:
            if child.type == "object_pattern":
                target = child
                break
        else:
            return []
    if target.type != "object_pattern":
        return []
    props: List[str] = []
    for child in target.named_children:
        if child.type == "shorthand_property_identifier_pattern":
            props.append(child.text.decode("utf-8"))
        elif child.type == "object_assignment_pattern":
            # e.g. variant = "primary"  →  first named child is the key
            key = child.named_children[0] if child.named_children else None
            if key and key.type == "shorthand_property_identifier_pattern":
                props.append(key.text.decode("utf-8"))
        elif child.type == "pair_pattern":
            key = child.child_by_field_name("key")
            if key:
                props.append(key.text.decode("utf-8"))
        elif child.type == "rest_pattern":
            for c in child.named_children:
                if c.type == "identifier":
                    props.append(f"...{c.text.decode('utf-8')}")
    return props


def _extract_exports(root) -> List[str]:
    """Collect all exported names from top-level export_statement nodes."""
    exports: List[str] = []
    for node in root.named_children:
        if node.type != "export_statement":
            continue
        for child in node.named_children:
            if child.type == "identifier":
                exports.append(child.text.decode("utf-8"))
            elif child.type in ("function_declaration", "class_declaration"):
                name = child.child_by_field_name("name")
                if name:
                    exports.append(name.text.decode("utf-8"))
            elif child.type in ("lexical_declaration", "variable_declaration"):
                for dc in child.named_children:
                    if dc.type == "variable_declarator":
                        name = dc.child_by_field_name("name")
                        if name:
                            exports.append(name.text.decode("utf-8"))
    return exports


def _iter_top_level_decls(root) -> List[Tuple[int, str, str, List[str]]]:
    """
    Walk the top-level AST children and return
    (start_byte, name, kw, props) for every named declaration.
    Unwraps export_statement wrappers transparently.
    Handles: functions, classes, interfaces, type aliases, enums.
    """
    results: List[Tuple[int, str, str, List[str]]] = []

    for node in root.named_children:
        ntype = node.type
        # skip imports, comments, hash-bangs
        if ntype in ("import_statement", "comment", "hash_bang_line"):
            continue

        # unwrap `export const/function/class …`
        actual = node
        if ntype == "export_statement":
            inner = None
            for child in node.named_children:
                if child.type in (
                    "lexical_declaration", "variable_declaration",
                    "function_declaration", "class_declaration",
                    "interface_declaration", "type_alias_declaration",
                    "enum_declaration",
                ):
                    inner = child
                    break
            if inner is None:
                # plain `export default X;` or `export { X }` — not a new chunk
                continue
            actual = inner

        atype = actual.type

        if atype in ("lexical_declaration", "variable_declaration"):
            for child in actual.named_children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    value_node = child.child_by_field_name("value")
                    if name_node:
                        name = name_node.text.decode("utf-8")
                        is_func = (
                            value_node is not None
                            and value_node.type in ("arrow_function", "function_expression")
                        )
                        kw = "function" if is_func else "variable"
                        props: List[str] = []
                        if value_node and value_node.type == "arrow_function":
                            params = (
                                value_node.child_by_field_name("parameters")
                                or value_node.child_by_field_name("parameter")
                            )
                            props = _extract_props(params)
                        results.append((node.start_byte, name, kw, props))
                    break  # only process the first declarator

        elif atype == "function_declaration":
            name_node = actual.child_by_field_name("name")
            if name_node:
                params = actual.child_by_field_name("parameters")
                results.append((
                    node.start_byte,
                    name_node.text.decode("utf-8"),
                    "function",
                    _extract_props(params),
                ))

        elif atype == "class_declaration":
            name_node = actual.child_by_field_name("name")
            if name_node:
                results.append((node.start_byte, name_node.text.decode("utf-8"), "class", []))

        elif atype == "interface_declaration":
            name_node = actual.child_by_field_name("name")
            if name_node:
                results.append((node.start_byte, name_node.text.decode("utf-8"), "interface", []))

        elif atype == "type_alias_declaration":
            name_node = actual.child_by_field_name("name")
            if name_node:
                results.append((node.start_byte, name_node.text.decode("utf-8"), "type_alias", []))

        elif atype == "enum_declaration":
            name_node = actual.child_by_field_name("name")
            if name_node:
                results.append((node.start_byte, name_node.text.decode("utf-8"), "enum", []))

    return results


def _ts_chunk_react(source: str, file_stem: str, file_path: str) -> List[Chunk]:
    """AST-accurate semantic chunking via tree-sitter TypeScript+TSX."""
    from tree_sitter import Parser

    try:
        parser = Parser(_get_ts_language())
    except Exception:
        # Fallback to JS grammar if TS not installed
        parser = Parser(_get_js_language())

    tree = parser.parse(source.encode())
    root = tree.root_node

    import_texts: List[str] = [
        source[n.start_byte : n.end_byte]
        for n in root.named_children
        if n.type == "import_statement"
    ]
    all_exports = _extract_exports(root)
    declarations = _iter_top_level_decls(root)

    if not declarations:
        chunk_id = _make_chunk_id(file_path, 0, source)
        return [
            Chunk(
                text=source.strip(),
                chunk_id=chunk_id,
                component_name=file_stem,
                chunk_type="module",
                chunk_index=0,
                imports=import_texts,
                exports=all_exports,
            )
        ]

    import_prefix = "\n".join(import_texts) + "\n\n" if import_texts else ""
    # preamble = everything before the first declaration (file comment + imports)
    preamble_text = source[: declarations[0][0]].rstrip()

    chunks: List[Chunk] = []
    for i, (start, name, kw, props) in enumerate(declarations):
        seg_end = declarations[i + 1][0] if i + 1 < len(declarations) else len(source)
        segment = source[start:seg_end].strip()
        if not segment:
            continue
        if i == 0:
            # First chunk: prepend full preamble (comment + imports) for context
            if preamble_text:
                segment = preamble_text + "\n\n" + segment
        else:
            # Subsequent chunks: prepend imports only so chunk is self-contained
            if import_prefix:
                segment = import_prefix + segment

        chunk_type = _determine_chunk_type(name, kw)
        chunk_id = _make_chunk_id(file_path, i, segment)
        chunks.append(
            Chunk(
                text=segment,
                chunk_id=chunk_id,
                component_name=name,
                chunk_type=chunk_type,
                chunk_index=i,
                imports=import_texts,
                exports=[name] if name in all_exports else [],
                props=props,
            )
        )

    return chunks or [
        Chunk(
            text=source.strip(),
            chunk_id=_make_chunk_id(file_path, 0, source),
            component_name=file_stem,
            chunk_type="module",
            chunk_index=0,
            imports=import_texts,
            exports=all_exports,
        )
    ]


# ── Regex fallback (used when tree-sitter unavailable) ───────────────────────

_TOP_LEVEL_RE = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?P<kw>const|let|var|function|class)\s+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)


def _regex_chunk_react(source: str, file_stem: str, file_path: str) -> List[Chunk]:
    """Fallback: regex-based chunking when tree-sitter is unavailable."""
    boundaries: List[Tuple[int, str, str]] = []
    for m in _TOP_LEVEL_RE.finditer(source):
        line_start = source.rfind("\n", 0, m.start()) + 1
        if m.start() - line_start != 0:
            continue
        if source[line_start:].lstrip().startswith("import"):
            continue
        boundaries.append((m.start(), m.group("name"), m.group("kw")))

    if not boundaries:
        chunk_id = _make_chunk_id(file_path, 0, source)
        return [
            Chunk(
                text=source.strip(),
                chunk_id=chunk_id,
                component_name=file_stem,
                chunk_type="module",
                chunk_index=0,
            )
        ]

    preamble = source[: boundaries[0][0]]
    chunks: List[Chunk] = []
    for i, (start, name, kw) in enumerate(boundaries):
        seg_end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(source)
        segment = source[start:seg_end].strip()
        if not segment:
            continue
        if i == 0 and preamble.strip():
            segment = preamble.rstrip() + "\n\n" + segment
        chunk_type = _determine_chunk_type(name, kw)
        chunk_id = _make_chunk_id(file_path, i, segment)
        chunks.append(
            Chunk(
                text=segment,
                chunk_id=chunk_id,
                component_name=name,
                chunk_type=chunk_type,
                chunk_index=i,
            )
        )

    return chunks or [
        Chunk(
            text=source.strip(),
            chunk_id=_make_chunk_id(file_path, 0, source),
            component_name=file_stem,
            chunk_type="module",
            chunk_index=0,
        )
    ]


# ── Public API — Code chunking ────────────────────────────────────────────────

def chunk_code_file(
    source: str,
    file_path: str,
    file_stem: Optional[str] = None,
) -> List[Chunk]:
    """Chunk a React/JS/TS file.  Uses tree-sitter AST; falls back to regex.

    Parameters
    ----------
    source : str
        The full file content (already read by scanner).
    file_path : str
        Relative monorepo path, used for chunk IDs.
    file_stem : str, optional
        Used as component_name fallback.  Defaults to the file stem of *file_path*.
    """
    stem = file_stem or Path(file_path).stem
    try:
        chunks = _ts_chunk_react(source, stem, file_path)
        logger.debug("tree-sitter chunked %s → %d chunks", Path(file_path).name, len(chunks))
    except Exception as exc:
        logger.warning(
            "tree-sitter failed for %s (%s); falling back to regex.", Path(file_path).name, exc
        )
        chunks = _regex_chunk_react(source, stem, file_path)
    return _apply_size_bounds(chunks, file_path)


def _apply_size_bounds(chunks: List[Chunk], file_path: str) -> List[Chunk]:
    """
    Post-process a list of chunks to enforce MIN/MAX size bounds.

    • Chunks < MIN_CHUNK_CHARS are merged forward into the next chunk
      (or backward into the previous if they are the last chunk).
    • Chunks > MAX_CHUNK_CHARS are split at the last blank line before
      the limit so we never cut mid-expression.
    """
    if not chunks:
        return chunks

    # ── Pass 1: merge tiny chunks forward ────────────────────────────
    merged: List[Chunk] = []
    pending_text: str = ""
    for i, chunk in enumerate(chunks):
        combined = (pending_text + "\n\n" + chunk.text).strip() if pending_text else chunk.text
        if len(combined) < MIN_CHUNK_CHARS and i < len(chunks) - 1:
            # Too small and not last — accumulate into pending
            pending_text = combined
        else:
            if pending_text:
                # Absorb accumulated pending text into this chunk
                combined = (pending_text + "\n\n" + chunk.text).strip()
                pending_text = ""
            else:
                combined = chunk.text
            merged.append(
                Chunk(
                    text=combined,
                    chunk_id=_make_chunk_id(file_path, len(merged), combined),
                    component_name=chunk.component_name,
                    chunk_type=chunk.chunk_type,
                    chunk_index=len(merged),
                    imports=chunk.imports,
                    exports=chunk.exports,
                    props=chunk.props,
                    heading_level=chunk.heading_level,
                    parent_section=chunk.parent_section,
                    section_path=chunk.section_path,
                    has_code_example=chunk.has_code_example,
                    code_language=chunk.code_language,
                    example_count=chunk.example_count,
                    mentioned_components=chunk.mentioned_components,
                    mentioned_packages=chunk.mentioned_packages,
                    config_type=chunk.config_type,
                    schema_name=chunk.schema_name,
                    fields=chunk.fields,
                    field_count=chunk.field_count,
                    extends=chunk.extends,
                )
            )
    # If a trailing pending_text was never flushed (shouldn't happen, but guard)
    if pending_text and merged:
        last = merged[-1]
        combined = (last.text + "\n\n" + pending_text).strip()
        merged[-1] = Chunk(
            text=combined,
            chunk_id=_make_chunk_id(file_path, len(merged) - 1, combined),
            component_name=last.component_name,
            chunk_type=last.chunk_type,
            chunk_index=last.chunk_index,
            imports=last.imports,
            exports=last.exports,
            props=last.props,
            heading_level=last.heading_level,
            parent_section=last.parent_section,
            section_path=last.section_path,
            has_code_example=last.has_code_example,
            code_language=last.code_language,
            example_count=last.example_count,
            mentioned_components=last.mentioned_components,
            mentioned_packages=last.mentioned_packages,
            config_type=last.config_type,
            schema_name=last.schema_name,
            fields=last.fields,
            field_count=last.field_count,
            extends=last.extends,
        )
    elif pending_text and not merged:
        # Edge case: entire file was tiny
        chunk_id = _make_chunk_id(file_path, 0, pending_text)
        return [Chunk(text=pending_text, chunk_id=chunk_id,
                      component_name="module", chunk_type="module", chunk_index=0)]

    # ── Pass 2: split oversized chunks at blank-line boundaries ──────
    result: List[Chunk] = []
    for chunk in merged:
        if len(chunk.text) <= MAX_CHUNK_CHARS:
            result.append(chunk)
            continue
        # Split at last blank line before MAX_CHUNK_CHARS
        text = chunk.text
        while len(text) > MAX_CHUNK_CHARS:
            split_pos = text.rfind("\n\n", 0, MAX_CHUNK_CHARS)
            if split_pos == -1:
                # No blank line — split at last newline before limit
                split_pos = text.rfind("\n", 0, MAX_CHUNK_CHARS)
            if split_pos == -1 or split_pos == 0:
                # No safe split point — keep as-is to avoid infinite loop
                break
            part = text[:split_pos].strip()
            if part:
                idx = len(result)
                result.append(
                    Chunk(
                        text=part,
                        chunk_id=_make_chunk_id(file_path, idx, part),
                        component_name=chunk.component_name,
                        chunk_type=chunk.chunk_type,
                        chunk_index=idx,
                        imports=chunk.imports,
                        exports=chunk.exports,
                        props=chunk.props,
                        heading_level=chunk.heading_level,
                        parent_section=chunk.parent_section,
                        section_path=chunk.section_path,
                        has_code_example=chunk.has_code_example,
                        code_language=chunk.code_language,
                        example_count=chunk.example_count,
                        mentioned_components=chunk.mentioned_components,
                        mentioned_packages=chunk.mentioned_packages,
                        config_type=chunk.config_type,
                        schema_name=chunk.schema_name,
                        fields=chunk.fields,
                        field_count=chunk.field_count,
                        extends=chunk.extends,
                    )
                )
            text = text[split_pos:].strip()
        if text:
            idx = len(result)
            result.append(
                Chunk(
                    text=text,
                    chunk_id=_make_chunk_id(file_path, idx, text),
                    component_name=chunk.component_name,
                    chunk_type=chunk.chunk_type,
                    chunk_index=idx,
                    imports=chunk.imports,
                    exports=chunk.exports,
                    props=chunk.props,
                    heading_level=chunk.heading_level,
                    parent_section=chunk.parent_section,
                    section_path=chunk.section_path,
                    has_code_example=chunk.has_code_example,
                    code_language=chunk.code_language,
                    example_count=chunk.example_count,
                    mentioned_components=chunk.mentioned_components,
                    mentioned_packages=chunk.mentioned_packages,
                    config_type=chunk.config_type,
                    schema_name=chunk.schema_name,
                    fields=chunk.fields,
                    field_count=chunk.field_count,
                    extends=chunk.extends,
                )
            )

    # Re-number chunk_index sequentially
    for i, c in enumerate(result):
        c.chunk_index = i

    return result


# Backward compat alias (reads file from disk)
def chunk_react_file(file_path: str) -> List[Chunk]:
    """Legacy: reads file from disk, then chunks it."""
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to read %s: %s", file_path, exc)
        return []
    return chunk_code_file(source, file_path, path.stem)


# ── Public API — Markdown / Doc chunking ──────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,3}\s+.+)$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```(\w+)?.*?```", re.DOTALL)
_COMPONENT_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")   # PascalCase

# ── Chunk size bounds (applied uniformly across all strategies) ───────────────
# A chunk smaller than MIN_CHUNK_CHARS carries almost no semantic signal and
# inflates the collection with noise vectors.
# A chunk larger than MAX_CHUNK_CHARS overflows most embedding context windows.
MIN_CHUNK_CHARS: int = 80    # ~20 tokens — below this we merge into the next chunk
MAX_CHUNK_CHARS: int = 6000  # ~1500 tokens — above this we split at a safe boundary

_MAX_CHARS: int = MAX_CHUNK_CHARS  # keep old name working


def _extract_mentions(text: str) -> Tuple[List[str], List[str]]:
    """Extract mentioned component names and package names from text."""
    components = sorted(set(_COMPONENT_NAME_RE.findall(text)))
    packages = sorted(pkg for pkg in _KNOWN_PACKAGES if pkg in text)
    return components, packages


def _count_code_blocks(text: str) -> Tuple[int, str]:
    """Return (count, dominant_language) for fenced code blocks in text."""
    blocks = _CODE_BLOCK_RE.findall(text)
    if not blocks:
        return 0, ""
    langs = [b.strip() for b in blocks if b.strip()]
    dominant = max(set(langs), key=langs.count) if langs else ""
    return len(blocks), dominant


def chunk_markdown_file(
    source: str,
    file_path: str,
    file_stem: Optional[str] = None,
) -> List[Chunk]:
    """
    Split a Markdown file by H1/H2/H3 headings into bounded chunks,
    with hierarchy tracking and mention extraction.
    """
    stem = file_stem or Path(file_path).stem

    # Strip YAML frontmatter (--- ... ---) so it doesn't pollute the first chunk
    source = _FRONTMATTER_RE.sub("", source, count=1)

    positions = [m.start() for m in _HEADING_RE.finditer(source)]

    if not positions:
        chunk_id = _make_chunk_id(file_path, 0, source)
        comps, pkgs = _extract_mentions(source)
        ex_count, ex_lang = _count_code_blocks(source)
        return [
            Chunk(
                text=source.strip(),
                chunk_id=chunk_id,
                component_name=stem,
                chunk_type="section",
                chunk_index=0,
                has_code_example=ex_count > 0,
                code_language=ex_lang,
                example_count=ex_count,
                mentioned_components=comps,
                mentioned_packages=pkgs,
            )
        ]

    # Build heading hierarchy for section_path
    heading_stack: List[Tuple[int, str]] = []  # [(level, title), ...]
    chunks: List[Chunk] = []

    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(source)
        text = source[start:end].strip()
        if not text:
            continue

        # Parse heading
        heading_line = text.split("\n")[0]
        m = re.match(r"^(#{1,3})\s+(.+)$", heading_line)
        level = len(m.group(1)) if m else 1
        section_name = m.group(2).strip() if m else stem

        # Maintain hierarchy stack
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        parent_section = heading_stack[-1][1] if heading_stack else ""
        heading_stack.append((level, section_name))
        section_path = " > ".join(title for _, title in heading_stack)

        # Extract richness metadata
        comps, pkgs = _extract_mentions(text)
        ex_count, ex_lang = _count_code_blocks(text)

        chunk_id = _make_chunk_id(file_path, i, text)
        chunks.append(
            Chunk(
                text=text,
                chunk_id=chunk_id,
                component_name=section_name,
                chunk_type="section",
                chunk_index=i,
                heading_level=level,
                parent_section=parent_section,
                section_path=section_path,
                has_code_example=ex_count > 0,
                code_language=ex_lang,
                example_count=ex_count,
                mentioned_components=comps,
                mentioned_packages=pkgs,
            )
        )

    # Apply size bounds: merge tiny heading-only sections, split huge ones
    return _apply_size_bounds(chunks, file_path)


# ── Public API — CSS / SCSS chunking ──────────────────────────────────────────

_CSS_BLOCK_RE = re.compile(
    r"""
    (                   # capture whole block
      (?:               # optional leading comments
        /\*.*?\*/\s*    #   block comment
        | //[^\n]*\n\s* #   line comment
      )*
      [^{}/]+           # selector / @rule
      \{                # opening brace
        (?:             # body (with nested braces)
          [^{}]
          | \{[^{}]*\}
        )*
      \}                # closing brace
    )
    """,
    re.DOTALL | re.VERBOSE,
)

_CSS_VARIABLE_BLOCK_RE = re.compile(r":root\s*\{[^}]*\}", re.DOTALL)


def chunk_style_file(
    source: str,
    file_path: str,
    file_stem: Optional[str] = None,
) -> List[Chunk]:
    """
    Chunk a CSS / SCSS file by top-level selectors / @-rules.

    Always splits by selector first, then _apply_size_bounds() merges
    tiny single-line rules and splits any accidentally huge blocks.
    The old hard 2000-char threshold caused either one giant chunk (small
    files) or dozens of 1-line chunks, both are now avoided.
    """
    stem = file_stem or Path(file_path).stem

    blocks = _CSS_BLOCK_RE.findall(source)
    if not blocks:
        return [
            Chunk(
                text=source.strip(),
                chunk_id=_make_chunk_id(file_path, 0, source),
                component_name=stem,
                chunk_type="style",
                chunk_index=0,
            )
        ]

    raw_chunks: List[Chunk] = []
    for i, block_text in enumerate(blocks):
        block_text = block_text.strip()
        if not block_text:
            continue
        # Extract selector name for component_name
        sel_match = re.match(r"[.#@\w][\w\-]*", block_text)
        name = sel_match.group(0) if sel_match else stem
        raw_chunks.append(
            Chunk(
                text=block_text,
                chunk_id=_make_chunk_id(file_path, i, block_text),
                component_name=name,
                chunk_type="style",
                chunk_index=i,
            )
        )

    if not raw_chunks:
        return [
            Chunk(
                text=source.strip(),
                chunk_id=_make_chunk_id(file_path, 0, source),
                component_name=stem,
                chunk_type="style",
                chunk_index=0,
            )
        ]

    # Merge tiny selector chunks and split oversized ones
    return _apply_size_bounds(raw_chunks, file_path)


# ── Public API — Interface / Type chunking (→ config collection) ──────────────

def chunk_interfaces(
    source: str,
    file_path: str,
    file_stem: Optional[str] = None,
) -> List[Chunk]:
    """
    Extract each interface / type alias / enum as a separate chunk.
    Uses tree-sitter to find boundaries, then returns per-definition chunks
    with fields and extends metadata populated.
    """
    stem = file_stem or Path(file_path).stem

    try:
        from tree_sitter import Parser
        try:
            parser = Parser(_get_ts_language())
        except Exception:
            parser = Parser(_get_js_language())

        tree = parser.parse(source.encode())
        root = tree.root_node
    except Exception as exc:
        logger.warning("tree-sitter unavailable for interface chunking (%s); using regex", exc)
        return _regex_chunk_interfaces(source, file_path, stem)

    chunks: List[Chunk] = []
    idx = 0

    for node in root.named_children:
        actual = node
        if node.type == "export_statement":
            for child in node.named_children:
                if child.type in (
                    "interface_declaration", "type_alias_declaration", "enum_declaration",
                ):
                    actual = child
                    break
            else:
                continue

        atype = actual.type
        if atype not in ("interface_declaration", "type_alias_declaration", "enum_declaration"):
            continue

        name_node = actual.child_by_field_name("name")
        if not name_node:
            continue

        name = name_node.text.decode("utf-8")
        text = source[node.start_byte:node.end_byte].strip()

        # Extract field names from the body
        fields: List[str] = []
        extends: List[str] = []

        if atype == "interface_declaration":
            config_type = "interface"
            body = actual.child_by_field_name("body")
            if body:
                for prop in body.named_children:
                    if prop.type in ("property_signature", "method_signature"):
                        pname = prop.child_by_field_name("name")
                        if pname:
                            fields.append(pname.text.decode("utf-8"))
            # Check for extends
            for child in actual.named_children:
                if child.type == "extends_type_clause":
                    for ext_child in child.named_children:
                        if ext_child.type in ("type_identifier", "generic_type"):
                            extends.append(ext_child.text.decode("utf-8"))

        elif atype == "type_alias_declaration":
            config_type = "type_alias"
            # For object-literal types, extract property names
            value = actual.child_by_field_name("value")
            if value and value.type == "object_type":
                for prop in value.named_children:
                    if prop.type == "property_signature":
                        pname = prop.child_by_field_name("name")
                        if pname:
                            fields.append(pname.text.decode("utf-8"))

        elif atype == "enum_declaration":
            config_type = "enum"
            body = actual.child_by_field_name("body")
            if body:
                for member in body.named_children:
                    if member.type == "enum_assignment":
                        member_name = member.child_by_field_name("name")
                        if member_name:
                            fields.append(member_name.text.decode("utf-8"))
                    elif member.type == "property_identifier":
                        fields.append(member.text.decode("utf-8"))
        else:
            config_type = "unknown"

        chunk_id = _make_chunk_id(file_path, idx, text)
        chunks.append(
            Chunk(
                text=text,
                chunk_id=chunk_id,
                component_name=name,
                chunk_type=config_type,
                chunk_index=idx,
                config_type=config_type,
                schema_name=name,
                fields=fields,
                field_count=len(fields),
                extends=extends,
            )
        )
        idx += 1

    # Merge single-liner type aliases (e.g. `type VisibleIf = VisibilityRule;`)
    # into neighbouring chunks so they are not standalone noise vectors.
    return _apply_size_bounds(chunks, file_path)


def _regex_chunk_interfaces(source: str, file_path: str, stem: str) -> List[Chunk]:
    """Regex fallback for extracting interfaces / types."""
    pattern = re.compile(
        r"^(?:export\s+)?(?:interface|type|enum)\s+(\w+)",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(source))
    if not matches:
        return []

    chunks: List[Chunk] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        text = source[start:end].strip()
        name = m.group(1)
        chunk_id = _make_chunk_id(file_path, i, text)
        chunks.append(
            Chunk(
                text=text,
                chunk_id=chunk_id,
                component_name=name,
                chunk_type="interface",
                chunk_index=i,
                config_type="interface",
                schema_name=name,
            )
        )
    return _apply_size_bounds(chunks, file_path)


# ── Public API — JSON config chunking (→ config collection) ───────────────────

def chunk_json_config(
    source: str,
    file_path: str,
    file_stem: Optional[str] = None,
) -> List[Chunk]:
    """
    Chunk a JSON file.  Small files become a single chunk;
    large objects are split by top-level key.
    """
    stem = file_stem or Path(file_path).stem
    try:
        data = json.loads(source)
    except json.JSONDecodeError:
        return [
            Chunk(
                text=source.strip(),
                chunk_id=_make_chunk_id(file_path, 0, source),
                component_name=stem,
                chunk_type="json_config",
                chunk_index=0,
                config_type="json_config",
                schema_name=stem,
            )
        ]

    # Small JSON → single chunk
    if len(source) < 3000 or not isinstance(data, dict):
        fields = list(data.keys()) if isinstance(data, dict) else []
        return [
            Chunk(
                text=source.strip(),
                chunk_id=_make_chunk_id(file_path, 0, source),
                component_name=stem,
                chunk_type="json_config",
                chunk_index=0,
                config_type="json_config",
                schema_name=stem,
                fields=fields,
                field_count=len(fields),
            )
        ]

    # Large JSON → one chunk per top-level key, then apply size bounds
    raw_chunks: List[Chunk] = []
    for i, (key, value) in enumerate(data.items()):
        text = json.dumps({key: value}, indent=2)
        raw_chunks.append(
            Chunk(
                text=text,
                chunk_id=_make_chunk_id(file_path, i, text),
                component_name=key,
                chunk_type="json_config",
                chunk_index=i,
                config_type="json_config",
                schema_name=f"{stem}.{key}",
                fields=[key],
                field_count=1,
            )
        )
    return _apply_size_bounds(raw_chunks, file_path)
