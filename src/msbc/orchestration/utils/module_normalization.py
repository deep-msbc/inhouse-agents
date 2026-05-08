"""
module_normalization.py — Merge and normalize module candidates.

Replaces canonicalization.py. Input: raw module_candidates from module_inventory_node.
Output: canonical_modules list (same downstream contract as before).

Algorithm:
  1. Structural scoring (compute_child_likelihood) — completely domain-agnostic.
     Uses 7 structural signals about the candidate's data, not its name.
     No hardcoded word lists. Works for manufacturing, healthcare, finance,
     HR, logistics, or any vertical.
  2. Returns remaining ambiguous candidates for optional LLM call (caller decides).

Re-exports make_module_key() and normalize_display_name() for backwards compat.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Classification thresholds ─────────────────────────────────────────────────
# Score returned by compute_child_likelihood() is 0.0 → 1.0.
#   >= _CHILD_THRESHOLD   → structurally identified as a child concept; absorb.
#   <= _AMBIGUOUS_THRESHOLD → clearly a standalone module; keep.
#   in between            → grey zone; send to LLM for final decision.
_CHILD_THRESHOLD = 0.40
_AMBIGUOUS_THRESHOLD = 0.20


# ── Public helpers (re-exported for backwards compat) ─────────────────────────

def normalize_display_name(display_name: str) -> str:
    if not display_name:
        return ""
    name = display_name.strip()
    # Strip leading section numbers like "1.", "1.1", "14. "
    name = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", name)
    # Strip trailing parenthetical version/status markers
    # Catches: (Final), (Final Document), (Final – Enterprise Level), (Updated with ...)
    name = re.sub(r"\s*\([^)]*(?:final|draft|complete|updated|enterprise|version|v\d)[^)]*\)", "", name, flags=re.IGNORECASE).strip()
    # Strip trailing em-dash/en-dash qualifiers: " – Final Document", " - Final Complete"
    name = re.sub(r"\s*[–—-]+\s*(?:final|draft|complete|updated|enterprise)\b.*$", "", name, flags=re.IGNORECASE).strip()
    # Strip trailing slash + alternative name only when the suffix looks like a
    # generic label (Sheet, Report, View, Panel, Screen, Module, Form, Grid, List)
    # rather than a distinct concept. Keeps "Material Mapping / Material Merge Module"
    # but strips "Stock Dashboard / Stock Sheet".
    name = re.sub(
        r"\s*/\s*(?:\w+\s+)?(?:Sheet|Report|View|Panel|Screen|Form|Grid|List|Tab|Dashboard)\b.*$",
        "", name, flags=re.IGNORECASE,
    ).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def make_module_key(display_name: str) -> str:
    name = normalize_display_name(display_name)
    if not name:
        return "module"
    key = name.lower()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return key or "module"


def compute_child_likelihood(
    candidate: dict[str, Any],
    all_candidates: list[dict[str, Any]],
) -> float:
    """
    Score how likely this candidate is a CHILD CONCEPT rather than a standalone module.

    Returns 0.0 → 1.0.  Higher = more likely a child concept that should be absorbed.

    Uses ONLY structural signals — completely domain-agnostic.
    No hardcoded word lists, no domain-specific vocabulary, no name pattern matching.
    Works identically for manufacturing, healthcare, finance, HR, logistics, or any
    other vertical a user story might come from.

    Seven signals (each contributes partial weight; no single signal is a hard gate):
      1. LLM confidence            — the LLM itself expresses uncertainty about module status.
      2. Primary entity count      — real modules own several data entities uniquely.
      3. Entity uniqueness         — if all this module's entities are a subset of another
                                     candidate's larger entity set, it is likely a sub-view.
      4. Main action count         — real modules support multiple user operations across a lifecycle.
      5. Business goal substance   — a thin / absent goal indicates a section, not a module.
      6. Chunk containment         — if all source chunks are within another candidate's chunks,
                                     this candidate is structurally nested inside that module.
      7. Name–entity overlap       — if this module's key matches a primary entity of another
                                     candidate, it is likely a detail view / CRUD screen for it.
    """
    confidence = float(candidate.get("confidence", 0.8))
    entities = [e.lower().strip() for e in (candidate.get("primary_entities") or [])]
    entity_set = set(entities)
    actions = candidate.get("main_actions") or []
    chunks = set(candidate.get("evidence_chunk_ids") or [])
    goal = (candidate.get("business_goal") or "").strip()
    own_key = candidate.get("module_key", "")

    score = 0.0

    # ── Signal 1: Low LLM confidence (max +0.25) ─────────────────────────────
    # The LLM itself signals that this candidate may not be a standalone module.
    if confidence < 0.50:
        score += 0.25
    elif confidence < 0.65:
        score += 0.10

    # ── Signal 2: No or very few primary entities (max +0.25) ────────────────
    # A real business module owns data. A candidate with zero owned entities is
    # a process, workflow step, rule set, or sub-screen — not a module.
    if not entity_set:
        score += 0.25
    elif len(entity_set) == 1:
        score += 0.10

    # ── Signal 3: Very few main actions (max +0.20) ───────────────────────────
    # A full module supports a lifecycle of user operations (create, view, edit, …).
    # A candidate with only one operation is usually a child feature or detail screen.
    if len(actions) == 0:
        score += 0.20
    elif len(actions) == 1:
        score += 0.08

    # ── Signal 4: Thin or absent business goal (max +0.10) ───────────────────
    # Standalone modules always have a meaningful, distinct business justification.
    # A child concept rarely has one that is independent of its parent module.
    goal_words = len(goal.split()) if goal else 0
    if goal_words == 0:
        score += 0.10
    elif goal_words < 6:
        score += 0.05

    # ── Signal 5: Entity subset of another candidate (max +0.20) ─────────────
    # If every entity this candidate "owns" is also owned by a different,
    # equal-or-higher-confidence candidate that owns MORE entities, this candidate
    # is likely a sub-view or detail screen of that larger module.
    if entity_set:
        for other in all_candidates:
            if other.get("module_key") == own_key:
                continue
            other_entities = set(e.lower().strip() for e in (other.get("primary_entities") or []))
            other_conf = float(other.get("confidence", 0.8))
            if (
                entity_set.issubset(other_entities)
                and other_entities != entity_set   # not identical twins
                and other_conf >= confidence
            ):
                score += 0.20
                break  # count only once

    # ── Signal 6: Chunk containment (max +0.20) ───────────────────────────────
    # If all source chunks for this candidate are a strict subset of another
    # candidate's source chunks, this candidate is structurally nested inside
    # the other module in the document layout.
    if chunks:
        for other in all_candidates:
            if other.get("module_key") == own_key:
                continue
            other_chunks = set(other.get("evidence_chunk_ids") or [])
            if other_chunks and chunks.issubset(other_chunks) and chunks != other_chunks:
                score += 0.20
                break  # count only once

    # ── Signal 7: Module name matches another's primary entity (max +0.15) ────
    # If this module's key (e.g. "batch_production_tracking") matches a primary
    # entity listed by another candidate (e.g. entity "Batch Production Tracking"
    # inside "batch_wise_production_tracking"), it is a detail / CRUD view for
    # that entity — not an independent business module.
    normalized_own = own_key.replace("_", " ").strip()
    for other in all_candidates:
        if other.get("module_key") == own_key:
            continue
        other_entity_names = {
            e.lower().replace("_", " ").strip()
            for e in (other.get("primary_entities") or [])
        }
        if normalized_own and normalized_own in other_entity_names:
            score += 0.15
            break  # count only once

    return min(score, 1.0)


def is_child_like(module_key: str) -> bool:
    """
    Deprecated — kept only so external callers don't get ImportError.

    The old vocabulary-based implementation has been replaced by
    compute_child_likelihood() which uses structural signals and is
    completely domain-agnostic.  Do NOT use this function for new code.
    """
    logger.warning(
        "is_child_like('%s') is deprecated. Use compute_child_likelihood() "
        "with full candidate context instead of name-based detection.",
        module_key,
    )
    return False  # never silently absorb without structural context


# ── Main normalization entry point ────────────────────────────────────────────

def normalize_module_candidates(
    module_candidates: list[dict[str, Any]],
    document_chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Normalize and merge module_candidates into canonical_modules.

    Returns:
        (canonical_modules, ambiguous_candidates)

        canonical_modules  — ready for downstream use (same contract as before)
        ambiguous_candidates — candidates the caller may send to an LLM for review
    """
    if not module_candidates:
        return [], []

    # Step 1: assign clean keys to all candidates
    candidates = _assign_keys(module_candidates)

    # Step 2: identify and absorb obvious child-like candidates
    canonical, child_absorbed, ambiguous = _separate_children(candidates)

    # Step 3: log what was absorbed
    if child_absorbed:
        absorbed_info = [
            f"{c['module_key']} (score={c.get('_child_score', '?')})"
            for c in child_absorbed
        ]
        logger.info(
            "module_normalization: absorbed %d child-like candidate(s): %s",
            len(child_absorbed),
            absorbed_info,
        )

    # Step 4: build canonical_modules dicts in the downstream-expected shape
    result: list[dict[str, Any]] = []
    for cand in canonical:
        # Merge absorbed children into child_concepts
        absorbed_for_this = [
            c for c in child_absorbed
            if _should_absorb_into(c, cand, candidates)
        ]
        merged_child_concepts = list(cand.get("child_concepts") or [])
        for child in absorbed_for_this:
            merged_child_concepts.append(child.get("display_name", child["module_key"]))
            # Also carry over the child's own child_concepts
            merged_child_concepts.extend(child.get("child_concepts") or [])
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for concept in merged_child_concepts:
            key = concept.lower().strip()
            if key not in seen:
                seen.add(key)
                deduped.append(concept)

        canonical_mod: dict[str, Any] = {
            "module_key":       cand["module_key"],
            "display_name":     cand["display_name"],
            "business_goal":    cand.get("business_goal", ""),
            "primary_entities": cand.get("primary_entities") or [],
            "main_actions":     cand.get("main_actions") or [],
            "child_concepts":   deduped,
            "evidence_chunk_ids": cand.get("evidence_chunk_ids") or [],
            "aliases":          cand.get("aliases") or [],
            "confidence":       float(cand.get("confidence", 0.8)),
            "merge_reason":     None,
        }
        result.append(canonical_mod)

    logger.info(
        "module_normalization: %d candidate(s) → %d canonical module(s) + %d ambiguous.",
        len(candidates), len(result), len(ambiguous),
    )
    return result, ambiguous


def merge_llm_normalized(
    llm_modules: list[dict[str, Any]],
    original_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    After an optional LLM normalization call, finalize the canonical_modules list.

    llm_modules is what the LLM returned (same shape as canonical_modules).
    original_candidates are the ambiguous ones that were sent to the LLM.
    Returns the merged canonical list.
    """
    result: list[dict[str, Any]] = []
    for m in llm_modules:
        key = make_module_key(m.get("display_name", "") or m.get("module_key", ""))
        result.append({
            "module_key":       key,
            "display_name":     m.get("display_name", ""),
            "business_goal":    m.get("business_goal", ""),
            "primary_entities": m.get("primary_entities") or [],
            "main_actions":     m.get("main_actions") or [],
            "child_concepts":   m.get("child_concepts") or [],
            "evidence_chunk_ids": m.get("evidence_chunk_ids") or [],
            "aliases":          m.get("aliases") or [],
            "confidence":       float(m.get("confidence", 0.8)),
            "merge_reason":     m.get("merge_reason"),
        })
    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _assign_keys(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add/normalise module_key for every candidate."""
    result = []
    for c in candidates:
        display = c.get("display_name") or c.get("module_key", "")
        key = make_module_key(display)
        result.append({**c, "module_key": key, "display_name": normalize_display_name(display)})
    return result


def _separate_children(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Score every candidate with compute_child_likelihood() and split into:
        canonical      — clearly standalone business modules (score <= _AMBIGUOUS_THRESHOLD)
        child_absorbed — structurally identified as child concepts (score >= _CHILD_THRESHOLD)
        ambiguous      — grey zone; caller sends these to LLM for final decision

    No vocabulary lists. No hardcoded patterns. All decisions are structural.
    """
    canonical: list[dict[str, Any]] = []
    child_absorbed: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []

    for cand in candidates:
        child_score = compute_child_likelihood(cand, candidates)

        if child_score >= _CHILD_THRESHOLD:
            child_absorbed.append({**cand, "_child_score": round(child_score, 3)})
        elif child_score <= _AMBIGUOUS_THRESHOLD and float(cand.get("confidence", 0.8)) >= 0.6:
            canonical.append(cand)
        else:
            # Score is in the grey zone, or confidence is weak — let LLM decide.
            ambiguous.append(cand)

    return canonical, child_absorbed, ambiguous


def _should_absorb_into(
    child: dict[str, Any],
    parent: dict[str, Any],
    all_candidates: list[dict[str, Any]],
) -> bool:
    """
    Decide whether `child` belongs inside `parent`.

    Uses the same structural signals as compute_child_likelihood, not vocabulary.
    Priority order (stop at first match):
      1. Chunk containment — child's chunks are a subset of parent's chunks.
      2. Explicit child_concepts list — parent already named this as a child.
      3. Entity subset — child's entities are a subset of parent's larger entity set.
    """
    child_chunks = set(child.get("evidence_chunk_ids") or [])
    parent_chunks = set(parent.get("evidence_chunk_ids") or [])
    if child_chunks and parent_chunks and child_chunks.issubset(parent_chunks):
        return True

    parent_child_concepts_lower = {
        c.lower().strip() for c in (parent.get("child_concepts") or [])
    }
    child_name_lower = child.get("display_name", "").lower().strip()
    if child_name_lower and child_name_lower in parent_child_concepts_lower:
        return True

    child_entities = {e.lower().strip() for e in (child.get("primary_entities") or [])}
    parent_entities = {e.lower().strip() for e in (parent.get("primary_entities") or [])}
    if child_entities and parent_entities and child_entities.issubset(parent_entities):
        return True

    return False
