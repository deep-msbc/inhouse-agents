"""
CLI script — embed RTK monorepo toolkit files into the Qdrant toolkit collection.

Usage
-----
python scripts/embed_toolkit.py [--dry-run] [--full-sync]

Flags
-----
--dry-run     Preview additions / updates / deletions without writing to Qdrant.
--full-sync   Re-embed every file on disk regardless of stored hash (first-run mode).

Environment
-----------
Set RTK_MONOREPO_PATH in your environment (or config/settings.yaml) before running.
Requires OPENAI_API_KEY and a running Qdrant instance at QDRANT_URL.

Exit codes
----------
0  Success.
1  Configuration error (e.g. RTK_MONOREPO_PATH not set).
2  Unexpected runtime error.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# ── Ensure the project root is on sys.path so `src.*` + `app.*` are importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import settings  # noqa: E402 — import after path fix
from src.msbc.embedding.ingestors.toolkit_ingestor import ingest_toolkit  # noqa: E402

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("embed_toolkit")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="embed_toolkit",
        description="Embed RTK monorepo source files into the Qdrant toolkit collection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview planned changes without writing to Qdrant.",
    )
    parser.add_argument(
        "--full-sync",
        action="store_true",
        default=False,
        help="Re-embed every file on disk, ignoring stored content hashes.",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _main(dry_run: bool, full_sync: bool) -> int:
    # ── Pre-flight checks ─────────────────────────────────────────────────────
    if not settings.RTK_MONOREPO_PATH:
        logger.error(
            "RTK_MONOREPO_PATH is not set.  "
            "Set it in your environment or in config/settings.yaml and re-run."
        )
        return 1

    if not settings.OPENAI_API_KEY:
        logger.error(
            "OPENAI_API_KEY is not set.  "
            "Export it in your shell or add it to config/settings.yaml."
        )
        return 1

    # ── Summary header ────────────────────────────────────────────────────────
    mode_flags: list[str] = []
    if dry_run:
        mode_flags.append("DRY-RUN")
    if full_sync:
        mode_flags.append("FULL-SYNC")
    mode_label = " | ".join(mode_flags) if mode_flags else "incremental"

    logger.info("=== embed_toolkit starting [%s] ===", mode_label)
    logger.info("Monorepo path : %s", settings.RTK_MONOREPO_PATH)
    logger.info("Qdrant URL    : %s", settings.QDRANT_URL)
    logger.info("Embedding model: %s (%d dims)", settings.OPENAI_EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)

    # ── Run ingestor ──────────────────────────────────────────────────────────
    try:
        result = await ingest_toolkit(dry_run=dry_run, full_sync=full_sync)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during toolkit ingestion: %s", exc)
        return 2

    # ── Result summary ────────────────────────────────────────────────────────
    logger.info("=== embed_toolkit complete ===")
    logger.info("  Added   : %d files", result.get("added", 0))
    logger.info("  Updated : %d files", result.get("updated", 0))
    logger.info("  Deleted : %d files", result.get("deleted", 0))
    logger.info("  Tokens  : %d", result.get("total_tokens", 0))
    logger.info(
        "  Cost    : $%.6f USD (estimated)",
        result.get("estimated_cost_usd", 0.0),
    )
    if dry_run:
        logger.info("  [DRY-RUN] No changes were written to Qdrant.")

    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(_main(dry_run=args.dry_run, full_sync=args.full_sync))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
