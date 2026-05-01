"""
CLI script — build (or rebuild) the KUZU toolkit knowledge graph.

Usage
-----
python scripts/build_graph.py [--rebuild] [--db-path <path>] [--examples-dir <path>]

Flags
-----
--rebuild              Drop all tables and rebuild the entire graph from scratch.
                       Without this flag the build is idempotent (MERGE / IF NOT EXISTS).
--db-path <path>       Override the on-disk KUZU database directory.
                       Defaults to settings.KUZU_DB_PATH ("./data/toolkit_graph.kuzu").
--examples-dir <path>  Override the correct_code_examples/ root directory.
                       Defaults to settings.EXAMPLES_DIR ("correct_code_examples").

Behaviour
---------
After the build completes, node and edge counts per table are logged so you can
verify the graph is populated correctly without opening a KUZU shell.

Exit codes
----------
0  Success.
1  Configuration error (e.g. examples directory not found).
2  Unexpected runtime error.
"""

import argparse
import logging
import sys
from pathlib import Path

# ── Ensure the project root is on sys.path so `src.*` + `app.*` are importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import settings  # noqa: E402 — import after path fix
from src.msbc.embedding.graph_builder import (  # noqa: E402
    build_graph,
    rebuild_graph,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("build_graph")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_graph",
        description="Build or rebuild the KUZU toolkit knowledge graph.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        default=False,
        help=(
            "Drop all tables and rebuild the graph from scratch.  "
            "Without this flag the build is idempotent."
        ),
    )
    parser.add_argument(
        "--db-path",
        metavar="PATH",
        default=None,
        help=(
            "Override the KUZU database directory.  "
            "Defaults to settings.KUZU_DB_PATH."
        ),
    )
    parser.add_argument(
        "--examples-dir",
        metavar="PATH",
        default=None,
        help=(
            "Override the correct_code_examples/ root directory.  "
            "Defaults to settings.EXAMPLES_DIR."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _main(rebuild: bool, db_path_override: str | None, examples_dir_override: str | None) -> int:
    # ── Resolve paths ─────────────────────────────────────────────────────────
    db_path = db_path_override or settings.KUZU_DB_PATH

    if examples_dir_override:
        examples_dir = Path(examples_dir_override).resolve()
    else:
        examples_dir = (_ROOT / settings.EXAMPLES_DIR).resolve()

    if not examples_dir.exists():
        logger.error(
            "Examples directory not found: %s\n"
            "Set EXAMPLES_DIR in config/settings.yaml or pass --examples-dir.",
            examples_dir,
        )
        return 1

    # ── Summary header ────────────────────────────────────────────────────────
    mode = "REBUILD (drop + recreate)" if rebuild else "BUILD (idempotent)"
    logger.info("=== build_graph starting [%s] ===", mode)
    logger.info("KUZU db path   : %s", db_path)
    logger.info("Examples dir   : %s", examples_dir)

    # ── Run builder ───────────────────────────────────────────────────────────
    try:
        if rebuild:
            rebuild_graph(db_path=db_path, examples_dir=examples_dir)
        else:
            build_graph(db_path=db_path, examples_dir=examples_dir)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during graph build: %s", exc)
        return 2

    logger.info("=== build_graph complete ===")
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = _main(
        rebuild=args.rebuild,
        db_path_override=args.db_path,
        examples_dir_override=args.examples_dir,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
