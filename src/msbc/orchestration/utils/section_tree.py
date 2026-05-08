"""
section_tree.py - Build a tree of DocumentSection objects from heading_hierarchy.

Called by section_classifier_node before any LLM call.
Pure Python - no LLM, no network I/O.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.msbc.orchestration.schemas.sections import DocumentSection

logger = logging.getLogger(__name__)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _find_heading_offset(
    document_text: str,
    heading: str,
    *,
    start_at: int = 0,
) -> int:
    """
    Locate *heading* in *document_text* while preferring forward-only matches.

    Matching passes:
      1. Exact substring from `start_at`
      2. Case-insensitive exact from `start_at`
      3. Flexible-whitespace regex from `start_at`
    """
    start_at = max(start_at, 0)

    idx = document_text.find(heading, start_at)
    if idx != -1:
        return idx

    idx = document_text.lower().find(heading.lower(), start_at)
    if idx != -1:
        return idx

    words = _normalize_whitespace(heading).split()
    if not words:
        return -1

    try:
        pattern = r"\s+".join(re.escape(word) for word in words)
        match = re.search(pattern, document_text[start_at:], re.IGNORECASE)
        if match:
            return start_at + match.start()
    except re.error:
        pass

    return -1


def build_section_tree(
    document_text: str,
    heading_hierarchy: list[dict[str, Any]],
) -> list[DocumentSection]:
    """
    Convert a flat heading_hierarchy list into a list of DocumentSection objects.

    Each section's text = document_text[start_char:end_char], where end_char is
    the start of the next located heading or the end of the document.
    """
    if not document_text or not heading_hierarchy:
        return []

    located: list[dict[str, Any]] = []
    search_start = 0

    for heading in heading_hierarchy:
        text = (heading.get("text") or "").strip()
        level = heading.get("level", 1)
        if not text:
            continue

        offset = _find_heading_offset(document_text, text, start_at=search_start)
        if offset == -1:
            fallback_offset = _find_heading_offset(document_text, text, start_at=0)
            if fallback_offset >= search_start:
                offset = fallback_offset

        if offset == -1:
            logger.debug(
                "build_section_tree: heading not found in document, skipping: %r",
                text[:80],
            )
            continue

        located.append({"level": level, "text": text, "offset": offset})
        search_start = max(search_start, offset + max(len(text), 1))

    if not located:
        logger.warning("build_section_tree: no headings could be located in document text.")
        return []

    located.sort(key=lambda item: (item["offset"], item["level"]))

    deduped: list[dict[str, Any]] = []
    seen_offsets: set[int] = set()
    for item in located:
        if item["offset"] in seen_offsets:
            continue
        seen_offsets.add(item["offset"])
        deduped.append(item)
    located = deduped

    for idx, item in enumerate(located):
        item["end_char"] = located[idx + 1]["offset"] if idx + 1 < len(located) else len(document_text)

    stack: list[tuple[int, str]] = []
    sections: list[DocumentSection] = []
    section_heading_by_id: dict[str, str] = {}

    for idx, item in enumerate(located):
        section_id = f"sec_{idx + 1:04d}"
        level = item["level"]

        while stack and stack[-1][0] >= level:
            stack.pop()

        parent_id = stack[-1][1] if stack else None
        heading_path = [section_heading_by_id[sid] for _, sid in stack if sid in section_heading_by_id]

        section = DocumentSection(
            section_id=section_id,
            heading=item["text"],
            level=level,
            parent_id=parent_id,
            heading_path=heading_path,
            start_char=item["offset"],
            end_char=item["end_char"],
            text=document_text[item["offset"]:item["end_char"]],
        )
        sections.append(section)
        section_heading_by_id[section_id] = section.heading
        stack.append((level, section_id))

    logger.info(
        "build_section_tree: built %d sections from %d heading(s) (doc length %d chars).",
        len(sections),
        len(heading_hierarchy),
        len(document_text),
    )
    return sections
