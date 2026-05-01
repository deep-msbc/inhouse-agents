"""
Monorepo-aware file scanner for the RTK toolkit embedding pipeline.

Walks the configured :data:`SCAN_DIRS` within the ReactToolKits monorepo,
classifies every embeddable file, and returns :class:`FileRecord` objects
ready for the chunking and ingestion pipeline.

Set the monorepo root via::

    RTK_MONOREPO_PATH=C:/path/to/ReactToolKits   # in .env or as env var

Skips
-----
• ``node_modules/``, ``dist/``, ``.storybook/``, ``__tests__/`` directories
• ``*.test.*``, ``*.spec.*``, ``*.d.ts``, ``*.stories.*`` files
• Empty files
• Unrecognized file extensions (SVG, fonts, lock files, …)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
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
# Namespace → module_layer
# ---------------------------------------------------------------------------

_NAMESPACE_LAYER: dict[str, str] = {
    "@msbc/react-toolkit":    "atomic",
    "@msbc/config-ui":        "ui",
    "@msbc/data-layer":       "data",
    "@msbc/config-app-shell": "shell",
    "@msbc/import-utils":     "utils",
    "@msbc/utils":            "utils",
}

# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------

_CODE_EXTS:    frozenset[str] = frozenset({".tsx", ".ts"})
_STYLE_EXTS:   frozenset[str] = frozenset({".scss", ".css"})
_DOC_EXTS:     frozenset[str] = frozenset({".md"})
_CONFIG_EXTS:  frozenset[str] = frozenset({".json"})
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

    # Test / spec / story files
    if ".test." in name or ".spec." in name or ".stories." in name:
        return True

    # Empty files
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return True

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_toolkit(monorepo_root: Path) -> list[FileRecord]:
    """
    Walk configured :data:`SCAN_DIRS` within *monorepo_root* and return a
    :class:`FileRecord` for every embeddable source file.

    Parameters
    ----------
    monorepo_root : Path
        Absolute path to the ReactToolKits monorepo root.

    Returns
    -------
    list[FileRecord]
        One record per embeddable file found under the configured scan dirs.
    """
    records: list[FileRecord] = []

    for scan_subdir, namespace in SCAN_DIRS.items():
        scan_abs = monorepo_root / scan_subdir
        if not scan_abs.exists():
            logger.warning("SCAN_DIR not found, skipping: %s", scan_abs)
            continue

        module_layer = _NAMESPACE_LAYER.get(namespace, "unknown")

        for path in scan_abs.rglob("*"):
            if not path.is_file():
                continue

            # Skip files inside excluded directories
            try:
                rel_to_scan = path.relative_to(scan_abs)
            except ValueError:
                continue

            # Check all *parent* parts (not the file name itself)
            if any(part in _SKIP_DIRS for part in rel_to_scan.parts[:-1]):
                continue

            if _should_skip(path):
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("Cannot read '%s': %s", path, exc)
                continue

            rel_path = str(path.relative_to(monorepo_root)).replace("\\", "/")

            records.append(FileRecord(
                rel_path=rel_path,
                abs_path=path,
                namespace=namespace,
                file_category=_detect_file_category(rel_path, path.name),
                language=_get_language(path),
                content_type=_get_content_type(path),
                module_layer=module_layer,
                content_hash=_compute_hash(content),
                size_bytes=path.stat().st_size,
                content=content,
            ))

    logger.info(
        "scan_toolkit: %d files found across %d SCAN_DIRS.",
        len(records),
        len(SCAN_DIRS),
    )
    return records
