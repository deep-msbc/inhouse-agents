"""
Examples ingestor: sync ``correct_code_examples/`` into the Qdrant examples collection.

Expected folder layout
----------------------
::

    examples_dir/
        {example_group}/          e.g. Dashboard_Samples, Form_Samples
            {example_id}/         e.g. Dashboard03, Form04
                *.tsx
                *.ts

Algorithm
---------
1. Bootstrap the Qdrant examples collection (create if absent, apply indexes).
2. Fetch stored ``{file_path: file_id}`` map from Qdrant.
3. Walk ``examples_dir/`` two levels deep: ``{group}/{example_id}/``.
4. For each ``example_id`` folder:

   a. Collect all ``.tsx``/``.ts`` files and their SHA-256 hashes.
   b. Compare against stored hashes to decide whether anything changed.
   c. If no files changed **and** the set of files is identical → skip.
   d. Otherwise (re-)process the entire folder:

      - Run feature detection on each file (pattern, role, MSBC imports, flags).
      - Build :class:`~schema.ExampleChunkPayload` for each file chunk.
      - Build a synthetic **summary chunk** that describes the whole folder.
      - Embed all texts in one batched call.
      - Delete old Qdrant points for the folder, then upsert the new points.

5. Orphan cleanup: delete Qdrant entries whose ``file_path`` is no longer on disk.
6. Log per-folder and overall summary.

Notes on summary chunks
-----------------------
Summary chunks have ``is_summary_chunk=True`` and ``file_id=""`` (no real file).
Because :meth:`~store.QdrantStore.get_stored_file_hashes` skips entries with an
empty ``file_id``, summary points are invisible to the incremental diff — they are
always regenerated whenever any file in their folder changes.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from qdrant_client.models import PointStruct

from app.core.config import settings
from src.msbc.embedding.chunker import (
    # Public API
    build_example_summary_chunk,
    chunk_example_file,
    extract_msbc_imports,
    # Private feature-detection helpers — reused directly per plan spec
    # (Python does not enforce single-underscore privacy at import time).
    _detect_complexity,
    _detect_dashboard_features,
    _detect_example_pattern,
    _detect_file_role,
    _detect_form_features,
    _generate_use_case,
)
from src.msbc.embedding.embedder import OpenAIEmbedder
from src.msbc.embedding.schema import (
    ExampleChunkPayload,
    make_point_id,
    text_hash as _text_hash,
)
from src.msbc.embedding.store import QdrantStore

logger = logging.getLogger(__name__)

# Cost constant mirrored from embedder.py.
_PRICE_PER_M_TOKENS: float = 0.13

# File extensions to include when scanning example folders.
_EXAMPLE_EXTS: frozenset[str] = frozenset({".tsx", ".ts", ".jsx", ".js"})

# Complexity ordering used to pick the "max" complexity for a folder.
_COMPLEXITY_RANK: dict[str, int] = {"simple": 0, "medium": 1, "complex": 2}
_RANK_TO_COMPLEXITY: dict[int, str] = {v: k for k, v in _COMPLEXITY_RANK.items()}


# ---------------------------------------------------------------------------
# Internal utility helpers
# ---------------------------------------------------------------------------

def _content_hash(content: str) -> str:
    """Return the SHA-256 hex digest of *content*."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _max_complexity(complexities: list[str]) -> str:
    """Return the 'worst' complexity string from a list."""
    if not complexities:
        return "simple"
    return _RANK_TO_COMPLEXITY[max(_COMPLEXITY_RANK.get(c, 0) for c in complexities)]


def _union_features(feature_list: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge a list of per-file feature dicts into one aggregate dict.

    • Boolean values are OR-combined (True if *any* file has the feature).
    • List values (``field_types_used``, ``filter_types``) are merged and
      de-duplicated.
    """
    merged: dict[str, Any] = {}
    for features in feature_list:
        for key, val in features.items():
            if isinstance(val, bool):
                merged[key] = merged.get(key, False) or val
            elif isinstance(val, list):
                existing: list = merged.get(key, [])
                merged[key] = sorted(set(existing) | set(val))
    return merged


def _dominant_pattern(patterns: list[str]) -> str:
    """
    Return the most frequent non-``"unknown"`` pattern in *patterns*.

    Falls back to ``"unknown"`` if all patterns are ``"unknown"`` or the
    list is empty.
    """
    counts = Counter(p for p in patterns if p != "unknown")
    if not counts:
        return "unknown"
    return counts.most_common(1)[0][0]


def _collect_all_disk_paths(examples_root: Path) -> set[str]:
    """
    Return the set of all ``file_path`` strings (relative to ``examples_root.parent``)
    for every source file currently on disk under *examples_root*.

    Used during orphan cleanup to identify paths present in Qdrant but gone
    from disk.
    """
    project_root = examples_root.parent
    paths: set[str] = set()

    for group_dir in examples_root.iterdir():
        if not group_dir.is_dir():
            continue
        for example_dir in group_dir.iterdir():
            if not example_dir.is_dir():
                continue
            for file_path in example_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in _EXAMPLE_EXTS:
                    paths.add(
                        str(file_path.relative_to(project_root)).replace("\\", "/")
                    )

    return paths


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def ingest_examples(
    examples_dir: Path | None = None,
    dry_run: bool = False,
    example_id_filter: str | None = None,
) -> dict:
    """
    Incremental sync of ``correct_code_examples/`` into the Qdrant examples collection.

    Parameters
    ----------
    examples_dir :
        Root directory containing the example groups.  Defaults to the value
        of ``settings.EXAMPLES_DIR`` (``"correct_code_examples"``).
    dry_run :
        If ``True``, log all planned changes but do **not** write to Qdrant.
    example_id_filter :
        If set, only the example folder whose name matches this string is
        processed (e.g. ``"Dashboard03"``).  All other folders are skipped.

    Returns
    -------
    dict
        ``{processed_folders, skipped_folders, total_tokens, estimated_cost_usd, dry_run}``

    Raises
    ------
    FileNotFoundError
        If the resolved examples directory does not exist.
    """
    if examples_dir is None:
        examples_dir = Path(settings.EXAMPLES_DIR)

    # Resolve to absolute path so all subsequent relative-path computations are
    # consistent regardless of working directory.
    examples_root: Path = examples_dir.resolve()

    if not examples_root.exists():
        raise FileNotFoundError(
            f"EXAMPLES_DIR does not exist: {examples_root}"
        )

    store = QdrantStore()
    embedder = OpenAIEmbedder()

    collection = store.ensure_collection("examples")
    logger.info(
        "Examples ingestor starting — collection='%s' examples_dir='%s' "
        "dry_run=%s filter='%s'",
        collection, examples_root, dry_run, example_id_filter,
    )

    stored_hashes = store.get_stored_file_hashes(collection)
    total_tokens = 0
    n_processed = 0
    n_skipped = 0

    # Maps example_id → list of Qdrant point UUID strings (for KUZU sync).
    processed_chunk_ids: dict[str, list[str]] = {}

    # Walk: examples_root/{example_group}/{example_id}/
    for group_dir in sorted(examples_root.iterdir()):
        if not group_dir.is_dir():
            continue
        example_group = group_dir.name

        for example_dir in sorted(group_dir.iterdir()):
            if not example_dir.is_dir():
                continue
            example_id = example_dir.name

            if example_id_filter and example_id != example_id_filter:
                continue

            tokens, was_processed, point_ids = await _ingest_example_folder(
                example_dir=example_dir,
                example_group=example_group,
                example_id=example_id,
                examples_root=examples_root,
                store=store,
                embedder=embedder,
                collection=collection,
                stored_hashes=stored_hashes,
                dry_run=dry_run,
            )

            total_tokens += tokens
            if was_processed:
                n_processed += 1
                if not dry_run and point_ids:
                    processed_chunk_ids[example_id] = point_ids
            else:
                n_skipped += 1

    # ── Orphan cleanup ────────────────────────────────────────────────────────
    # Remove Qdrant entries for source files that have been deleted from disk.
    # Summary chunks are excluded from stored_hashes (file_id==""), so they
    # do not appear as false orphans.
    disk_file_paths = _collect_all_disk_paths(examples_root)
    orphan_paths = set(stored_hashes.keys()) - disk_file_paths

    if orphan_paths:
        logger.info(
            "Orphan cleanup: removing %d path(s) no longer on disk.",
            len(orphan_paths),
        )
        if not dry_run:
            for fp in orphan_paths:
                store.delete_by_file_path(collection, fp)
        else:
            logger.info(
                "[DRY RUN] Would remove orphans: %s …",
                list(orphan_paths)[:5],
            )

    estimated_cost = round((total_tokens / 1_000_000) * _PRICE_PER_M_TOKENS, 6)

    # ── Sync qdrant_chunk_ids back to KUZU ────────────────────────────────────────
    # After embedding, write the Qdrant point UUIDs back into the KUZU graph
    # so Example nodes carry their own qdrant_chunk_ids. This step is
    # non-blocking — a failure here does not abort the ingest result.
    if not dry_run and processed_chunk_ids:
        import os
        kuzu_db_path = settings.KUZU_DB_PATH
        if os.path.exists(kuzu_db_path):
            try:
                from src.msbc.embedding.graph_store import KuzuStore
                kuzu_store = KuzuStore(db_path=kuzu_db_path)
                for eid, cids in processed_chunk_ids.items():
                    kuzu_store.update_example_chunk_ids(eid, cids)
                    logger.info(
                        "KUZU sync: '%s' → %d chunk IDs written.", eid, len(cids)
                    )
                kuzu_store.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("KUZU chunk-ID sync failed (non-fatal): %s", exc)
        else:
            logger.debug(
                "KUZU DB not found at '%s' — skipping chunk ID sync. "
                "Run 'python scripts/build_graph.py' first.",
                kuzu_db_path,
            )

    summary = {
        "processed_folders":  n_processed,
        "skipped_folders":    n_skipped,
        "total_tokens":       total_tokens,
        "estimated_cost_usd": estimated_cost,
        "dry_run":            dry_run,
    }

    logger.info(
        "Examples ingest complete — processed=%d skipped=%d "
        "tokens=%d cost=$%.4f%s",
        n_processed, n_skipped,
        total_tokens, estimated_cost,
        " [DRY RUN]" if dry_run else "",
    )
    return summary


# ---------------------------------------------------------------------------
# Internal: per-example-folder processing
# ---------------------------------------------------------------------------

async def _ingest_example_folder(
    example_dir: Path,
    example_group: str,
    example_id: str,
    examples_root: Path,
    store: QdrantStore,
    embedder: OpenAIEmbedder,
    collection: str,
    stored_hashes: dict[str, str],
    dry_run: bool,
) -> tuple[int, bool, list[str]]:
    """
    Process one example folder (e.g. ``Dashboard03/``).

    Returns
    -------
    (tokens_used, was_processed, point_ids)
        ``was_processed`` is ``False`` when the folder was skipped because
        nothing changed since the last ingest run.
        ``point_ids`` is the list of Qdrant point UUID strings upserted
        (empty when skipped or dry_run).
    """
    project_root = examples_root.parent

    def _rel_path(p: Path) -> str:
        """Return the path relative to *project_root*, with forward slashes."""
        return str(p.relative_to(project_root)).replace("\\", "/")

    # ── Collect source files ──────────────────────────────────────────────────
    source_files = sorted(
        f for f in example_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _EXAMPLE_EXTS
    )

    if not source_files:
        logger.debug("Example '%s' has no source files — skipping.", example_id)
        return 0, False, []

    # ── Load content + compute hashes ─────────────────────────────────────────
    file_contents: dict[Path, str] = {}
    file_hashes: dict[Path, str] = {}

    for fp in source_files:
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read '%s': %s", fp, exc)
            continue
        file_contents[fp] = content
        file_hashes[fp] = _content_hash(content)

    if not file_contents:
        logger.warning("All files in '%s' were unreadable.", example_id)
        return 0, False, []

    # ── Incremental sync check ────────────────────────────────────────────────
    # get_stored_file_hashes skips points with empty file_id (summary chunks)
    # so stored_hashes already contains only real file paths.
    folder_prefix = (
        f"{examples_root.name}/{example_group}/{example_id}/"
    )
    stored_paths_for_folder = {
        fp for fp in stored_hashes
        if fp.startswith(folder_prefix)
    }
    disk_rel_paths = {_rel_path(fp) for fp in file_contents}

    # Changed if: set of files differs, or any file hash differs.
    any_changed = stored_paths_for_folder != disk_rel_paths or any(
        file_hashes[fp] != stored_hashes.get(_rel_path(fp))
        for fp in file_contents
    )

    if not any_changed:
        logger.debug("Example '%s/%s' unchanged — skipping.", example_group, example_id)
        return 0, False, []

    logger.info("Processing example folder: %s/%s", example_group, example_id)

    # ── Feature detection for each file ──────────────────────────────────────
    file_analyses: list[dict[str, Any]] = []

    for fp, content in file_contents.items():
        file_name = fp.name
        rel_fp = _rel_path(fp)

        pattern = _detect_example_pattern(content, rel_fp)
        file_role = _detect_file_role(file_name, content)
        msbc_symbols, msbc_packages = extract_msbc_imports(content)

        features: dict[str, Any] = {}
        if pattern == "ConfigurableDashboard":
            features = _detect_dashboard_features(content)
        elif pattern == "ConfigurableForm":
            features = _detect_form_features(content)

        complexity = _detect_complexity(content, file_role, features)
        use_case = _generate_use_case(example_id, pattern, file_role, features)

        file_analyses.append({
            "fp":           fp,
            "rel_fp":       rel_fp,
            "file_name":    file_name,
            "content":      content,
            "content_hash": file_hashes[fp],
            "pattern":      pattern,
            "file_role":    file_role,
            "msbc_symbols": msbc_symbols,
            "msbc_packages": msbc_packages,
            "features":     features,
            "complexity":   complexity,
            "use_case":     use_case,
        })

    if not file_analyses:
        logger.warning("No analyzable files for '%s/%s'.", example_group, example_id)
        return 0, False, []

    # ── Aggregate folder-level attributes ────────────────────────────────────
    all_patterns    = [a["pattern"] for a in file_analyses]
    aggregate_pattern = _dominant_pattern(all_patterns)

    aggregate_features = _union_features([a["features"] for a in file_analyses])
    max_complexity     = _max_complexity([a["complexity"] for a in file_analyses])

    all_msbc_symbols: list[str] = sorted({
        sym for a in file_analyses for sym in a["msbc_symbols"]
    })
    all_msbc_packages: list[str] = sorted({
        pkg for a in file_analyses for pkg in a["msbc_packages"]
    })

    summary_use_case = _generate_use_case(
        example_id, aggregate_pattern, "summary", aggregate_features
    )
    file_list = [a["file_name"] for a in file_analyses]

    # ── Build per-file chunk payloads ─────────────────────────────────────────
    all_texts: list[str] = []
    all_payloads: list[ExampleChunkPayload] = []

    for analysis in file_analyses:
        ext = Path(analysis["file_name"]).suffix.lower()
        language: Literal["typescript", "tsx", "unknown"] = (
            "tsx"        if ext == ".tsx" else
            "typescript" if ext in (".ts", ".js", ".jsx") else
            "unknown"
        )

        # chunk_example_file always returns exactly one ChunkResult per file
        chunks = chunk_example_file(
            source=analysis["content"],
            file_path=analysis["rel_fp"],
            file_name=analysis["file_name"],
            example_id=example_id,
            example_group=example_group,
        )
        if not chunks:
            logger.warning(
                "chunk_example_file produced no chunks for '%s'.", analysis["rel_fp"]
            )
            continue

        chunk = chunks[0]
        features = analysis["features"]

        payload = ExampleChunkPayload(
            file_path=analysis["rel_fp"],
            file_name=analysis["file_name"],
            file_id=analysis["content_hash"],
            chunk_id=chunk.chunk_id,
            chunk_index=0,
            total_chunks=1,
            language=language,
            example_id=example_id,
            example_group=example_group,
            example_pattern=aggregate_pattern,
            file_role=analysis["file_role"],
            complexity=analysis["complexity"],
            is_verified=True,
            use_case=analysis["use_case"],
            msbc_imports=analysis["msbc_symbols"],
            msbc_packages=analysis["msbc_packages"],
            # Dashboard feature flags
            has_search=features.get("has_search", False),
            has_filters=features.get("has_filters", False),
            has_actions=features.get("has_actions", False),
            has_list_view=features.get("has_list_view", False),
            has_mode_switch=features.get("has_mode_switch", False),
            has_pagination=features.get("has_pagination", False),
            has_advance_filters=features.get("has_advance_filters", False),
            has_api_integration=features.get("has_api_integration", False),
            has_row_selection=features.get("has_row_selection", False),
            # Form feature flags
            has_sections=features.get("has_sections", False),
            has_nested_groups=features.get("has_nested_groups", False),
            has_custom_validators=features.get("has_custom_validators", False),
            has_custom_component=features.get("has_custom_component", False),
            has_conditional_visibility=features.get("has_conditional_visibility", False),
            has_conditional_validation=features.get("has_conditional_validation", False),
            has_dependent_fields=features.get("has_dependent_fields", False),
            has_file_upload=features.get("has_file_upload", False),
            field_types_used=features.get("field_types_used", []),
            is_summary_chunk=False,
            text=chunk.text,
            summary=analysis["use_case"],
            text_hash=_text_hash(chunk.text_to_embed),
        )

        all_texts.append(chunk.text_to_embed)
        all_payloads.append(payload)

    # ── Build synthetic summary chunk ─────────────────────────────────────────
    summary_chunk = build_example_summary_chunk(
        example_id=example_id,
        example_pattern=aggregate_pattern,
        use_case=summary_use_case,
        features=aggregate_features,
        file_list=file_list,
        complexity=max_complexity,
    )

    # Canonical file_path for the summary point — used for delete + indexing.
    # This is a synthetic chunk aggregating all files in the folder.
    # The __summary__ suffix in file_path is a bookkeeping convention used by
    # delete_by_file_path to target this specific point across runs.
    # It does NOT correspond to a real file on disk.
    summary_rel_path = (
        f"{examples_root.name}/{example_group}/{example_id}/__summary__"
    )

    summary_payload = ExampleChunkPayload(
        file_path=summary_rel_path,
        file_name=example_id,          # the folder name, e.g. "Form03"
        file_id="",                    # synthetic — excluded from get_stored_file_hashes
        chunk_id=summary_chunk.chunk_id,
        chunk_index=0,
        total_chunks=1,
        language="tsx",
        example_id=example_id,
        example_group=example_group,
        example_pattern=aggregate_pattern,
        file_role="summary",
        complexity=max_complexity,
        is_verified=True,
        use_case=summary_use_case,
        msbc_imports=all_msbc_symbols,
        msbc_packages=all_msbc_packages,
        has_search=aggregate_features.get("has_search", False),
        has_filters=aggregate_features.get("has_filters", False),
        has_actions=aggregate_features.get("has_actions", False),
        has_list_view=aggregate_features.get("has_list_view", False),
        has_mode_switch=aggregate_features.get("has_mode_switch", False),
        has_pagination=aggregate_features.get("has_pagination", False),
        has_advance_filters=aggregate_features.get("has_advance_filters", False),
        has_api_integration=aggregate_features.get("has_api_integration", False),
        has_row_selection=aggregate_features.get("has_row_selection", False),
        has_sections=aggregate_features.get("has_sections", False),
        has_nested_groups=aggregate_features.get("has_nested_groups", False),
        has_custom_validators=aggregate_features.get("has_custom_validators", False),
        has_custom_component=aggregate_features.get("has_custom_component", False),
        has_conditional_visibility=aggregate_features.get("has_conditional_visibility", False),
        has_conditional_validation=aggregate_features.get("has_conditional_validation", False),
        has_dependent_fields=aggregate_features.get("has_dependent_fields", False),
        has_file_upload=aggregate_features.get("has_file_upload", False),
        field_types_used=aggregate_features.get("field_types_used", []),
        is_summary_chunk=True,
        text=summary_chunk.text,
        summary=summary_chunk.text,
        text_hash=_text_hash(summary_chunk.text_to_embed),
    )

    all_texts.append(summary_chunk.text_to_embed)
    all_payloads.append(summary_payload)

    if not all_texts:
        logger.warning("No texts to embed for '%s/%s'.", example_group, example_id)
        return 0, True, []

    # ── Embed all texts in one batch ──────────────────────────────────────────
    vectors, usage = await embedder.embed_texts(all_texts)
    tokens: int = usage.get("total_tokens", 0)

    # ── Build PointStructs ────────────────────────────────────────────────────
    points: list[PointStruct] = [
        PointStruct(
            id=make_point_id(payload.chunk_id),
            vector=vector,
            payload=payload.model_dump(),
        )
        for payload, vector in zip(all_payloads, vectors)
    ]

    # ── Delete old points then upsert fresh ones ──────────────────────────────
    if not dry_run:
        # Remove all old file chunks for this folder
        for analysis in file_analyses:
            store.delete_by_file_path(collection, analysis["rel_fp"])
        # Remove old summary chunk
        store.delete_by_file_path(collection, summary_rel_path)
        # Upsert everything at once
        store.upsert_batch(collection, points)
    else:
        logger.info(
            "[DRY RUN] '%s/%s' — would upsert %d points (%d tokens).",
            example_group, example_id, len(points), tokens,
        )
    logger.info(
        "Example '%s/%s' — %d file chunk(s) + 1 summary upserted (%d tokens).",
        example_group, example_id, len(file_analyses), tokens,
    )

    # Return the Qdrant point IDs so the caller can sync them back to KUZU.
    point_ids = [str(p.id) for p in points]
    return tokens, True, point_ids
