"""
Unified ingestion pipeline — single collection + examples collection.

Replaces the old 3-collection ingest.py.  Scans the ReactToolKits monorepo
via db/scanner.py, chunks each file, enriches metadata, and upserts into:

  rtk_unified_{model}_{dims}   — code + docs + config in ONE collection
  rtk_examples_{model}_{dims}  — correct_code_examples (forms & dashboards)

Change detection:
  ADD    — file is new (no matching file_id in Qdrant)
  UPDATE — content hash changed → delete old chunks, upsert new
  DELETE — file no longer on disk → remove all its chunks

Run:
    python db/unified_ingest.py                         # full sync
    python db/unified_ingest.py --dry-run               # preview
    python db/unified_ingest.py --examples-only         # only ingest examples
    python db/unified_ingest.py --unified-only           # only ingest toolkit code
"""

import argparse
import hashlib
import logging
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    PayloadSchemaType,
)

from db.chunker import (
    Chunk,
    chunk_code_file,
    chunk_interfaces,
    chunk_json_config,
    chunk_markdown_file,
    chunk_style_file,
)
from db.unified_chunker import chunk_for_examples
from db.embedder import DEFAULT_DIMENSIONS, DEFAULT_MODEL_NAME, get_embedder
from db.enricher import Enricher
from db.scanner import FileRecord, scan_monorepo
from db.unified_schema import (
    UnifiedChunkPayload,
    get_all_collection_names,
    get_collection_name,
    get_vector_config,
    get_unified_payload_indexes,
    get_unified_text_indexes,
    get_examples_payload_indexes,
    PACKAGE_LAYERS,
    file_content_hash,
    text_hash,
    make_point_id,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 64
QDRANT_URL = "http://localhost:6333"

# Correct code examples path (relative to this project)
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "correct_code_examples"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Qdrant state ──────────────────────────────────────────────────────────────

def _get_stored_files(client: QdrantClient, collection_name: str) -> Dict[str, str]:
    """Scroll all points and return {file_path: file_id}."""
    stored: Dict[str, str] = {}
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=None,
            with_payload=["file_path", "file_id"],
            limit=256,
            offset=offset,
        )
        for r in records:
            pl = r.payload or {}
            fp = pl.get("file_path")
            fid = pl.get("file_id")
            if fp and fid:
                stored.setdefault(fp, fid)
        if offset is None:
            break
    return stored


def _delete_file_chunks(
    client: QdrantClient,
    collection_name: str,
    fid: str,
    dry_run: bool = False,
) -> int:
    """Delete every point whose file_id matches *fid*."""
    count_result = client.count(
        collection_name=collection_name,
        count_filter=Filter(
            must=[FieldCondition(key="file_id", match=MatchValue(value=fid))]
        ),
        exact=True,
    )
    n = count_result.count
    if dry_run or n == 0:
        return n
    client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[FieldCondition(key="file_id", match=MatchValue(value=fid))]
        ),
    )
    return n


# ── Collection setup ──────────────────────────────────────────────────────────

def _ensure_collection(
    client: QdrantClient,
    collection_name: str,
    dimensions: int,
    kind: str,
) -> None:
    """Create collection with payload indexes if it doesn't exist."""
    existing = {c.name for c in client.get_collections().collections}
    if collection_name in existing:
        logger.info("Collection '%s' already exists.", collection_name)
        return

    logger.info("Creating collection '%s' (kind=%s, dims=%d)", collection_name, kind, dimensions)
    client.create_collection(
        collection_name=collection_name,
        vectors_config=get_vector_config(dimensions),
    )

    # Create payload indexes
    if kind == "unified":
        for field_name, schema_type in get_unified_payload_indexes().items():
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema_type,
            )
        for field_name, text_params in get_unified_text_indexes().items():
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=text_params,
            )
    elif kind == "examples":
        for field_name, schema_type in get_examples_payload_indexes().items():
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema_type,
            )


def _ensure_all_collections(
    client: QdrantClient,
    model_name: str,
    dimensions: int,
) -> Dict[str, str]:
    """Create both collections. Returns {kind: collection_name}."""
    names = get_all_collection_names(model_name, dimensions)
    for kind, cname in names.items():
        _ensure_collection(client, cname, dimensions, kind)
    return names


# ── Unified: Chunking dispatch ────────────────────────────────────────────────

def _determine_content_type(rec: FileRecord) -> str:
    """Map existing file_category to unified content_type."""
    if rec.file_category in ("readme", "story", "package_manifest"):
        return "doc"
    if rec.file_category in ("type_definition", "json_config", "registry"):
        return "config"
    return "code"


def _determine_module_layer(package_name: str) -> str:
    """Map package_name to module_layer."""
    return PACKAGE_LAYERS.get(package_name, "infra")


def _chunk_for_unified(
    rec: FileRecord,
    enricher: Enricher,
    enrichment_meta: Dict,
) -> List[Tuple[Chunk, Dict]]:
    """
    Chunk one FileRecord for the unified collection.

    Returns list of (Chunk, payload_dict).
    All content types go to the same collection with content_type field
    set appropriately.
    """
    results: List[Tuple[Chunk, Dict]] = []
    content_type = _determine_content_type(rec)

    # ── Chunk based on content type ──────────────────────────────────
    if content_type == "code":
        if rec.language in ("typescript", "javascript"):
            chunks = chunk_code_file(rec.content, rec.rel_path, rec.path.stem)
        elif rec.language in ("scss", "css"):
            chunks = chunk_style_file(rec.content, rec.rel_path, rec.path.stem)
        else:
            chunks = chunk_code_file(rec.content, rec.rel_path, rec.path.stem)

    elif content_type == "doc":
        if rec.language == "markdown" or rec.file_category in ("readme", "package_manifest"):
            chunks = chunk_markdown_file(rec.content, rec.rel_path, rec.path.stem)
        elif rec.file_category == "story":
            chunks = chunk_code_file(rec.content, rec.rel_path, rec.path.stem)
        else:
            chunks = chunk_markdown_file(rec.content, rec.rel_path, rec.path.stem)

    elif content_type == "config":
        if rec.file_category == "json_config":
            chunks = chunk_json_config(rec.content, rec.rel_path, rec.path.stem)
        else:
            # Interface / type extraction
            chunks = chunk_interfaces(rec.content, rec.rel_path, rec.path.stem)
            # If interface extraction found nothing, fall back to code chunking
            if not chunks:
                chunks = chunk_code_file(rec.content, rec.rel_path, rec.path.stem)
    else:
        chunks = chunk_code_file(rec.content, rec.rel_path, rec.path.stem)

    total = len(chunks)
    now_iso = datetime.now(timezone.utc).isoformat()

    for chunk in chunks:
        # Build unified payload
        payload = UnifiedChunkPayload(
            # Universal
            content_type=content_type,
            repo_name="react-toolkit",
            namespace=rec.package_name,
            file_path=rec.rel_path,
            file_name=rec.path.name,
            file_id=rec.file_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            total_chunks=total,
            language=rec.language,
            summary=enricher.generate_summary(
                chunk.text, chunk.component_name, chunk.chunk_type
            ),
            # Sync
            text_hash=_text_hash(chunk.text),
            ingested_at=now_iso,
        )

        # ── Code-specific fields ─────────────────────────────────────
        if content_type == "code":
            payload.file_category = rec.file_category
            payload.chunk_type = chunk.chunk_type
            payload.symbol_name = chunk.component_name
            payload.module_path = rec.module_path
            payload.module_layer = _determine_module_layer(rec.package_name)
            payload.parameters = chunk.props
            payload.exports = chunk.exports
            payload.imports = chunk.imports
            payload.dependencies = enrichment_meta.get("dependencies", [])
            payload.related_files = enrichment_meta.get("related_files", [])

        # ── Doc-specific fields ──────────────────────────────────────
        elif content_type == "doc":
            doc_type_map = {
                "readme": "readme",
                "story": "storybook_story",
                "package_manifest": "package_manifest",
            }
            payload.doc_type = doc_type_map.get(rec.file_category, "usage_example")
            payload.section_title = chunk.component_name
            payload.heading_level = chunk.heading_level
            payload.section_path = chunk.section_path
            payload.has_code_example = chunk.has_code_example
            payload.code_language = chunk.code_language
            payload.mentioned_symbols = (
                chunk.mentioned_components
                or enrichment_meta.get("mentioned_components", [])
            )
            payload.mentioned_modules = (
                chunk.mentioned_packages
                or enrichment_meta.get("mentioned_packages", [])
            )

        # ── Config-specific fields ───────────────────────────────────
        elif content_type == "config":
            payload.config_type = chunk.config_type or "interface"
            payload.schema_name = chunk.schema_name or chunk.component_name
            payload.config_fields = chunk.fields if chunk.fields else []
            payload.extends = chunk.extends if chunk.extends else []

        results.append((chunk, payload.to_dict()))

    return results


# ── Embedding + upserting ─────────────────────────────────────────────────────

def _upsert_batch(
    client: QdrantClient,
    collection_name: str,
    embedder,
    batch: List[Tuple[Chunk, dict]],
) -> int:
    """Embed and upsert a batch. Returns count upserted."""
    texts = [c.text for c, _ in batch]
    vectors = embedder.embed_texts(texts, task="search_document")
    points: List[PointStruct] = []
    for (chunk, payload), vector in zip(batch, vectors):
        payload["text"] = chunk.text
        point_id = make_point_id(payload["chunk_id"])
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))
    client.upsert(collection_name=collection_name, points=points)
    return len(points)


# ═════════════════════════════════════════════════════════════════════════════
# UNIFIED COLLECTION SYNC
# ═════════════════════════════════════════════════════════════════════════════

def sync_unified(
    client: QdrantClient,
    collection_name: str,
    embedder,
    model_name: str,
    dimensions: int,
    dry_run: bool = False,
) -> Dict:
    """Sync the monorepo into the unified collection."""
    # 1. Scan monorepo
    logger.info("Scanning monorepo...")
    fs_files: Dict[str, FileRecord] = scan_monorepo()
    logger.info("Files on disk: %d", len(fs_files))

    # 2. Prepare enricher
    enricher = Enricher(fs_files)
    enricher.prepare()

    # 3. Read Qdrant state
    stored = _get_stored_files(client, collection_name)
    logger.info("Unified collection: %d files stored", len(stored))

    # 4. Classify changes
    to_add: List[FileRecord] = []
    to_update: List[FileRecord] = []
    to_delete: List[Tuple[str, str]] = []

    for rel_path, rec in fs_files.items():
        if rel_path not in stored:
            to_add.append(rec)
        elif stored[rel_path] != rec.file_id:
            to_update.append(rec)

    for rel_path, fid in stored.items():
        if rel_path not in fs_files:
            to_delete.append((rel_path, fid))

    logger.info("Plan — ADD: %d  UPDATE: %d  DELETE: %d", len(to_add), len(to_update), len(to_delete))

    if dry_run:
        logger.info("[DRY-RUN] No changes will be written.")
        for r in to_add:
            logger.info("  [ADD]    %s", r.rel_path)
        for r in to_update:
            logger.info("  [UPDATE] %s", r.rel_path)
        for rp, _ in to_delete:
            logger.info("  [DELETE] %s", rp)
        return {
            "collection": collection_name,
            "added": len(to_add),
            "updated": len(to_update),
            "deleted": len(to_delete),
            "upserted": 0,
            "dry_run": True,
        }

    # 5. Execute deletes
    for rel_path, fid in to_delete:
        n = _delete_file_chunks(client, collection_name, fid)
        logger.info("Deleted %d old chunks for: %s", n, rel_path)
    for rec in to_update:
        old_fid = stored[rec.rel_path]
        n = _delete_file_chunks(client, collection_name, old_fid)
        logger.info("Deleted %d stale chunks for: %s", n, rec.rel_path)

    # 6. Chunk + enrich + embed + upsert
    all_pairs: List[Tuple[Chunk, dict]] = []
    for rec in to_add + to_update:
        enrichment_meta = enricher.enrich(rec)
        items = _chunk_for_unified(rec, enricher, enrichment_meta)
        for chunk, payload in items:
            all_pairs.append((chunk, payload))

    total_upserted = 0
    if all_pairs:
        logger.info("Embedding and upserting %d chunks...", len(all_pairs))
        for batch_start in range(0, len(all_pairs), BATCH_SIZE):
            batch = all_pairs[batch_start : batch_start + BATCH_SIZE]
            n = _upsert_batch(client, collection_name, embedder, batch)
            total_upserted += n

    logger.info("Unified sync complete: %d points upserted.", total_upserted)
    return {
        "collection": collection_name,
        "added": len(to_add),
        "updated": len(to_update),
        "deleted": len(to_delete),
        "upserted": total_upserted,
        "dry_run": False,
    }


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLES COLLECTION SYNC
# ═════════════════════════════════════════════════════════════════════════════

def _scan_examples_dir() -> List[Dict]:
    """
    Walk correct_code_examples/ and return a list of file records.

    Each record: {
        path, file_name, rel_path, content, file_id,
        example_id, example_group, related_files
    }
    """
    if not EXAMPLES_DIR.exists():
        logger.warning("Examples directory not found: %s", EXAMPLES_DIR)
        return []

    records: List[Dict] = []

    for group_dir in sorted(EXAMPLES_DIR.iterdir()):
        if not group_dir.is_dir():
            continue
        example_group = group_dir.name  # "Dashboard_Samples" or "Form_Samples"

        for example_dir in sorted(group_dir.iterdir()):
            if not example_dir.is_dir():
                continue
            example_id = example_dir.name  # "Dashboard01", "Form08"

            # Collect all files in this example folder
            files_in_example = [
                f for f in sorted(example_dir.iterdir())
                if f.is_file() and f.suffix.lower() in (".ts", ".tsx", ".jsx", ".js")
            ]
            file_names = [f.name for f in files_in_example]

            for fpath in files_in_example:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                rel_path = fpath.relative_to(EXAMPLES_DIR).as_posix()
                related = [n for n in file_names if n != fpath.name]

                records.append({
                    "path": fpath,
                    "file_name": fpath.name,
                    "rel_path": rel_path,
                    "content": content,
                    "file_id": file_content_hash(content),
                    "example_id": example_id,
                    "example_group": example_group,
                    "related_files": related,
                })

    logger.info("Scanned %d example files.", len(records))
    return records


def sync_examples(
    client: QdrantClient,
    collection_name: str,
    embedder,
    dry_run: bool = False,
) -> Dict:
    """Sync correct_code_examples into the examples collection."""
    # 1. Scan examples
    file_records = _scan_examples_dir()
    if not file_records:
        logger.info("No example files found.")
        return {"collection": collection_name, "added": 0, "updated": 0, "deleted": 0, "upserted": 0, "dry_run": dry_run}

    # 2. Read Qdrant state
    stored = _get_stored_files(client, collection_name)
    logger.info("Examples collection: %d files stored", len(stored))

    # 3. Classify changes
    to_add = []
    to_update = []
    to_delete = []

    current_paths = set()
    for rec in file_records:
        current_paths.add(rec["rel_path"])
        if rec["rel_path"] not in stored:
            to_add.append(rec)
        elif stored[rec["rel_path"]] != rec["file_id"]:
            to_update.append(rec)

    for rel_path, fid in stored.items():
        if rel_path not in current_paths:
            to_delete.append((rel_path, fid))

    logger.info("Examples plan — ADD: %d  UPDATE: %d  DELETE: %d", len(to_add), len(to_update), len(to_delete))

    if dry_run:
        logger.info("[DRY-RUN] No changes will be written to examples collection.")
        return {
            "collection": collection_name,
            "added": len(to_add),
            "updated": len(to_update),
            "deleted": len(to_delete),
            "upserted": 0,
            "dry_run": True,
        }

    # 4. Execute deletes
    for rel_path, fid in to_delete:
        n = _delete_file_chunks(client, collection_name, fid)
        logger.info("Examples: deleted %d chunks for: %s", n, rel_path)
    for rec in to_update:
        old_fid = stored[rec["rel_path"]]
        n = _delete_file_chunks(client, collection_name, old_fid)
        logger.info("Examples: deleted %d stale chunks for: %s", n, rec["rel_path"])

    # 5. Chunk + embed + upsert
    all_pairs: List[Tuple[Chunk, dict]] = []
    for rec in to_add + to_update:
        pairs = chunk_for_examples(
            source=rec["content"],
            file_path=rec["rel_path"],
            file_name=rec["file_name"],
            example_id=rec["example_id"],
            example_group=rec["example_group"],
            related_files=rec["related_files"],
        )
        all_pairs.extend(pairs)

    total_upserted = 0
    if all_pairs:
        logger.info("Examples: embedding and upserting %d chunks...", len(all_pairs))
        for batch_start in range(0, len(all_pairs), BATCH_SIZE):
            batch = all_pairs[batch_start : batch_start + BATCH_SIZE]
            n = _upsert_batch(client, collection_name, embedder, batch)
            total_upserted += n

    logger.info("Examples sync complete: %d points upserted.", total_upserted)
    return {
        "collection": collection_name,
        "added": len(to_add),
        "updated": len(to_update),
        "deleted": len(to_delete),
        "upserted": total_upserted,
        "dry_run": False,
    }


# ═════════════════════════════════════════════════════════════════════════════
# COMBINED SYNC
# ═════════════════════════════════════════════════════════════════════════════

def sync(
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
    dry_run: bool = False,
    unified_only: bool = False,
    examples_only: bool = False,
) -> Dict:
    """
    Full sync: unified collection + examples collection.

    Returns combined summary dict.
    """
    client = QdrantClient(url=QDRANT_URL, timeout=60)
    collection_names = _ensure_all_collections(client, model_name, dimensions)
    embedder = get_embedder(model_name, dimensions)

    summary = {
        "collections": collection_names,
        "model_name": model_name,
        "dimensions": dimensions,
        "dry_run": dry_run,
    }

    if not examples_only:
        unified_stats = sync_unified(
            client=client,
            collection_name=collection_names["unified"],
            embedder=embedder,
            model_name=model_name,
            dimensions=dimensions,
            dry_run=dry_run,
        )
        summary["unified"] = unified_stats

    if not unified_only:
        examples_stats = sync_examples(
            client=client,
            collection_name=collection_names["examples"],
            embedder=embedder,
            dry_run=dry_run,
        )
        summary["examples"] = examples_stats

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync ReactToolKits + correct code examples into Qdrant (unified architecture)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    parser.add_argument("--unified-only", action="store_true", help="Only sync the unified collection.")
    parser.add_argument("--examples-only", action="store_true", help="Only sync the examples collection.")
    args = parser.parse_args()

    result = sync(
        dry_run=args.dry_run,
        unified_only=args.unified_only,
        examples_only=args.examples_only,
    )

    import json as _json
    print(_json.dumps(result, indent=2))
