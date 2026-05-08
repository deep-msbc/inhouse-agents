"""
agents/code_generator/retriever.py
───────────────────────────────────
Phase 2 — Retrieval.

Builds a complete ScreenContext for one screen via four sub-phases:
  A. Kuzu structural lookup (features → examples, component internals + TypeDefs)
  B. Qdrant toolkit vector search + Kuzu→Qdrant example exact lookup
  C. Whole-file assembly (always fetch all chunks for a matched file)
  D. Reranking (toolkit by vector score; examples by Kuzu score + role priority)

Entry point: retrieve_for_screen()
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import settings
from src.msbc.embedding.embedder import OpenAIEmbedder
from src.msbc.embedding.schema import get_collection_name
from src.msbc.llm.clients.openai_client import call_llm_with_schema
from src.msbc.llm.prompts.loader import load_prompt
from src.msbc.models.schemas.code_generator import ScreenContext

# Matches TypeScript/JS import statements that reference relative paths.
# e.g. import { Foo } from './foo'  or  import type { Bar } from '../bar'
_TS_RELATIVE_IMPORT_RE = re.compile(
    r"""import\s+(?:type\s+)?(?:\{[^}]+\}|\*\s+as\s+\w+|\w+)\s+from\s+['"](\.[^'"]+)['"]""",
    re.MULTILINE,
)

logger = logging.getLogger(__name__)

# Flip to True once score-based retrieval is validated in production.
ENABLE_LLM_RERANKING = False

_RERANK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["ranked_paths"],
    "properties": {
        "ranked_paths": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Import-following: fetch referenced sibling files from Qdrant
# ---------------------------------------------------------------------------

def _follow_imports(
    assembled: list[dict],
    qdrant_store: Any,
    collection: str,
    already_fetched: set[str],
    max_extra: int = 3,
) -> list[dict]:
    """
    For each file in *assembled*, parse its relative imports and fetch any
    referenced files that were not already retrieved.

    This ensures that when an example service file imports from './types',
    the LLM also receives the types file as context — preventing it from
    inventing type names.

    Parameters
    ----------
    assembled       : files already assembled (each has 'file_path', 'content')
    qdrant_store    : QdrantStore used for scroll_by_file_path
    collection      : Qdrant collection to search
    already_fetched : set of file_path strings already in context (mutated in-place)
    max_extra       : hard cap on how many extra files to add (avoids runaway fetches)

    Returns
    -------
    List of newly assembled file dicts (NOT including the originals).
    """
    extra: list[dict] = []
    added = 0

    for file in assembled:
        if added >= max_extra:
            break
        file_path: str = file.get("file_path", "")
        content: str = file.get("content", "")
        if not content:
            continue

        # Derive the directory of this file so relative paths can be resolved.
        # file_path is stored as a relative path within the collection
        # (e.g. "ProductionProcessMaster/ProductionProcessMaster.service.ts")
        parts = file_path.replace("\\", "/").rsplit("/", 1)
        file_dir = parts[0] if len(parts) == 2 else ""

        for match in _TS_RELATIVE_IMPORT_RE.finditer(content):
            if added >= max_extra:
                break
            rel = match.group(1)  # e.g. './types/ProductionProcessMaster.types'

            # Resolve the relative path against file_dir
            segments = (file_dir + "/" + rel).replace("\\", "/").split("/")
            resolved_parts: list[str] = []
            for seg in segments:
                if seg == "..":
                    if resolved_parts:
                        resolved_parts.pop()
                elif seg and seg != ".":
                    resolved_parts.append(seg)
            resolved = "/".join(resolved_parts)

            # Try common extensions
            candidates = [resolved, resolved + ".ts", resolved + ".tsx"]
            for candidate in candidates:
                if candidate in already_fetched:
                    break
                chunks = qdrant_store.scroll_by_file_path(collection, candidate)
                if chunks:
                    full_text = "\n".join(c.get("text", "") for c in chunks)
                    extra.append({
                        "file_path": candidate,
                        "content": full_text,
                        "best_score": 0.0,
                        "total_chunks": len(chunks),
                        "file_role": "imported_dependency",
                    })
                    already_fetched.add(candidate)
                    added += 1
                    logger.debug(
                        "[retriever] import-follow: fetched %s (referenced by %s)",
                        candidate,
                        file_path,
                    )
                    break

    return extra


# ---------------------------------------------------------------------------
# Phase A — Feature inference & Kuzu lookup
# ---------------------------------------------------------------------------

def _infer_features(screen: Any) -> list[str]:
    """Infer feature flags from a ScreenPlan object."""
    flags: list[str] = []
    components = getattr(screen, "components", [])

    if any(getattr(c, "filters", None) for c in components):
        flags.append("has_filters")

    if any(getattr(c, "type", "") == "filter_panel" for c in components):
        flags.append("has_search")

    if any(
        getattr(a, "behavior", "") in ("delete", "bulk_delete")
        for c in components
        for a in getattr(c, "actions", [])
    ):
        flags.append("has_row_selection")

    if any(getattr(c, "actions", None) for c in components):
        flags.append("has_actions")

    if any(getattr(c, "data_hook", "") == "useApiRequest" for c in components):
        flags.append("has_api_integration")

    if any(
        getattr(f, "type", "") == "fileUpload"
        for c in components
        for f in getattr(c, "fields", [])
    ):
        flags.append("has_file_upload")

    return flags


def _score_examples_by_kuzu_features(
    screen: Any,
    kuzu_candidates: list[dict],
) -> list[dict]:
    """
    Score Kuzu example candidates and return all of them sorted descending by score.

    Each returned dict has an ``example_score`` key added.  Callers should
    slice to their desired top-N (default: top-3).
    """
    components = getattr(screen, "components", [])
    primary = getattr(components[0], "toolkit_mapping", "") if components else ""
    n = len(components)
    similarity_query: str = getattr(screen, "similarity_query", "") or ""

    scored: list[dict] = []
    for ex in kuzu_candidates:
        score = 0.5  # baseline: passed Kuzu structural filter

        if ex.get("pattern") == primary:
            score += 3.0

        if n >= 4 and ex.get("complexity") == "complex":
            score += 1.0
        elif n <= 2 and ex.get("complexity") == "simple":
            score += 1.0

        if ex.get("use_case") and ex["use_case"] in similarity_query:
            score += 0.5

        scored.append({**ex, "example_score": score})

    return sorted(scored, key=lambda x: x["example_score"], reverse=True)


# ---------------------------------------------------------------------------
# Phase C — Whole-file assembly
# ---------------------------------------------------------------------------

def _assemble_full_files(
    hits: list[dict],
    qdrant_store: Any,
    collection: str,
) -> list[dict]:
    """
    Given a list of Qdrant hits (either search results or get_by_ids results),
    group by file_path, fetch every chunk via scroll_by_file_path(), and merge
    into one complete file block per file.

    Handles two hit shapes:
      - Search hits:   {"id", "score", "payload": {"file_path": ..., ...}}
      - get_by_ids hits (flat): {"id", "file_path": ..., ...}

    Extra metadata fields (example_score, file_role) are preserved from the
    first hit seen for each file_path so rerankers have the data they need.
    """
    # Per-file tracking: best vector score, file_role, example_score
    seen_score: dict[str, float] = {}
    seen_role: dict[str, str] = {}
    seen_example_score: dict[str, float] = {}

    for h in hits:
        # Normalise: search hits nest payload; get_by_ids / example hits are flat
        if "payload" in h and isinstance(h["payload"], dict):
            payload = h["payload"]
            score = float(h.get("score", 0.0))
        else:
            payload = {k: v for k, v in h.items() if k != "id"}
            score = float(h.get("score", 0.0))

        file_path = payload.get("file_path", "")
        if not file_path:
            continue

        seen_score[file_path] = max(seen_score.get(file_path, 0.0), score)

        if file_path not in seen_role:
            role = payload.get("file_role", "") or payload.get("file_type", "")
            if role:
                seen_role[file_path] = role

        if file_path not in seen_example_score:
            ex_score = payload.get("example_score")
            if ex_score is not None:
                seen_example_score[file_path] = float(ex_score)

    assembled: list[dict] = []

    for file_path, best_score in seen_score.items():
        chunks = qdrant_store.scroll_by_file_path(collection, file_path)

        full_text = "\n".join(c.get("text", "") for c in chunks)

        entry: dict = {
            "file_path": file_path,
            "content": full_text,
            "best_score": best_score,
            "total_chunks": len(chunks),
        }
        if file_path in seen_role:
            entry["file_role"] = seen_role[file_path]
        if file_path in seen_example_score:
            entry["example_score"] = seen_example_score[file_path]

        assembled.append(entry)

    return assembled


# ---------------------------------------------------------------------------
# Phase D — Reranking
# ---------------------------------------------------------------------------

def _rerank_toolkit_by_score(
    assembled: list[dict],
    top_n: int = 5,
    min_score: float = 0.30,
) -> list[dict]:
    """Filter by min_score threshold, then return top_n by descending score."""
    filtered = [f for f in assembled if f.get("best_score", 0.0) >= min_score]
    return sorted(filtered, key=lambda f: f.get("best_score", 0.0), reverse=True)[:top_n]


def _rerank_examples_by_kuzu_score(
    assembled: list[dict],
    top_n: int = 3,
) -> list[dict]:
    """
    Rank example files by (example_score + role_priority), descending.

    Example files come from Kuzu + exact Qdrant lookup, so they carry no
    vector-search relevance score.  Never filter by vector score threshold.
    ``example_score`` is attached per-file by ``_assemble_full_files`` from
    the Kuzu candidate scoring step.
    """
    if not assembled:
        return []

    # Higher numeric priority = more useful for generation.
    role_priority: dict[str, float] = {
        "page":           1.00,
        "page_component": 1.00,
        "form":           0.95,
        "config":         0.90,
        "service":        0.85,
        "types":          0.75,
        "component":      0.70,
        "hook":           0.65,
        "index":          0.40,
        "style":          0.20,
    }

    ranked: list[dict] = []
    for f in assembled:
        example_score = float(f.get("example_score") or 0.0)
        role = f.get("file_role") or f.get("file_type") or ""
        role_score = role_priority.get(role, 0.50)
        final_score = example_score + role_score
        ranked.append({
            **f,
            "role_priority": role_score,
            "final_score": final_score,
        })

    return sorted(
        ranked,
        key=lambda f: (
            float(f.get("final_score", 0.0)),
            float(f.get("example_score", 0.0)),
            float(f.get("role_priority", 0.0)),
        ),
        reverse=True,
    )[:top_n]


# ---------------------------------------------------------------------------
# Phase D (optional) — LLM reranking
# ---------------------------------------------------------------------------

async def _llm_rerank(
    assembled: list[dict],
    screen_plan: Any,
    file_type: str,
    top_n: int,
) -> list[dict]:
    """
    Re-order *assembled* file blocks by LLM relevance judgment.

    Only called when ENABLE_LLM_RERANKING is True.  Falls back to the
    original order if the LLM call fails or returns unrecognised paths.
    """
    if not assembled:
        return assembled

    prompt = load_prompt("code_generator/rerank_chunks.yaml")

    screen_name = getattr(screen_plan, "screen_name", "unknown")

    # Build abbreviated candidates: file_path + first 400 chars of content.
    candidates = [
        {
            "file_path": f["file_path"],
            "preview": f.get("content", "")[:400],
        }
        for f in assembled
    ]

    # Abbreviate screen plan to avoid blowing token budget.
    try:
        raw_plan = screen_plan.model_dump() if hasattr(screen_plan, "model_dump") else {}
        plan_summary = {
            "screen_name": raw_plan.get("screen_name", screen_name),
            "type": raw_plan.get("type", ""),
            "similarity_query": raw_plan.get("similarity_query", ""),
        }
    except Exception:
        plan_summary = {"screen_name": screen_name}

    user_text = prompt._fmt(
        prompt.user_template,
        screen_name=screen_name,
        file_type=file_type,
        screen_plan_json=json.dumps(plan_summary, indent=2),
        candidates_json=json.dumps(candidates, indent=2),
    )
    system_text = prompt._fmt(
        prompt.system,
        top_n=str(top_n),
    )

    try:
        result = await call_llm_with_schema(
            system_prompt=system_text,
            user_prompt=user_text,
            schema=_RERANK_SCHEMA,
            max_retries=1,
        )
        ranked_paths: list[str] = result.get("ranked_paths", [])
    except Exception as exc:
        logger.warning("[retriever] LLM rerank failed, keeping score order: %s", exc)
        return assembled[:top_n]

    # Map ranked paths back to full file blocks; drop unknowns.
    path_index = {f["file_path"]: f for f in assembled}
    reranked = [path_index[p] for p in ranked_paths if p in path_index]

    # Append any blocks not mentioned by the LLM (keep them at the end).
    mentioned = set(ranked_paths)
    tail = [f for f in assembled if f["file_path"] not in mentioned]
    return (reranked + tail)[:top_n]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def retrieve_for_screen(
    screen_plan: Any,
    module_name: str,
    business_rules: list[str],
    kuzu_store: Any,
    qdrant_store: Any,
) -> ScreenContext:
    """
    Build a complete ScreenContext for one screen.

    Parameters
    ----------
    screen_plan
        A ScreenPlan Pydantic object (from FrontendPlan).
    module_name : str
        Parent module name.
    business_rules : list[str]
        Business rules from ExtractionOutput for the module.
    kuzu_store
        KuzuStore instance (from embedding.graph_store).
    qdrant_store
        QdrantStore instance (from embedding.store).

    Returns
    -------
    ScreenContext
    """
    screen_name: str = getattr(screen_plan, "screen_name", "unknown")
    logger.info("[retriever] screen=%s module=%s", screen_name, module_name)

    # ── Phase A: Kuzu structural lookup ──────────────────────────────────────

    features = _infer_features(screen_plan)
    logger.debug("[retriever] %s features=%s", screen_name, features)

    kuzu_candidates = kuzu_store.get_examples_by_features(features) if features else []
    # Score all candidates and take the top-3 (gives generation more pattern variety)
    top_examples = _score_examples_by_kuzu_features(screen_plan, kuzu_candidates)[:3]
    logger.debug(
        "[retriever] %s kuzu_candidates=%d top_examples=%d",
        screen_name,
        len(kuzu_candidates),
        len(top_examples),
    )

    # Component internals + TypeDefs from Kuzu
    component_graph: list[dict] = []
    components = getattr(screen_plan, "components", [])
    mappings: set[str] = {
        getattr(c, "toolkit_mapping", "")
        for c in components
        if getattr(c, "toolkit_mapping", "")
    }
    for mapping in mappings:
        component_graph += kuzu_store.get_component_internals(mapping)
        component_graph += kuzu_store.get_component_types(mapping)

    # ── Phase B: Qdrant retrieval ─────────────────────────────────────────────

    toolkit_col = get_collection_name("toolkit", settings.EMBEDDING_DIMENSIONS)
    examples_col = get_collection_name("examples", settings.EMBEDDING_DIMENSIONS)

    similarity_query: str = getattr(screen_plan, "similarity_query", "") or screen_name
    embedder = OpenAIEmbedder()
    vectors, _ = await embedder.embed_texts([similarity_query])
    query_vec: list[float] = vectors[0]

    # Toolkit: vector search
    toolkit_hits = qdrant_store.search(
        toolkit_col,
        query_vec,
        filters={"content_type": ["code", "config"], "language": "typescript"},
        top_k=15,
    )
    logger.debug("[retriever] %s toolkit_hits=%d", screen_name, len(toolkit_hits))

    # Examples: exact lookup via Kuzu → Qdrant get_by_ids for each top example.
    # example_score is embedded into each hit so _assemble_full_files can
    # propagate it and _rerank_examples_by_kuzu_score can use it.
    example_hits: list[dict] = []
    for ex in top_examples:
        example_id = ex.get("example_id", "")
        example_score = float(ex.get("example_score", 0.0))
        if not example_id:
            continue

        example_files_meta = kuzu_store.get_example_files(example_id)
        chunk_ids = [
            f["qdrant_chunk_id"]
            for f in example_files_meta
            if f.get("qdrant_chunk_id")
        ]
        if not chunk_ids:
            continue

        raw = qdrant_store.get_by_ids(examples_col, chunk_ids)
        # Build lookup: chunk_id → file metadata from Kuzu
        meta_map = {
            f["qdrant_chunk_id"]: f
            for f in example_files_meta
            if f.get("qdrant_chunk_id")
        }
        for hit in raw:
            meta = meta_map.get(hit.get("id", ""), {})
            hit.setdefault("file_role", meta.get("file_role", ""))
            hit.setdefault("file_path", meta.get("file_path", hit.get("file_path", "")))
            # Embed example_score so _assemble_full_files can copy it to the assembled entry
            hit["example_score"] = example_score
        example_hits.extend(raw)

    logger.debug("[retriever] %s example_hits=%d", screen_name, len(example_hits))

    # ── Phase C: Whole-file assembly ──────────────────────────────────────────

    assembled_toolkit = _assemble_full_files(toolkit_hits, qdrant_store, toolkit_col)
    assembled_examples = _assemble_full_files(example_hits, qdrant_store, examples_col)

    # ── Phase C+: Import-following ────────────────────────────────────────────
    # Collect file_paths already fetched so we don't re-fetch them.
    already_fetched: set[str] = {f["file_path"] for f in assembled_toolkit + assembled_examples}

    # Follow imports in toolkit files — mainly catches .types.ts / .service.ts
    # siblings referenced by retrieved example pages or config files.
    toolkit_import_extras = _follow_imports(
        assembled_toolkit, qdrant_store, toolkit_col, already_fetched, max_extra=3
    )
    # Follow imports in example files (same collection as examples).
    example_import_extras = _follow_imports(
        assembled_examples, qdrant_store, examples_col, already_fetched, max_extra=3
    )
    assembled_toolkit = assembled_toolkit + toolkit_import_extras
    assembled_examples = assembled_examples + example_import_extras

    logger.debug(
        "[retriever] %s import-follow: +%d toolkit, +%d example files",
        screen_name,
        len(toolkit_import_extras),
        len(example_import_extras),
    )

    # ── Phase D: Reranking ────────────────────────────────────────────────────

    toolkit_files = _rerank_toolkit_by_score(assembled_toolkit, top_n=5)
    example_files = _rerank_examples_by_kuzu_score(assembled_examples, top_n=3)

    if ENABLE_LLM_RERANKING:
        file_type = (
            getattr(screen_plan, "file_structure", [{}])[0].get("type", "page")
            if getattr(screen_plan, "file_structure", [])
            else "page"
        )
        toolkit_files = await _llm_rerank(toolkit_files, screen_plan, file_type, top_n=5)
        example_files = await _llm_rerank(example_files, screen_plan, file_type, top_n=3)

    logger.info(
        "[retriever] %s done — toolkit=%d examples=%d component_graph=%d",
        screen_name,
        len(toolkit_files),
        len(example_files),
        len(component_graph),
    )

    return ScreenContext(
        screen_name=screen_name,
        module_name=module_name,
        toolkit_files=toolkit_files,
        example_files=example_files,
        component_graph=component_graph,
        business_rules=business_rules,
        screen_plan=screen_plan.model_dump(),
    )
