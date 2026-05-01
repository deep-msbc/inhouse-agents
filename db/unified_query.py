"""
Unified query layer — single-collection search with payload filtering.

Replaces the old multi-collection db/query.py.  All searches hit ONE
collection and use content_type payload filters to narrow results.

Also provides search against the examples collection for retrieving
correct code reference material.

Public API
──────────
  search_unified()                  — search unified collection (optional content_type filter)
  search_unified_multi_lane()       — per-lane weighted search inside unified collection
  search_unified_with_file_context()— semantic search + sibling-chunk expansion
  search_examples()                 — search examples collection
  search_examples_with_file_context()
  get_full_example_set()            — fetch every file for one example_id
  search_combined()                 — ONE call: intent-aware search across both collections
"""

import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from db.embedder import DEFAULT_DIMENSIONS, DEFAULT_MODEL_NAME, get_embedder
from db.unified_schema import CollectionKind, ContentType, get_collection_name

logger = logging.getLogger(__name__)

QDRANT_URL = "http://localhost:6333"
TOP_K = 5


# ── Filter builder ────────────────────────────────────────────────────────────

def _build_unified_filter(
    content_types: Optional[List[str]] = None,
    extra_filters: Optional[Dict[str, Any]] = None,
) -> Optional[Filter]:
    """
    Build a Qdrant Filter for the unified collection.

    Always filters by content_type first (the most selective pre-filter).
    Then adds any additional keyword filters.
    """
    conditions = []

    if content_types:
        if len(content_types) == 1:
            conditions.append(
                FieldCondition(key="content_type", match=MatchValue(value=content_types[0]))
            )
        else:
            conditions.append(
                FieldCondition(key="content_type", match=MatchAny(any=content_types))
            )

    if extra_filters:
        for field_name, value in extra_filters.items():
            if isinstance(value, list):
                conditions.append(
                    FieldCondition(key=field_name, match=MatchAny(any=value))
                )
            elif isinstance(value, (str, int, float, bool)):
                conditions.append(
                    FieldCondition(key=field_name, match=MatchValue(value=value))
                )
            # skip None, dict, or any other non-scalar — Qdrant MatchValue can't handle them

    return Filter(must=conditions) if conditions else None


def _build_examples_filter(
    extra_filters: Optional[Dict[str, Any]] = None,
) -> Optional[Filter]:
    """Build a Qdrant Filter for the examples collection."""
    if not extra_filters:
        return None
    conditions = []
    for field_name, value in extra_filters.items():
        if isinstance(value, list):
            conditions.append(
                FieldCondition(key=field_name, match=MatchAny(any=value))
            )
        elif isinstance(value, (str, int, float, bool)):
            conditions.append(
                FieldCondition(key=field_name, match=MatchValue(value=value))
            )
        # skip None, dict, or any other non-scalar
    return Filter(must=conditions) if conditions else None


def _format_hit(hit) -> Dict[str, Any]:
    """Normalize a Qdrant hit into a standard result dict."""
    payload = hit.payload or {}
    return {
        "score": hit.score,
        "text": payload.get("text", ""),
        "metadata": {k: v for k, v in payload.items() if k != "text"},
    }


# ═════════════════════════════════════════════════════════════════════════════
# UNIFIED COLLECTION SEARCH
# ═════════════════════════════════════════════════════════════════════════════

def search_unified(
    query: str,
    content_types: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Search the unified collection with optional content_type and payload filters.

    Parameters
    ----------
    content_types : list of "code" | "doc" | "config", or None for all types.
    filters : additional payload filters (e.g. {"language": "typescript"}).
    """
    collection = get_collection_name(model_name, dimensions, "unified")
    embedder = get_embedder(model_name, dimensions)
    query_vector = embedder.embed_texts([query], task="search_query")[0]

    client = QdrantClient(url=QDRANT_URL, timeout=60)
    qdrant_filter = _build_unified_filter(content_types, filters)

    logger.info(
        "Searching unified '%s' (content_types=%s, top_k=%d, filters=%s)",
        collection, content_types, top_k, filters,
    )

    # Check collection exists
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        logger.warning("Unified collection '%s' doesn't exist yet.", collection)
        return []

    response = client.query_points(
        collection_name=collection,
        query=query_vector,
        query_filter=qdrant_filter,
        limit=top_k,
        with_payload=True,
    )

    hits = [_format_hit(h) for h in response.points]
    logger.info("Found %d results.", len(hits))
    return hits


def search_unified_multi_lane(
    query: str,
    targets: Optional[List[Tuple[str, float]]] = None,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Multi-lane search within the unified collection.

    Each lane queries a content_type with its own weight, then results
    are merged and sorted by weighted score.

    Parameters
    ----------
    targets : list of (content_type, weight), e.g.
        [("code", 1.0), ("doc", 0.8), ("config", 0.6)]
        If None, searches all types with equal weight.
    """
    if targets is None:
        targets = [("code", 1.0), ("doc", 1.0), ("config", 1.0)]

    collection = get_collection_name(model_name, dimensions, "unified")
    embedder = get_embedder(model_name, dimensions)
    query_vector = embedder.embed_texts([query], task="search_query")[0]
    client = QdrantClient(url=QDRANT_URL, timeout=60)

    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        logger.warning("Unified collection '%s' doesn't exist yet.", collection)
        return []

    all_hits: List[Dict[str, Any]] = []

    for content_type, weight in targets:
        qdrant_filter = _build_unified_filter([content_type], filters)

        try:
            response = client.query_points(
                collection_name=collection,
                query=query_vector,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning("Search failed for content_type '%s': %s", content_type, exc)
            continue

        for hit in response.points:
            result = _format_hit(hit)
            result["score"] = result["score"] * weight
            result["metadata"]["content_type"] = content_type
            all_hits.append(result)

    all_hits.sort(key=lambda x: x["score"], reverse=True)
    return all_hits[:top_k * len(targets)]


def search_unified_with_file_context(
    query: str,
    content_types: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Semantic search + file-context expansion (fetch all sibling chunks).

    Returns results grouped by file with all chunks in reading order.
    """
    hits = search_unified(
        query, content_types, filters, top_k, model_name, dimensions
    )
    if not hits:
        return []

    # Deduplicate by file_id, keep highest score per file
    file_scores: Dict[str, Tuple[float, str]] = {}  # file_id -> (score, content_type)
    for hit in hits:
        fid = hit["metadata"].get("file_id")
        ct = hit["metadata"].get("content_type", "code")
        if fid and (fid not in file_scores or hit["score"] > file_scores[fid][0]):
            file_scores[fid] = (hit["score"], ct)

    collection = get_collection_name(model_name, dimensions, "unified")
    client = QdrantClient(url=QDRANT_URL, timeout=60)
    results: List[Dict[str, Any]] = []

    for file_id, (best_score, content_type) in file_scores.items():
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
                    "symbol_name": r.payload.get("symbol_name", ""),
                    "parameters": r.payload.get("parameters", []),
                    "exports": r.payload.get("exports", []),
                    "content_type": r.payload.get("content_type", ""),
                }
                for r in records
            ],
            key=lambda x: x["chunk_index"],
        )

        first_payload = records[0].payload or {}
        results.append({
            "file_name": first_payload.get("file_name", ""),
            "file_path": first_payload.get("file_path", ""),
            "file_id": file_id,
            "namespace": first_payload.get("namespace", ""),
            "content_type": content_type,
            "total_chunks": first_payload.get("total_chunks", len(sorted_chunks)),
            "best_match_score": best_score,
            "chunks": sorted_chunks,
        })

    results.sort(key=lambda x: x["best_match_score"], reverse=True)
    return results


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLES COLLECTION SEARCH
# ═════════════════════════════════════════════════════════════════════════════

def search_examples(
    query: str,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Search the correct_code_examples collection.

    Common filters:
      {"example_pattern": "ConfigurableForm"}
      {"example_pattern": "ConfigurableDashboard"}
      {"complexity": "complex"}
      {"has_sections": True, "has_custom_validators": True}
      {"file_role": "config"}
      {"example_group": "Form_Samples"}
    """
    collection = get_collection_name(model_name, dimensions, "examples")
    embedder = get_embedder(model_name, dimensions)
    query_vector = embedder.embed_texts([query], task="search_query")[0]

    client = QdrantClient(url=QDRANT_URL, timeout=60)
    qdrant_filter = _build_examples_filter(filters)

    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        logger.warning("Examples collection '%s' doesn't exist yet.", collection)
        return []

    response = client.query_points(
        collection_name=collection,
        query=query_vector,
        query_filter=qdrant_filter,
        limit=top_k,
        with_payload=True,
    )

    hits = [_format_hit(h) for h in response.points]
    logger.info("Found %d example results.", len(hits))
    return hits


def search_examples_with_file_context(
    query: str,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = TOP_K,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Search examples + expand each hit to include all sibling chunks from the
    same example file.
    """
    hits = search_examples(query, filters, top_k, model_name, dimensions)
    if not hits:
        return []

    file_scores: Dict[str, float] = {}
    for hit in hits:
        fid = hit["metadata"].get("file_id")
        if fid and (fid not in file_scores or hit["score"] > file_scores[fid]):
            file_scores[fid] = hit["score"]

    collection = get_collection_name(model_name, dimensions, "examples")
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
                    "symbol_name": r.payload.get("symbol_name", ""),
                    "chunk_type": r.payload.get("chunk_type", ""),
                    "file_role": r.payload.get("file_role", ""),
                }
                for r in records
            ],
            key=lambda x: x["chunk_index"],
        )

        first_payload = records[0].payload or {}
        results.append({
            "file_name": first_payload.get("file_name", ""),
            "file_path": first_payload.get("file_path", ""),
            "file_id": file_id,
            "example_id": first_payload.get("example_id", ""),
            "example_group": first_payload.get("example_group", ""),
            "example_pattern": first_payload.get("example_pattern", ""),
            "file_role": first_payload.get("file_role", ""),
            "complexity": first_payload.get("complexity", ""),
            "use_case": first_payload.get("use_case", ""),
            "total_chunks": first_payload.get("total_chunks", len(sorted_chunks)),
            "best_match_score": best_score,
            "related_files": first_payload.get("related_files", []),
            "chunks": sorted_chunks,
        })

    results.sort(key=lambda x: x["best_match_score"], reverse=True)
    return results


def _expand_examples_by_example_id(
    hits: List[Dict[str, Any]],
    model_name: str,
    dimensions: int,
) -> List[Dict[str, Any]]:
    """
    Given raw example chunk hits, group by example_id and return ALL files
    for each matched example via get_full_example_set().

    This fixes the "only config.ts returned" problem: even when the ANN match
    was on a config chunk, the tsx page_component and types file are included.
    """
    example_scores: Dict[str, float] = {}
    for hit in hits:
        eid = hit["metadata"].get("example_id", "")
        score = hit.get("score", 0.0)
        if eid and (eid not in example_scores or score > example_scores[eid]):
            example_scores[eid] = score
    if not example_scores:
        return []
    results: List[Dict[str, Any]] = []
    for example_id, best_score in sorted(
        example_scores.items(), key=lambda x: x[1], reverse=True
    ):
        for file_result in get_full_example_set(example_id, model_name, dimensions):
            file_result["example_id"] = example_id
            file_result["best_match_score"] = best_score
            file_result["_source"] = "examples"
            results.append(file_result)
    return results


def get_full_example_set(
    example_id: str,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> List[Dict[str, Any]]:
    """
    Fetch ALL files/chunks for a specific example (e.g. "Form08").

    Useful when you want the complete reference: page + config + types + custom component.
    """
    collection = get_collection_name(model_name, dimensions, "examples")
    client = QdrantClient(url=QDRANT_URL, timeout=60)

    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        return []

    records, _ = client.scroll(
        collection_name=collection,
        scroll_filter=Filter(
            must=[FieldCondition(key="example_id", match=MatchValue(value=example_id))]
        ),
        with_payload=True,
        limit=500,
    )

    # Group by file_path
    files: Dict[str, List[Dict]] = {}
    for r in records:
        pl = r.payload or {}
        fp = pl.get("file_path", "")
        if fp not in files:
            files[fp] = []
        files[fp].append({
            "text": pl.get("text", ""),
            "chunk_index": pl.get("chunk_index", 0),
            "symbol_name": pl.get("symbol_name", ""),
            "file_role": pl.get("file_role", ""),
        })

    results = []
    for fp, chunks in files.items():
        chunks.sort(key=lambda x: x["chunk_index"])
        first_rec = next((r for r in records if (r.payload or {}).get("file_path") == fp), None)
        pl = first_rec.payload if first_rec else {}
        results.append({
            "file_path": fp,
            "file_name": pl.get("file_name", ""),
            "file_role": pl.get("file_role", ""),
            "example_pattern": pl.get("example_pattern", ""),
            "complexity": pl.get("complexity", ""),
            "use_case": pl.get("use_case", ""),
            "chunks": chunks,
        })

    # Sort: page_component first, then config, then types, then custom_component
    role_order = {"page_component": 0, "config": 1, "types": 2, "custom_component": 3}
    results.sort(key=lambda x: role_order.get(x["file_role"], 99))
    return results


# ═════════════════════════════════════════════════════════════════════════════
# COMBINED SEARCH — single entry point for the planner / API
# ═════════════════════════════════════════════════════════════════════════════

# Intent patterns: (compiled_regex, content_type, weight_boost)
# Evaluated in order; first match wins the primary intent.
_INTENT_RULES: List[Tuple[re.Pattern, str, float]] = [
    # Doc intent — "how to", "usage", "guide", "what is", "explain", "story"
    (re.compile(
        r"\b(how\s+to|what\s+is|explain|guide|tutorial|usage|example|storybook|readme|docs?)\b",
        re.IGNORECASE,
    ), "doc", 1.2),
    # Config intent — type/interface/schema/props keywords
    (re.compile(
        r"\b(interface|type\s+alias|schema|props?\b|config\s+type|extends|enum)\b",
        re.IGNORECASE,
    ), "config", 1.2),
    # Code / component intent — PascalCase component name or hook or import
    (re.compile(
        r"\b(use[A-Z]\w+|[A-Z][a-z]+(?:[A-Z][a-z]+)+|import|component|hook)\b",
    ), "code", 1.1),
]

# weights for each content_type lane when no strong intent detected
# code > config > doc reflects typical query relevance priority
_DEFAULT_LANE_WEIGHTS: Dict[str, float] = {
    "code":   1.0,
    "config": 0.9,
    "doc":    0.7,
}


def _classify_intent(query: str) -> Dict[str, float]:
    """
    Return per-content_type weights based on keywords in the query.

    All three lanes are always searched; the matched intent just boosts
    the weight of the most relevant lane so those results rank higher
    after merge.
    """
    weights = dict(_DEFAULT_LANE_WEIGHTS)
    for pattern, content_type, boost in _INTENT_RULES:
        if pattern.search(query):
            weights[content_type] = max(weights[content_type], boost)
            break  # only first matching intent changes the primary boost
    return weights


class CombinedSearchResult:
    """Structured result from search_combined()."""

    def __init__(
        self,
        unified_hits: List[Dict[str, Any]],
        example_hits: List[Dict[str, Any]],
        intent_weights: Dict[str, float],
        query: str,
    ) -> None:
        self.unified_hits = unified_hits          # from unified collection
        self.example_hits = example_hits          # from examples collection
        self.intent_weights = intent_weights      # {"code": 1.0, "doc": 1.2, ...}
        self.query = query

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "intent_weights": self.intent_weights,
            "unified_results": self.unified_hits,
            "example_results": self.example_hits,
            "total_unified": len(self.unified_hits),
            "total_examples": len(self.example_hits),
        }


def search_combined(
    query: str,
    unified_top_k: int = TOP_K,
    examples_top_k: int = TOP_K,
    unified_filters: Optional[Dict[str, Any]] = None,
    examples_filters: Optional[Dict[str, Any]] = None,
    expand_files: bool = False,
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> CombinedSearchResult:
    """
    Single entry-point that searches BOTH collections intelligently.

    How unified collection retrieval works:
    ─────────────────────────────────────────
    The unified collection stores code, doc, and config chunks together.
    A blind ANN search over all of them would mix apples and oranges because
    the same query phrase can appear in code comments, readme sections, and
    type definitions.

    To fix this we run THREE separate sub-queries — one per content_type —
    each with its own Qdrant filter so ANN stays within its type bucket.
    The results are merged and re-ranked using intent-derived weights:

      • Query contains "how to" / "usage" / "guide" → doc weight boosted to 1.2
      • Query contains "interface" / "schema" / "props" → config weight boosted to 1.2
      • Query contains a PascalCase component name or "hook" → code weight boosted to 1.1
      • No strong signal → equal weights (1.0 / 0.9 / 0.8) so code ranks slightly first

    How examples collection retrieval works:
    ─────────────────────────────────────────
    The examples collection contains human-verified ConfigurableForm and
    ConfigurableDashboard implementations.  It is searched with embedding
    similarity against the same query, then results are returned alongside
    the unified results so the planner / LLM can choose the most relevant
    reference implementation.

    Parameters
    ----------
    unified_top_k      : results per content_type lane (code / doc / config).
    examples_top_k     : max example results.
    unified_filters    : extra Qdrant payload filters applied to every lane.
    examples_filters   : payload filters for the examples collection.
    expand_files       : if True, expand hits to all sibling chunks from the
                         same file (useful for full implementation context).
    """
    intent_weights = _classify_intent(query)

    # ── Unified: per-lane retrieval with code-lane TypeScript filter ──────────
    # Restricting the code lane to language=typescript prevents CSS/SCSS
    # selector chunks from outranking component files on dashboard queries.
    code_filters = dict(unified_filters or {})
    if "language" not in code_filters:
        code_filters["language"] = "typescript"

    unified_hits: List[Dict[str, Any]] = []

    if expand_files:
        # Code lane — TypeScript only, full file context
        code_lane_hits = search_unified_with_file_context(
            query=query,
            content_types=["code"],
            filters=code_filters,
            top_k=unified_top_k,
            model_name=model_name,
            dimensions=dimensions,
        )
        for hit in code_lane_hits:
            hit["_source"] = "unified"
            hit["_content_type"] = "code"
            hit["best_match_score"] = hit.get("best_match_score", 0.0) * intent_weights["code"]
        unified_hits.extend(code_lane_hits)
        # Doc + Config lanes — no language restriction
        for content_type in ("doc", "config"):
            weight = intent_weights[content_type]
            lane_hits = search_unified_with_file_context(
                query=query,
                content_types=[content_type],
                filters=unified_filters,
                top_k=unified_top_k,
                model_name=model_name,
                dimensions=dimensions,
            )
            for hit in lane_hits:
                hit["_source"] = "unified"
                hit["_content_type"] = content_type
                hit["best_match_score"] = hit.get("best_match_score", 0.0) * weight
            unified_hits.extend(lane_hits)
        # Deduplicate by file_id, keep highest weighted score
        seen_fids: Dict[str, int] = {}
        deduped: List[Dict[str, Any]] = []
        for item in unified_hits:
            fid = item.get("file_id", "")
            if fid not in seen_fids:
                seen_fids[fid] = len(deduped)
                deduped.append(item)
            else:
                existing_item = deduped[seen_fids[fid]]
                if item["best_match_score"] > existing_item["best_match_score"]:
                    deduped[seen_fids[fid]] = item
        unified_hits = sorted(deduped, key=lambda x: x["best_match_score"], reverse=True)
    else:
        # Chunk-level: code lane TypeScript-restricted, doc+config unrestricted
        code_hits = search_unified_multi_lane(
            query=query,
            targets=[("code", intent_weights["code"])],
            filters=code_filters,
            top_k=unified_top_k,
            model_name=model_name,
            dimensions=dimensions,
        )
        other_hits = search_unified_multi_lane(
            query=query,
            targets=[
                ("doc",    intent_weights["doc"]),
                ("config", intent_weights["config"]),
            ],
            filters=unified_filters,
            top_k=unified_top_k,
            model_name=model_name,
            dimensions=dimensions,
        )
        unified_hits = sorted(
            code_hits + other_hits, key=lambda x: x["score"], reverse=True
        )
        for hit in unified_hits:
            hit["_source"] = "unified"

    # ── Examples: ANN hit → expand ALL files for each matched example_id ──────
    # search_examples_with_file_context only expands by file_id — it returns
    # full chunks for the matched file but NOT the other files in the same
    # example set (e.g. the tsx page_component when ANN matched the config).
    # _expand_examples_by_example_id uses get_full_example_set() to pull
    # every file (tsx + config + types) for each unique matched example_id.
    raw_example_hits = search_examples(
        query=query,
        filters=examples_filters,
        top_k=examples_top_k,
        model_name=model_name,
        dimensions=dimensions,
    )
    if expand_files:
        example_hits = _expand_examples_by_example_id(raw_example_hits, model_name, dimensions)
    else:
        example_hits = raw_example_hits
        for hit in example_hits:
            hit["_source"] = "examples"

    logger.info(
        "search_combined: %d unified hits, %d example hits (intent_weights=%s)",
        len(unified_hits), len(example_hits), intent_weights,
    )

    return CombinedSearchResult(
        unified_hits=unified_hits,
        example_hits=example_hits,
        intent_weights=intent_weights,
        query=query,
    )
