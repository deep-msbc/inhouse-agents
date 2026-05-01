"""
Multi-collection query layer.

Supports searching one collection at a time or across all 3 simultaneously
with per-collection score weighting.
"""
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from db.embedder import EmbeddingService, get_embedder, DEFAULT_MODEL_NAME, DEFAULT_DIMENSIONS
from db.schema import CollectionType, get_all_collection_names, get_collection_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

QDRANT_URL = "http://localhost:6333"
TOP_K = 5

# Per-collection allowed filter fields
_CODE_FILTER_FIELDS = {
    "package_name", "package_layer", "module_path", "language",
    "file_category", "component_name", "chunk_type",
}
_DOCS_FILTER_FIELDS = {
    "package_name", "doc_type", "section_title", "heading_level",
    "has_code_example",
}
_CONFIG_FILTER_FIELDS = {
    "package_name", "config_type", "schema_name",
}

_ALLOWED_FIELDS_BY_TYPE: Dict[str, set] = {
    "code": _CODE_FILTER_FIELDS,
    "docs": _DOCS_FILTER_FIELDS,
    "config": _CONFIG_FILTER_FIELDS,
}


def _build_filter(
    filter_dict: Optional[Dict[str, Any]],
    collection_type: str = "code",
) -> Optional[Filter]:
    """Convert a plain dict into a Qdrant Filter with must-conditions."""
    if not filter_dict:
        return None
    allowed = _ALLOWED_FIELDS_BY_TYPE.get(collection_type, _CODE_FILTER_FIELDS)
    conditions = []
    for field_name, value in filter_dict.items():
        if field_name not in allowed:
            logger.warning(
                "Ignoring unknown filter field '%s' for collection type '%s'",
                field_name, collection_type,
            )
            continue
        conditions.append(FieldCondition(key=field_name, match=MatchValue(value=value)))
    return Filter(must=conditions) if conditions else None


def _format_hit(hit) -> Dict[str, Any]:
    """Normalize a Qdrant hit into our standard result dict."""
    payload = hit.payload or {}
    return {
        "score": hit.score,
        "text": payload.get("text", ""),
        "metadata": {k: v for k, v in payload.items() if k != "text"},
    }


# ── Single-collection search ─────────────────────────────────────────────────

def search(
    query: str,
    collection_type: CollectionType = "code",
    filter: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Embed *query* and search a single collection.

    Parameters
    ----------
    collection_type : "code" | "docs" | "config"
    """
    embedder = get_embedder(model_name, dimensions)
    collection = get_collection_name(model_name, dimensions, collection_type)
    query_vector = embedder.embed_texts([query], task="search_query")[0]

    client = QdrantClient(url=QDRANT_URL, timeout=60)
    qdrant_filter = _build_filter(filter, collection_type)

    logger.info(
        "Searching '%s' (top_k=%d, filter=%s)...", collection, top_k, filter
    )
    response = client.query_points(
        collection_name=collection,
        query=query_vector,
        query_filter=qdrant_filter,
        limit=top_k,
        with_payload=True,
    )

    hits = [_format_hit(h) for h in response.points]
    logger.info("Found %d results in '%s'.", len(hits), collection)
    return hits


# ── Multi-collection search ──────────────────────────────────────────────────

def search_collections(
    query: str,
    targets: Optional[List[Tuple[CollectionType, float]]] = None,
    filter: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Search across multiple collections with weighted scoring.

    Parameters
    ----------
    targets : list of (collection_type, weight), e.g.
        [("code", 1.0), ("docs", 0.8), ("config", 0.6)]
        If None, searches all 3 with equal weight.

    Returns hits sorted by weighted score, each tagged with
    ``metadata["collection_type"]``.
    """
    if targets is None:
        targets = [("code", 1.0), ("docs", 1.0), ("config", 1.0)]

    embedder = get_embedder(model_name, dimensions)
    query_vector = embedder.embed_texts([query], task="search_query")[0]
    client = QdrantClient(url=QDRANT_URL, timeout=60)

    all_hits: List[Dict[str, Any]] = []

    for ctype, weight in targets:
        cname = get_collection_name(model_name, dimensions, ctype)

        # Check if collection exists
        existing = {c.name for c in client.get_collections().collections}
        if cname not in existing:
            logger.debug("Collection '%s' doesn't exist yet, skipping.", cname)
            continue

        qdrant_filter = _build_filter(filter, ctype)

        try:
            response = client.query_points(
                collection_name=cname,
                query=query_vector,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning("Search failed for '%s': %s", cname, exc)
            continue

        for hit in response.points:
            result = _format_hit(hit)
            result["score"] = result["score"] * weight
            result["metadata"]["collection_type"] = ctype
            all_hits.append(result)

    # Sort by weighted score, take top_k overall
    all_hits.sort(key=lambda x: x["score"], reverse=True)
    return all_hits[:top_k]


# ── File-context expansion ────────────────────────────────────────────────────

def search_with_file_context(
    query: str,
    collection_type: CollectionType = "code",
    filter: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Semantic search + automatic expansion to all sibling chunks from the same file.

    Returns hits grouped by file with all chunks in reading order.
    """
    hits = search(query, collection_type, filter, top_k, model_name, dimensions)
    if not hits:
        return []

    # Deduplicate file_ids, preserve order
    file_scores: Dict[str, float] = {}
    for hit in hits:
        fid = hit["metadata"].get("file_id")
        if fid and fid not in file_scores:
            file_scores[fid] = hit["score"]

    collection = get_collection_name(model_name, dimensions, collection_type)
    client = QdrantClient(url=QDRANT_URL, timeout=60)
    results: List[Dict[str, Any]] = []

    for file_id, best_score in file_scores.items():
        records, _ = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="file_id", match=MatchValue(value=file_id))]
            ),
            with_payload=True,
            limit=200,
        )
        if not records:
            continue

        sorted_chunks = sorted(
            [
                {
                    "text": r.payload.get("text", ""),
                    "chunk_index": r.payload.get("chunk_index", 0),
                    "chunk_type": r.payload.get("chunk_type", ""),
                    "component_name": r.payload.get("component_name", ""),
                    "props": r.payload.get("props", []),
                    "exports": r.payload.get("exports", []),
                }
                for r in records
            ],
            key=lambda x: x["chunk_index"],
        )

        first_payload = records[0].payload or {}
        results.append(
            {
                "file_name": first_payload.get("file_name", ""),
                "file_path": first_payload.get("file_path", ""),
                "file_id": file_id,
                "package_name": first_payload.get("package_name", ""),
                "total_chunks": first_payload.get("total_chunks", len(sorted_chunks)),
                "best_match_score": best_score,
                "collection_type": collection_type,
                "chunks": sorted_chunks,
            }
        )

    results.sort(key=lambda x: x["best_match_score"], reverse=True)
    return results
