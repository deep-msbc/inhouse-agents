"""
code_graph_builder.py
─────────────────────
Scans the ReactToolKits monorepo and builds the code-level Kuzu graph.

What it does
------------
For every .ts / .tsx file inside every package in the monorepo:

1.  Creates a ``SourceFile`` node.
2.  Parses ``import`` and ``export * from`` statements (regex-based, no
    TypeScript compiler needed) to extract:
    - Named imports/re-exports → ``import_specifiers``
    - The import specifier (relative path or @msbc/* package)
3.  Resolves relative import specifiers to the actual ``SourceFile`` id and
    creates ``ImportsFrom`` or ``ReExportsFrom`` edges.
4.  Cross-package @msbc/* imports create ``ImportsPackage`` edges to the
    existing ``Package`` nodes.
5.  Parses ``export`` statements to create ``ExportedSymbol`` nodes +
    ``ExportsSymbol`` edges.
6.  For each ``ExportedSymbol`` whose name matches an existing ``Component``
    node in the semantic graph, creates a ``SymbolLinkedToComponent`` bridge
    edge.
7.  Creates ``FileBelongsTo`` edges (``SourceFile`` → ``Package``).

Call ``build_code_graph(db_path, monorepo_path)`` from scripts/build_rtk_code_graph.py.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import kuzu

from src.msbc.embedding.graph_schema import (
    ALL_DDL,
    DROP_ORDER,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# File extensions we care about.
_TS_EXTS: set[str] = {".ts", ".tsx"}

# File patterns to skip (tests, stories, build output, node_modules).
_SKIP_PATTERNS: set[str] = {
    ".stories.tsx",
    ".stories.ts",
    ".test.ts",
    ".test.tsx",
    ".spec.ts",
    ".spec.tsx",
    "vitest.config.ts",
    "tsup.config.ts",
    "vitest.shims.d.ts",
}

# Directories to ignore entirely.
_SKIP_DIRS: set[str] = {"node_modules", "dist", ".storybook", "__pycache__"}

# ---------------------------------------------------------------------------
# Regex patterns for TypeScript import / export parsing
# ---------------------------------------------------------------------------

# import { X, Y as Z } from './path'  or  import Foo from './path'
# Also handles: import type { … } from '…'
_IMPORT_RE = re.compile(
    r"""^[ \t]*import\s+(?:type\s+)?
        (?:
            \{([^}]*)\}               # named imports  → group 1
            |(\w+)                    # default import → group 2
            |(\*\s+as\s+\w+)         # namespace import → group 3
            |(\{[^}]*\}\s*,\s*\w+)   # combined named + default (rare)
        )?
        \s*(?:,\s*(?:\{[^}]*\}|\w+|\*\s+as\s+\w+))?
        \s*from\s+['"]([^'"]+)['"]   # specifier → last group
    """,
    re.VERBOSE | re.MULTILINE,
)

# export * from './path'
_REEXPORT_STAR_RE = re.compile(
    r"""^[ \t]*export\s+\*\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# export { X, Y } from './path'   (re-export with names)
_REEXPORT_NAMED_RE = re.compile(
    r"""^[ \t]*export\s+\{([^}]*)\}\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# export const/function/class/interface/type/enum Identifier
_EXPORT_DECL_RE = re.compile(
    r"""^[ \t]*export\s+(?:default\s+)?
        (abstract\s+class|class|function\s*\*?|const|let|var|interface|type|enum)\s+
        ([A-Za-z_$][A-Za-z0-9_$]*)
    """,
    re.VERBOSE | re.MULTILINE,
)

# export default function/class (anonymous allowed)
_EXPORT_DEFAULT_RE = re.compile(
    r"""^[ \t]*export\s+default\s+(function|class)\s*([A-Za-z_$][A-Za-z0-9_$]*)?""",
    re.MULTILINE,
)

# export { Foo, Bar }  (without 'from')
_EXPORT_BRACE_RE = re.compile(
    r"""^[ \t]*export\s+\{([^}]*)\}\s*;""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    """Escape single quotes in a Cypher string literal."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _cypher_str_list(items: list[str]) -> str:
    inner = ", ".join(f"'{_esc(i)}'" for i in items)
    return f"[{inner}]"


def _exec(conn: kuzu.Connection, cypher: str) -> None:
    logger.debug("KUZU: %s", cypher.strip()[:140])
    conn.execute(cypher)


def _exec_safe(conn: kuzu.Connection, cypher: str, label: str = "") -> None:
    try:
        conn.execute(cypher)
    except Exception as exc:  # noqa: BLE001
        logger.debug("KUZU [%s] non-fatal: %s | %s", label, exc, cypher.strip()[:80])


# ---------------------------------------------------------------------------
# Monorepo scanning
# ---------------------------------------------------------------------------


def _discover_packages(monorepo_root: Path) -> list[dict[str, Any]]:
    """
    Return a list of package descriptors from the monorepo's ``packages/`` dir.

    Each descriptor:
        {
            "pkg_dir":       Path,          # absolute path to package root
            "package_name":  str,           # @msbc/config-ui
            "src_dir":       Path | None,   # package/src/ if it exists
        }
    """
    import json

    packages_dir = monorepo_root / "packages"
    if not packages_dir.exists():
        raise FileNotFoundError(f"packages/ directory not found inside {monorepo_root}")

    result = []
    for pkg_dir in sorted(packages_dir.iterdir()):
        if not pkg_dir.is_dir():
            continue
        pkg_json = pkg_dir / "package.json"
        if not pkg_json.exists():
            continue
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            package_name = data.get("name", "")
        except Exception:  # noqa: BLE001
            logger.warning("Cannot parse package.json at %s — skipping.", pkg_dir)
            continue

        if not package_name:
            continue

        src_dir = pkg_dir / "src"
        result.append({
            "pkg_dir":      pkg_dir,
            "package_name": package_name,
            "src_dir":      src_dir if src_dir.exists() else pkg_dir,
        })
    return result


def _should_skip_file(path: Path) -> bool:
    """Return True if this file should be excluded from the graph."""
    name = path.name
    for pat in _SKIP_PATTERNS:
        if name.endswith(pat):
            return True
    # Skip .d.ts declaration files
    if name.endswith(".d.ts"):
        return True
    return False


def _should_skip_dir(path: Path) -> bool:
    return path.name in _SKIP_DIRS


def _scan_source_files(src_dir: Path) -> list[Path]:
    """Recursively collect .ts / .tsx files under src_dir, skipping ignored dirs/files."""
    collected: list[Path] = []
    stack = [src_dir]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except PermissionError:
            continue
        for entry in sorted(entries):
            if entry.is_dir():
                if not _should_skip_dir(entry):
                    stack.append(entry)
            elif entry.suffix.lower() in _TS_EXTS and not _should_skip_file(entry):
                collected.append(entry)
    return collected


# ---------------------------------------------------------------------------
# File-type classification
# ---------------------------------------------------------------------------


def _classify_file_type(file_name: str, content: str) -> str:
    """Coarsely classify a source file into a type string."""
    name_lower = file_name.lower()
    if name_lower == "index.ts" or name_lower == "index.tsx":
        return "index"
    if name_lower.endswith(".types.ts") or name_lower.endswith(".types.tsx"):
        return "types"
    if "hook" in name_lower or re.search(r"\buse[A-Z]", content):
        return "hook"
    if name_lower.endswith(".tsx") and re.search(r"\bReact\b|\bJSX\b|return\s*\(", content):
        return "component"
    if "config" in name_lower or "settings" in name_lower:
        return "config"
    if "util" in name_lower or "helper" in name_lower:
        return "utility"
    return "module"


# ---------------------------------------------------------------------------
# Export extraction
# ---------------------------------------------------------------------------


def _extract_exports(content: str) -> list[dict[str, str]]:
    """
    Parse a file's content and return a list of exported symbol dicts:
        { "name": str, "symbol_type": str }
    """
    symbols: dict[str, str] = {}  # name → symbol_type

    # export const/function/class/interface/type/enum Identifier
    for m in _EXPORT_DECL_RE.finditer(content):
        keyword = m.group(1).strip().split()[0]  # first word e.g. "class", "interface"
        sym_name = m.group(2)
        sym_type = _kw_to_symbol_type(keyword)
        symbols[sym_name] = sym_type

    # export default function/class
    for m in _EXPORT_DEFAULT_RE.finditer(content):
        keyword = m.group(1)
        sym_name = m.group(2) or "default"
        sym_type = _kw_to_symbol_type(keyword)
        symbols[sym_name] = sym_type

    # export { Foo, Bar as Baz }  (local re-exports, no 'from')
    for m in _EXPORT_BRACE_RE.finditer(content):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            # "Foo as Bar" → "Bar" is the exported name
            if " as " in part:
                sym_name = part.split(" as ")[-1].strip()
            else:
                sym_name = part
            if sym_name and sym_name not in symbols:
                symbols[sym_name] = "unknown"

    return [{"name": n, "symbol_type": t} for n, t in symbols.items()]


def _kw_to_symbol_type(keyword: str) -> str:
    mapping = {
        "class":     "class",
        "abstract":  "class",
        "function":  "function",
        "const":     "constant",
        "let":       "constant",
        "var":       "constant",
        "interface": "interface",
        "type":      "type",
        "enum":      "enum",
    }
    return mapping.get(keyword, "unknown")


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _extract_imports(content: str) -> list[dict[str, Any]]:
    """
    Parse import statements and return a list of import descriptors:
        {
            "specifier":  str,          # raw from-path: './Button' or '@msbc/react-toolkit'
            "names":      list[str],    # named symbols extracted (may be empty)
        }
    """
    imports: list[dict[str, Any]] = []

    for m in _IMPORT_RE.finditer(content):
        specifier = m.group(5)  # the path after 'from'
        if not specifier:
            continue
        # Extract named symbols from group 1 (named import block)
        raw_names = m.group(1) or ""
        names = [
            part.strip().split(" as ")[0].strip()  # handle "Foo as Bar" → "Foo"
            for part in raw_names.split(",")
            if part.strip() and not part.strip().startswith("type ")
        ]
        names = [n for n in names if n]
        imports.append({"specifier": specifier, "names": names})

    return imports


def _extract_reexport_stars(content: str) -> list[str]:
    """Return list of specifiers from 'export * from ...' statements."""
    return [m.group(1) for m in _REEXPORT_STAR_RE.finditer(content)]


def _extract_reexport_named(content: str) -> list[dict[str, Any]]:
    """Return list of {specifier, names} from 'export { X } from ...' statements."""
    result = []
    for m in _REEXPORT_NAMED_RE.finditer(content):
        raw_names = m.group(1)
        specifier = m.group(2)
        names = [
            part.strip().split(" as ")[0].strip()
            for part in raw_names.split(",")
            if part.strip()
        ]
        names = [n for n in names if n]
        result.append({"specifier": specifier, "names": names})
    return result


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _resolve_relative(
    source_file: Path,
    specifier: str,
    src_dir: Path,
    file_id_map: dict[str, str],  # abs path string → file_id
) -> str | None:
    """
    Resolve a relative import specifier (starts with './' or '../') to a
    SourceFile id.  Returns None if the target cannot be found.
    """
    if not specifier.startswith("."):
        return None

    base_dir = source_file.parent
    candidate_base = (base_dir / specifier).resolve()

    # Try with explicit extensions then index files
    for suffix in (".ts", ".tsx", ".d.ts"):
        candidate = Path(str(candidate_base) + suffix)
        cand_str = str(candidate)
        if cand_str in file_id_map:
            return file_id_map[cand_str]

    # Try as a directory with index.ts / index.tsx
    for idx in ("index.ts", "index.tsx"):
        candidate = candidate_base / idx
        cand_str = str(candidate)
        if cand_str in file_id_map:
            return file_id_map[cand_str]

    return None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_code_graph(db_path: str, monorepo_path: str) -> None:
    """
    Scan *monorepo_path* and populate the code-graph tables in the Kuzu
    database at *db_path*.

    The function is additive — it uses MERGE for nodes so it is safe to
    re-run without duplicating nodes.  Relationship inserts are wrapped in
    try/except so duplicate edges are silently skipped.

    Parameters
    ----------
    db_path :
        Path to the on-disk ``.kuzu`` directory.
    monorepo_path :
        Absolute path to the ReactToolKits monorepo root.
    """
    monorepo_root = Path(monorepo_path).resolve()
    if not monorepo_root.exists():
        raise FileNotFoundError(f"Monorepo path not found: {monorepo_root}")

    logger.info("Opening Kuzu database at '%s' …", db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db   = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    # Ensure schema (idempotent)
    logger.info("Applying schema DDL …")
    created_count = 0
    for stmt in ALL_DDL:
        stmt = stmt.strip()
        if stmt:
            try:
                _exec(conn, stmt)
                created_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("DDL statement failed (may be OK if IF NOT EXISTS): %s", str(exc)[:100])
    logger.info("Applied %d DDL statements", created_count)

    # ── Step 1: Discover packages ─────────────────────────────────────────────
    packages = _discover_packages(monorepo_root)
    logger.info("Discovered %d packages: %s", len(packages),
                [p["package_name"] for p in packages])

    # ── Step 2: Ensure Package nodes exist ───────────────────────────────────
    # The semantic graph builder may have already created them; skip silently
    # if they already exist (kuzu MERGE violates PK constraint on duplicates).
    for pkg in packages:
        pkg_name = pkg["package_name"]
        # Check if already present before inserting
        res = conn.execute(
            f"MATCH (p:Package {{name: '{_esc(pkg_name)}'}}) RETURN count(p)"
        )
        count = res.get_next()[0] if res.has_next() else 0
        if count == 0:
            _exec(conn, (
                f"CREATE (:Package {{"
                f"name: '{_esc(pkg_name)}', "
                f"import_path: '{_esc(pkg_name)}', "
                f"description: ''"
                f"}})"
            ))

    # ── Step 3: Scan all source files and build file registry ─────────────────
    # file_id_map: abs_path_string → file_id  (for resolving relative imports)
    file_id_map: dict[str, str] = {}
    file_records: list[dict[str, Any]] = []

    for pkg in packages:
        pkg_name = pkg["package_name"]
        src_dir  = pkg["src_dir"]
        source_files = _scan_source_files(src_dir)

        for fp in source_files:
            rel_path = fp.relative_to(pkg["pkg_dir"]).as_posix()
            file_id  = f"{pkg_name}::{rel_path}"
            file_id_map[str(fp.resolve())] = file_id
            file_records.append({
                "fp":           fp,
                "file_id":      file_id,
                "file_name":    fp.name,
                "rel_path":     rel_path,
                "package_name": pkg_name,
                "src_dir":      src_dir,
            })

    logger.info("Found %d source files across all packages.", len(file_records))

    # ── Step 4: Insert SourceFile nodes + FileBelongsTo edges ─────────────────
    for rec in file_records:
        try:
            content   = rec["fp"].read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", rec["fp"], exc)
            content = ""

        file_type = _classify_file_type(rec["file_name"], content)
        rec["content"]   = content
        rec["file_type"] = file_type

        _exec_safe(conn, (
            f"MERGE (:SourceFile {{"
            f"id: '{_esc(rec['file_id'])}', "
            f"file_name: '{_esc(rec['file_name'])}', "
            f"rel_path: '{_esc(rec['rel_path'])}', "
            f"package_name: '{_esc(rec['package_name'])}', "
            f"file_type: '{_esc(file_type)}'"
            f"}})"
        ), label="SourceFile")

        # FileBelongsTo edge  SourceFile → Package
        _exec_safe(conn, (
            f"MATCH (sf:SourceFile {{id: '{_esc(rec['file_id'])}'}}), "
            f"(p:Package {{name: '{_esc(rec['package_name'])}'}}) "
            f"CREATE (sf)-[:FileBelongsTo]->(p)"
        ), label="FileBelongsTo")

    logger.info("SourceFile nodes inserted.")

    # ── Step 5: Insert ExportedSymbol nodes + ExportsSymbol edges ─────────────
    symbol_to_file: dict[str, str] = {}  # symbol_id → file_id  (for linking)

    for rec in file_records:
        content  = rec.get("content", "")
        pkg_name = rec["package_name"]
        file_id  = rec["file_id"]

        exports = _extract_exports(content)
        for sym in exports:
            sym_id   = f"{pkg_name}::{sym['name']}"
            sym_name = sym["name"]
            sym_type = sym["symbol_type"]

            _exec_safe(conn, (
                f"MERGE (:ExportedSymbol {{"
                f"id: '{_esc(sym_id)}', "
                f"name: '{_esc(sym_name)}', "
                f"symbol_type: '{_esc(sym_type)}', "
                f"package_name: '{_esc(pkg_name)}'"
                f"}})"
            ), label="ExportedSymbol")
            symbol_to_file[sym_id] = file_id

            _exec_safe(conn, (
                f"MATCH (sf:SourceFile {{id: '{_esc(file_id)}'}}), "
                f"(es:ExportedSymbol {{id: '{_esc(sym_id)}'}}) "
                f"CREATE (sf)-[:ExportsSymbol]->(es)"
            ), label="ExportsSymbol")

    logger.info("ExportedSymbol nodes inserted.")

    # ── Step 6: Insert import edges ───────────────────────────────────────────
    msbc_pkg_names = {pkg["package_name"] for pkg in packages}

    import_count    = 0
    reexport_count  = 0
    pkg_import_count = 0

    for rec in file_records:
        content  = rec.get("content", "")
        file_id  = rec["file_id"]
        src_dir  = rec["src_dir"]

        # — Regular imports —
        for imp in _extract_imports(content):
            specifier = imp["specifier"]
            names     = imp["names"]

            if specifier.startswith("."):
                # Relative import — resolve to another SourceFile
                target_id = _resolve_relative(
                    rec["fp"], specifier, src_dir, file_id_map
                )
                if target_id:
                    _exec_safe(conn, (
                        f"MATCH (a:SourceFile {{id: '{_esc(file_id)}'}}), "
                        f"(b:SourceFile {{id: '{_esc(target_id)}'}}) "
                        f"CREATE (a)-[:ImportsFrom {{import_specifiers: {_cypher_str_list(names)}}}]->(b)"
                    ), label="ImportsFrom")
                    import_count += 1
            elif specifier.startswith("@msbc/") or specifier in msbc_pkg_names:
                # Cross-package import — link to Package node
                # Extract the base package name (e.g. '@msbc/react-toolkit' from '@msbc/react-toolkit/...')
                pkg_target = specifier.split("/")[0] + "/" + specifier.split("/")[1] \
                    if specifier.startswith("@") else specifier
                if pkg_target in msbc_pkg_names and pkg_target != rec["package_name"]:
                    _exec_safe(conn, (
                        f"MATCH (sf:SourceFile {{id: '{_esc(file_id)}'}}), "
                        f"(p:Package {{name: '{_esc(pkg_target)}'}}) "
                        f"CREATE (sf)-[:ImportsPackage {{import_specifiers: {_cypher_str_list(names)}}}]->(p)"
                    ), label="ImportsPackage")
                    pkg_import_count += 1

        # — export * from '...' —
        for specifier in _extract_reexport_stars(content):
            if specifier.startswith("."):
                target_id = _resolve_relative(
                    rec["fp"], specifier, src_dir, file_id_map
                )
                if target_id:
                    _exec_safe(conn, (
                        f"MATCH (a:SourceFile {{id: '{_esc(file_id)}'}}), "
                        f"(b:SourceFile {{id: '{_esc(target_id)}'}}) "
                        f"CREATE (a)-[:ReExportsFrom]->(b)"
                    ), label="ReExportsFrom")
                    reexport_count += 1

        # — export { X } from '...' —
        for reexp in _extract_reexport_named(content):
            specifier = reexp["specifier"]
            names     = reexp["names"]
            if specifier.startswith("."):
                target_id = _resolve_relative(
                    rec["fp"], specifier, src_dir, file_id_map
                )
                if target_id:
                    _exec_safe(conn, (
                        f"MATCH (a:SourceFile {{id: '{_esc(file_id)}'}}), "
                        f"(b:SourceFile {{id: '{_esc(target_id)}'}}) "
                        f"CREATE (a)-[:ImportsFrom {{import_specifiers: {_cypher_str_list(names)}}}]->(b)"
                    ), label="ImportsFrom(reexport-named)")
                    import_count += 1
            elif specifier.startswith("@msbc/"):
                pkg_target = "@msbc/" + specifier.split("/")[1]
                if pkg_target in msbc_pkg_names and pkg_target != rec["package_name"]:
                    _exec_safe(conn, (
                        f"MATCH (sf:SourceFile {{id: '{_esc(file_id)}'}}), "
                        f"(p:Package {{name: '{_esc(pkg_target)}'}}) "
                        f"CREATE (sf)-[:ImportsPackage {{import_specifiers: {_cypher_str_list(names)}}}]->(p)"
                    ), label="ImportsPackage(reexport)")
                    pkg_import_count += 1

    logger.info(
        "Import edges: %d ImportsFrom, %d ReExportsFrom, %d ImportsPackage.",
        import_count, reexport_count, pkg_import_count,
    )

    # Commit all changes to disk
    logger.debug("Committing all changes to disk…")
    conn.execute("CHECKPOINT")

    # ── Step 7: Bridge ExportedSymbol → Component (semantic link) ─────────────
    bridge_count = 0
    try:
        # Fetch existing Component ids from the semantic graph
        result = conn.execute("MATCH (c:Component) RETURN c.id AS cid, c.name AS cname")
        component_map: dict[str, str] = {}  # name → component_id
        while result.has_next():
            row = result.get_next()
            cid, cname = row[0], row[1]
            component_map[cname] = cid
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not query Component nodes for bridging: %s", exc)
        component_map = {}

    for sym_id, _file_id in symbol_to_file.items():
        # sym_id = "{package_name}::{symbol_name}"
        sym_name = sym_id.split("::", 1)[-1]
        comp_id  = component_map.get(sym_name)
        if comp_id:
            _exec_safe(conn, (
                f"MATCH (es:ExportedSymbol {{id: '{_esc(sym_id)}'}}), "
                f"(c:Component {{id: '{_esc(comp_id)}'}}) "
                f"CREATE (es)-[:SymbolLinkedToComponent]->(c)"
            ), label="SymbolLinkedToComponent")
            bridge_count += 1

    logger.info("SymbolLinkedToComponent bridge edges: %d.", bridge_count)

    # ── Step 8: Summary counts ────────────────────────────────────────────────
    _log_code_graph_counts(conn)
    
    # Final commit to ensure all changes are persisted
    logger.debug("Final checkpoint to persist all changes…")
    try:
        conn.execute("CHECKPOINT")
    except Exception as exc:  # noqa: BLE001
        logger.warning("CHECKPOINT failed (non-fatal): %s", exc)
    
    # Close connection to force flush to disk
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    
    logger.info("Code graph build complete.")


def rebuild_code_graph(db_path: str, monorepo_path: str) -> None:
    """
    Drop all code-graph tables and rebuild from scratch.

    Only drops the code-graph tables (SourceFile, ExportedSymbol and their
    relationships); the semantic knowledge graph (Component, Feature, etc.)
    is preserved.
    """
    code_graph_rels = [
        "SymbolLinkedToComponent",
        "ReExportsFrom",
        "ExportsSymbol",
        "ImportsPackage",
        "ImportsFrom",
        "FileBelongsTo",
    ]
    code_graph_nodes = [
        "ExportedSymbol",
        "SourceFile",
    ]

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db   = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    logger.info("Dropping code-graph tables …")
    for table in code_graph_rels + code_graph_nodes:
        try:
            conn.execute(f"DROP TABLE {table}")
            logger.debug("Dropped: %s", table)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Drop %s (non-fatal): %s", table, exc)

    # Persist drops before rebuilding
    try:
        conn.execute("CHECKPOINT")
        logger.debug("Checkpointed after drops")
    except Exception as exc:  # noqa: BLE001
        logger.warning("CHECKPOINT after drops failed: %s", exc)

    # Close connection to avoid lock conflicts
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass

    logger.info("Rebuilding code graph …")
    build_code_graph(db_path, monorepo_path)


# ---------------------------------------------------------------------------
# Count logger
# ---------------------------------------------------------------------------


def _log_code_graph_counts(conn: kuzu.Connection) -> None:
    tables = {
        "SourceFile":            "MATCH (n:SourceFile) RETURN count(n)",
        "ExportedSymbol":        "MATCH (n:ExportedSymbol) RETURN count(n)",
        "FileBelongsTo":         "MATCH ()-[r:FileBelongsTo]->() RETURN count(r)",
        "ImportsFrom":           "MATCH ()-[r:ImportsFrom]->() RETURN count(r)",
        "ImportsPackage":        "MATCH ()-[r:ImportsPackage]->() RETURN count(r)",
        "ReExportsFrom":         "MATCH ()-[r:ReExportsFrom]->() RETURN count(r)",
        "ExportsSymbol":         "MATCH ()-[r:ExportsSymbol]->() RETURN count(r)",
        "SymbolLinkedToComponent": "MATCH ()-[r:SymbolLinkedToComponent]->() RETURN count(r)",
    }
    for label, query in tables.items():
        try:
            res = conn.execute(query)
            count = res.get_next()[0] if res.has_next() else 0
            logger.info("  %-30s %d", label, count)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Count query failed for %s: %s", label, exc)
