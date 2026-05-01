"""
Post-chunking enrichment for the 3-collection pipeline.

Enrichment passes (run in order)
────────────────────────────────
1. package_layer      — classify package into architecture layer
2. file_category      — auto-detect from naming conventions (already done by scanner)
3. related_files      — sibling files in the same module directory
4. dependencies       — resolved package names from import statements
5. used_by_packages   — reverse index (which packages import X)
6. summary            — auto-generated one-liner from chunk text
7. mention_extraction — components & packages mentioned in docs
"""

import re
import logging
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Dict, List, Set, Tuple

from db.scanner import FileRecord

logger = logging.getLogger(__name__)

# ── Package prefixes for dependency resolution ────────────────────────────────

_PACKAGE_IMPORT_PREFIXES = {
    "@msbc/react-toolkit": "@msbc/react-toolkit",
    "@msbc/config-ui":     "@msbc/config-ui",
    "@msbc/data-layer":    "@msbc/data-layer",
    "@msbc/config-app-shell": "@msbc/config-app-shell",
    "@msbc/import-utils":  "@msbc/import-utils",
    "@msbc/utils":         "@msbc/utils",
}

_IMPORT_RE = re.compile(
    r"""(?:import|from)\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

_COMPONENT_RE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")


# ── Pass 3: related_files ─────────────────────────────────────────────────────

def _build_sibling_map(records: Dict[str, FileRecord]) -> Dict[str, List[str]]:
    """
    Group files by their parent directory and return
    {rel_path: [sibling_rel_paths...]} (excluding self).
    """
    dir_to_files: Dict[str, List[str]] = defaultdict(list)
    for rel in records:
        if rel.startswith("__synthetic__/"):
            continue
        parent = str(PurePosixPath(rel).parent)
        dir_to_files[parent].append(rel)

    sibling_map: Dict[str, List[str]] = {}
    for parent, siblings in dir_to_files.items():
        for rel in siblings:
            sibling_map[rel] = [s for s in siblings if s != rel]
    return sibling_map


# ── Pass 4: dependencies ──────────────────────────────────────────────────────

def _extract_dependencies(content: str) -> List[str]:
    """
    Parse import statements and return list of resolved @msbc/* package names.
    """
    deps: Set[str] = set()
    for match in _IMPORT_RE.finditer(content):
        specifier = match.group(1)
        for prefix, pkg_name in _PACKAGE_IMPORT_PREFIXES.items():
            if specifier.startswith(prefix):
                deps.add(pkg_name)
                break
    return sorted(deps)


# ── Pass 5: used_by_packages (reverse index) ─────────────────────────────────

def build_used_by_index(records: Dict[str, FileRecord]) -> Dict[str, Set[str]]:
    """
    For each package, find which OTHER packages import it.

    Returns {package_name: {importing_package_names...}}.
    """
    used_by: Dict[str, Set[str]] = defaultdict(set)

    for rec in records.values():
        if rec.language not in ("typescript", "javascript"):
            continue
        deps = _extract_dependencies(rec.content)
        for dep_pkg in deps:
            if dep_pkg != rec.package_name:
                used_by[dep_pkg].add(rec.package_name)

    return dict(used_by)


# ── Pass 6: summary ──────────────────────────────────────────────────────────

_JSDOC_DESC_RE = re.compile(r"/\*\*\s*\n?\s*\*?\s*(.+?)(?:\n|\*/)", re.DOTALL)
_SINGLE_COMMENT_RE = re.compile(r"^//\s*(.+)$", re.MULTILINE)


def _generate_summary(chunk_text: str, component_name: str, chunk_type: str) -> str:
    """
    Build a one-line summary from the chunk.

    Tries: JSDoc first sentence → first // comment → auto-generated fallback.
    """
    # Try JSDoc
    jsdoc = _JSDOC_DESC_RE.search(chunk_text)
    if jsdoc:
        desc = jsdoc.group(1).strip().rstrip(".")
        if len(desc) > 10:
            return desc[:200]

    # Try first single-line comment
    comment = _SINGLE_COMMENT_RE.search(chunk_text)
    if comment:
        desc = comment.group(1).strip()
        if len(desc) > 10:
            return desc[:200]

    # Fallback
    return f"{chunk_type}: {component_name}"


# ── Pass 7: mention extraction (for docs) ────────────────────────────────────

def _extract_mentioned_components(text: str) -> List[str]:
    """Find PascalCase component names in text."""
    return sorted(set(_COMPONENT_RE.findall(text)))


def _extract_mentioned_packages(text: str) -> List[str]:
    """Find @msbc/* package mentions in text."""
    return sorted(
        pkg for pkg in _PACKAGE_IMPORT_PREFIXES.values() if pkg in text
    )


# ── Orchestrator ──────────────────────────────────────────────────────────────

class Enricher:
    """
    Stateful enricher that runs all 7 passes.

    Usage
    -----
        enricher = Enricher(records)
        enricher.prepare()                    # build global indices
        meta = enricher.enrich(file_record)   # returns dict of extra metadata
    """

    def __init__(self, records: Dict[str, FileRecord]):
        self._records = records
        self._sibling_map: Dict[str, List[str]] = {}
        self._used_by: Dict[str, Set[str]] = {}

    def prepare(self) -> None:
        """Build global cross-file indices.  Call once before enriching."""
        self._sibling_map = _build_sibling_map(self._records)
        self._used_by = build_used_by_index(self._records)
        logger.info(
            "Enricher prepared: %d sibling groups, %d used-by entries",
            len(self._sibling_map),
            len(self._used_by),
        )

    def enrich(self, rec: FileRecord) -> Dict:
        """
        Return enrichment metadata for a single FileRecord.

        The returned dict has keys matching CodeChunkPayload / DocChunkPayload
        field names.  Caller merges these into the payload before upsert.
        """
        meta: Dict = {}

        # Pass 3: related_files
        meta["related_files"] = self._sibling_map.get(rec.rel_path, [])

        # Pass 4: dependencies
        if rec.language in ("typescript", "javascript"):
            meta["dependencies"] = _extract_dependencies(rec.content)
        else:
            meta["dependencies"] = []

        # Pass 5: used_by_packages
        meta["used_by_packages"] = sorted(
            self._used_by.get(rec.package_name, set())
        )

        # Pass 7: mention extraction (always useful, docs especially)
        meta["mentioned_components"] = _extract_mentioned_components(rec.content)
        meta["mentioned_packages"] = _extract_mentioned_packages(rec.content)

        return meta

    def generate_summary(
        self, chunk_text: str, component_name: str, chunk_type: str
    ) -> str:
        """Pass 6: generate a summary for one chunk (called per-chunk)."""
        return _generate_summary(chunk_text, component_name, chunk_type)
