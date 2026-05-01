"""
Node implementations for the requirement extractor LangGraph workflow.

Phases:
  0   — segmentation_node     : identify modules (1 LLM call)
  0.5 — build_slices_node     : pure-Python fan-out via Send API
  1   — extract_module_node   : extraction + summary per module (parallel)
  2   — finalize_node         : pure-Python collect + graph-builder LLM call
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
    CLASSIFICATION_SCHEMA,
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


# ── Phase 0: Segmentation ─────────────────────────────────────────────────────

def _pre_clean_headings(heading_hierarchy: list[dict]) -> list[dict]:
    """
    Lightweight Python pre-cleanup before the LLM holistic module selection call.

    Python's job is ONLY to remove obvious structural noise — blank entries,
    excessively long paragraphs accidentally tagged as headings, emoji-prefixed
    decorative callouts, and field-label headings (e.g. "Module Name: X").
    All semantic decisions (module vs. sub-section vs. UI element) are delegated
    entirely to the LLM so that genuine module headings are never silently dropped.

    Filters applied (in order):
      1. Blank headings removed.
      2. Top three heading levels are kept — deeper levels (L4+) are very rarely
         module boundaries but L3 can contain named masters or process steps.
      3. Headings > 150 characters removed — these are paragraphs accidentally
         formatted as headings in Word (real titles are short).
      4. Emoji / symbol starters removed (U+2600+) — decorative section markers.
      5. Explicit field-label headings removed — "Module Name: X", "Section Title: Y".
      6. Deduplicated by exact text (first occurrence wins).

    Intentionally NOT filtered here (let the LLM decide):
      • Dotted sub-sections ("2.1 Purpose", "3.4 Business Rules") — the LLM
        prompt explicitly excludes them, but they provide useful structural
        context for adjacent headings.
      • Broad document-title headings ("Job Module") — LLM rules handle them.
      • UI component names ("Filter Panel") — LLM rules handle them.

    Returns a new list of heading dicts (same shape: {level, text}).
    """
    import re as _re

    if not heading_hierarchy:
        return []

    _label_re = _re.compile(
        r"^(module\s*(name|no\.?|number|title)|section\s+title)\s*[:—\-]",
        _re.IGNORECASE,
    )

    # Determine the three shallowest levels present so L3 masters/steps are included.
    all_levels = sorted({
        h.get("level", 99)
        for h in heading_hierarchy
        if (h.get("text") or "").strip()
    })
    keep_levels: set[int] = set(all_levels[:3])

    seen: set[str] = set()
    cleaned: list[dict] = []

    for h in heading_hierarchy:
        level = h.get("level", 99)
        text  = (h.get("text") or "").strip()

        if not text:
            continue
        if level not in keep_levels:
            continue
        if len(text) > 150:
            continue
        if ord(text[0]) >= 0x2600:
            continue
        if _label_re.match(text):
            continue
        if text in seen:
            continue

        seen.add(text)
        cleaned.append({"level": level, "text": text})

    logger.info(
        "_pre_clean_headings: %d of %d heading(s) kept after pre-clean "
        "(levels kept: %s).",
        len(cleaned), len(heading_hierarchy), sorted(keep_levels),
    )
    return cleaned


def _heading_to_module_name(heading: str) -> str:
    """
    Derive a clean 2-6 word module name from a raw heading string when the
    LLM does not provide one.  Strips leading number prefixes and parenthetical
    suffixes like "(Final Document)", "(FINAL – WITH BATCH LAYER)".

    Examples:
      "8. Material Issue With Job"                 → "Material Issue With Job"
      "Step 1 – How Purchase Order is Created"     → "How Purchase Order is Created"
      "Material Consumption (Against Job) – Final" → "Material Consumption"
    """
    import re as _re

    name = heading.strip()
    name = _re.sub(r"^\d+\.\s*", "", name)
    name = _re.sub(r"^(Step|Phase|Stage)\s+\d+\s*[–\-]\s*", "", name, flags=_re.IGNORECASE)
    name = _re.sub(
        r"\s*[\(–\-].*?(final|document|updated|complete|version)[^\)]*\)?$",
        "", name, flags=_re.IGNORECASE,
    ).strip()
    name = name.rstrip("–-— ").strip()
    return name or heading[:50]


def _select_module_candidates(cleaned_headings: list[dict]) -> list[dict]:
    """
    Reduce pre-cleaned headings to structural module candidates before the LLM call.

    Real modules are "container" headings — they own multiple sub-sections below
    them.  Leaf sections (Validation Rules, Business Rules, Save Logic, etc.) have
    zero sub-headings and must never reach the LLM.

    Algorithm (two passes):
      Pass 1 — Level selection:
        Walk levels from shallowest to deepest.
        Skip singleton levels (1 heading = document title).
        Return the first level whose heading count is in [2, MAX_MODULE_COUNT].
        This handles the common case: the shallowest non-singleton level is
        exactly the module level (e.g. 5 L1 headings for 5 top-level modules).

      Pass 2 — Sub-heading count filter (only when Pass 1 level has > MAX_MODULE_COUNT):
        Among headings at the overcrowded level, keep only those with >= MIN_CHILDREN
        sub-headings immediately below them.  Leaf / near-leaf sections are excluded.

      Fallback: return all cleaned headings so the pipeline can still proceed.

    Typical result: 3–20 candidates instead of 100–200, making LLM classification
    accurate and fast.
    """
    import collections as _col

    MAX_MODULE_COUNT = 25
    MIN_CHILDREN     = 4

    if not cleaned_headings:
        return cleaned_headings

    n = len(cleaned_headings)

    by_level: dict[int, list[dict]] = _col.defaultdict(list)
    for h in cleaned_headings:
        by_level[h["level"]].append(h)

    # Pre-compute each heading's index for O(1) position lookup
    pos_map: dict[int, int] = {id(h): i for i, h in enumerate(cleaned_headings)}

    def _child_count(h: dict) -> int:
        """Count sub-headings that follow h before the next sibling/parent heading."""
        start = pos_map[id(h)]
        level = h["level"]
        count = 0
        for j in range(start + 1, n):
            if cleaned_headings[j]["level"] <= level:
                break
            count += 1
        return count

    for level in sorted(by_level.keys()):
        headings_at_level = by_level[level]
        count = len(headings_at_level)

        if count <= 1:
            # Singleton = document title; skip to the next (deeper) level.
            continue

        if count <= MAX_MODULE_COUNT:
            # Perfect module count — use this level directly.
            logger.info(
                "_select_module_candidates: L%d — %d heading(s) selected.",
                level, count,
            )
            return headings_at_level

        # More than MAX_MODULE_COUNT headings at this level.
        # Filter to structural containers (>= MIN_CHILDREN sub-headings).
        filtered = [h for h in headings_at_level if _child_count(h) >= MIN_CHILDREN]

        if len(filtered) >= 2:
            logger.info(
                "_select_module_candidates: L%d — %d candidate(s) "
                "(filtered from %d, min %d children).",
                level, len(filtered), count, MIN_CHILDREN,
            )
            return filtered

        # Fewer than 2 containers at this level — try the next deeper level.

    logger.info(
        "_select_module_candidates: fallback — using all %d cleaned heading(s).",
        len(cleaned_headings),
    )
    return cleaned_headings


async def segmentation_node(state: ExtractionState) -> dict[str, Any]:
    """
    Identify top-level modules using structural pre-filtering + LLM classification.

    Strategy:
      1. Python pre-clean: remove structural noise (blank, too long, emoji,
         field-label headings). Top-3 heading levels kept.
      2. Structural candidate selection: from ~100-200 cleaned headings, keep
         only those that are structural containers — the shallowest heading level
         with 2-25 entries, or (when a level is overcrowded) only the headings
         at that level with >= 4 direct sub-headings.  Leaf sections like
         "Business Rules", "Validation Rules", "Save Logic" are dropped here
         without ever reaching the LLM.  Result: 3-25 candidates.
      3. LLM classification: receives 3-25 candidates and classifies each as
         MODULE or IGNORE.  Small input = accurate decisions.
      4. Python filter: keep only MODULE headings, enforce document order.
      5. Fallback: if no MODULE headings found, treat whole document as one module.
    """
    logger.info("segmentation_node: classifying headings via LLM.")
    prompt_data = _load_prompt("segmentation")

    # ── Step 1: Python pre-clean ──────────────────────────────────────────────
    heading_hierarchy: list[dict] = state.get("heading_hierarchy") or []
    cleaned_headings = _pre_clean_headings(heading_hierarchy)

    if not cleaned_headings:
        logger.warning(
            "segmentation_node: no headings after pre-clean; "
            "falling back to single-module."
        )
        return {
            "modules": [{
                "name": "Application",
                "heading": "",
                "level": 1,
                "description": "Full document",
            }],
            "all_usage": [],
        }

    # ── Step 1b: Structural candidate selection ───────────────────────────────
    # Reduces 100-200 cleaned headings to 3-25 structural module candidates.
    # Only headings that "own" multiple sub-sections are module candidates;
    # leaf sections (Business Rules, Validation Rules, Save Logic, …) are dropped.
    # The position_index is built from the full cleaned list so document order
    # is preserved correctly even though the LLM receives only the candidates.
    candidates = _select_module_candidates(cleaned_headings)

    # ── Step 2: Build heading list for LLM ────────────────────────────────────
    position_index: dict[str, int] = {}
    for pos, h in enumerate(cleaned_headings):     # full list for accurate ordering
        text = h["text"]
        if text not in position_index:
            position_index[text] = pos

    heading_lines: list[str] = [
        f"[L{h['level']}] {h['text']}" for h in candidates
    ]
    heading_list_text = "\n".join(heading_lines)
    heading_count = len(candidates)

    user_prompt = _fmt(
        prompt_data["user_template"],
        heading_list=heading_list_text,
        heading_count=str(heading_count),
    )

    logger.info(
        "segmentation_node: classifying %d candidate(s) (from %d cleaned) with LLM.",
        heading_count, len(cleaned_headings),
    )

    # ── Step 3: LLM per-heading classification ────────────────────────────────
    # CLASSIFICATION_SCHEMA — LLM returns [{heading, type, module_name, description}]
    # for every input heading.  Python keeps only type=="MODULE".
    result, usages = await call_llm_with_schema(
        system_prompt=prompt_data["system"],
        user_prompt=user_prompt,
        schema=CLASSIFICATION_SCHEMA,
        schema_name="segmentation_classify",
    )

    classifications: list[dict] = result.get("classifications", [])

    # ── Step 4: Filter MODULE headings, enrich, enforce document order ─────────
    level_by_heading: dict[str, int] = {h["text"]: h["level"] for h in cleaned_headings}
    seen_headings: set[str] = set()
    enriched: list[dict[str, Any]] = []

    for item in classifications:
        if item.get("type") != "MODULE":
            continue

        heading = (item.get("heading") or "").strip()
        if not heading or heading in seen_headings:
            continue
        seen_headings.add(heading)

        # Use LLM-provided name; fall back to heuristic if blank or too long
        name = (item.get("module_name") or "").strip()
        if not name or len(name.split()) > 8:
            name = _heading_to_module_name(heading)

        desc = (item.get("description") or "").strip() or f"Requirements for {name}"
        level = level_by_heading.get(heading, 2)

        # Unrecognised headings (not in cleaned list) go to end
        doc_pos = position_index.get(heading, 10_000)

        enriched.append({
            "name":        name,
            "heading":     heading,
            "level":       level,
            "description": desc,
            "_doc_pos":    doc_pos,
        })

    # Sort by original document position (critical for correct text slicing)
    enriched.sort(key=lambda x: x["_doc_pos"])

    modules: list[dict[str, Any]] = [
        {k: v for k, v in m.items() if k != "_doc_pos"}
        for m in enriched
    ]

    logger.info(
        "segmentation_node: LLM classified %d candidate(s) → %d MODULE(s).",
        heading_count, len(modules),
    )

    # ── Step 5: Fallback ──────────────────────────────────────────────────────
    if not modules:
        logger.warning(
            "segmentation_node: no MODULE headings found; falling back to single module."
        )
        modules = [{
            "name": "Application",
            "heading": "",
            "level": 1,
            "description": "Full document",
        }]

    logger.info(
        "segmentation_node: final module list (%d): %s",
        len(modules), [m["name"] for m in modules],
    )
    return {"modules": modules, "all_usage": usages}


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
            "index":       idx,
            "module_name": module_meta["name"],
            "module_text": module_text,
            "mode":        mode,
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
        f"— extract only requirements visible in this part.\n\n{chunk}"
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


def _get_module_semaphore() -> asyncio.Semaphore:
    """
    Return (lazily creating) the module-level concurrency semaphore.

    Always called from within a running event loop (inside a coroutine),
    so asyncio.Semaphore() is always bound to the correct loop.
    """
    global _MODULE_SEMAPHORE
    if _MODULE_SEMAPHORE is None:
        _MODULE_SEMAPHORE = asyncio.Semaphore(MODULE_BATCH_SIZE)
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
    module_name = slice_input["module_name"]
    module_text = slice_input["module_text"]
    mode        = slice_input["mode"]

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
        chunks = _split_module_into_chunks(module_text, token_budget, module_name)
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
        "module_name": module_name,
        "extraction":  extraction_result,
        "summary":     summary_result,
        "usage":       all_usages,
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


# ── Phase 2: Finalize (pure-Python collect + graph builder LLM) ──────────────

def _python_merge_results(
    results: list[ModuleResult],
    modules: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    """
    Pure-Python collect: assemble per-module extractions in segmentation order.
    No LLM call — instant. Mirrors Phase 2 of user_story_parser/llm_service.py.
    """
    order_map: dict[str, int] = {m["name"]: idx for idx, m in enumerate(modules)}
    sorted_results = sorted(
        results, key=lambda r: order_map.get(r["module_name"], 999)
    )

    module_list = [
        {
            "name":  res["module_name"],
            "order": idx + 1,
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

    # ── Pure-Python merge (instant) ───────────────────────────────────────────
    extraction = _python_merge_results(state["results"], state["modules"], state["mode"])

    # ── Graph builder LLM call (uses summaries only — small context) ──────────
    prompt_data   = _load_prompt("graph_builder")
    all_summaries = [r["summary"] for r in state["results"]]

    # Build the ordered list of valid module IDs (snake_case) from module names.
    # These are passed explicitly to the LLM so it cannot invent phantom nodes.
    def _to_module_id(name: str) -> str:
        return name.lower().replace(" ", "_").replace("-", "_")

    module_names   = [r["module_name"] for r in state["results"]]
    valid_ids      = [_to_module_id(name) for name in module_names]
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
    filtered_nodes = [n for n in graph.get("nodes", []) if n.get("id") in valid_id_set]

    # Ensure every extracted module has a node (fill gaps if LLM omitted any)
    existing_ids = {n["id"] for n in filtered_nodes}
    for mid, mname in zip(valid_ids, module_names):
        if mid not in existing_ids:
            filtered_nodes.append({"id": mid, "label": mname, "type": "feature", "description": None, "external_dependencies": []})

    # Keep only edges where both endpoints are valid extracted module IDs
    filtered_edges = [
        e for e in graph.get("edges", [])
        if e.get("from") in valid_id_set and e.get("to") in valid_id_set
    ]

    # Recompute entry_points from filtered graph
    inbound_ids = {
        e["to"] for e in filtered_edges
        if e.get("relation") in ("depends_on", "calls")
    }
    entry_points = [n["id"] for n in filtered_nodes if n["id"] not in inbound_ids]

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
    return {"extraction": extraction, "graph": graph_result["graph"], "all_usage": graph_usages}
