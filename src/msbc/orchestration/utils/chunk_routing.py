"""
chunk_routing.py — Deterministic chunk → canonical module router.

Routes each DocumentChunk to one or more canonical modules without any LLM call.
Uses a priority-ordered matching algorithm; only truly unresolved chunks are
flagged for optional LLM repair (caller decides whether to call).

Routing priority (stops at first match):
  1. evidence_chunk_ids from module_inventory already maps chunk → module.
  2. title_hint exact/fuzzy match against module display_name or aliases.
  3. local_headings overlap with module's primary_entities or child_concepts.
  4. Return route_type="unassigned" for the caller to handle via LLM if needed.
"""

from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Minimum token overlap fraction to trigger shared-chunk routing
_SHARED_OVERLAP_THRESHOLD = 0.3


# ── Public entry point ────────────────────────────────────────────────────────

def route_chunks(
    document_chunks: list[dict[str, Any]],
    canonical_modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Route every document chunk to one or more canonical modules.

    Returns a list of ChunkRoute-compatible dicts with fields:
        chunk_id, module_keys, route_type, reason, confidence
    """
    if not document_chunks or not canonical_modules:
        return []

    # Build a reverse map: chunk_id → list of module_keys (from evidence_chunk_ids)
    evidence_map: dict[str, list[str]] = _build_evidence_map(canonical_modules)

    routes: list[dict[str, Any]] = []
    for chunk in document_chunks:
        chunk_id = chunk["chunk_id"]
        route = _route_single_chunk(chunk, canonical_modules, evidence_map)
        routes.append(route)

    assigned = sum(1 for r in routes if r["route_type"] != "unassigned")
    unassigned = len(routes) - assigned
    logger.info(
        "chunk_routing: %d chunk(s) → %d assigned, %d unassigned.",
        len(routes), assigned, unassigned,
    )
    return routes


def apply_llm_routes(
    existing_routes: list[dict[str, Any]],
    llm_routes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge LLM-resolved routes into the existing route list.
    Only updates routes that were previously unassigned.
    """
    llm_by_chunk: dict[str, dict[str, Any]] = {r["chunk_id"]: r for r in llm_routes}
    result: list[dict[str, Any]] = []
    for route in existing_routes:
        if route["route_type"] == "unassigned" and route["chunk_id"] in llm_by_chunk:
            result.append(llm_by_chunk[route["chunk_id"]])
        else:
            result.append(route)
    return result


# ── Internal routing ──────────────────────────────────────────────────────────

def _route_single_chunk(
    chunk: dict[str, Any],
    canonical_modules: list[dict[str, Any]],
    evidence_map: dict[str, list[str]],
) -> dict[str, Any]:
    chunk_id = chunk["chunk_id"]

    # Priority 1: evidence_chunk_ids mapping (set by module_inventory_node)
    if chunk_id in evidence_map:
        module_keys = evidence_map[chunk_id]
        route_type = "shared" if len(module_keys) > 1 else "primary"
        return {
            "chunk_id": chunk_id,
            "module_keys": module_keys,
            "route_type": route_type,
            "reason": "evidence_chunk_ids from module_inventory",
            "confidence": 0.95,
        }

    title_hint = (chunk.get("title_hint") or "").strip()
    local_headings = chunk.get("local_headings") or []

    # Priority 2: title_hint fuzzy match against module display_name / aliases
    if title_hint:
        matched = _match_by_name(title_hint, canonical_modules)
        if matched:
            module_keys = [m["module_key"] for m in matched]
            route_type = "shared" if len(module_keys) > 1 else "primary"
            return {
                "chunk_id": chunk_id,
                "module_keys": module_keys,
                "route_type": route_type,
                "reason": f"title_hint '{title_hint}' matched module display_name/alias",
                "confidence": 0.80,
            }

    # Priority 3: local_headings overlap with module entities/child_concepts
    if local_headings:
        matched = _match_by_headings(local_headings, canonical_modules)
        if matched:
            module_keys = [m["module_key"] for m in matched]
            route_type = "shared" if len(module_keys) > 1 else "primary"
            return {
                "chunk_id": chunk_id,
                "module_keys": module_keys,
                "route_type": route_type,
                "reason": "local_headings overlap with module entities/child_concepts",
                "confidence": 0.65,
            }

    # Unresolved — caller can send to LLM repair
    return {
        "chunk_id": chunk_id,
        "module_keys": [],
        "route_type": "unassigned",
        "reason": "no deterministic match found",
        "confidence": 0.0,
    }


def _build_evidence_map(
    canonical_modules: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """
    Build chunk_id → [module_key, ...] from canonical_modules' evidence_chunk_ids.
    A chunk may appear in multiple modules' evidence lists → shared route.
    """
    ev_map: dict[str, list[str]] = {}
    for mod in canonical_modules:
        mk = mod["module_key"]
        for chunk_id in (mod.get("evidence_chunk_ids") or []):
            if chunk_id not in ev_map:
                ev_map[chunk_id] = []
            if mk not in ev_map[chunk_id]:
                ev_map[chunk_id].append(mk)
    return ev_map


def _match_by_name(
    title_hint: str,
    canonical_modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Fuzzy match title_hint against each module's display_name and aliases.
    Returns matched modules (may be more than one for shared chunks).
    """
    matched: list[dict[str, Any]] = []
    norm_title = _normalize_for_match(title_hint)

    for mod in canonical_modules:
        candidates = [mod.get("display_name", "")] + list(mod.get("aliases") or [])
        for candidate in candidates:
            if not candidate:
                continue
            norm_cand = _normalize_for_match(candidate)
            if norm_title == norm_cand:
                matched.append(mod)
                break
            if norm_title in norm_cand or norm_cand in norm_title:
                matched.append(mod)
                break
            if _token_overlap(norm_title, norm_cand) >= _SHARED_OVERLAP_THRESHOLD:
                matched.append(mod)
                break

    return matched


def _match_by_headings(
    local_headings: list[str],
    canonical_modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Match a chunk's local_headings against each module's primary_entities
    and child_concepts. Returns matched modules.
    """
    norm_headings = {_normalize_for_match(h) for h in local_headings}
    matched: list[dict[str, Any]] = []

    for mod in canonical_modules:
        module_terms: set[str] = set()
        for entity in (mod.get("primary_entities") or []):
            module_terms.add(_normalize_for_match(entity))
        for concept in (mod.get("child_concepts") or []):
            module_terms.add(_normalize_for_match(concept))

        overlap = norm_headings & module_terms
        if overlap:
            matched.append(mod)

    return matched


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _token_overlap(a: str, b: str) -> float:
    """Jaccard overlap between word sets of two normalized strings."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)
