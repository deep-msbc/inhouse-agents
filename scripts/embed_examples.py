"""
CLI script — embed correct_code_examples/ files into the Qdrant examples collection.

Usage
-----
python scripts/embed_examples.py [--dry-run] [--example-id <id>] [--examples-dir <path>]

Flags
-----
--dry-run              Preview additions / updates / deletions without writing to Qdrant.
--example-id <id>      Process only the one example folder whose name matches <id>
                       (e.g. "Dashboard03").  All other folders are skipped.
--examples-dir <path>  Override the examples root directory.
                       Defaults to settings.EXAMPLES_DIR ("correct_code_examples").

Environment
-----------
Requires OPENAI_API_KEY and a running Qdrant instance at QDRANT_URL.

Exit codes
----------
0  Success.
1  Configuration error (e.g. examples directory not found).
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
from src.msbc.embedding.ingestors.examples_ingestor import ingest_examples  # noqa: E402

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("embed_examples")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="embed_examples",
        description="Embed correct_code_examples/ into the Qdrant examples collection.",
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
        "--example-id",
        metavar="ID",
        default=None,
        help=(
            "Only process the example folder whose name matches this ID "
            "(e.g. Dashboard03).  Skips all other folders."
        ),
    )
    parser.add_argument(
        "--examples-dir",
        metavar="PATH",
        default=None,
        help=(
            "Override the examples root directory.  "
            "Defaults to settings.EXAMPLES_DIR ('correct_code_examples')."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _main(
    dry_run: bool,
    example_id: str | None,
    examples_dir_override: str | None,
) -> int:
    # ── Pre-flight checks ─────────────────────────────────────────────────────
    if not settings.OPENAI_API_KEY:
        logger.error(
            "OPENAI_API_KEY is not set.  "
            "Export it in your shell or add it to config/settings.yaml."
        )
        return 1

    # Resolve the examples directory
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
    mode_flags: list[str] = []
    if dry_run:
        mode_flags.append("DRY-RUN")
    if example_id:
        mode_flags.append(f"filter={example_id}")
    mode_label = " | ".join(mode_flags) if mode_flags else "incremental"

    logger.info("=== embed_examples starting [%s] ===", mode_label)
    logger.info("Examples dir   : %s", examples_dir)
    logger.info("Qdrant URL     : %s", settings.QDRANT_URL)
    logger.info("Embedding model: %s (%d dims)", settings.OPENAI_EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)

    # ── Run ingestor ──────────────────────────────────────────────────────────
    try:
        result = await ingest_examples(
            examples_dir=examples_dir,
            dry_run=dry_run,
            example_id_filter=example_id,
        )
    except FileNotFoundError as exc:
        logger.error("Examples directory not found: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during examples ingestion: %s", exc)
        return 2

    # ── Result summary ────────────────────────────────────────────────────────
    logger.info("=== embed_examples complete ===")
    logger.info("  Processed : %d example folder(s)", result.get("processed_folders", 0))
    logger.info("  Skipped   : %d example folder(s)", result.get("skipped_folders", 0))
    logger.info("  Tokens    : %d", result.get("total_tokens", 0))
    logger.info(
        "  Cost      : $%.6f USD (estimated)",
        result.get("estimated_cost_usd", 0.0),
    )
    if dry_run:
        logger.info("  [DRY-RUN] No changes were written to Qdrant.")

    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(
        _main(
            dry_run=args.dry_run,
            example_id=args.example_id,
            examples_dir_override=args.examples_dir,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
