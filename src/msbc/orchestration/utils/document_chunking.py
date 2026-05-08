"""
document_chunking.py — Coarse document chunker for the requirement extractor.

Replaces build_section_tree() / section_classifier_node batch logic.
Produces 3–10 large chunks per document instead of 200+ per-heading sections.

Chunking strategy (priority order — stops at first match):
  1. Numbered top-level sections ("1.", "2.", "3." …) → chunk per numbered top-level.
  2. Reliable major headings (level 1 or 2, ≥3 occurrences) → chunk per major heading.
  3. No reliable structure → sliding token window (max 2000 tokens, 200 overlap).

The heading_normalization utility is reused to clean headings before inspection.
"""

from __future__ import annotations

import re
import logging
from typing import Any

from src.msbc.llm.clients.openai_client import count_tokens
from src.msbc.orchestration.utils.heading_normalization import normalize_heading_hierarchy

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_NUMBERED_TOP_LEVEL_RE = re.compile(r"^\s*(\d+)\.\s+\S")  # "1. Foo", "2. Bar"
_FIELD_LABEL_RE = re.compile(
    r"^(module\s*(name|no\.?|number|title)|section\s+title)\s*[:\-]",
    re.IGNORECASE,
)
_TOKEN_WINDOW = 2000
_TOKEN_OVERLAP = 200
_MIN_CHUNKS = 3
_MAX_CHUNKS = 30


# ── Public entry point ────────────────────────────────────────────────────────

def build_document_chunks(
    document_text: str,
    heading_hierarchy: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Split a document into coarse business-area chunks.

    Returns a list of DocumentChunk-compatible dicts with fields:
        chunk_id, title_hint, text, start_char, end_char,
        local_headings, token_count, chunk_strategy
    """
    if not document_text:
        return []

    cleaned_headings = normalize_heading_hierarchy(heading_hierarchy)
    logger.info(
        "document_chunking: %d raw headings → %d cleaned headings.",
        len(heading_hierarchy), len(cleaned_headings),
    )

    # Strategy 1: numbered top-level sections
    chunks = _chunk_by_numbered_sections(document_text, cleaned_headings)
    if chunks and _MIN_CHUNKS <= len(chunks) <= _MAX_CHUNKS:
        logger.info("document_chunking: strategy=numbered_sections → %d chunks.", len(chunks))
        _tag_strategy(chunks, "numbered_sections")
        return chunks
    if chunks and len(chunks) > _MAX_CHUNKS:
        # Too many numbered sections — fall through to major-heading strategy
        logger.info(
            "document_chunking: numbered strategy gave %d chunks (> %d), trying major headings.",
            len(chunks), _MAX_CHUNKS,
        )
    elif chunks and len(chunks) < _MIN_CHUNKS:
        logger.info(
            "document_chunking: numbered strategy gave %d chunks (< %d), trying major headings.",
            len(chunks), _MIN_CHUNKS,
        )

    # Strategy 2: reliable major headings
    chunks = _chunk_by_major_headings(document_text, cleaned_headings)
    if chunks and _MIN_CHUNKS <= len(chunks) <= _MAX_CHUNKS:
        logger.info("document_chunking: strategy=major_headings → %d chunks.", len(chunks))
        _tag_strategy(chunks, "major_headings")
        return chunks

    # Strategy 3: token window fallback
    chunks = _chunk_by_token_window(document_text)
    logger.info("document_chunking: strategy=token_window → %d chunks.", len(chunks))
    _tag_strategy(chunks, "token_window")
    return chunks


def _tag_strategy(chunks: list[dict[str, Any]], strategy: str) -> None:
    """Tag every chunk in-place with the strategy that produced it."""
    for c in chunks:
        c["chunk_strategy"] = strategy


# ── Strategy 1: numbered top-level sections ───────────────────────────────────

def _chunk_by_numbered_sections(
    document_text: str,
    cleaned_headings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Find top-level numbered headings ("1. Foo", "2. Bar") in the document text
    and split at each one. Returns [] if fewer than 2 numbered headings found.
    """
    # Collect headings whose text starts with a top-level number ("1. …")
    numbered: list[dict[str, Any]] = [
        h for h in cleaned_headings
        if _NUMBERED_TOP_LEVEL_RE.match(h.get("text", ""))
        and _extract_top_number(h["text"]) is not None
    ]

    if len(numbered) < 2:
        return []

    # Locate each heading's character offset in the document text
    anchors: list[tuple[int, str]] = []  # (start_char, heading_text)
    search_from = 0
    for h in numbered:
        text = h["text"]
        idx = _find_heading_in_text(document_text, text, search_from)
        if idx == -1:
            continue
        anchors.append((idx, text))
        search_from = idx + 1

    if len(anchors) < 2:
        return []

    return _anchors_to_chunks(document_text, anchors, cleaned_headings)


def _extract_top_number(heading_text: str) -> int | None:
    m = _NUMBERED_TOP_LEVEL_RE.match(heading_text)
    if m:
        return int(m.group(1))
    return None


# ── Strategy 2: reliable major headings ──────────────────────────────────────

def _chunk_by_major_headings(
    document_text: str,
    cleaned_headings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Use level-1 and level-2 headings that appear at least 3 times as split points.
    Returns [] if no reliable major headings are found.
    """
    # Count occurrences of each level
    level_counts: dict[int, int] = {}
    for h in cleaned_headings:
        lvl = h.get("level", 1)
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    # Pick the shallowest reliable level (≥3 occurrences, level 1 or 2)
    reliable_levels = [
        lvl for lvl in (1, 2)
        if level_counts.get(lvl, 0) >= 3
    ]
    if not reliable_levels:
        return []

    split_level = reliable_levels[0]
    major_headings = [h for h in cleaned_headings if h.get("level") == split_level]

    anchors: list[tuple[int, str]] = []
    search_from = 0
    for h in major_headings:
        idx = _find_heading_in_text(document_text, h["text"], search_from)
        if idx == -1:
            continue
        anchors.append((idx, h["text"]))
        search_from = idx + 1

    if len(anchors) < 2:
        return []

    return _anchors_to_chunks(document_text, anchors, cleaned_headings)


# ── Strategy 3: token window ──────────────────────────────────────────────────

def _chunk_by_token_window(document_text: str) -> list[dict[str, Any]]:
    """
    Slide a fixed token window over the document text.
    Splits at sentence/paragraph boundaries where possible.
    """
    words = document_text.split()
    if not words:
        return []

    # Approximate chars-per-token ratio for splitting
    total_chars = len(document_text)
    total_tokens = count_tokens(document_text)
    chars_per_token = total_chars / max(total_tokens, 1)

    window_chars = int(_TOKEN_WINDOW * chars_per_token)
    overlap_chars = int(_TOKEN_OVERLAP * chars_per_token)

    chunks: list[dict[str, Any]] = []
    start = 0
    chunk_idx = 0

    while start < total_chars:
        end = min(start + window_chars, total_chars)

        # Try to snap to a paragraph or sentence boundary
        if end < total_chars:
            snap = _find_break_before(document_text, end)
            if snap > start + overlap_chars:
                end = snap

        chunk_text = document_text[start:end]
        chunk_id = f"chunk_{chunk_idx + 1:03d}"
        local_headings = _extract_headings_from_text(chunk_text)

        chunks.append({
            "chunk_id": chunk_id,
            "title_hint": local_headings[0] if local_headings else None,
            "text": chunk_text,
            "start_char": start,
            "end_char": end,
            "local_headings": local_headings,
            "token_count": count_tokens(chunk_text),
        })
        chunk_idx += 1

        if end >= total_chars:
            break
        start = end - overlap_chars

    return chunks


# ── Shared helpers ────────────────────────────────────────────────────────────

def _anchors_to_chunks(
    document_text: str,
    anchors: list[tuple[int, str]],
    all_cleaned_headings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Given sorted (start_char, title) anchors, slice the document into chunks.
    Each chunk runs from its anchor to the next anchor (or end of document).
    Collects sub-headings that appear within the chunk range.
    """
    # Add a sentinel at the end
    anchors_sorted = sorted(anchors, key=lambda x: x[0])
    total_len = len(document_text)

    # Build a lookup of all heading positions for local_headings collection
    heading_positions: list[tuple[int, str]] = []
    search_from = 0
    for h in all_cleaned_headings:
        idx = _find_heading_in_text(document_text, h["text"], search_from)
        if idx != -1:
            heading_positions.append((idx, h["text"]))
            search_from = idx

    chunks: list[dict[str, Any]] = []
    for i, (start_char, title) in enumerate(anchors_sorted):
        end_char = anchors_sorted[i + 1][0] if i + 1 < len(anchors_sorted) else total_len
        chunk_text = document_text[start_char:end_char]
        chunk_id = f"chunk_{i + 1:03d}"

        # Collect sub-headings within this range (excluding the title itself)
        local_headings = [
            htxt for hpos, htxt in heading_positions
            if start_char < hpos < end_char and htxt != title
        ]

        chunks.append({
            "chunk_id": chunk_id,
            "title_hint": title,
            "text": chunk_text,
            "start_char": start_char,
            "end_char": end_char,
            "local_headings": local_headings,
            "token_count": count_tokens(chunk_text),
        })

    return chunks


def _find_heading_in_text(document_text: str, heading_text: str, start: int = 0) -> int:
    """
    Search for a heading string in document_text starting from `start`.
    Uses a flexible match: strips leading/trailing whitespace and looks for
    the heading on its own line (or at least preceded by a newline or start).
    Returns -1 if not found.
    """
    # Escape special regex characters in the heading text
    escaped = re.escape(heading_text.strip())
    # Allow optional leading whitespace, numbering already included in the text
    pattern = re.compile(r"(?:^|\n)[^\S\n]*" + escaped, re.IGNORECASE)
    m = pattern.search(document_text, start)
    if m:
        return m.start()
    # Fallback: plain substring search
    idx = document_text.find(heading_text.strip(), start)
    return idx


def _find_break_before(text: str, pos: int) -> int:
    """
    Find the best break point at or before `pos`: prefer double-newline,
    then single newline, then any whitespace.
    """
    # Look back up to 400 chars for a paragraph break
    search_region = text[max(0, pos - 400): pos]
    double_nl = search_region.rfind("\n\n")
    if double_nl != -1:
        return max(0, pos - 400) + double_nl + 2

    single_nl = search_region.rfind("\n")
    if single_nl != -1:
        return max(0, pos - 400) + single_nl + 1

    space = search_region.rfind(" ")
    if space != -1:
        return max(0, pos - 400) + space + 1

    return pos


def _extract_headings_from_text(chunk_text: str) -> list[str]:
    """
    Naively extract short lines that look like headings from raw chunk text.
    Used for local_headings in token-window chunks that have no pre-known headings.
    """
    headings: list[str] = []
    for line in chunk_text.splitlines():
        stripped = line.strip()
        # Skip lines with table/pipe noise, field labels, or that are just fragments
        if "|" in stripped or stripped.startswith(("Case ", "Pending", "N/A")):
            continue
        if _FIELD_LABEL_RE.match(stripped):
            continue
        if 3 <= len(stripped) <= 120 and not stripped.endswith((".", ",", ";")):
            words = stripped.split()
            if len(words) <= 8 and (
                _NUMBERED_TOP_LEVEL_RE.match(stripped)
                or all(w[0].isupper() for w in words if w and w[0].isalpha())
            ):
                headings.append(stripped)
    return headings[:20]  # cap to avoid noise
