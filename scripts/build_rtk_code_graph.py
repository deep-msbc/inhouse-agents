"""
CLI script — build (or rebuild) the ReactToolKits code-level Kuzu graph.

Scans every .ts / .tsx source file in the RTK monorepo and creates:

  SourceFile nodes       — one per .ts/.tsx file
  ExportedSymbol nodes   — one per exported name
  FileBelongsTo          — SourceFile → Package
  ImportsFrom            — SourceFile → SourceFile  (relative imports, resolved)
  ImportsPackage         — SourceFile → Package     (@msbc/* cross-package imports)
  ReExportsFrom          — SourceFile → SourceFile  (export * from '...')
  ExportsSymbol          — SourceFile → ExportedSymbol
  SymbolLinkedToComponent— ExportedSymbol → Component  (code ↔ semantic bridge)

Usage
-----
  python scripts/build_rtk_code_graph.py [--rebuild] [--db-path PATH] [--monorepo-path PATH]

Flags
-----
  --rebuild              Drop code-graph tables and rebuild from scratch.
  --db-path PATH         KUZU database directory (default: settings.KUZU_DB_PATH).
  --monorepo-path PATH   ReactToolKits monorepo root (default: settings.RTK_MONOREPO_PATH).

Exit codes
----------
  0  Success
  1  Configuration error
  2  Runtime error
"""

import argparse
import logging
import sys
from pathlib import Path

# ── sys.path fix so src.* and app.* are importable ──────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import settings  # noqa: E402
from src.msbc.embedding.code_graph_builder import (  # noqa: E402
    build_code_graph,
    rebuild_code_graph,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("build_rtk_code_graph")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_rtk_code_graph",
        description="Build the ReactToolKits code-level Kuzu graph.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        default=False,
        help="Drop code-graph tables and rebuild from scratch.",
    )
    parser.add_argument(
        "--db-path",
        metavar="PATH",
        default=None,
        help="KUZU database directory. Defaults to settings.KUZU_DB_PATH.",
    )
    parser.add_argument(
        "--monorepo-path",
        metavar="PATH",
        default=None,
        help="ReactToolKits monorepo root. Defaults to settings.RTK_MONOREPO_PATH.",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()

    # ── Resolve db path ──────────────────────────────────────────────────────
    db_path = args.db_path or getattr(settings, "KUZU_DB_PATH", "./data/toolkit_graph.kuzu")
    if not db_path:
        logger.error("KUZU_DB_PATH is not configured. Pass --db-path or set it in .env.")
        return 1

    # ── Resolve monorepo path ────────────────────────────────────────────────
    monorepo_path = args.monorepo_path or getattr(settings, "RTK_MONOREPO_PATH", "")

    # On Windows the .env uses WSL-style /mnt/... paths; translate if needed.
    # Only convert if the path doesn't already exist (i.e. we're on Windows, not inside WSL).
    if monorepo_path and monorepo_path.startswith("/mnt/") and not Path(monorepo_path).exists():
        # e.g. /mnt/c/Users/... → C:/Users/...
        parts = monorepo_path[len("/mnt/"):].split("/", 1)
        if len(parts) == 2:
            monorepo_path = parts[0].upper() + ":/" + parts[1]

    if not monorepo_path:
        logger.error(
            "RTK_MONOREPO_PATH is not configured. "
            "Pass --monorepo-path or set RTK_MONOREPO_PATH in .env."
        )
        return 1

    if not Path(monorepo_path).exists():
        logger.error("Monorepo path does not exist: %s", monorepo_path)
        return 1

    logger.info("DB path      : %s", db_path)
    logger.info("Monorepo path: %s", monorepo_path)
    logger.info("Mode         : %s", "REBUILD" if args.rebuild else "INCREMENTAL")

    try:
        if args.rebuild:
            rebuild_code_graph(db_path, monorepo_path)
        else:
            build_code_graph(db_path, monorepo_path)
    except FileNotFoundError as exc:
        logger.error("Path error: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error: %s", exc)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
