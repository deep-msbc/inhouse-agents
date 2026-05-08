"""
Monorepo-aware file scanner for the RTK toolkit embedding pipeline.

Walks the configured :data:`SCAN_DIRS` within the ReactToolKits monorepo,
classifies every embeddable file, and returns :class:`FileRecord` objects
ready for the chunking and ingestion pipeline.

Set the monorepo root via::

    RTK_MONOREPO_PATH=C:/path/to/ReactToolKits   # in .env or as env var

Scans
-----
• ``packages/*/src/``  — all TypeScript, TSX, SCSS, Markdown, JSON source files
• ``packages/*/``      — package-root READMEs and build-config files (tsconfig, vite.config…)
• Storybook story files (``.stories.tsx``) — included as ``content_type="doc"``
• Monorepo root        — top-level README.md

Skips
-----
• ``node_modules/``, ``dist/``, ``.storybook/``, ``__tests__/`` directories
• ``*.test.*``, ``*.spec.*``, ``*.d.ts`` files
• Empty files, lock files, binary assets
• ``package.json`` files (not embedded by design)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SCAN_DIRS: relative src directory → @msbc/* namespace
# ---------------------------------------------------------------------------

SCAN_DIRS: dict[str, str] = {
    "packages/react-toolkit/src":    "@msbc/react-toolkit",
    "packages/config-ui/src":        "@msbc/config-ui",
    "packages/data-layer/src":       "@msbc/data-layer",
    "packages/config-app-shell/src": "@msbc/config-app-shell",
    "packages/import-utils/src":     "@msbc/import-utils",
    "packages/utils/src":            "@msbc/utils",
}

# ---------------------------------------------------------------------------
# PACKAGE_ROOTS: relative package directory → @msbc/* namespace
# Used to pick up README.md and build-config files at the package root level.
# ---------------------------------------------------------------------------

PACKAGE_ROOTS: dict[str, str] = {
    "packages/react-toolkit":    "@msbc/react-toolkit",
    "packages/config-ui":        "@msbc/config-ui",
    "packages/data-layer":       "@msbc/data-layer",
    "packages/config-app-shell": "@msbc/config-app-shell",
    "packages/import-utils":     "@msbc/import-utils",
    "packages/utils":            "@msbc/utils",
}

# Root-level monorepo files to include (relative to monorepo root).
_MONOREPO_ROOT_FILES: tuple[str, ...] = ("README.md",)

# ---------------------------------------------------------------------------
# Namespace → module_layer
# ---------------------------------------------------------------------------

_NAMESPACE_LAYER: dict[str, str] = {
    "@msbc/react-toolkit":    "atomic",
    "@msbc/config-ui":        "ui",
    "@msbc/data-layer":       "data",
    "@msbc/config-app-shell": "shell",
    "@msbc/import-utils":     "utils",
    "@msbc/utils":            "utils",
    "monorepo":               "infra",
}

# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------

_CODE_EXTS:    frozenset[str] = frozenset({".tsx", ".ts"})
_STYLE_EXTS:   frozenset[str] = frozenset({".scss", ".css"})
_DOC_EXTS:     frozenset[str] = frozenset({".md"})
_CONFIG_EXTS:  frozenset[str] = frozenset({".json"})
# Build-config source extensions scanned at package root level only
_BUILD_CONFIG_EXTS: frozenset[str] = frozenset({".ts", ".js", ".json"})
_ALL_EMBEDDABLE: frozenset[str] = _CODE_EXTS | _STYLE_EXTS | _DOC_EXTS | _CONFIG_EXTS

# ---------------------------------------------------------------------------
# Skip rules
# ---------------------------------------------------------------------------

# Directories whose *contents* (and the directory itself) are never scanned.
_SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", "dist", "build", ".git", "__pycache__",
    "coverage", ".turbo", ".next", ".storybook", "__tests__",
})


# ---------------------------------------------------------------------------
# FileRecord dataclass
# ---------------------------------------------------------------------------

@dataclass
class FileRecord:
    """One scanned source file from the RTK monorepo."""

    rel_path: str
    """Relative path from the monorepo root (forward-slashes, no leading /)."""

    abs_path: Path
    """Absolute path on disk."""

    namespace: str
    """``@msbc/*`` package name, e.g. ``"@msbc/config-ui"``."""

    file_category: Literal[
        "component", "hook", "util", "service", "config",
        "type", "style", "doc", "unknown",
    ]
    """Coarse functional category inferred from naming conventions."""

    language: Literal["typescript", "tsx", "scss", "markdown", "json", "unknown"]
    """Programming language / file type (maps to ``ToolkitChunkPayload.language``)."""

    content_type: Literal["code", "style", "doc", "config"]
    """High-level content type (maps to ``ToolkitChunkPayload.content_type``)."""

    module_layer: str
    """Architecture layer, e.g. ``"ui"``, ``"data"``, ``"atomic"``."""

    content_hash: str
    """SHA-256 hex digest of the raw file content — used as ``file_id`` in Qdrant."""

    size_bytes: int
    """File size in bytes (at scan time)."""

    content: str
    """Raw UTF-8 file content loaded during scanning."""

    doc_type: str = ""
    """Optional doc sub-type: ``"readme"``, ``"storybook_story"``, ``"build_config"``."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_language(
    path: Path,
) -> Literal["typescript", "tsx", "scss", "markdown", "json", "unknown"]:
    ext = path.suffix.lower()
    if ext == ".tsx":
        return "tsx"
    if ext == ".ts":
        return "typescript"
    if ext in (".scss", ".css"):
        return "scss"
    if ext == ".md":
        return "markdown"
    if ext == ".json":
        return "json"
    return "unknown"


def _get_content_type(path: Path) -> Literal["code", "style", "doc", "config"]:
    ext = path.suffix.lower()
    if ext in _CODE_EXTS:
        return "code"
    if ext in _STYLE_EXTS:
        return "style"
    if ext in _DOC_EXTS:
        return "doc"
    return "config"


def _detect_file_category(
    rel_path: str,
    file_name: str,
) -> Literal["component", "hook", "util", "service", "config", "type", "style", "doc", "unknown"]:
    """
    Infer the file_category from naming conventions.

    Priority
    --------
    1. Extension-based: ``.scss``/``.css`` → style, ``.md`` → doc, ``.json`` → config.
    2. Type definition files: ``.types.ts`` / ``.type.ts``.
    3. Config files: ``"config"`` in filename.
    4. Hooks: ``use<Upper>`` prefix.
    5. Components: PascalCase stem.
    6. Service / API by path segment.
    7. Util / helper by path segment.
    8. ``"unknown"`` fallback.
    """
    ext = Path(file_name).suffix.lower()
    stem = Path(file_name).stem
    path_lower = rel_path.lower()

    if ext in (".scss", ".css"):
        return "style"
    if ext == ".md":
        return "doc"
    if ext == ".json":
        return "config"

    # Type definition files (.types.ts, .type.ts, types.ts)
    if ".types" in file_name or ".type." in file_name:
        return "type"

    # Config files
    if "config" in file_name.lower():
        return "config"

    # Hook: useXxx pattern
    if stem.startswith("use") and len(stem) > 3 and stem[3].isupper():
        return "hook"

    # Component: PascalCase (first char uppercase, not all-caps)
    if stem and stem[0].isupper():
        return "component"

    # Service / API by path
    if "service" in path_lower or "/api/" in path_lower:
        return "service"

    # Util / helpers by path
    if "util" in path_lower or "helper" in path_lower:
        return "util"

    return "unknown"


def _should_skip(path: Path) -> bool:
    """Return True if this file should be excluded from the embedding pipeline."""
    name = path.name
    ext = path.suffix.lower()

    # Only embed recognised extensions
    if ext not in _ALL_EMBEDDABLE:
        return True

    # TypeScript declaration files
    if name.endswith(".d.ts"):
        return True

    # Test / spec files (but NOT story files — they are included as docs)
    if ".test." in name or ".spec." in name:
        return True

    # package.json — skipped by design
    if name == "package.json":
        return True

    # Lock / ignore / RC files
    _SKIP_NAMES = frozenset({
        "pnpm-lock.yaml", "pnpm-workspace.yaml", ".npmrc", ".prettierrc",
        ".gitignore", "vite-env.d.ts", "vitest.shims.d.ts",
    })
    if name in _SKIP_NAMES:
        return True

    # Empty files
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return True

    return False


def _should_skip_src(path: Path) -> bool:
    """
    Skip rule for files inside SCAN_DIRS source directories.
    Identical to _should_skip but also skips backup files that embed noise.
    """
    if _should_skip(path):
        return True
    name = path.name
    # Backup / generated files
    if "-bkp." in name or name.endswith(".bkp.tsx") or name.endswith(".bkp.ts"):
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_toolkit(monorepo_root: Path) -> list[FileRecord]:
    """
    Scan the RTK monorepo and return a :class:`FileRecord` for every
    embeddable file across three scan passes:

    1. ``SCAN_DIRS`` — package ``src/`` trees (code, style, JSON, markdown,
       and ``.stories.tsx`` usage-example docs).
    2. ``PACKAGE_ROOTS`` — per-package root files: ``README.md`` and build
       config files (``tsconfig.json``, ``vite.config.ts``, etc.).
    3. Monorepo root — top-level ``README.md``.

    Deduplication is enforced via a ``seen`` set of ``rel_path`` values so
    that a file discovered in multiple passes is only returned once.

    Parameters
    ----------
    monorepo_root : Path
        Absolute path to the ReactToolKits monorepo root.

    Returns
    -------
    list[FileRecord]
        Deduplicated list of all embeddable files found.
    """
    records: list[FileRecord] = []
    seen: set[str] = set()   # rel_path deduplication across all passes

    # ── Helper ────────────────────────────────────────────────────────────────

    def _read(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read '%s': %s", path, exc)
            return None

    def _add(rec: FileRecord) -> None:
        if rec.rel_path not in seen:
            seen.add(rec.rel_path)
            records.append(rec)

    # ── Pass 1: src/ directories ──────────────────────────────────────────────

    for scan_subdir, namespace in SCAN_DIRS.items():
        scan_abs = monorepo_root / scan_subdir
        if not scan_abs.exists():
            logger.warning("SCAN_DIR not found, skipping: %s", scan_abs)
            continue

        module_layer = _NAMESPACE_LAYER.get(namespace, "unknown")

        for path in scan_abs.rglob("*"):
            if not path.is_file():
                continue

            try:
                rel_to_scan = path.relative_to(scan_abs)
            except ValueError:
                continue

            # Skip files inside excluded directories
            if any(part in _SKIP_DIRS for part in rel_to_scan.parts[:-1]):
                continue

            if _should_skip_src(path):
                continue

            content = _read(path)
            if content is None:
                continue

            rel_path = str(path.relative_to(monorepo_root)).replace("\\", "/")
            name = path.name
            is_story = ".stories." in name

            if is_story:
                # Story files → doc, even though they are TS/TSX code files
                _add(FileRecord(
                    rel_path=rel_path,
                    abs_path=path,
                    namespace=namespace,
                    file_category="doc",
                    language=_get_language(path),
                    content_type="doc",
                    module_layer=module_layer,
                    content_hash=_compute_hash(content),
                    size_bytes=path.stat().st_size,
                    content=content,
                    doc_type="storybook_story",
                ))
            else:
                _add(FileRecord(
                    rel_path=rel_path,
                    abs_path=path,
                    namespace=namespace,
                    file_category=_detect_file_category(rel_path, name),
                    language=_get_language(path),
                    content_type=_get_content_type(path),
                    module_layer=module_layer,
                    content_hash=_compute_hash(content),
                    size_bytes=path.stat().st_size,
                    content=content,
                ))

    # ── Pass 2: package-root files ────────────────────────────────────────────

    for pkg_rel, namespace in PACKAGE_ROOTS.items():
        pkg_dir = monorepo_root / pkg_rel
        if not pkg_dir.exists():
            continue

        module_layer = _NAMESPACE_LAYER.get(namespace, "unknown")

        for path in sorted(pkg_dir.iterdir()):
            if not path.is_file():
                continue

            name = path.name
            ext = path.suffix.lower()
            rel_path = str(path.relative_to(monorepo_root)).replace("\\", "/")

            # README.md → doc chunk
            if name == "README.md":
                content = _read(path)
                if content and path.stat().st_size > 0:
                    _add(FileRecord(
                        rel_path=rel_path,
                        abs_path=path,
                        namespace=namespace,
                        file_category="doc",
                        language="markdown",
                        content_type="doc",
                        module_layer=module_layer,
                        content_hash=_compute_hash(content),
                        size_bytes=path.stat().st_size,
                        content=content,
                        doc_type="readme",
                    ))
                continue

            # Build-config files at package root only:
            # tsconfig*.json, vite.config.ts, tsup.config.ts, eslint.config.*
            _CONFIG_STEMS = ("tsconfig", "vite.config", "tsup.config", "eslint.config",
                              "jest.config", "babel.config", "rollup.config")
            is_build_config = (
                ext in _BUILD_CONFIG_EXTS
                and any(name.startswith(s) for s in _CONFIG_STEMS)
                # skip package.json (explicit decision)
                and name != "package.json"
                and not name.endswith(".d.ts")
                and not name.endswith("-lock.yaml")
            )

            if is_build_config:
                content = _read(path)
                if content and path.stat().st_size > 0:
                    lang = _get_language(path)
                    _add(FileRecord(
                        rel_path=rel_path,
                        abs_path=path,
                        namespace=namespace,
                        file_category="config",
                        language=lang,
                        content_type="config",
                        module_layer=module_layer,
                        content_hash=_compute_hash(content),
                        size_bytes=path.stat().st_size,
                        content=content,
                        doc_type="build_config",
                    ))

    # ── Pass 3: monorepo root files ───────────────────────────────────────────

    for root_file in _MONOREPO_ROOT_FILES:
        path = monorepo_root / root_file
        if not path.exists() or not path.is_file():
            continue
        content = _read(path)
        if not content or path.stat().st_size == 0:
            continue
        rel_path = root_file
        _add(FileRecord(
            rel_path=rel_path,
            abs_path=path,
            namespace="monorepo",
            file_category="doc",
            language="markdown",
            content_type="doc",
            module_layer="infra",
            content_hash=_compute_hash(content),
            size_bytes=path.stat().st_size,
            content=content,
            doc_type="readme",
        ))

    # ── Summary log ───────────────────────────────────────────────────────────

    from collections import Counter
    ct_counts = Counter(r.content_type for r in records)
    logger.info(
        "scan_toolkit: %d files found — code=%d style=%d doc=%d config=%d",
        len(records),
        ct_counts.get("code", 0),
        ct_counts.get("style", 0),
        ct_counts.get("doc", 0),
        ct_counts.get("config", 0),
    )
    return records
