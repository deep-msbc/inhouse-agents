"""
Toolkit ingestor: incremental sync from the RTK monorepo into Qdrant.

Algorithm
---------
1. Bootstrap the Qdrant toolkit collection (create if absent, apply payload indexes).
2. Fetch stored ``{file_path: file_id}`` map from Qdrant via
   :meth:`~QdrantStore.get_stored_file_hashes`.
3. Scan the monorepo with :func:`~scanner.scan_toolkit`.
4. Diff:
   • **ADD**    — file on disk but not in Qdrant.
   • **UPDATE** — file exists in both but SHA-256 hash differs.
   • **DELETE** — file in Qdrant but no longer on disk.
5. DELETE removed files (filter-delete all their chunks from Qdrant).
6. ADD / UPDATE each file:
   a. Extract file-level imports/exports.
   b. Chunk with :func:`~chunker.chunk_toolkit_file`.
   c. Embed all chunk texts in one batched call via :class:`~embedder.OpenAIEmbedder`.
   d. Build :class:`~schema.ToolkitChunkPayload` + :class:`PointStruct` per chunk.
   e. Upsert via :class:`~store.QdrantStore`.
7. Log summary: added, updated, deleted, total tokens, estimated cost.
"""

from __future__ import annotations

import logging
from pathlib import Path

from qdrant_client.models import PointStruct

from app.core.config import settings
from src.msbc.embedding.chunker import (
    chunk_toolkit_file,
    extract_file_exports,
    extract_file_imports,
    extract_msbc_imports,
)
from src.msbc.embedding.embedder import OpenAIEmbedder
from src.msbc.embedding.ingestors.scanner import FileRecord, scan_toolkit
from src.msbc.embedding.schema import (
    ToolkitChunkPayload,
    make_point_id,
    text_hash as _text_hash,
)
from src.msbc.embedding.store import QdrantStore

logger = logging.getLogger(__name__)

# Mirrors the pricing constant in embedder.py — kept local to avoid a
# circular dependency when computing summary cost.
_PRICE_PER_M_TOKENS: float = 0.13


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def ingest_toolkit(
    dry_run: bool = False,
    full_sync: bool = False,
) -> dict:
    """
    Run an incremental sync of the RTK monorepo into the Qdrant toolkit collection.

    Parameters
    ----------
    dry_run :
        If ``True``, log every planned change but do **not** write to Qdrant.
        Useful for previewing what would be embedded before committing.
    full_sync :
        If ``True``, skip the stored-hash comparison and re-embed every file on
        disk regardless of whether it changed.  Equivalent to a first-time run.

    Returns
    -------
    dict
        ``{added, updated, deleted, total_tokens, estimated_cost_usd, dry_run}``

    Raises
    ------
    ValueError
        If ``RTK_MONOREPO_PATH`` is not configured.
    FileNotFoundError
        If the configured monorepo path does not exist on disk.
    """
    monorepo_path_str = settings.RTK_MONOREPO_PATH
    if not monorepo_path_str:
        raise ValueError(
            "RTK_MONOREPO_PATH is not configured. "
            "Set it in your .env file or as an environment variable."
        )

    monorepo_root = Path(monorepo_path_str)
    if not monorepo_root.exists():
        raise FileNotFoundError(
            f"RTK_MONOREPO_PATH does not exist on disk: {monorepo_root}"
        )

    store = QdrantStore()
    embedder = OpenAIEmbedder()

    collection = store.ensure_collection("toolkit")
    logger.info(
        "Toolkit ingestor starting — collection='%s' dry_run=%s full_sync=%s",
        collection, dry_run, full_sync,
    )

    # ── Step 1: Load stored hashes ────────────────────────────────────────────
    stored_hashes: dict[str, str] = (
        {} if full_sync else store.get_stored_file_hashes(collection)
    )

    # ── Step 2: Scan the monorepo ─────────────────────────────────────────────
    records = scan_toolkit(monorepo_root)
    disk_by_path: dict[str, FileRecord] = {r.rel_path: r for r in records}

    stored_paths = set(stored_hashes.keys())
    disk_paths = set(disk_by_path.keys())

    # ── Step 3: Diff ──────────────────────────────────────────────────────────
    to_delete: set[str] = stored_paths - disk_paths
    to_add: dict[str, FileRecord] = {
        p: disk_by_path[p] for p in disk_paths - stored_paths
    }
    to_update: dict[str, FileRecord] = {
        p: disk_by_path[p]
        for p in disk_paths & stored_paths
        if disk_by_path[p].content_hash != stored_hashes[p]
    }

    logger.info(
        "Diff — add: %d | update: %d | delete: %d | total on disk: %d",
        len(to_add), len(to_update), len(to_delete), len(records),
    )

    total_tokens = 0

    # ── Step 4: Delete removed files ──────────────────────────────────────────
    if dry_run:
        if to_delete:
            logger.info(
                "[DRY RUN] Would delete %d file(s): %s …",
                len(to_delete), list(to_delete)[:5],
            )
    else:
        for file_path in to_delete:
            store.delete_by_file_path(collection, file_path)
            logger.debug("Deleted stale file: '%s'", file_path)

    logger.info("Deleted %d stale file(s).", len(to_delete) if not dry_run else 0)

    # ── Step 5: Embed and upsert new / changed files ──────────────────────────
    to_process: dict[str, FileRecord] = {**to_add, **to_update}

    for file_path, record in to_process.items():
        points, tokens = await _process_file(record, embedder)
        total_tokens += tokens

        if dry_run:
            logger.debug(
                "[DRY RUN] '%s' — would upsert %d chunks (%d tokens).",
                file_path, len(points), tokens,
            )
            continue

        if points:
            # For updates, delete old chunks first (chunk count may differ)
            if file_path in to_update:
                store.delete_by_file_path(collection, file_path)
            store.upsert_batch(collection, points)

        logger.debug(
            "Processed '%s' — chunks: %d, tokens: %d.",
            file_path, len(points), tokens,
        )

    # ── Step 6: Summary ───────────────────────────────────────────────────────
    estimated_cost = round((total_tokens / 1_000_000) * _PRICE_PER_M_TOKENS, 6)

    summary = {
        "added":              len(to_add),
        "updated":            len(to_update),
        "deleted":            len(to_delete),
        "total_tokens":       total_tokens,
        "estimated_cost_usd": estimated_cost,
        "dry_run":            dry_run,
    }

    logger.info(
        "Toolkit ingest complete — added=%d updated=%d deleted=%d "
        "tokens=%d cost=$%.4f%s",
        summary["added"], summary["updated"], summary["deleted"],
        summary["total_tokens"], summary["estimated_cost_usd"],
        " [DRY RUN]" if dry_run else "",
    )
    return summary


# ---------------------------------------------------------------------------
# Internal: process one file
# ---------------------------------------------------------------------------

async def _process_file(
    record: FileRecord,
    embedder: OpenAIEmbedder,
) -> tuple[list[PointStruct], int]:
    """
    Chunk, embed, and build Qdrant :class:`PointStruct` objects for *record*.

    Returns
    -------
    (points, total_tokens)
        A list of ready-to-upsert ``PointStruct`` objects and the total
        OpenAI embedding tokens consumed for this file.
    """
    source = record.content

    # File-level metadata extraction (runs once per file, applied to all chunks)
    file_imports = extract_file_imports(source)
    msbc_symbols, _msbc_packages = extract_msbc_imports(source)
    all_exports = extract_file_exports(source)

    # Chunk — may return 1 (small files) or N (AST-split) chunks
    chunks = chunk_toolkit_file(
        source=source,
        file_path=record.rel_path,
        file_name=record.abs_path.name,
        namespace=record.namespace,
        file_category=record.file_category,
        module_layer=record.module_layer,
        file_imports=file_imports,
        msbc_imports=msbc_symbols,
        all_file_exports=all_exports,
    )

    if not chunks:
        logger.warning("No chunks produced for '%s' — skipping.", record.rel_path)
        return [], 0

    # Embed all chunks in a single batched call
    texts = [c.text_to_embed for c in chunks]
    vectors, usage = await embedder.embed_texts(texts)
    total_tokens: int = usage.get("total_tokens", 0)

    total_chunks = len(chunks)
    points: list[PointStruct] = []

    for chunk, vector in zip(chunks, vectors):
        payload = ToolkitChunkPayload(
            content_type=record.content_type,
            namespace=record.namespace,
            file_path=record.rel_path,
            file_name=record.abs_path.name,
            file_id=record.content_hash,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            total_chunks=total_chunks,
            language=record.language,
            file_category=record.file_category,
            chunk_type=chunk.chunk_type,
            symbol_name=chunk.symbol_name,
            module_layer=record.module_layer,
            file_imports=file_imports,
            chunk_exports=chunk.chunk_exports,
            msbc_imports=msbc_symbols,
            text_hash=_text_hash(chunk.text_to_embed),
        )

        points.append(PointStruct(
            id=make_point_id(chunk.chunk_id),
            vector=vector,
            payload=payload.model_dump(),
        ))

    return points, total_tokens
