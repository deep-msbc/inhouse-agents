"""
Node implementations for the requirement extractor LangGraph workflow.

New Phase 1 pipeline (chunk-based, replaces section_classifier_node):
  document_chunker_node   — pure Python, coarse document chunks
  module_inventory_node   — 1 LLM call on chunk outline → module candidates
  module_normalizer_node  — Python merge rules + optional LLM → canonical modules
  chunk_router_node       — pure Python deterministic chunk → module routing
  module_bundle_builder_node — assembles combined_text per canonical module

Downstream (unchanged):
  extract_module_node × N — parallel extraction per module (Send fan-out)
  artifact_index_node     — pure Python artifact catalog
  global_deduplication_node — pure Python deduplication
  finalize_node           — pure-Python collect + graph-builder LLM call
  requirement_linter_node — deterministic quality gate
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml

from src.msbc.agents.schemas.requirement_extractor import (
    BACKEND_SCHEMA,
    COMBINED_SCHEMA,
    FRONTEND_SCHEMA,
    GRAPH_OUTPUT_SCHEMA,
    SUMMARY_SCHEMA,
)
from src.msbc.llm.clients.openai_client import call_llm_with_schema, count_tokens, merge_usage
from src.msbc.config import TOTAL_INPUT_TOKEN_LIMIT, PROMPT_MAX_TOKENS, MODULE_EXTRACTION_TIMEOUT, MODULE_BATCH_SIZE
from src.msbc.orchestration.state import ExtractionState, ModuleResult, ModuleSlice

logger = logging.getLogger(__name__)

# ── Prompt loader ─────────────────────────────────────────────────────────────

_PROMPTS_DIR = (
    Path(__file__).parent.parent.parent  # src/msbc/
    / "llm" / "prompts" / "templates" / "requirement_extractor"
)


def _load_prompt(name: str) -> dict[str, str]:
    """Load a YAML prompt file and return {'system': ..., 'user_template': ...}."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fmt(template: str, **kwargs: str) -> str:
    """
    Safe prompt template substitution.

    Uses plain str.replace() instead of str.format() so that JSON examples
    inside the YAML prompt (e.g. {"level": 1}) are never mistaken for
    Python format placeholders, avoiding KeyError on those keys.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", value)
    return result


# ── Document slicing (mirrors _slice_module_text from old llm_service.py) ─────

def _normalize_whitespace(text: str) -> str:
    """Collapse all runs of whitespace (spaces, tabs, newlines) to a single space."""
    import re as _re
    return _re.sub(r"\s+", " ", text).strip()


def _find_heading(document_text: str, heading: str) -> int:
    """
    Locate *heading* inside *document_text* using three progressively looser passes:

    1. Exact substring match.
    2. Case-insensitive exact match.
    3. Whitespace-collapsed case-insensitive match — handles PDF/docx artifacts
       where the extractor inserts extra spaces, tabs, or stray page numbers
       between words (e.g. 'Step 1        6 How …' vs 'Step 1 How …').

    Returns the start index, or -1 if none of the passes succeed.
    """
    # Pass 1 — exact
    idx = document_text.find(heading)
    if idx != -1:
        return idx

    # Pass 2 — case-insensitive exact
    idx = document_text.lower().find(heading.lower())
    if idx != -1:
        return idx

    # Pass 3 — whitespace-collapsed search
    # Build a normalised shadow of the document, find the normalised heading,
    # then map the match position back to the original document.
    norm_doc     = _normalize_whitespace(document_text)
    norm_heading = _normalize_whitespace(heading)
    norm_idx     = norm_doc.lower().find(norm_heading.lower())
    if norm_idx == -1:
        return -1

    # Recover approximate position in original document.
    # Walk the original text, counting non-whitespace chars to match the
    # normalised offset. This is O(n) but documents are typically < 200k chars.
    original_pos = 0
    norm_pos     = 0
    prev_was_ws  = False
    for orig_pos, ch in enumerate(document_text):
        if norm_pos >= norm_idx:
            return orig_pos
        if ch in (" ", "\t", "\n", "\r"):
            if not prev_was_ws:
                norm_pos    += 1  # collapsed whitespace counts as one space char
                prev_was_ws  = True
        else:
            norm_pos    += 1
            prev_was_ws  = False
            original_pos = orig_pos

    return original_pos


def _slice_module_text(
    document_text: str,
    module_heading: str,
    next_heading: str | None,
) -> str:
    """
    Extract the text slice for a module by locating its heading in the document.
    Returns from module_heading up to (but not including) next_heading, or end of doc.
    Falls back to the full document if the heading is not found.
    """
    start_idx = _find_heading(document_text, module_heading)
    if start_idx == -1:
        logger.warning(
            "Heading '%s' not found in document; using full text as fallback.",
            module_heading,
        )
        return document_text

    if next_heading:
        end_idx = _find_heading(document_text[start_idx + len(module_heading):], next_heading)
        if end_idx != -1:
            # end_idx is relative to the slice — shift back to absolute
            end_idx += start_idx + len(module_heading)
            return document_text[start_idx:end_idx]

    return document_text[start_idx:]


# ── Validation: cross-reference opens_screen (mirrors old _validate_opens_screen_refs) ──

def _validate_opens_screen_refs(
    screen: dict[str, Any], known_screens: set[str]
) -> None:
    """Walk a screen's components and warn about unknown opens_screen references."""
    for comp in screen.get("components", []):
        t = comp.get("type", "")
        if t == "toolbar":
            for action in comp.get("actions", []):
                ref = action.get("opens_screen")
                if ref and ref not in known_screens:
                    logger.warning(
                        "opens_screen '%s' in toolbar action '%s' of screen '%s' "
                        "does not match any defined screen.",
                        ref, action.get("label"), screen.get("name"),
                    )
        elif t == "grid":
            for ra in comp.get("row_actions", []):
                ref = ra.get("opens_screen")
                if ref and ref not in known_screens:
                    logger.warning(
                        "opens_screen '%s' in row_action '%s' of screen '%s' "
                        "does not match any defined screen.",
                        ref, ra.get("label"), screen.get("name"),
                    )
        elif t == "tabs":
            for tab in comp.get("children", []):
                _validate_opens_screen_refs(
                    {"name": screen.get("name"), "components": tab.get("components", [])},
                    known_screens,
                )


# ── Frontend component normalizer ─────────────────────────────────────────────

# Maps the UPPERCASE named-key labels the LLM may emit (from the old prompt
# template) to the correct `type` string expected by the schema.
_COMPONENT_KEY_TO_TYPE: dict[str, str] = {
    "TOOLBAR":        "toolbar",
    "FILTER_PANEL":   "filter_panel",
    "GRID":           "grid",
    "KPI":            "kpi",
    "TABS":           "tabs",
    "FORM":           "form",
    "SCAN_PANEL":     "scan_panel",
    "STEPPER":        "stepper",
    "FEEDBACK_AREA":  "feedback_area",
    "BARCODE_PANEL":  "barcode_panel",
    "INFO_PANEL":     "info_panel",
    "UPLOAD_ZONE":    "upload_zone",
    "TIMELINE":       "timeline",
    "SUMMARY_SECTION": "summary_section",
}


def _unwrap_components(components: list[Any]) -> list[dict[str, Any]]:
    """
    Coerce a components list into the flat-object format the schema expects.

    Handles two malformed formats the LLM may return:
      1. Each array element is a wrapper object whose keys are UPPERCASE type
         labels and whose values are the real component dicts, e.g.
           [{"TOOLBAR": {"id": "tb", "type": "toolbar", ...}, "GRID": {...}}]
         → unwrapped to [{"id": "tb", "type": "toolbar", ...}, {"id": "g", ...}]

      2. The component dict is missing the required `type` field but its
         position under a named key makes the type unambiguous — inferred.
    """
    normalized: list[dict[str, Any]] = []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        if "type" in comp:
            # Already correct flat format — keep as-is (recurse into tabs children)
            if comp.get("type") == "tabs":
                for child in comp.get("children", []):
                    child["components"] = _unwrap_components(
                        child.get("components", [])
                    )
            normalized.append(comp)
        else:
            # Wrapped format: each key is an UPPERCASE label, value is the component
            for key, type_value in _COMPONENT_KEY_TO_TYPE.items():
                if key in comp and isinstance(comp[key], dict):
                    inner = dict(comp[key])
                    if "type" not in inner:
                        inner["type"] = type_value
                    # Recurse into tabs children if present
                    if inner.get("type") == "tabs":
                        for child in inner.get("children", []):
                            child["components"] = _unwrap_components(
                                child.get("components", [])
                            )
                    normalized.append(inner)
    return normalized


def _normalize_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """
    Safety-net normalizer: fix component format when the LLM wraps components
    in UPPERCASE named keys instead of emitting flat objects with `type`.
    Also filters out enums with empty values arrays (schema violation).
    Handles both frontend mode (module.screens) and both mode (module.frontend.screens).
    Applied after JSON parsing and before schema validation on every attempt.
    """
    module = data.get("module", {})

    # ── Block 1: component unwrapping ────────────────────────────────────────
    # Isolated so a malformed screen never silently prevents block 2 from running.
    try:
        for screen in module.get("screens", []):
            screen["components"] = _unwrap_components(screen.get("components", []))
        for screen in module.get("frontend", {}).get("screens", []):
            screen["components"] = _unwrap_components(screen.get("components", []))
    except Exception:
        pass  # Return components unchanged if unwrapping fails

    # ── Block 2: enum filtering ───────────────────────────────────────────────
    # Strip any enum whose values list is empty (schema requires minItems: 1).
    # Runs unconditionally — independent of block 1.
    try:
        if "enums" in module:
            module["enums"] = [e for e in module["enums"] if e.get("values")]
        frontend = module.get("frontend", {})
        if "enums" in frontend:
            frontend["enums"] = [e for e in frontend["enums"] if e.get("values")]
    except Exception:
        pass  # Return enums unchanged if filtering fails

    return data


# ── Phase 1 (new): Document Chunker ──────────────────────────────────────────

def document_chunker_node(state: ExtractionState) -> dict[str, Any]:
    """
    Split the document into 3-10 coarse business-area chunks (pure Python, no LLM).

    Replaces section_classifier_node's heading-tree construction entirely.
    Uses heading_normalization + document_chunking utilities.

    Reads:  state["document_text"], state["heading_hierarchy"]
    Writes: state["document_chunks"]
    """
    from src.msbc.orchestration.utils.document_chunking import build_document_chunks

    document_text: str = state.get("document_text") or ""
    heading_hierarchy: list[dict] = state.get("heading_hierarchy") or []

    logger.info(
        "document_chunker_node: chunking document (%d chars, %d headings).",
        len(document_text), len(heading_hierarchy),
    )

    chunks = build_document_chunks(document_text, heading_hierarchy)

    logger.info(
        "document_chunker_node: produced %d chunk(s): %s",
        len(chunks),
        [c.get("title_hint") or c["chunk_id"] for c in chunks],
    )
    return {"document_chunks": chunks}


# ── Phase 1 (new): Module Inventory ──────────────────────────────────────────

async def module_inventory_node(state: ExtractionState) -> dict[str, Any]:
    """
    Discover business module candidates with a single LLM call on chunk summaries.

    Sends the LLM only a compact outline (chunk title hints + local headings),
    NOT the full document text. Token cost: ~400-800 tokens for a 35k doc.

    Replaces section_classifier_node's 5+ sequential batched LLM calls.

    Reads:  state["document_chunks"]
    Writes: state["module_candidates"], state["all_usage"]
    """
    from src.msbc.agents.schemas.requirement_extractor.module_inventory import (
        MODULE_INVENTORY_SCHEMA,
    )
    from src.msbc.orchestration.utils.module_normalization import make_module_key

    chunks: list[dict] = state.get("document_chunks") or []

    if not chunks:
        logger.warning("module_inventory_node: no document_chunks; returning empty candidates.")
        return {"module_candidates": [], "all_usage": []}

    # Build compact outline — title hints + local headings only
    # Include chunk_strategy so the LLM knows whether these are structured peers
    chunk_strategies = {c["chunk_id"]: c.get("chunk_strategy", "unknown") for c in chunks}
    unique_strategies = set(chunk_strategies.values())
    strategy_hint = (
        "numbered_sections" if "numbered_sections" in unique_strategies
        else "major_headings" if "major_headings" in unique_strategies
        else "token_window"
    )

    outline_lines: list[str] = []
    if strategy_hint in ("numbered_sections", "major_headings"):
        outline_lines.append(
            f"NOTE: These {len(chunks)} chunks were split by document headings "
            f"(strategy: {strategy_hint}). Each chunk corresponds to a distinct "
            f"heading in the document. Peer-level chunks MUST each be a separate "
            f"module candidate unless one is clearly a rule/validation section."
        )
        outline_lines.append("")

    for chunk in chunks:
        title = chunk.get("title_hint") or chunk["chunk_id"]
        outline_lines.append(f'Chunk {chunk["chunk_id"]}: "{title}"')
        local = chunk.get("local_headings") or []
        if local:
            headings_str = ", ".join(local[:20])  # cap at 20 headings per chunk
            outline_lines.append(f"  Sub-headings: {headings_str}")
        outline_lines.append("")

    document_outline = "\n".join(outline_lines).strip()

    prompt = _load_prompt("module_inventory")
    system_text = prompt["system"]
    user_text = _fmt(
        prompt["user_template"],
        document_outline=document_outline,
        chunk_count=str(len(chunks)),
    )

    # Token budget check
    total_tokens = count_tokens(system_text) + count_tokens(user_text)
    logger.info(
        "module_inventory_node: calling LLM with %d tokens (outline for %d chunks).",
        total_tokens, len(chunks),
    )

    result, usages = await call_llm_with_schema(
        system_prompt=system_text,
        user_prompt=user_text,
        schema=MODULE_INVENTORY_SCHEMA,
        schema_name="module_inventory",
    )

    candidates: list[dict] = result.get("module_candidates") or []

    # ── Post-LLM recovery: catch chunks the LLM silently dropped ─────────────
    # If a chunk has a non-trivial title and meaningful internal structure
    # (local_headings or token count > 300) but doesn't appear in any candidate's
    # evidence_chunk_ids, the LLM forgot it. We create a recovery candidate so
    # routing and extraction still cover that content.
    #
    # This is purely structural: no vocabulary checks. A chunk is considered
    # "substantive" if it has internal sub-headings OR substantial text.
    represented_ids: set[str] = set()
    for c in candidates:
        for cid in (c.get("evidence_chunk_ids") or []):
            represented_ids.add(cid)

    recovery: list[dict] = []
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        if chunk_id in represented_ids:
            continue
        title = chunk.get("title_hint") or ""
        local_headings = chunk.get("local_headings") or []
        token_count = chunk.get("token_count") or 0

        # Skip chunks with no meaningful title (they're intros or noise)
        if not title or title == chunk_id:
            continue

        # A chunk is "substantive" if it has internal structure or enough text
        is_substantive = len(local_headings) >= 2 or token_count >= 300
        if not is_substantive:
            continue

        # Create a recovery candidate using the exact heading text
        rec_key = make_module_key(title)
        # Avoid duplicate keys with existing candidates
        existing_keys = {c.get("module_key", "") for c in candidates}
        existing_keys.update(r.get("module_key", "") for r in recovery)
        if rec_key in existing_keys:
            continue

        recovery.append({
            "module_key": rec_key,
            "display_name": title,
            "business_goal": "",
            "primary_entities": [],
            "main_actions": [],
            "evidence_chunk_ids": [chunk_id],
            "child_concepts": local_headings[:10],
            "shared_artifacts": [],
            "confidence": 0.65,  # lower than LLM output → normalizer may send to LLM review
        })

    if recovery:
        logger.info(
            "module_inventory_node: recovery added %d candidate(s) for LLM-dropped chunks: %s",
            len(recovery),
            [r["module_key"] for r in recovery],
        )
        candidates = candidates + recovery

    logger.info(
        "module_inventory_node: LLM returned %d module candidate(s) (+ %d recovery): %s",
        len(candidates) - len(recovery),
        len(recovery),
        [c.get("module_key", "?") for c in candidates],
    )
    return {"module_candidates": candidates, "all_usage": usages}


# ── Phase 1 (new): Module Normalizer ─────────────────────────────────────────

async def module_normalizer_node(state: ExtractionState) -> dict[str, Any]:
    """
    Merge and normalize module candidates into canonical modules.

    Step 1: Deterministic Python merge rules (absorb obvious child-like candidates).
    Step 2: Optional single LLM call for remaining ambiguous candidates.

    Replaces module_canonicalizer_node.

    Reads:  state["module_candidates"], state["document_chunks"]
    Writes: state["canonical_modules"], state["all_usage"]
    """
    from src.msbc.orchestration.utils.module_normalization import (
        normalize_module_candidates,
        merge_llm_normalized,
    )
    from src.msbc.agents.schemas.requirement_extractor.module_inventory import (
        MODULE_NORMALIZATION_SCHEMA,
    )

    candidates: list[dict] = state.get("module_candidates") or []
    chunks: list[dict] = state.get("document_chunks") or []
    usages: list[dict] = []

    if not candidates:
        logger.warning("module_normalizer_node: no module_candidates; returning empty canonical_modules.")
        return {"canonical_modules": [], "all_usage": []}

    # Step 1: deterministic Python normalization
    canonical, ambiguous = normalize_module_candidates(candidates, chunks)

    logger.info(
        "module_normalizer_node: after Python rules — %d canonical, %d ambiguous.",
        len(canonical), len(ambiguous),
    )

    # Step 2: optional LLM call for ambiguous candidates
    if ambiguous:
        logger.info(
            "module_normalizer_node: sending %d ambiguous candidate(s) to LLM for review.",
            len(ambiguous),
        )
        try:
            prompt = _load_prompt("module_normalization")
            system_text = prompt["system"]
            user_text = _fmt(
                prompt["user_template"],
                ambiguous_candidates_json=json.dumps(ambiguous, indent=2),
                candidate_count=str(len(ambiguous)),
            )

            norm_result, norm_usages = await call_llm_with_schema(
                system_prompt=system_text,
                user_prompt=user_text,
                schema=MODULE_NORMALIZATION_SCHEMA,
                schema_name="module_normalization",
            )

            llm_modules: list[dict] = norm_result.get("canonical_modules") or []
            usages.extend(norm_usages)

            if llm_modules:
                resolved = merge_llm_normalized(llm_modules, ambiguous)
                canonical.extend(resolved)
                logger.info(
                    "module_normalizer_node: LLM resolved %d ambiguous candidate(s) → %d module(s).",
                    len(ambiguous), len(resolved),
                )
        except Exception as exc:
            logger.warning(
                "module_normalizer_node: LLM normalization failed (%s); keeping Python-resolved modules only.",
                exc,
            )

    logger.info(
        "module_normalizer_node: final canonical modules (%d): %s",
        len(canonical),
        [m["module_key"] for m in canonical],
    )
    return {"canonical_modules": canonical, "all_usage": usages}


# ── Phase 1 (new): Chunk Router ───────────────────────────────────────────────

def chunk_router_node(state: ExtractionState) -> dict[str, Any]:
    """
    Route each DocumentChunk to one or more canonical modules (pure Python, no LLM).

    Uses deterministic priority-order matching:
      1. evidence_chunk_ids from module_inventory (resolves 80-90% of chunks)
      2. title_hint fuzzy match against module display_name / aliases
      3. local_headings overlap with module primary_entities / child_concepts

    Reads:  state["document_chunks"], state["canonical_modules"]
    Writes: state["chunk_routes"]
    """
    from src.msbc.orchestration.utils.chunk_routing import route_chunks

    chunks: list[dict] = state.get("document_chunks") or []
    canonical: list[dict] = state.get("canonical_modules") or []

    if not chunks or not canonical:
        logger.warning(
            "chunk_router_node: missing chunks (%d) or canonical_modules (%d); returning empty routes.",
            len(chunks), len(canonical),
        )
        return {"chunk_routes": []}

    routes = route_chunks(chunks, canonical)

    unassigned = [r for r in routes if r["route_type"] == "unassigned"]
    if unassigned:
        logger.warning(
            "chunk_router_node: %d chunk(s) unassigned after deterministic routing: %s",
            len(unassigned),
            [r["chunk_id"] for r in unassigned],
        )
        # Build chunk position index for proximity fallback
        chunk_pos: dict[str, int] = {c["chunk_id"]: i for i, c in enumerate(chunks)}
        # Build module anchor positions (median position of each module's evidence chunks)
        module_positions: dict[str, float] = {}
        for cm in canonical:
            ev_ids = cm.get("evidence_chunk_ids") or []
            positions = [chunk_pos[cid] for cid in ev_ids if cid in chunk_pos]
            if positions:
                module_positions[cm["module_key"]] = sum(positions) / len(positions)

        for route in unassigned:
            cid = route["chunk_id"]
            pos = chunk_pos.get(cid, 0)
            # Assign to the module whose evidence chunks are closest in document position
            if module_positions:
                closest_key = min(module_positions, key=lambda mk: abs(module_positions[mk] - pos))
            else:
                closest_key = canonical[0]["module_key"] if canonical else ""
            route["module_keys"] = [closest_key] if closest_key else []
            route["route_type"] = "primary"
            route["reason"] = "fallback: assigned to nearest canonical module by document position"
            route["confidence"] = 0.3

    logger.info(
        "chunk_router_node: %d route(s) built for %d chunk(s).",
        len(routes), len(chunks),
    )
    return {"chunk_routes": routes}


# ── Phase 1.5: Module Bundle Builder ──────────────────────────────────────────

def module_bundle_builder_node(state: ExtractionState) -> dict[str, Any]:
    """
    Assemble the text bundle for each canonical module from document chunks.

    Reads document_chunks + chunk_routes (new Phase 1 flow) instead of the
    old document_sections + classified_sections. For each CanonicalModule,
    collects its routed chunks and concatenates their text with chunk headers.

    Token budget enforcement (same rules as before):
      - Total combined_text is capped at TOTAL_INPUT_TOKEN_LIMIT tokens.
      - Over-budget modules drop lowest-priority chunks first.

    Writes to state:
      module_bundles — list of ModuleBundle dicts (one per canonical module).

    Pure Python — no LLM, no network I/O.
    """
    logger.info("module_bundle_builder_node: building text bundles from document chunks.")

    canonical_modules: list[dict] = state.get("canonical_modules") or []
    document_chunks: list[dict] = state.get("document_chunks") or []
    chunk_routes: list[dict] = state.get("chunk_routes") or []

    if not canonical_modules:
        logger.warning("module_bundle_builder_node: no canonical_modules; nothing to bundle.")
        return {"module_bundles": []}

    # Build lookups
    chunk_by_id: dict[str, dict] = {c["chunk_id"]: c for c in document_chunks}

    # Build reverse map: module_key → [chunk_id, ...] (in document order)
    module_to_chunk_ids: dict[str, list[str]] = {cm["module_key"]: [] for cm in canonical_modules}
    for route in chunk_routes:
        for mk in (route.get("module_keys") or []):
            if mk in module_to_chunk_ids:
                cid = route["chunk_id"]
                if cid not in module_to_chunk_ids[mk]:
                    module_to_chunk_ids[mk].append(cid)

    # Document order: use position of chunk_id in document_chunks list
    chunk_order: dict[str, int] = {c["chunk_id"]: i for i, c in enumerate(document_chunks)}

    MODULE_TEXT_BUDGET = max(TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS, 2000)

    module_bundles: list[dict[str, Any]] = []

    for cm in canonical_modules:
        module_key: str = cm["module_key"]
        display_name: str = cm["display_name"]
        business_goal: str = cm.get("business_goal", "")
        child_concepts: list[str] = cm.get("child_concepts") or []

        # Get chunk_ids in document order
        raw_chunk_ids = module_to_chunk_ids.get(module_key) or []

        # Fallback: if routing produced nothing, use evidence_chunk_ids from the module itself
        if not raw_chunk_ids:
            raw_chunk_ids = list(cm.get("evidence_chunk_ids") or [])
            logger.info(
                "module_bundle_builder_node: '%s' had no routes — falling back to evidence_chunk_ids: %s",
                module_key, raw_chunk_ids,
            )

        # Sort by document order
        sorted_chunk_ids = sorted(raw_chunk_ids, key=lambda cid: chunk_order.get(cid, 9999))

        # Build parts list
        parts: list[dict[str, Any]] = []
        for cid in sorted_chunk_ids:
            chunk = chunk_by_id.get(cid)
            if not chunk:
                continue
            text = chunk.get("text", "")
            if not text.strip():
                continue
            parts.append({
                "chunk_id": cid,
                "title": chunk.get("title_hint") or cid,
                "text": text,
                "tokens": chunk.get("token_count") or count_tokens(text),
            })

        if not parts:
            logger.warning(
                "module_bundle_builder_node: no text chunks for module %r; skipping.",
                module_key,
            )
            continue

        total_tokens = sum(p["tokens"] for p in parts)

        # Apply truncation if over budget (drop last chunks first — they're usually
        # shared/lower-priority content)
        if total_tokens > MODULE_TEXT_BUDGET:
            kept_parts: list[dict] = []
            used = 0
            for part in parts:
                if used + part["tokens"] <= MODULE_TEXT_BUDGET:
                    kept_parts.append(part)
                    used += part["tokens"]
                else:
                    logger.info(
                        "module_bundle_builder_node: '%s' — dropping chunk %r (%d tokens) over budget.",
                        module_key, part["chunk_id"], part["tokens"],
                    )
            logger.info(
                "module_bundle_builder_node: '%s' trimmed %d → %d chunk(s) (%d → %d tokens).",
                module_key, len(parts), len(kept_parts), total_tokens, used,
            )
            parts = kept_parts

        # Build combined text
        header_lines: list[str] = [f"# Canonical Module: {display_name}"]
        if business_goal:
            header_lines.append(f"\nBusiness Goal:\n{business_goal}")
        if child_concepts:
            concepts_str = "\n".join(f"- {c}" for c in child_concepts)
            header_lines.append(f"\nIncluded Child Concepts:\n{concepts_str}")
        included_chunk_ids = [p["chunk_id"] for p in parts]
        chunks_str = "\n".join(f"- {cid}" for cid in included_chunk_ids)
        header_lines.append(f"\nSource Chunks:\n{chunks_str}")
        header_lines.append("\n## Source Content")

        chunk_blocks: list[str] = ["\n".join(header_lines)]
        for part in parts:
            block_header = f"\n### Chunk: {part['title']} ({part['chunk_id']})\n\n"
            chunk_blocks.append(block_header + part["text"])

        combined_text = "\n".join(chunk_blocks)

        bundle: dict[str, Any] = {
            "module_key": module_key,
            "display_name": display_name,
            "combined_text": combined_text,
            "source_chunk_ids": included_chunk_ids,
        }
        module_bundles.append(bundle)

    logger.info(
        "module_bundle_builder_node: built %d bundle(s) for canonical modules.",
        len(module_bundles),
    )
    return {"module_bundles": module_bundles}


# ── Phase 0.5: Build slices (fan-out prep) ────────────────────────────────────

def build_slices_node(state: ExtractionState) -> list["Send"]:  # type: ignore[name-defined]
    """
    Slice the document text per module and return a list of Send objects
    to fan-out extract_module_node in parallel.

    This function is used as a conditional-edge function (returns Send objects),
    not a regular node — imported by edge_logic.py.
    """
    from langgraph.types import Send  # local import to avoid circular import at module level

    modules: list[dict[str, Any]] = state["modules"]
    document_text: str = state["document_text"]
    mode: str = state["mode"]

    sends: list[Send] = []
    for idx, module_meta in enumerate(modules):
        heading = module_meta.get("heading", "") or module_meta.get("name", "")
        next_heading = (
            (modules[idx + 1].get("heading", "") or modules[idx + 1].get("name", ""))
            if idx + 1 < len(modules)
            else None
        )
        module_text = _slice_module_text(document_text, heading, next_heading)

        slice_input: ModuleSlice = {
            "index":              idx,
            "module_name":        module_meta["name"],
            "module_text":        module_text,
            "mode":               mode,
            "module_key":         None,
            "source_chunk_ids": [],
        }
        sends.append(Send("extract_module_node", slice_input))

    logger.info("build_slices_node: fanning out %d module slice(s).", len(sends))
    return sends


# ── Chunk-and-merge helpers ───────────────────────────────────────────────────

def _split_module_into_chunks(
    text: str,
    budget_tokens: int,
    module_name: str,
    *,
    min_chunk_tokens: int = 300,
    max_chunks: int = 10,
) -> list[str]:
    """
    Split *text* into N chunks each fitting within *budget_tokens*.

    Splitting strategy (in order of preference):
    1. At Markdown heading boundaries (## / ###) — semantic sections.
    2. At numbered-section boundaries (e.g. "8.1 Sub-section", "3.2.4 Tab")
       — the primary pattern in ERP/fenestration user story documents where
       authors use bold-numbered paragraphs rather than Word Heading styles.
       This ensures "8.16 Transaction History" and "8.17 Print Format" become
       separate logical units rather than being split mid-way at blank lines.
    3. At blank-line paragraph boundaries — if a single section still exceeds
       the budget after the above passes.

    Tiny trailing sections (< min_chunk_tokens) are merged into the previous
    chunk to avoid single-sentence chunks that waste an LLM call.

    Chunks beyond max_chunks are discarded with a WARNING — prevents a
    pathologically large module from spawning hundreds of LLM calls.

    Every returned chunk is prefixed with a context header so the LLM knows
    it is receiving a partial view:
        [Part 2/4 of module 'PO Creation Flow'] — extract only the
        requirements visible in this part.
    """
    import re as _re

    # Matches both Markdown headings and numbered-section lines.
    # Numbered-section pattern: optional leading whitespace, one or more
    # digit groups separated by dots (e.g. 8, 8.1, 3.2.4), optional trailing
    # dot, whitespace, then an uppercase or accented letter.
    heading_re  = _re.compile(r"^#{1,6}\s+.+$")
    numbered_re = _re.compile(r"^\s*\d+(\.\d+)*\.?\s+[A-Z\u0080-\uFFFF]")

    def _is_section_boundary(line: str) -> bool:
        stripped = line.rstrip()
        return bool(heading_re.match(stripped) or numbered_re.match(stripped))

    # ── Group lines into boundary-delimited sections ──────────────────────────
    lines    = text.splitlines(keepends=True)
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        if _is_section_boundary(line) and current:
            sec = "".join(current)
            if sec.strip():
                sections.append(sec)
            current = [line]
        else:
            current.append(line)
    if current:
        sec = "".join(current)
        if sec.strip():
            sections.append(sec)

    # Fallback: no structured boundaries found → split at blank lines
    if len(sections) <= 1:
        sections = [p.strip() for p in _re.split(r"\n{2,}", text) if p.strip()]
        if not sections:
            sections = [text]

    # ── Accumulate sections into budget-sized chunks ──────────────────────────
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for section in sections:
        section_tokens = count_tokens(section)

        # A single section exceeds the budget — split it at blank lines
        if section_tokens > budget_tokens:
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0
            sub_parts: list[str] = []
            sub_tokens = 0
            for sub in [p.strip() for p in _re.split(r"\n{2,}", section) if p.strip()]:
                st = count_tokens(sub)
                # If even a single paragraph exceeds the budget, split at sentences
                if st > budget_tokens:
                    if sub_parts:
                        chunks.append("\n\n".join(sub_parts))
                        sub_parts  = []
                        sub_tokens = 0
                    sentences = _re.split(r"(?<=[.!?])\s+", sub)
                    sent_parts: list[str] = []
                    sent_tokens = 0
                    for sent in sentences:
                        stk = count_tokens(sent)
                        if sent_tokens + stk > budget_tokens and sent_parts:
                            chunks.append(" ".join(sent_parts))
                            sent_parts  = [sent]
                            sent_tokens = stk
                        else:
                            sent_parts.append(sent)
                            sent_tokens += stk
                    if sent_parts:
                        chunks.append(" ".join(sent_parts))
                    continue
                if sub_tokens + st > budget_tokens and sub_parts:
                    chunks.append("\n\n".join(sub_parts))
                    sub_parts  = [sub]
                    sub_tokens = st
                else:
                    sub_parts.append(sub)
                    sub_tokens += st
            if sub_parts:
                chunks.append("\n\n".join(sub_parts))
            continue

        if current_tokens + section_tokens > budget_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts  = [section]
            current_tokens = section_tokens
        else:
            current_parts.append(section)
            current_tokens += section_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    # ── Merge tiny trailing chunks (< min_chunk_tokens) into previous ─────────
    merged: list[str] = []
    for chunk in chunks:
        if merged and count_tokens(chunk) < min_chunk_tokens:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)

    # ── Cap at max_chunks ─────────────────────────────────────────────────────
    if len(merged) > max_chunks:
        logger.warning(
            "_split_module_into_chunks: '%s' produced %d chunks (cap=%d); "
            "last %d chunk(s) will not be extracted — some requirements may be incomplete.",
            module_name, len(merged), max_chunks, len(merged) - max_chunks,
        )
        merged = merged[:max_chunks]

    # ── Prefix every chunk with a context header ──────────────────────────────
    total = len(merged)
    return [
        f"[Part {i + 1}/{total} of module '{module_name}'] "
        f"— Extract ALL requirements, fields, rules, and behaviors visible in this part. "
        f"Do NOT skip subsections, edge cases, or validation rules. "
        f"Capture every field, every status value, every dropdown option, every business rule.\n\n{chunk}"
        for i, chunk in enumerate(merged)
    ]


def _merge_chunk_extractions(
    chunk_results: list[dict[str, Any]],
    mode: str,
    module_name: str,
) -> dict[str, Any]:
    """
    Merge N per-chunk extraction dicts into one combined result.

    Dedup keys:
      screens       → by 'name'
      api_endpoints → by (method, path)
      models / enums → by 'name'
      business_rules / business_logic / workflows → concat + exact-key dedup
    """
    if not chunk_results:
        return {"module": {"name": module_name}}
    if len(chunk_results) == 1:
        return chunk_results[0]

    def _dedup_by_name(items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out:  list[dict] = []
        for item in items:
            k = item.get("name", "")
            if k and k not in seen:
                seen.add(k)
                out.append(item)
            elif not k:
                out.append(item)
        return out

    def _dedup_endpoints(items: list[dict]) -> list[dict]:
        seen: set[tuple] = set()
        out:  list[dict] = []
        for ep in items:
            k = (ep.get("method", "").upper(), ep.get("path", ""))
            if k not in seen:
                seen.add(k)
                out.append(ep)
        return out

    def _dedup_list(items: list) -> list:
        seen: set = set()
        out:  list = []
        for item in items:
            if isinstance(item, str):
                key = item
            elif isinstance(item, dict):
                key = next((v for v in item.values() if isinstance(v, str)), repr(item))
            else:
                key = repr(item)
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    description = next(
        (r.get("module", {}).get("description")
         for r in chunk_results if r.get("module", {}).get("description")),
        None,
    )

    if mode == "both":
        screens, enums, fe_rules, fe_flows         = [], [], [], []
        endpoints, models, be_logic, be_flows      = [], [], [], []
        for r in chunk_results:
            m  = r.get("module", {})
            fe = m.get("frontend", {})
            be = m.get("backend",  {})
            screens.extend(   fe.get("screens",        []))
            enums.extend(     fe.get("enums",          []))
            fe_rules.extend(  fe.get("business_rules", []))
            fe_flows.extend(  fe.get("workflows",      []))
            endpoints.extend( be.get("api_endpoints",  []))
            models.extend(    be.get("models",         []))
            be_logic.extend(  be.get("business_logic", []))
            be_flows.extend(  be.get("workflows",      []))
        return {
            "module": {
                "name":        module_name,
                "description": description,
                "frontend": {
                    "screens":         _dedup_by_name(screens),
                    "enums":           _dedup_by_name(enums),
                    "business_rules":  _dedup_list(fe_rules),
                    "workflows":       _dedup_list(fe_flows),
                },
                "backend": {
                    "api_endpoints":   _dedup_endpoints(endpoints),
                    "models":          _dedup_by_name(models),
                    "business_logic":  _dedup_list(be_logic),
                    "workflows":       _dedup_list(be_flows),
                },
            }
        }

    if mode == "frontend":
        screens, enums, rules, flows = [], [], [], []
        for r in chunk_results:
            m = r.get("module", {})
            screens.extend(m.get("screens",        []))
            enums.extend(  m.get("enums",          []))
            rules.extend(  m.get("business_rules", []))
            flows.extend(  m.get("workflows",      []))
        return {
            "module": {
                "name":           module_name,
                "description":    description,
                "screens":        _dedup_by_name(screens),
                "enums":          _dedup_by_name(enums),
                "business_rules": _dedup_list(rules),
                "workflows":      _dedup_list(flows),
            }
        }

    # mode == "backend"
    endpoints, models, logic, flows = [], [], [], []
    for r in chunk_results:
        m = r.get("module", {})
        endpoints.extend(m.get("api_endpoints",  []))
        models.extend(   m.get("models",         []))
        logic.extend(    m.get("business_logic", []))
        flows.extend(    m.get("workflows",      []))
    return {
        "module": {
            "name":           module_name,
            "description":    description,
            "api_endpoints":  _dedup_endpoints(endpoints),
            "models":         _dedup_by_name(models),
            "business_logic": _dedup_list(logic),
            "workflows":      _dedup_list(flows),
        }
    }


async def _extract_chunk_for_mode(
    chunk_text: str,
    module_name: str,
    mode: str,
    fe_prompt: dict[str, str] | None,
    be_prompt: dict[str, str] | None,
    extraction_prompt: dict[str, str] | None,
    extraction_schema: dict[str, Any] | None,
    base_rules_text: str,
    chunk_label: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Run extraction LLM call(s) for a single chunk of module text.

    mode='both'            → fires fe + be calls in parallel (asyncio.gather).
    mode='frontend'/'backend' → single LLM call.

    Returns (extraction_result_dict, usages_list).
    Summary is NOT run here — the caller handles it on the first chunk only.
    """
    if mode == "both":
        fe_user = _fmt(
            fe_prompt["user_template"],
            module_name=module_name,
            module_text=chunk_text,
            base_rules=base_rules_text,
        )
        be_user = _fmt(
            be_prompt["user_template"],
            module_name=module_name,
            module_text=chunk_text,
            base_rules=base_rules_text,
        )
        (fe_result, fe_usages), (be_result, be_usages) = await asyncio.gather(
            call_llm_with_schema(
                system_prompt=fe_prompt["system"],
                user_prompt=fe_user,
                schema=FRONTEND_SCHEMA,
                schema_name=f"extraction:fe:{module_name}:{chunk_label}",
                normalizer=_normalize_extraction,
            ),
            call_llm_with_schema(
                system_prompt=be_prompt["system"],
                user_prompt=be_user,
                schema=BACKEND_SCHEMA,
                schema_name=f"extraction:be:{module_name}:{chunk_label}",
            ),
        )
        fe_module = fe_result.get("module", {})
        be_module = be_result.get("module", {})
        extraction_result: dict[str, Any] = {
            "module": {
                "name":        module_name,
                "description": be_module.get("description") or fe_module.get("description"),
                "frontend": {
                    "screens":        fe_module.get("screens",        []),
                    "enums":          fe_module.get("enums",          []),
                    "business_rules": fe_module.get("business_rules", []),
                    "workflows":      fe_module.get("workflows",      []),
                },
                "backend": {
                    "api_endpoints":  be_module.get("api_endpoints",  []),
                    "models":         be_module.get("models",         []),
                    "business_logic": be_module.get("business_logic", []),
                    "workflows":      be_module.get("workflows",      []),
                },
            }
        }
        return extraction_result, fe_usages + be_usages

    # mode == "frontend" or "backend"
    extraction_normalizer = _normalize_extraction if mode == "frontend" else None
    extraction_user = _fmt(
        extraction_prompt["user_template"],
        module_name=module_name,
        module_text=chunk_text,
        base_rules=base_rules_text,
    )
    extraction_result, extraction_usages = await call_llm_with_schema(
        system_prompt=extraction_prompt["system"],
        user_prompt=extraction_user,
        schema=extraction_schema,
        schema_name=f"extraction:{mode}:{module_name}:{chunk_label}",
        normalizer=extraction_normalizer,
    )
    if extraction_result.get("module", {}).get("name", "") == "":
        extraction_result.setdefault("module", {})["name"] = module_name
    return extraction_result, extraction_usages


# ── Module concurrency semaphore (Phase 5) ────────────────────────────────────
# The LangGraph Send fan-out fires all N extract_module_node coroutines at once.
# Capping concurrent executions at MODULE_BATCH_SIZE (default 3) prevents the
# rate-limit cascade that causes MODULE_EXTRACTION_TIMEOUT on large documents.

_MODULE_SEMAPHORE: asyncio.Semaphore | None = None
_MODULE_SEMAPHORE_LOOP: object | None = None  # track which event loop owns the semaphore


def _get_module_semaphore() -> asyncio.Semaphore:
    """
    Return (lazily creating) the module-level concurrency semaphore.

    The semaphore is re-created whenever the running event loop changes so that
    background-task restarts and test teardowns don't leave a semaphore bound
    to a closed loop (which causes 'attached to a different loop' errors).
    """
    global _MODULE_SEMAPHORE, _MODULE_SEMAPHORE_LOOP
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if _MODULE_SEMAPHORE is None or current_loop is not _MODULE_SEMAPHORE_LOOP:
        _MODULE_SEMAPHORE = asyncio.Semaphore(MODULE_BATCH_SIZE)
        _MODULE_SEMAPHORE_LOOP = current_loop
    return _MODULE_SEMAPHORE


# ── Phase 1: Per-module extraction + summary (parallel via Send fan-out) ───────

async def _extract_module_body(slice_input: ModuleSlice) -> dict[str, Any]:
    """
    Core extraction logic for ONE module: chunking → LLM extraction → merge → summary.

    In mode='both': Phase A runs all FE extractions + summary in parallel (N+1
    concurrent), then Phase B runs all BE extractions in parallel (N concurrent).
    This halves peak concurrency vs the old approach of running FE+BE together
    for every chunk simultaneously (previously 2N+1 concurrent).

    In mode='frontend' or 'backend': all chunks run in one parallel gather (N+1
    concurrent) — same as before.

    Called exclusively through extract_module_node which applies the module-level
    concurrency semaphore (MODULE_BATCH_SIZE) before delegating here.
    """
    module_name         = slice_input["module_name"]
    module_text         = slice_input["module_text"]
    mode                = slice_input["mode"]
    module_key          = slice_input.get("module_key") or ""
    source_chunk_ids  = slice_input.get("source_chunk_ids") or []

    # Cap raised to 20 (from 10) so large modules (ERP user stories) lose fewer
    # requirements. Each chunk still fits within the token budget.
    _MAX_CHUNKS = 20

    summary_prompt  = _load_prompt("summary_extraction")
    base_rules_text = _load_prompt("base_rules").get("rules", "")

    # ── Load extraction prompt(s) and compute real token overhead ─────────────
    # Render templates with empty module_text so base_rules, module_name, and
    # all fixed boilerplate are counted accurately — excluding only the content.
    if mode == "both":
        fe_prompt         = _load_prompt("frontend_extraction")
        be_prompt         = _load_prompt("backend_extraction")
        extraction_prompt = None
        extraction_schema = None
        fe_overhead = (
            count_tokens(fe_prompt["system"])
            + count_tokens(_fmt(fe_prompt["user_template"], module_name=module_name, module_text="", base_rules=base_rules_text))
        )
        be_overhead = (
            count_tokens(be_prompt["system"])
            + count_tokens(_fmt(be_prompt["user_template"], module_name=module_name, module_text="", base_rules=base_rules_text))
        )
        actual_overhead = max(fe_overhead, be_overhead)
    else:
        fe_prompt = None
        be_prompt = None
        mode_map = {
            "frontend": ("frontend_extraction", FRONTEND_SCHEMA),
            "backend":  ("backend_extraction",  BACKEND_SCHEMA),
        }
        prompt_name, extraction_schema = mode_map[mode]
        extraction_prompt = _load_prompt(prompt_name)
        actual_overhead = (
            count_tokens(extraction_prompt["system"])
            + count_tokens(_fmt(extraction_prompt["user_template"], module_name=module_name, module_text="", base_rules=base_rules_text))
        )

    token_budget       = max(TOTAL_INPUT_TOKEN_LIMIT - actual_overhead, 1000)
    module_token_count = count_tokens(module_text)

    # ── Single-pass (fits) vs chunk-and-merge (too large) ────────────────────
    if module_token_count <= token_budget:
        chunks = [module_text]
    else:
        chunks = _split_module_into_chunks(module_text, token_budget, module_name, max_chunks=_MAX_CHUNKS)
        logger.info(
            "extract_module_node: '%s' too large for single pass "
            "(%d tokens > budget %d) — splitting into %d chunk(s) for full coverage.",
            module_name, module_token_count, token_budget, len(chunks),
        )

    logger.info(
        "extract_module_node: extracting '%s' (mode=%s, chunks=%d, timeout=%ds).",
        module_name, mode, len(chunks), MODULE_EXTRACTION_TIMEOUT,
    )

    # ── Build summary coroutine ───────────────────────────────────────────────
    # Runs on the first chunk only — contains the module overview; no base_rules.
    summary_user = _fmt(
        summary_prompt["user_template"],
        module_name=module_name,
        module_text=chunks[0],
    )
    summary_coro = call_llm_with_schema(
        system_prompt=summary_prompt["system"],
        user_prompt=summary_user,
        schema=SUMMARY_SCHEMA,
        schema_name=f"summary:{module_name}",
    )

    total_chunks = len(chunks)

    # ── Run extraction under module timeout (Phase 4: sequential FE/BE for "both") ──
    # mode="both"  → Phase A (all FE + summary in parallel, N+1 concurrent)
    #                → Phase B (all BE in parallel, N concurrent)
    #                Peak drops from 2N+1 → N+1, halving rate-limit pressure.
    # mode="frontend"/"backend" → single parallel gather, unchanged (1 call/chunk).
    chunk_pairs:    list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    summary_result: dict[str, Any]       = {}
    summary_usages: list[dict[str, Any]] = []

    try:
        if mode == "both":
            _phase_start = time.monotonic()

            # Phase A — all FE extractions + summary in parallel (N+1 concurrent)
            fe_coros = [
                _extract_chunk_for_mode(
                    chunk_text=chunk,
                    module_name=module_name,
                    mode="frontend",
                    fe_prompt=None,
                    be_prompt=None,
                    extraction_prompt=fe_prompt,
                    extraction_schema=FRONTEND_SCHEMA,
                    base_rules_text=base_rules_text,
                    chunk_label=f"fe-p{i + 1}of{total_chunks}",
                )
                for i, chunk in enumerate(chunks)
            ]
            phase_a = await asyncio.wait_for(
                asyncio.gather(summary_coro, *fe_coros),
                timeout=MODULE_EXTRACTION_TIMEOUT,
            )
            (summary_result, summary_usages), *fe_pairs = phase_a

            # Phase B — all BE extractions in parallel (N concurrent)
            _be_timeout = max(MODULE_EXTRACTION_TIMEOUT - (time.monotonic() - _phase_start), 60.0)
            be_coros = [
                _extract_chunk_for_mode(
                    chunk_text=chunk,
                    module_name=module_name,
                    mode="backend",
                    fe_prompt=None,
                    be_prompt=None,
                    extraction_prompt=be_prompt,
                    extraction_schema=BACKEND_SCHEMA,
                    base_rules_text=base_rules_text,
                    chunk_label=f"be-p{i + 1}of{total_chunks}",
                )
                for i, chunk in enumerate(chunks)
            ]
            be_pairs = list(await asyncio.wait_for(
                asyncio.gather(*be_coros),
                timeout=_be_timeout,
            ))

            # Stitch FE + BE per chunk into the unified "both" structure
            for (fe_result, fe_usages), (be_result, be_usages) in zip(fe_pairs, be_pairs):
                fe_mod = fe_result.get("module", {})
                be_mod = be_result.get("module", {})
                combined: dict[str, Any] = {
                    "module": {
                        "name":        module_name,
                        "description": be_mod.get("description") or fe_mod.get("description"),
                        "frontend": {
                            "screens":        fe_mod.get("screens",        []),
                            "enums":          fe_mod.get("enums",          []),
                            "business_rules": fe_mod.get("business_rules", []),
                            "workflows":      fe_mod.get("workflows",      []),
                        },
                        "backend": {
                            "api_endpoints":  be_mod.get("api_endpoints",  []),
                            "models":         be_mod.get("models",         []),
                            "business_logic": be_mod.get("business_logic", []),
                            "workflows":      be_mod.get("workflows",      []),
                        },
                    }
                }
                chunk_pairs.append((combined, fe_usages + be_usages))

        else:
            # Single-mode (frontend or backend): all chunks + summary in parallel
            extraction_coros = [
                _extract_chunk_for_mode(
                    chunk_text=chunk,
                    module_name=module_name,
                    mode=mode,
                    fe_prompt=fe_prompt,
                    be_prompt=be_prompt,
                    extraction_prompt=extraction_prompt,
                    extraction_schema=extraction_schema,
                    base_rules_text=base_rules_text,
                    chunk_label=f"p{i + 1}of{total_chunks}",
                )
                for i, chunk in enumerate(chunks)
            ]
            all_results = await asyncio.wait_for(
                asyncio.gather(*extraction_coros, summary_coro),
                timeout=MODULE_EXTRACTION_TIMEOUT,
            )
            *raw_pairs, (summary_result, summary_usages) = all_results
            chunk_pairs = list(raw_pairs)

    except asyncio.TimeoutError:
        raise RuntimeError(
            f"Module '{module_name}' exceeded the {MODULE_EXTRACTION_TIMEOUT}s deadline "
            f"(mode={mode}, chunks={total_chunks}). The LLM calls did not complete in time — "
            f"consider raising MODULE_EXTRACTION_TIMEOUT or LLM_TIMEOUT."
        )

    chunk_extraction_results                    = [pair[0] for pair in chunk_pairs]
    extraction_usages: list[dict[str, Any]]     = [u for pair in chunk_pairs for u in pair[1]]

    # ── Merge chunk extractions ───────────────────────────────────────────────
    if len(chunk_extraction_results) == 1:
        extraction_result = chunk_extraction_results[0]
    else:
        extraction_result = _merge_chunk_extractions(chunk_extraction_results, mode, module_name)
        logger.info(
            "extract_module_node: '%s' merged %d chunk(s) into final extraction.",
            module_name, len(chunk_extraction_results),
        )

    # ── Cross-validate screen references ─────────────────────────────────────
    if mode in ("both", "frontend"):
        _cross_validate_module(extraction_result, mode)

    # ── Ensure module name is set (single-mode edge case) ────────────────────
    if mode != "both" and extraction_result.get("module", {}).get("name", "") == "":
        extraction_result.setdefault("module", {})["name"] = module_name

    # ── BE api_endpoints retry guard (Phase 7) ────────────────────────────────
    # If the LLM produced models but 0 endpoints the output was silently
    # truncated. Fire one targeted retry with an explicit mandate.
    if mode in ("both", "backend"):
        _be_prompt_ref = be_prompt if mode == "both" else extraction_prompt
        if _be_prompt_ref is not None:
            _be_mod = (extraction_result.get("module") or {})
            if mode == "both":
                _be_mod = _be_mod.get("backend", {})
            _has_endpoints = bool(_be_mod.get("api_endpoints"))
            _has_models    = bool(_be_mod.get("models"))
            if not _has_endpoints and _has_models:
                logger.warning(
                    "_extract_module_body: '%s' has %d model(s) but 0 api_endpoints — "
                    "firing targeted BE retry.",
                    module_name, len(_be_mod.get("models", [])),
                )
                _retry_user = (
                    _fmt(
                        _be_prompt_ref["user_template"],
                        module_name=module_name,
                        module_text=chunks[0],   # always fits budget by construction
                        base_rules=base_rules_text,
                    )
                    + "\n\n\u26a0\ufe0f IMPORTANT: Your previous response contained 0 api_endpoints."
                      " This is always wrong. You MUST derive API endpoints from the user"
                      " actions described in the text (view, create, edit, delete, approve,"
                      " scan, upload, export \u2026). Return the full JSON with a non-empty"
                      " api_endpoints array."
                )
                try:
                    _retry_result, _retry_usages = await call_llm_with_schema(
                        system_prompt=_be_prompt_ref["system"],
                        user_prompt=_retry_user,
                        schema=BACKEND_SCHEMA,
                        schema_name=f"extraction:be_retry:{module_name}",
                    )
                    _retry_endpoints = _retry_result.get("module", {}).get("api_endpoints", [])
                    if _retry_endpoints:
                        if mode == "both":
                            extraction_result["module"]["backend"]["api_endpoints"] = _retry_endpoints
                        else:
                            extraction_result["module"]["api_endpoints"] = _retry_endpoints
                        extraction_usages.extend(_retry_usages)
                        logger.info(
                            "_extract_module_body: '%s' BE retry recovered %d endpoint(s).",
                            module_name, len(_retry_endpoints),
                        )
                except Exception as _retry_exc:
                    logger.warning(
                        "_extract_module_body: '%s' BE retry failed: %s",
                        module_name, _retry_exc,
                    )

    # ── Logging ───────────────────────────────────────────────────────────────
    all_usages = extraction_usages + summary_usages
    if mode == "backend":
        logger.info(
            "extract_module_node: '%s' done — %d endpoints, %d models.",
            module_name,
            len((extraction_result.get("module") or {}).get("api_endpoints", [])),
            len((extraction_result.get("module") or {}).get("models", [])),
        )
    elif mode == "both":
        fe = (extraction_result.get("module") or {}).get("frontend", {})
        be = (extraction_result.get("module") or {}).get("backend", {})
        logger.info(
            "extract_module_node: '%s' done — %d screens, %d endpoints, %d models.",
            module_name,
            len(fe.get("screens", [])),
            len(be.get("api_endpoints", [])),
            len(be.get("models", [])),
        )
    else:
        logger.info(
            "extract_module_node: '%s' done — %d screens.",
            module_name,
            _screen_count(extraction_result, mode),
        )

    module_result: ModuleResult = {
        "module_name":        module_name,
        "extraction":         extraction_result,
        "summary":            summary_result,
        "usage":              all_usages,
        "module_key":         module_key,
        "source_chunk_ids": source_chunk_ids,
    }
    # Append to the state's results list via the Annotated reducer
    return {"results": [module_result]}


async def extract_module_node(slice_input: ModuleSlice) -> dict[str, Any]:
    """
    Public LangGraph node — throttles concurrent module extractions with a
    semaphore (MODULE_BATCH_SIZE, default 3) before delegating to
    _extract_module_body.

    Prevents the Send fan-out from firing all N modules simultaneously on
    large documents, which causes rate-limit cascades and timeout failures
    (the root cause of Stock Module 2/3 and PO Module empty responses).
    """
    async with _get_module_semaphore():
        return await _extract_module_body(slice_input)


def _cross_validate_module(result: dict[str, Any], mode: str) -> None:
    """Warn about opens_screen references that don't match any screen in this module."""
    if mode == "both":
        screens = (result.get("module") or {}).get("frontend", {}).get("screens", [])
    else:
        screens = (result.get("module") or {}).get("screens", [])

    known: set[str] = {s.get("name", "") for s in screens}
    for screen in screens:
        _validate_opens_screen_refs(screen, known)


def _screen_count(result: dict[str, Any], mode: str) -> int:
    """Count extracted screens for frontend-mode modules only."""
    return len((result.get("module") or {}).get("screens", []))


# ── Phase 2: Artifact Index Node ─────────────────────────────────────────────

def artifact_index_node(state: ExtractionState) -> dict[str, Any]:
    """
    Phase 2: Build a flat catalog of normalized artifact signatures across all modules.

    Runs ONCE after all parallel extract_module_node tasks complete.
    The fan-in is automatic: the Annotated[list, operator.add] reducer on
    state["results"] accumulates every result before this node runs.

    Reads:
      state["results"] — fully accumulated list of ModuleResult dicts.
      state["mode"]    — extraction mode (frontend | backend | both).

    Writes to state:
      artifact_index — dict mapping artifact type → list of ArtifactSignature dicts.
    """
    from src.msbc.orchestration.utils.artifact_index import build_artifact_index

    results: list[ModuleResult] = state.get("results") or []
    mode:    str                = state.get("mode") or "both"

    if not results:
        logger.warning("artifact_index_node: no results in state; skipping.")
        return {"artifact_index": {}}

    logger.info(
        "artifact_index_node: building artifact index from %d module result(s).",
        len(results),
    )
    try:
        artifact_index = build_artifact_index(list(results), mode)
    except Exception as exc:
        logger.error(
            "artifact_index_node: failed to build artifact index: %s. "
            "Continuing with empty index.",
            exc,
        )
        artifact_index = {}

    return {"artifact_index": artifact_index}


# ── Phase 2: Artifact Deduplication Node ──────────────────────────────────────

def artifact_deduplication_node(state: ExtractionState) -> dict[str, Any]:
    """
    Phase 2: Deduplicate artifacts across canonical modules and flag conflicts.

    Reads state["artifact_index"] (built by artifact_index_node) and:
      1. Merges compatible duplicates (same API path+method, same DB model name,
         same enum name with compatible values, semantically equivalent business rules).
      2. Flags incompatible duplicates as conflicts with needs_review=True.
      3. Produces a full audit trail in dedupe_report.

    Self-edge removal from the dependency graph is handled in finalize_node
    (the graph is not yet built when this node runs) and appended to dedupe_report.

    Reads:
      state["artifact_index"] — output of artifact_index_node.

    Writes to state:
      artifact_index — cleaned (deduplicated) artifact index.
      dedupe_report  — merge decisions, conflicts, placeholder for self-edges.
    """
    from src.msbc.orchestration.utils.deduplication import run_deduplication

    artifact_index: dict[str, Any] = state.get("artifact_index") or {}

    if not artifact_index:
        logger.warning(
            "artifact_deduplication_node: empty artifact_index; skipping deduplication."
        )
        empty_report: dict[str, Any] = {
            "merged_artifacts":  [],
            "conflicts":         [],
            "self_edges_removed": [],
            "summary": {
                "total_artifacts_before":  0,
                "total_artifacts_after":   0,
                "duplicate_groups_merged": 0,
                "conflicts_flagged":       0,
                "self_edges_removed":      0,
            },
        }
        return {"artifact_index": {}, "dedupe_report": empty_report}

    logger.info("artifact_deduplication_node: running deduplication pass.")
    try:
        cleaned_index, dedupe_report = run_deduplication(artifact_index)
    except Exception as exc:
        logger.error(
            "artifact_deduplication_node: deduplication failed: %s. "
            "Continuing with unmodified artifact_index.",
            exc,
        )
        total = sum(len(v) for v in artifact_index.values())
        cleaned_index = artifact_index
        dedupe_report = {
            "merged_artifacts":  [],
            "conflicts":         [],
            "self_edges_removed": [],
            "summary": {
                "total_artifacts_before":  total,
                "total_artifacts_after":   total,
                "duplicate_groups_merged": 0,
                "conflicts_flagged":       0,
                "self_edges_removed":      0,
            },
        }

    return {"artifact_index": cleaned_index, "dedupe_report": dedupe_report}


# ── Phase 3: Requirement Linter Node ──────────────────────────────────────────

def _deprecated_requirement_linter_node_copy(state: ExtractionState) -> dict[str, Any]:
    """
    Phase 3: Deterministic quality gate — no LLM, never blocks the pipeline.

    Runs 12 checks across the fully assembled extraction output and produces a
    quality_report dict that is merged into state["extraction"]. On any internal
    error the node logs and returns a degraded-but-valid report rather than
    raising, so downstream response assembly is never interrupted.

    Checks performed (all deterministic Python):
      CHILD_SECTION_EXTRACTED_AS_MODULE — a primary section is not BUSINESS_MODULE type
      DUPLICATE_MODULE_NAME             — two canonical modules share the same key
      DUPLICATE_API_INTENT              — same (method, path) post-dedup across modules
      SAME_API_DIFFERENT_SCHEMA         — same path but conflicting schemas (from dedupe)
      DUPLICATE_DB_MODEL                — same table_name post-dedup across modules
      SAME_ENUM_DIFFERENT_VALUES        — enum conflict still unresolved (from dedupe)
      SELF_GRAPH_EDGE                   — a module's graph edge points to itself
      ORPHAN_GRAPH_NODE                 — graph node with zero edges
      EMPTY_FILTER_PANEL                — filter_panel component with no filter fields
      EMPTY_GRID_COLUMNS                — grid component with no columns defined
      FORM_WITHOUT_SUBMIT_ACTION        — form component with no save/submit action
      MISSING_SOURCE_SECTION            — module result has no source_chunk_ids

    Reads:
      state["extraction"]         — assembled modules list with components
      state["graph"]              — dependency graph nodes + edges
      state["artifact_index"]     — cleaned ArtifactSignature catalog (Phase 2)
      state["dedupe_report"]      — Phase 2 deduplication audit trail
      state["canonical_modules"]  — CanonicalModule dicts (Phase 1)
      state["canonical_modules"]  — used for module key checks
      state["results"]            — per-module extraction results

    Writes to state:
      extraction     — extraction dict with "quality_report" key added.
      quality_report — same report also stored as a standalone state key.
    """
    import re as _re

    issues:  list[dict[str, Any]] = []

    def _issue(check: str, description: str, **extra: Any) -> None:
        entry: dict[str, Any] = {"check": check, "description": description}
        entry.update({k: v for k, v in extra.items() if v is not None})
        issues.append(entry)
        logger.info("requirement_linter_node [%s]: %s", check, description)

    try:
        extraction         = state.get("extraction")         or {}
        graph_data         = state.get("graph")              or {}
        artifact_index     = state.get("artifact_index")     or {}
        dedupe_report      = state.get("dedupe_report")      or {}
        canonical_modules  = state.get("canonical_modules")  or []
        module_candidates  = state.get("module_candidates")  or []
        results            = state.get("results")            or []

        # classified_by_id removed: section-type lookup no longer applicable
        # (section_classifier_node removed in Phase 1 chunk-based flow)
        classified_by_id: dict[str, str] = {}

        # ── 1. CHILD_SECTION_EXTRACTED_AS_MODULE ──────────────────────────────
        # A canonical module's primary_section_id is classified as a child type.
        child_types = {
            "SCREEN", "FORM", "GRID", "TOOLBAR", "FILTER_PANEL",
            "WORKFLOW", "VALIDATION_RULES", "BUSINESS_RULES",
            "ENUM_DEFINITION", "API_SPEC", "MODEL_SPEC",
            "INTEGRATION", "EXAMPLE", "NOTE", "UNKNOWN",
        }
        for cm in canonical_modules:
            primary_id  = cm.get("primary_section_id", "")
            sec_type    = classified_by_id.get(primary_id, "")
            module_key  = cm.get("module_key", "")
            if sec_type and sec_type in child_types:
                _issue(
                    "CHILD_SECTION_EXTRACTED_AS_MODULE",
                    f"Module '{module_key}' primary section {primary_id!r} "
                    f"has type '{sec_type}', not BUSINESS_MODULE.",
                    module_key=module_key,
                    section_id=primary_id,
                    section_type=sec_type,
                )

        # ── 2. DUPLICATE_MODULE_NAME ──────────────────────────────────────────
        seen_keys: dict[str, str] = {}
        for cm in canonical_modules:
            key = cm.get("module_key", "")
            if not key:
                continue
            if key in seen_keys:
                _issue(
                    "DUPLICATE_MODULE_NAME",
                    f"Canonical module key '{key}' appears more than once.",
                    module_key=key,
                )
            else:
                seen_keys[key] = key

        # ── 3. DUPLICATE_API_INTENT (post-dedup) ─────────────────────────────
        # Same (method, path) still present in multiple modules after Phase 2.
        api_sigs: list[dict[str, Any]] = artifact_index.get("api_endpoints", [])
        api_by_key: dict[tuple[str, str], list[str]] = {}
        for sig in api_sigs:
            ep_key = (
                (sig.get("method") or "").upper(),
                sig.get("path") or "/",
            )
            api_by_key.setdefault(ep_key, []).append(sig.get("module_key", ""))
        for (method, path), module_keys in api_by_key.items():
            unique_modules = list(dict.fromkeys(module_keys))
            if len(unique_modules) > 1:
                _issue(
                    "DUPLICATE_API_INTENT",
                    f"{method} {path} still present in multiple modules after dedup: "
                    + ", ".join(unique_modules),
                    endpoint=f"{method} {path}",
                    module_keys=unique_modules,
                )

        # ── 4. SAME_API_DIFFERENT_SCHEMA (from dedupe conflicts) ──────────────
        for conflict in dedupe_report.get("conflicts", []):
            if conflict.get("artifact_type") == "api_endpoint":
                _issue(
                    "SAME_API_DIFFERENT_SCHEMA",
                    f"API endpoint conflict not resolved: {conflict.get('reason', '')}",
                    canonical_id=conflict.get("canonical_id"),
                    conflicting_ids=conflict.get("conflicting_ids"),
                    needs_review=conflict.get("needs_review", True),
                )

        # ── 5. DUPLICATE_DB_MODEL (post-dedup) ───────────────────────────────
        model_sigs: list[dict[str, Any]] = artifact_index.get("db_models", [])
        model_by_table: dict[str, list[str]] = {}
        for sig in model_sigs:
            table = sig.get("table_name") or sig.get("normalized_name") or ""
            model_by_table.setdefault(table, []).append(sig.get("module_key", ""))
        for table, module_keys in model_by_table.items():
            unique_modules = list(dict.fromkeys(module_keys))
            if len(unique_modules) > 1:
                _issue(
                    "DUPLICATE_DB_MODEL",
                    f"DB model '{table}' still present in multiple modules after dedup: "
                    + ", ".join(unique_modules),
                    table_name=table,
                    module_keys=unique_modules,
                )

        # ── 6. SAME_ENUM_DIFFERENT_VALUES (unresolved enum conflicts) ─────────
        for conflict in dedupe_report.get("conflicts", []):
            if conflict.get("artifact_type") == "enum":
                _issue(
                    "SAME_ENUM_DIFFERENT_VALUES",
                    f"Enum conflict not resolved: {conflict.get('reason', '')}",
                    canonical_id=conflict.get("canonical_id"),
                    recommended_canonical=conflict.get("recommended_canonical"),
                    needs_review=conflict.get("needs_review", True),
                )

        # ── 7. SELF_GRAPH_EDGE ────────────────────────────────────────────────
        graph_edges: list[dict[str, Any]] = graph_data.get("edges", [])
        for edge in graph_edges:
            if edge.get("from") and edge.get("from") == edge.get("to"):
                _issue(
                    "SELF_GRAPH_EDGE",
                    f"Graph edge '{edge['from']}' → '{edge['to']}' is a self-reference.",
                    module_key=edge.get("from"),
                )

        # ── 8. ORPHAN_GRAPH_NODE ──────────────────────────────────────────────
        graph_nodes: list[dict[str, Any]] = graph_data.get("nodes", [])
        node_ids_with_edges: set[str] = set()
        for edge in graph_edges:
            node_ids_with_edges.add(edge.get("from", ""))
            node_ids_with_edges.add(edge.get("to",   ""))
        for node in graph_nodes:
            nid = node.get("id", "")
            if nid and nid not in node_ids_with_edges:
                _issue(
                    "ORPHAN_GRAPH_NODE",
                    f"Graph node '{nid}' has no edges (no dependencies defined).",
                    module_key=nid,
                )

        # ── 9–11. Component-level checks (EMPTY_FILTER_PANEL, EMPTY_GRID_COLUMNS,
        #          FORM_WITHOUT_SUBMIT_ACTION) ──────────────────────────────────
        def _check_screen_components(
            screen: dict[str, Any],
            module_key: str,
        ) -> None:
            """Walk a screen's components list and run component-level lint checks."""
            for comp in screen.get("components", []):
                if not isinstance(comp, dict):
                    continue
                ctype = comp.get("type", "")
                cname = comp.get("id") or comp.get("name") or ctype

                # 9. EMPTY_FILTER_PANEL
                if ctype == "filter_panel":
                    fields = comp.get("fields") or comp.get("filters") or []
                    if not fields:
                        _issue(
                            "EMPTY_FILTER_PANEL",
                            f"Screen '{screen.get('name', '?')}' has a filter_panel "
                            f"'{cname}' with no filter fields defined.",
                            module_key=module_key,
                            screen=screen.get("name"),
                            component=cname,
                        )

                # 10. EMPTY_GRID_COLUMNS
                elif ctype == "grid":
                    columns = comp.get("columns") or comp.get("fields") or []
                    if not columns:
                        _issue(
                            "EMPTY_GRID_COLUMNS",
                            f"Screen '{screen.get('name', '?')}' has a grid "
                            f"'{cname}' with no columns defined.",
                            module_key=module_key,
                            screen=screen.get("name"),
                            component=cname,
                        )

                # 11. FORM_WITHOUT_SUBMIT_ACTION
                elif ctype == "form":
                    actions = comp.get("actions") or []
                    submit_keywords = {"save", "submit", "create", "update",
                                       "add", "confirm", "apply", "ok"}
                    has_submit = any(
                        any(kw in str(a.get("label", "")).lower()
                            or kw in str(a.get("action", "")).lower()
                            for kw in submit_keywords)
                        for a in actions
                        if isinstance(a, dict)
                    )
                    if not has_submit and not actions:
                        _issue(
                            "FORM_WITHOUT_SUBMIT_ACTION",
                            f"Screen '{screen.get('name', '?')}' has a form "
                            f"'{cname}' with no save/submit action defined.",
                            module_key=module_key,
                            screen=screen.get("name"),
                            component=cname,
                        )

                # Recurse into tabs children
                if ctype == "tabs":
                    for tab in comp.get("children", []):
                        _check_screen_components(
                            {"name": screen.get("name"), "components": tab.get("components", [])},
                            module_key,
                        )

        mode = state.get("mode") or "both"
        for mod in extraction.get("modules", []):
            mk = mod.get("module_key") or mod.get("name") or ""
            if mode == "both":
                screens = mod.get("frontend", {}).get("screens", [])
            else:
                screens = mod.get("screens", [])
            for screen in (screens or []):
                if isinstance(screen, dict):
                    _check_screen_components(screen, mk)

        # ── 12. MISSING_SOURCE_SECTION ────────────────────────────────────────
        for res in results:
            mk  = res.get("module_key") or res.get("module_name") or "?"
            sids = res.get("source_chunk_ids") or []
            if not sids:
                _issue(
                    "MISSING_SOURCE_SECTION",
                    f"Module '{mk}' has no source_chunk_ids — "
                    f"cannot trace artifacts back to document sections.",
                    module_key=mk,
                )

    except Exception as exc:
        logger.error(
            "requirement_linter_node: unexpected error during lint checks: %s. "
            "Quality report will be partial.",
            exc,
        )
        issues.append({
            "check":       "LINTER_INTERNAL_ERROR",
            "description": f"Linter crashed: {exc}",
        })

    # ── Build metrics ─────────────────────────────────────────────────────────
    dedupe_summary = dedupe_report.get("summary") or {}
    metrics: dict[str, Any] = {
        "module_count_before_canonicalization": len(module_candidates),
        "module_count_after_canonicalization":  len(canonical_modules),
        "duplicate_module_clusters_merged":     dedupe_summary.get("duplicate_groups_merged", 0),
        "duplicate_api_groups_found": sum(
            1 for i in issues if i.get("check") == "DUPLICATE_API_INTENT"
        ),
        "enum_conflicts":      dedupe_summary.get("conflicts_flagged", 0),
        "self_graph_edges_removed": dedupe_summary.get("self_edges_removed", 0),
    }

    # Check codes that are not warnings — presence means passed=False
    blocking_checks = {
        "DUPLICATE_MODULE_NAME",
        "DUPLICATE_API_INTENT",
        "DUPLICATE_DB_MODEL",
        "SAME_ENUM_DIFFERENT_VALUES",
        "SELF_GRAPH_EDGE",
        "LINTER_INTERNAL_ERROR",
    }
    passed = not any(i.get("check") in blocking_checks for i in issues)

    quality_report: dict[str, Any] = {
        "passed":  passed,
        "metrics": metrics,
        "issues":  issues,
    }

    logger.info(
        "requirement_linter_node: %s — %d issue(s) found. "
        "(modules %d→%d, %d merge(s), %d conflict(s), %d self-edge(s) removed)",
        "PASSED" if passed else "FAILED",
        len(issues),
        metrics["module_count_before_canonicalization"],
        metrics["module_count_after_canonicalization"],
        metrics["duplicate_module_clusters_merged"],
        metrics["enum_conflicts"],
        metrics["self_graph_edges_removed"],
    )

    # Merge quality_report into the extraction dict that finalize_node produced.
    updated_extraction = dict(state.get("extraction") or {})
    updated_extraction["quality_report"] = quality_report

    return {
        "extraction":    updated_extraction,
        "quality_report": quality_report,
    }


# ── Phase 3: Quality Gate Node ────────────────────────────────────────────────

def quality_gate_node(state: ExtractionState) -> dict[str, Any]:
    """
    Phase 3: Deterministic quality gate — no LLM, never blocks the pipeline.

    Runs 14 checks across the fully assembled extraction output and produces a
    quality_report dict that is merged into state["extraction"]. On any internal
    error the node logs and returns a degraded-but-valid report rather than
    raising, so downstream response assembly is never interrupted.

    Checks performed (all deterministic Python):
      CHILD_SECTION_EXTRACTED_AS_MODULE — a primary section is not BUSINESS_MODULE type
      DUPLICATE_MODULE_NAME             — two canonical modules share the same key
      DUPLICATE_API_INTENT              — same (method, path) post-dedup across modules
      SAME_API_DIFFERENT_SCHEMA         — same path but conflicting schemas (from dedupe)
      DUPLICATE_DB_MODEL                — same table_name post-dedup across modules
      SAME_ENUM_DIFFERENT_VALUES        — enum conflict still unresolved (from dedupe)
      SELF_GRAPH_EDGE                   — a module's graph edge points to itself
      ORPHAN_GRAPH_NODE                 — graph node with zero edges
      EMPTY_FILTER_PANEL                — filter_panel component with no filter fields
      EMPTY_GRID_COLUMNS                — grid component with no columns defined
      FORM_WITHOUT_SUBMIT_ACTION        — form component with no save/submit action
      MISSING_SOURCE_SECTION            — module result has no source_chunk_ids
      MODULE_COUNT_WARNING              — canonical module count exceeds expected range
      SUSPICIOUS_MODULE_NAME            — module key contains child-concept patterns

    Reads:
      state["extraction"]         — assembled modules list with components
      state["graph"]              — dependency graph nodes + edges
      state["artifact_index"]     — cleaned ArtifactSignature catalog (Phase 2)
      state["dedupe_report"]      — Phase 2 deduplication audit trail
      state["canonical_modules"]  — CanonicalModule dicts (Phase 1)
      state["canonical_modules"]  — used for module key checks
      state["results"]            — per-module extraction results

    Writes to state:
      extraction     — extraction dict with "quality_report" key added.
      quality_report — same report also stored as a standalone state key.
    """
    import re as _re

    issues:  list[dict[str, Any]] = []

    def _issue(check: str, description: str, **extra: Any) -> None:
        entry: dict[str, Any] = {"check": check, "description": description}
        entry.update({k: v for k, v in extra.items() if v is not None})
        issues.append(entry)
        logger.info("quality_gate_node [%s]: %s", check, description)

    try:
        extraction         = state.get("extraction")         or {}
        graph_data         = state.get("graph")              or {}
        artifact_index     = state.get("artifact_index")     or {}
        dedupe_report      = state.get("dedupe_report")      or {}
        canonical_modules  = state.get("canonical_modules")  or []
        module_candidates  = state.get("module_candidates")  or []
        results            = state.get("results")            or []

        # classified_by_id removed: section-type lookup no longer applicable
        # (section_classifier_node removed in Phase 1 chunk-based flow)
        classified_by_id: dict[str, str] = {}

        # ── 1. CHILD_SECTION_EXTRACTED_AS_MODULE ──────────────────────────────
        # A canonical module's primary_section_id is classified as a child type.
        child_types = {
            "SCREEN", "FORM", "GRID", "TOOLBAR", "FILTER_PANEL",
            "WORKFLOW", "VALIDATION_RULES", "BUSINESS_RULES",
            "ENUM_DEFINITION", "API_SPEC", "MODEL_SPEC",
            "INTEGRATION", "EXAMPLE", "NOTE", "UNKNOWN",
        }
        for cm in canonical_modules:
            primary_id  = cm.get("primary_section_id", "")
            sec_type    = classified_by_id.get(primary_id, "")
            module_key  = cm.get("module_key", "")
            if sec_type and sec_type in child_types:
                _issue(
                    "CHILD_SECTION_EXTRACTED_AS_MODULE",
                    f"Module '{module_key}' primary section {primary_id!r} "
                    f"has type '{sec_type}', not BUSINESS_MODULE.",
                    module_key=module_key,
                    section_id=primary_id,
                    section_type=sec_type,
                )

        # ── 2. DUPLICATE_MODULE_NAME ──────────────────────────────────────────
        seen_keys: dict[str, str] = {}
        for cm in canonical_modules:
            key = cm.get("module_key", "")
            if not key:
                continue
            if key in seen_keys:
                _issue(
                    "DUPLICATE_MODULE_NAME",
                    f"Canonical module key '{key}' appears more than once.",
                    module_key=key,
                )
            else:
                seen_keys[key] = key

        # ── 3. DUPLICATE_API_INTENT (post-dedup) ─────────────────────────────
        # Same (method, path) still present in multiple modules after Phase 2.
        api_sigs: list[dict[str, Any]] = artifact_index.get("api_endpoints", [])
        api_by_key: dict[tuple[str, str], list[str]] = {}
        for sig in api_sigs:
            ep_key = (
                (sig.get("method") or "").upper(),
                sig.get("path") or "/",
            )
            api_by_key.setdefault(ep_key, []).append(sig.get("module_key", ""))
        for (method, path), module_keys in api_by_key.items():
            unique_modules = list(dict.fromkeys(module_keys))
            if len(unique_modules) > 1:
                _issue(
                    "DUPLICATE_API_INTENT",
                    f"{method} {path} still present in multiple modules after dedup: "
                    + ", ".join(unique_modules),
                    endpoint=f"{method} {path}",
                    module_keys=unique_modules,
                )

        # ── 4. SAME_API_DIFFERENT_SCHEMA (from dedupe conflicts) ──────────────
        for conflict in dedupe_report.get("conflicts", []):
            if conflict.get("artifact_type") == "api_endpoint":
                _issue(
                    "SAME_API_DIFFERENT_SCHEMA",
                    f"API endpoint conflict not resolved: {conflict.get('reason', '')}",
                    canonical_id=conflict.get("canonical_id"),
                    conflicting_ids=conflict.get("conflicting_ids"),
                    needs_review=conflict.get("needs_review", True),
                )

        # ── 5. DUPLICATE_DB_MODEL (post-dedup) ───────────────────────────────
        model_sigs: list[dict[str, Any]] = artifact_index.get("db_models", [])
        model_by_table: dict[str, list[str]] = {}
        for sig in model_sigs:
            table = sig.get("table_name") or sig.get("normalized_name") or ""
            model_by_table.setdefault(table, []).append(sig.get("module_key", ""))
        for table, module_keys in model_by_table.items():
            unique_modules = list(dict.fromkeys(module_keys))
            if len(unique_modules) > 1:
                _issue(
                    "DUPLICATE_DB_MODEL",
                    f"DB model '{table}' still present in multiple modules after dedup: "
                    + ", ".join(unique_modules),
                    table_name=table,
                    module_keys=unique_modules,
                )

        # ── 6. SAME_ENUM_DIFFERENT_VALUES (unresolved enum conflicts) ─────────
        for conflict in dedupe_report.get("conflicts", []):
            if conflict.get("artifact_type") == "enum":
                _issue(
                    "SAME_ENUM_DIFFERENT_VALUES",
                    f"Enum conflict not resolved: {conflict.get('reason', '')}",
                    canonical_id=conflict.get("canonical_id"),
                    recommended_canonical=conflict.get("recommended_canonical"),
                    needs_review=conflict.get("needs_review", True),
                )

        # ── 7. SELF_GRAPH_EDGE ────────────────────────────────────────────────
        graph_edges: list[dict[str, Any]] = graph_data.get("edges", [])
        for edge in graph_edges:
            if edge.get("from") and edge.get("from") == edge.get("to"):
                _issue(
                    "SELF_GRAPH_EDGE",
                    f"Graph edge '{edge['from']}' → '{edge['to']}' is a self-reference.",
                    module_key=edge.get("from"),
                )

        # ── 8. ORPHAN_GRAPH_NODE ──────────────────────────────────────────────
        graph_nodes: list[dict[str, Any]] = graph_data.get("nodes", [])
        node_ids_with_edges: set[str] = set()
        for edge in graph_edges:
            node_ids_with_edges.add(edge.get("from", ""))
            node_ids_with_edges.add(edge.get("to",   ""))
        for node in graph_nodes:
            nid = node.get("id", "")
            if nid and nid not in node_ids_with_edges:
                _issue(
                    "ORPHAN_GRAPH_NODE",
                    f"Graph node '{nid}' has no edges (no dependencies defined).",
                    module_key=nid,
                )

        # ── 9–11. Component-level checks (EMPTY_FILTER_PANEL, EMPTY_GRID_COLUMNS,
        #          FORM_WITHOUT_SUBMIT_ACTION) ──────────────────────────────────
        def _check_screen_components(
            screen: dict[str, Any],
            module_key: str,
        ) -> None:
            """Walk a screen's components list and run component-level lint checks."""
            for comp in screen.get("components", []):
                if not isinstance(comp, dict):
                    continue
                ctype = comp.get("type", "")
                cname = comp.get("id") or comp.get("name") or ctype

                # 9. EMPTY_FILTER_PANEL
                if ctype == "filter_panel":
                    fields = comp.get("fields") or comp.get("filters") or []
                    if not fields:
                        _issue(
                            "EMPTY_FILTER_PANEL",
                            f"Screen '{screen.get('name', '?')}' has a filter_panel "
                            f"'{cname}' with no filter fields defined.",
                            module_key=module_key,
                            screen=screen.get("name"),
                            component=cname,
                        )

                # 10. EMPTY_GRID_COLUMNS
                elif ctype == "grid":
                    columns = comp.get("columns") or comp.get("fields") or []
                    if not columns:
                        _issue(
                            "EMPTY_GRID_COLUMNS",
                            f"Screen '{screen.get('name', '?')}' has a grid "
                            f"'{cname}' with no columns defined.",
                            module_key=module_key,
                            screen=screen.get("name"),
                            component=cname,
                        )

                # 11. FORM_WITHOUT_SUBMIT_ACTION
                elif ctype == "form":
                    actions = comp.get("actions") or []
                    submit_keywords = {"save", "submit", "create", "update",
                                       "add", "confirm", "apply", "ok"}
                    has_submit = any(
                        any(kw in str(a.get("label", "")).lower()
                            or kw in str(a.get("action", "")).lower()
                            for kw in submit_keywords)
                        for a in actions
                        if isinstance(a, dict)
                    )
                    if not has_submit and not actions:
                        _issue(
                            "FORM_WITHOUT_SUBMIT_ACTION",
                            f"Screen '{screen.get('name', '?')}' has a form "
                            f"'{cname}' with no save/submit action defined.",
                            module_key=module_key,
                            screen=screen.get("name"),
                            component=cname,
                        )

                # Recurse into tabs children
                if ctype == "tabs":
                    for tab in comp.get("children", []):
                        _check_screen_components(
                            {"name": screen.get("name"), "components": tab.get("components", [])},
                            module_key,
                        )

        mode = state.get("mode") or "both"
        for mod in extraction.get("modules", []):
            mk = mod.get("module_key") or mod.get("name") or ""
            if mode == "both":
                screens = mod.get("frontend", {}).get("screens", [])
            else:
                screens = mod.get("screens", [])
            for screen in (screens or []):
                if isinstance(screen, dict):
                    _check_screen_components(screen, mk)

        # ── 12. MISSING_SOURCE_SECTION ────────────────────────────────────────
        for res in results:
            mk  = res.get("module_key") or res.get("module_name") or "?"
            sids = res.get("source_chunk_ids") or []
            if not sids:
                _issue(
                    "MISSING_SOURCE_SECTION",
                    f"Module '{mk}' has no source_chunk_ids — "
                    f"cannot trace artifacts back to document sections.",
                    module_key=mk,
                )

    except Exception as exc:
        logger.error(
            "quality_gate_node: unexpected error during quality checks: %s. "
            "Quality report will be partial.",
            exc,
        )
        issues.append({
            "check":       "LINTER_INTERNAL_ERROR",
            "description": f"Linter crashed: {exc}",
        })

    # ── Build metrics ─────────────────────────────────────────────────────────
    dedupe_summary = dedupe_report.get("summary") or {}
    metrics: dict[str, Any] = {
        "module_count_before_canonicalization": len(module_candidates),
        "module_count_after_canonicalization":  len(canonical_modules),
        "duplicate_module_clusters_merged":     dedupe_summary.get("duplicate_groups_merged", 0),
        "duplicate_api_groups_found": sum(
            1 for i in issues if i.get("check") == "DUPLICATE_API_INTENT"
        ),
        "enum_conflicts":      dedupe_summary.get("conflicts_flagged", 0),
        "self_graph_edges_removed": dedupe_summary.get("self_edges_removed", 0),
    }

    # ── Derive status ──────────────────────────────────────────────────────
    # Blocking checks → "repair_required" | warnings → "warning" | none → "pass"
    blocking_checks = {
        "DUPLICATE_MODULE_NAME",
        "DUPLICATE_API_INTENT",
        "DUPLICATE_DB_MODEL",
        "SAME_ENUM_DIFFERENT_VALUES",
        "SELF_GRAPH_EDGE",
        "LINTER_INTERNAL_ERROR",
    }
    warning_checks = {
        "MODULE_COUNT_WARNING",
        "SUSPICIOUS_MODULE_NAME",
        "CHILD_SECTION_EXTRACTED_AS_MODULE",
        "ORPHAN_GRAPH_NODE",
        "MISSING_SOURCE_SECTION",
        "EMPTY_FILTER_PANEL",
        "EMPTY_GRID_COLUMNS",
        "FORM_WITHOUT_SUBMIT_ACTION",
        "SAME_API_DIFFERENT_SCHEMA",
    }

    has_blocking = any(i.get("check") in blocking_checks for i in issues)
    has_warnings = any(i.get("check") in warning_checks  for i in issues)
    passed = not has_blocking

    if has_blocking:
        status = "repair_required"
    elif has_warnings:
        status = "warning"
    else:
        status = "pass"

    suspicious_modules = [
        i["module_key"]
        for i in issues
        if i.get("check") == "SUSPICIOUS_MODULE_NAME" and "module_key" in i
    ]
    dedupe_anomalies = [
        i for i in issues
        if i.get("check") in {"SAME_API_DIFFERENT_SCHEMA", "SAME_ENUM_DIFFERENT_VALUES"}
    ]

    quality_report: dict[str, Any] = {
        # Plan-specified top-level keys (Section 5.9)
        "status":             status,
        "module_count":       len(canonical_modules),
        "expected_range":     "4-8",
        "suspicious_modules": suspicious_modules,
        "dedupe_anomalies":   dedupe_anomalies,
        "weak_modules":       [],   # reserved for future extension
        # Legacy keys kept for backward compatibility
        "passed":  passed,
        "metrics": metrics,
        "issues":  issues,
    }

    logger.info(
        "quality_gate_node: %s — %d issue(s) found. "
        "(modules %d→%d, %d merge(s), %d conflict(s), %d self-edge(s) removed)",
        status.upper(),
        len(issues),
        metrics["module_count_before_canonicalization"],
        metrics["module_count_after_canonicalization"],
        metrics["duplicate_module_clusters_merged"],
        metrics["enum_conflicts"],
        metrics["self_graph_edges_removed"],
    )

    # Merge quality_report into the extraction dict that finalize_node produced.
    updated_extraction = dict(state.get("extraction") or {})
    updated_extraction["quality_report"] = quality_report

    return {
        "extraction":    updated_extraction,
        "quality_report": quality_report,
    }


# ── Phase 2 (legacy label): Finalize (pure-Python collect + graph builder LLM) ─

def _python_merge_results(
    results: list[ModuleResult],
    modules: list[dict[str, Any]],
    canonical_modules: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    """
    Pure-Python collect: assemble per-module extractions in segmentation order.
    No LLM call — instant. Mirrors Phase 2 of user_story_parser/llm_service.py.

    When canonical_modules are available (Phase 1 path), sort by their order.
    Falls back to the legacy modules list order for the legacy path.
    """
    # Build order map: prefer canonical_modules order, fall back to modules list.
    if canonical_modules:
        order_map: dict[str, int] = {}
        for idx, cm in enumerate(canonical_modules):
            order_map[cm.get("module_key", "")] = idx
            order_map[cm.get("display_name", "")] = idx
    else:
        order_map = {m["name"]: idx for idx, m in enumerate(modules)}

    def _sort_key(r: ModuleResult) -> int:
        # Prefer module_key ordering, fall back to module_name.
        mk = r.get("module_key") or ""
        if mk and mk in order_map:
            return order_map[mk]
        return order_map.get(r["module_name"], 999)

    sorted_results = sorted(results, key=_sort_key)

    module_list = [
        {
            "name":               res["module_name"],
            "module_key":         res.get("module_key") or "",
            "order":              idx + 1,
            "source_chunk_ids": res.get("source_chunk_ids") or [],
            **res["extraction"].get("module", {}),
        }
        for idx, res in enumerate(sorted_results)
    ]

    return {
        "mode":          mode,
        "total_modules": len(module_list),
        "modules":       module_list,
    }


async def finalize_node(state: ExtractionState) -> dict[str, Any]:
    """
    Phase 2: Assemble all per-module extractions (pure Python, instant) and
    build the dependency graph (one LLM call on summaries only).

    Replaces the old unification_node (LLM on all extraction JSONs → timeout)
    and graph_builder_node (which ran sequentially after that).
    """
    n = len(state["results"])
    logger.info("finalize_node: assembling %d module(s) + building dependency graph.", n)

    canonical_modules: list[dict[str, Any]] = state.get("canonical_modules") or []

    # ── Pure-Python merge (instant) ───────────────────────────────────────────
    extraction = _python_merge_results(
        state["results"],
        [],  # legacy modules list not used in chunk-based flow
        canonical_modules,
        state["mode"],
    )

    # ── Graph builder LLM call (uses summaries only — small context) ──────────
    prompt_data   = _load_prompt("graph_builder")
    all_summaries = [r["summary"] for r in state["results"]]

    # Build the ordered list of valid module IDs.
    # Phase 1 path: use module_key from canonical_modules for clean, stable IDs.
    # Legacy path: derive from module_name as before.
    def _to_module_id(name: str) -> str:
        return name.lower().replace(" ", "_").replace("-", "_")

    results = state["results"]
    if canonical_modules:
        # Use the module_key from each result (set by extract_module_node).
        # Fall back to slugging the module_name if module_key is empty.
        module_names = [r["module_name"] for r in results]
        valid_ids = [
            (r.get("module_key") or _to_module_id(r["module_name"]))
            for r in results
        ]
    else:
        module_names = [r["module_name"] for r in results]
        valid_ids    = [_to_module_id(name) for name in module_names]

    module_ids_json = json.dumps(valid_ids, indent=2)

    user_prompt = _fmt(
        prompt_data["user_template"],
        mode=state["mode"],
        module_ids=module_ids_json,
        module_count=str(len(valid_ids)),
        all_summaries=json.dumps(all_summaries, indent=2),
    )

    graph_result, graph_usages = await call_llm_with_schema(
        system_prompt=_fmt(
            prompt_data["system"],
            mode=state["mode"],
            module_ids=module_ids_json,
        ),
        user_prompt=user_prompt,
        schema=GRAPH_OUTPUT_SCHEMA,
        schema_name="graph_builder",
    )

    # ── Post-process: strip any phantom nodes/edges the LLM may have produced ─
    valid_id_set = set(valid_ids)
    graph = graph_result.get("graph", {})

    # Keep only nodes whose IDs are in the extracted set
    filtered_nodes = [nd for nd in graph.get("nodes", []) if nd.get("id") in valid_id_set]

    # Ensure every extracted module has a node (fill gaps if LLM omitted any)
    existing_ids = {nd["id"] for nd in filtered_nodes}
    for mid, mname in zip(valid_ids, module_names):
        if mid not in existing_ids:
            filtered_nodes.append({
                "id": mid,
                "label": mname,
                "type": "feature",
                "description": None,
                "external_dependencies": [],
            })

    # Keep only edges where both endpoints are valid extracted module IDs
    filtered_edges = [
        e for e in graph.get("edges", [])
        if e.get("from") in valid_id_set and e.get("to") in valid_id_set
    ]

    # ── Remove self-referencing edges and record them in dedupe_report ────────
    from src.msbc.orchestration.utils.deduplication import remove_self_edges
    filtered_edges, self_edge_ids = remove_self_edges(filtered_edges)

    # Extend dedupe_report with self-edge removal results (populated here because
    # the graph is not built until this node; global_deduplication_node runs first).
    dedupe_report: dict[str, Any] = state.get("dedupe_report") or {}
    if self_edge_ids or dedupe_report:
        # Create a mutable copy so we don't mutate the state dict in-place.
        dedupe_report = dict(dedupe_report)
        existing_removed: list[str] = list(dedupe_report.get("self_edges_removed") or [])
        all_removed = existing_removed + self_edge_ids
        dedupe_report["self_edges_removed"] = all_removed
        summary = dict(dedupe_report.get("summary") or {})
        summary["self_edges_removed"] = len(all_removed)
        dedupe_report["summary"] = summary

    # Recompute entry_points from filtered graph
    inbound_ids = {
        e["to"] for e in filtered_edges
        if e.get("relation") in ("depends_on", "calls")
    }
    entry_points = [nd["id"] for nd in filtered_nodes if nd["id"] not in inbound_ids]

    graph_result["graph"] = {
        "nodes":        filtered_nodes,
        "edges":        filtered_edges,
        "entry_points": entry_points,
        "metadata": {
            "total_modules": len(filtered_nodes),
            "mode":          state["mode"],
            "total_edges":   len(filtered_edges),
        },
    }

    node_count = len(graph_result.get("graph", {}).get("nodes", []))
    edge_count = len(graph_result.get("graph", {}).get("edges", []))
    logger.info(
        "finalize_node: complete — %d module(s), graph: %d nodes, %d edges.",
        n, node_count, edge_count,
    )

    # Include the deduplication report (Phase 2) as a top-level key in extraction.
    # When Phase 2 nodes did not run (empty dedupe_report), an empty dict is inserted
    # so downstream consumers always see the key and can safely check it.
    extraction_output = dict(extraction)
    if dedupe_report:
        extraction_output["deduplication_report"] = dedupe_report

    return {
        "extraction": extraction_output,
        "graph":      graph_result["graph"],
        "all_usage":  (state.get("all_usage") or []) + graph_usages,
    }
