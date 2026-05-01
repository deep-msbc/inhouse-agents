"""
Monorepo-aware file scanner for the @msbc/react-toolkit repository.

Walks the ReactToolKits monorepo directory, classifies every embeddable file,
and returns structured FileRecord objects ready for the chunking + ingestion
pipeline.

Configuration
─────────────
Set the monorepo path via environment variable::

    RTK_MONOREPO_PATH=C:/Users/yug.chauhan/Documents/GitHub/ReactToolKits

Or add it to a .env file in the project root.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Monorepo root ─────────────────────────────────────────────────────────────

_DEFAULT_MONOREPO_PATH = "/mnt/c/Users/yug.chauhan/Documents/GitHub/ReactToolKits"

MONOREPO_ROOT = Path(
    os.environ.get("RTK_MONOREPO_PATH", _DEFAULT_MONOREPO_PATH)
).resolve()

# ── Package mapping ───────────────────────────────────────────────────────────
# Maps relative source directories → package name used in metadata.

SCAN_DIRS: Dict[str, str] = {
    "packages/react-toolkit/src": "@msbc/react-toolkit",
    "packages/config-ui/src":     "@msbc/config-ui",
    "packages/data-layer/src":    "@msbc/data-layer",
    "packages/config-app-shell/src": "@msbc/config-app-shell",
    "packages/import-utils/src":  "@msbc/import-utils",
    "packages/utils/src":         "@msbc/utils",
    "app/dev-app/src":            "dev-app",
}

# Per-package README + config files to scan
PACKAGE_ROOTS: Dict[str, str] = {
    "packages/react-toolkit": "@msbc/react-toolkit",
    "packages/config-ui":     "@msbc/config-ui",
    "packages/data-layer":    "@msbc/data-layer",
    "packages/config-app-shell": "@msbc/config-app-shell",
    "packages/import-utils":  "@msbc/import-utils",
    "packages/utils":         "@msbc/utils",
    "app/dev-app":            "dev-app",
}

# Root-level files that belong to "monorepo-root"
ROOT_FILES: List[str] = [
    "README.md",
    "Dockerfile",
    "eslint.config.js",
    "scripts/update-workspace-versions.js",
]

# Storybook config (inside react-toolkit)
STORYBOOK_DIR = "packages/react-toolkit/.storybook"

# ── File extensions we care about ─────────────────────────────────────────────

_CODE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}
_STYLE_EXTENSIONS = {".scss", ".css"}
_DOC_EXTENSIONS = {".md"}
_CONFIG_EXTENSIONS = {".json"}

# ── Skip rules ────────────────────────────────────────────────────────────────

_SKIP_FILE_NAMES = frozenset({
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    ".npmrc",
    ".prettierrc",
    ".prettierignore",
    ".gitignore",
    "vite-env.d.ts",
    "vitest.shims.d.ts",
})

_SKIP_FILE_PATTERNS = frozenset({
    "-bkp.",       # backup files (MultiInput-bkp.tsx)
    "tsconfig.app.",
    "tsconfig.node.",
})

_SKIP_EXTENSIONS = frozenset({
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
    ".eot", ".ttf", ".pdf", ".lock",
})

_SKIP_DIRS = frozenset({
    "node_modules", "dist", "build", ".git", "__pycache__",
    "coverage", ".turbo", ".next",
})


# ── FileRecord dataclass ─────────────────────────────────────────────────────

@dataclass
class FileRecord:
    """Represents one scanned source file from the monorepo."""
    path: Path                  # absolute path
    rel_path: str               # relative to monorepo root (forward slashes)
    file_id: str                # SHA-256 of file content
    content: str                # raw file content
    package_name: str           # "@msbc/react-toolkit" | "dev-app" | "monorepo-root"
    package_layer: str          # "atomic" | "orchestration" | …
    module_path: str            # "components/button" | "api" | "hooks"
    file_category: str          # "component" | "hook" | "type_definition" | …
    language: str               # "typescript" | "scss" | "css" | "markdown" | "json"
    collection_targets: List[str] = field(default_factory=list)  # ["code"] or ["docs"] or ["code","config"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _file_id(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _should_skip(path: Path) -> bool:
    """Return True if this file should not be embedded."""
    name = path.name

    if name in _SKIP_FILE_NAMES:
        return True
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return True
    for pat in _SKIP_FILE_PATTERNS:
        if pat in name:
            return True
    # Skip empty files
    if path.stat().st_size == 0:
        return True
    return False


def _get_language(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".tsx", ".ts"}:
        return "typescript"
    if ext in {".jsx", ".js"}:
        return "javascript"
    if ext in {".scss"}:
        return "scss"
    if ext in {".css"}:
        return "css"
    if ext in {".md"}:
        return "markdown"
    if ext in {".json"}:
        return "json"
    return "text"


def _get_module_path(rel_path: str, src_prefix: str) -> str:
    """
    Derive the module path relative to the package src/.

    "packages/react-toolkit/src/components/button/Button.tsx"
    with src_prefix = "packages/react-toolkit/src"
    → "components/button"
    """
    after_src = rel_path[len(src_prefix):].lstrip("/")
    parts = after_src.split("/")
    if len(parts) > 1:
        return "/".join(parts[:-1])  # drop the filename
    return ""


def _detect_file_category(file_path: str, file_name: str) -> str:
    """Auto-detect the file_category from naming conventions."""
    name_lower = file_name.lower()
    stem = Path(file_name).stem

    if file_name == "index.ts" or file_name == "index.tsx":
        return "barrel_export"
    if ".types.ts" in file_name or ".type.ts" in file_name:
        return "type_definition"
    if ".stories.tsx" in file_name or ".stories.ts" in file_name:
        return "story"
    if file_name.endswith((".scss", ".css")):
        return "style"
    if stem.startswith("use") and len(stem) > 3 and stem[3].isupper():
        return "hook"
    if "store/" in file_path or "Store" in file_name or "Slice" in file_name or "slice" in file_name:
        return "store_slice"
    if "api/" in file_path or "apiClient" in file_name or "axiosInstance" in file_name:
        return "api_client"
    if file_name in ("Dockerfile",) or "config.ts" in name_lower or "config.js" in name_lower:
        return "build_config"
    if "Registry" in file_name:
        return "registry"
    if "Mapper" in file_name or "mapper" in file_name:
        return "mapper"
    if "Pagination" in file_name or "FileIcons" in file_name:
        return "sub_component"
    if file_name == "tokenManager.ts":
        return "api_client"
    if file_name.endswith(".json"):
        return "json_config"
    if file_name.endswith(".md"):
        return "readme"
    return "component"


def _get_package_layer(package_name: str) -> str:
    from db.schema import PACKAGE_LAYERS
    return PACKAGE_LAYERS.get(package_name, "infrastructure")


def _decide_collection_targets(file_category: str, language: str) -> List[str]:
    """
    Decide which collection(s) this file should be ingested into.

    Some files intentionally go into multiple collections (e.g. .types.ts
    goes into both code and config with different chunking strategies).
    """
    if file_category == "readme":
        return ["docs"]
    if file_category == "story":
        return ["docs"]                   # stories are "usage examples"
    if file_category == "type_definition":
        return ["code", "config"]         # dual: function-chunked + interface-chunked
    if file_category == "json_config":
        return ["config"]
    if file_category in ("registry", "mapper"):
        return ["code", "config"]         # implementation + reference
    if file_category == "style" and language in ("scss", "css"):
        # Global style files with tokens/variables also go to config
        return ["code"]                   # individual styles just in code
    if file_category == "barrel_export":
        return ["code"]
    if file_category == "build_config":
        return ["code"]
    # Default: code
    return ["code"]


# ── package.json synthetic summary ────────────────────────────────────────────

def _generate_package_summary(pkg_json_path: Path, package_name: str) -> Optional[str]:
    """
    Generate a human-readable summary from a package.json file.
    Returns the synthetic text, or None if the file can't be read.
    """
    try:
        data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    name = data.get("name", package_name)
    version = data.get("version", "unknown")
    description = data.get("description", "")

    lines = [f"Package: {name} v{version}"]
    if description:
        lines.append(f"Description: {description}")
    lines.append("")

    # Dependencies
    deps = data.get("dependencies", {})
    if deps:
        lines.append("Dependencies:")
        for dep_name, dep_ver in sorted(deps.items()):
            tag = "(workspace)" if dep_ver.startswith("workspace:") else dep_ver
            lines.append(f"  - {dep_name} {tag}")
        lines.append("")

    # Peer dependencies
    peers = data.get("peerDependencies", {})
    if peers:
        lines.append("Peer Dependencies:")
        for dep_name, dep_ver in sorted(peers.items()):
            lines.append(f"  - {dep_name} {dep_ver}")
        lines.append("")

    # Scripts
    scripts = data.get("scripts", {})
    if scripts:
        lines.append(f"Scripts: {', '.join(sorted(scripts.keys()))}")

    return "\n".join(lines)


# ── Main scanning function ────────────────────────────────────────────────────

def scan_monorepo() -> Dict[str, FileRecord]:
    """
    Walk the entire monorepo and return {rel_path: FileRecord} for every
    embeddable file.

    Raises FileNotFoundError if the monorepo root doesn't exist.
    """
    if not MONOREPO_ROOT.exists():
        raise FileNotFoundError(
            f"Monorepo not found at: {MONOREPO_ROOT}\n"
            f"Set RTK_MONOREPO_PATH in your .env or environment."
        )

    records: Dict[str, FileRecord] = {}

    # ── 1. Scan package source directories ────────────────────────────
    for src_rel, pkg_name in SCAN_DIRS.items():
        src_dir = MONOREPO_ROOT / src_rel

        if not src_dir.exists():
            logger.warning("Source dir missing: %s", src_dir)
            continue

        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if _should_skip(path):
                continue

            ext = path.suffix.lower()
            if ext not in (_CODE_EXTENSIONS | _STYLE_EXTENSIONS | _DOC_EXTENSIONS | _CONFIG_EXTENSIONS):
                continue

            content = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(MONOREPO_ROOT).as_posix()
            category = _detect_file_category(rel, path.name)

            records[rel] = FileRecord(
                path=path,
                rel_path=rel,
                file_id=_file_id(content),
                content=content,
                package_name=pkg_name,
                package_layer=_get_package_layer(pkg_name),
                module_path=_get_module_path(rel, src_rel),
                file_category=category,
                language=_get_language(path),
                collection_targets=_decide_collection_targets(category, _get_language(path)),
            )

    # ── 2. Per-package root files (README.md, package.json, configs) ──
    for pkg_rel, pkg_name in PACKAGE_ROOTS.items():
        pkg_dir = MONOREPO_ROOT / pkg_rel
        if not pkg_dir.exists():
            continue

        for path in sorted(pkg_dir.iterdir()):
            if not path.is_file():
                continue
            if _should_skip(path):
                continue

            name = path.name
            ext = path.suffix.lower()

            # README.md
            if name == "README.md":
                content = path.read_text(encoding="utf-8", errors="replace")
                rel = path.relative_to(MONOREPO_ROOT).as_posix()
                if rel not in records:
                    records[rel] = FileRecord(
                        path=path, rel_path=rel, file_id=_file_id(content),
                        content=content, package_name=pkg_name,
                        package_layer=_get_package_layer(pkg_name),
                        module_path="", file_category="readme",
                        language="markdown",
                        collection_targets=["docs"],
                    )

            # package.json → synthetic summary
            elif name == "package.json":
                summary = _generate_package_summary(path, pkg_name)
                if summary:
                    rel = path.relative_to(MONOREPO_ROOT).as_posix()
                    records[f"__synthetic__/{rel}"] = FileRecord(
                        path=path, rel_path=f"__synthetic__/{rel}",
                        file_id=_file_id(summary),
                        content=summary, package_name=pkg_name,
                        package_layer=_get_package_layer(pkg_name),
                        module_path="", file_category="package_manifest",
                        language="text",
                        collection_targets=["docs"],
                    )

            # Build configs (tsconfig.json, tsup.config.ts, vite.config.ts, etc.)
            elif ext in {".ts", ".js", ".json"} and "config" in name.lower():
                content = path.read_text(encoding="utf-8", errors="replace")
                rel = path.relative_to(MONOREPO_ROOT).as_posix()
                if rel not in records:
                    records[rel] = FileRecord(
                        path=path, rel_path=rel, file_id=_file_id(content),
                        content=content, package_name=pkg_name,
                        package_layer=_get_package_layer(pkg_name),
                        module_path="", file_category="build_config",
                        language=_get_language(path),
                        collection_targets=["code"],
                    )

    # ── 3. Storybook config ───────────────────────────────────────────
    storybook_dir = MONOREPO_ROOT / STORYBOOK_DIR
    if storybook_dir.exists():
        for path in sorted(storybook_dir.iterdir()):
            if not path.is_file() or _should_skip(path):
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(MONOREPO_ROOT).as_posix()
            records[rel] = FileRecord(
                path=path, rel_path=rel, file_id=_file_id(content),
                content=content, package_name="@msbc/react-toolkit",
                package_layer="atomic", module_path=".storybook",
                file_category="build_config", language=_get_language(path),
                collection_targets=["code"],
            )

    # ── 4. Root-level monorepo files ──────────────────────────────────
    for root_file in ROOT_FILES:
        path = MONOREPO_ROOT / root_file
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(MONOREPO_ROOT).as_posix()
        category = "readme" if path.suffix == ".md" else "build_config"
        lang = _get_language(path)
        targets = ["docs"] if category == "readme" else ["code"]

        records[rel] = FileRecord(
            path=path, rel_path=rel, file_id=_file_id(content),
            content=content, package_name="monorepo-root",
            package_layer="infrastructure", module_path="",
            file_category=category, language=lang,
            collection_targets=targets,
        )

    # ── 5. Root package.json → synthetic summary ──────────────────────
    root_pkg = MONOREPO_ROOT / "package.json"
    if root_pkg.exists():
        summary = _generate_package_summary(root_pkg, "monorepo-root")
        if summary:
            records["__synthetic__/package.json"] = FileRecord(
                path=root_pkg, rel_path="__synthetic__/package.json",
                file_id=_file_id(summary), content=summary,
                package_name="monorepo-root", package_layer="infrastructure",
                module_path="", file_category="package_manifest",
                language="text", collection_targets=["docs"],
            )

    logger.info(
        "Scanner found %d embeddable files from monorepo at %s",
        len(records), MONOREPO_ROOT,
    )
    return records


# ── CLI quick-test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    records = scan_monorepo()

    # Print summary by package
    from collections import Counter
    pkg_counts = Counter(r.package_name for r in records.values())
    cat_counts = Counter(r.file_category for r in records.values())
    target_counts = Counter(
        t for r in records.values() for t in r.collection_targets
    )

    print(f"\n{'='*60}")
    print(f"Total files: {len(records)}")
    print(f"\nBy package:")
    for pkg, count in pkg_counts.most_common():
        print(f"  {pkg}: {count}")
    print(f"\nBy category:")
    for cat, count in cat_counts.most_common():
        print(f"  {cat}: {count}")
    print(f"\nBy collection target:")
    for t, count in target_counts.most_common():
        print(f"  {t}: {count}")
