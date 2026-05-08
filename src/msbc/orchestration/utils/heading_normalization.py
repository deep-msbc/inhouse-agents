"""
heading_normalization.py - Shared heading cleanup helpers.

Used by the requirement extractor before section-tree construction so the
classifier receives cleaner structural signals without losing meaningful
nested headings.
"""

from __future__ import annotations

import re
from typing import Any


_FIELD_LABEL_RE = re.compile(
    r"^(module\s*(name|no\.?|number|title)|section\s+title)\s*[:\-]",
    re.IGNORECASE,
)


def normalize_heading_hierarchy(
    heading_hierarchy: list[dict[str, Any]],
    *,
    preserve_deep_levels: bool = True,
    max_distinct_levels: int = 3,
    max_heading_chars: int = 180,
) -> list[dict[str, Any]]:
    """
    Normalize raw heading metadata before section-tree construction.

    Goals:
      - remove obvious extractor noise
      - preserve repeated headings that appear under different modules
      - preserve deep numeric heading structure for the Phase 1 classifier

    `preserve_deep_levels=False` keeps only the shallowest N distinct levels and
    exists so the legacy segmentation helper can continue to behave similarly to
    its old implementation.
    """
    if not heading_hierarchy:
        return []

    keep_levels: set[int] | None = None
    if not preserve_deep_levels:
        all_levels = sorted({
            _coerce_level(h.get("level"))
            for h in heading_hierarchy
            if (h.get("text") or "").strip()
        })
        keep_levels = set(all_levels[:max_distinct_levels])

    cleaned: list[dict[str, Any]] = []
    previous_key: tuple[int, str] | None = None

    for heading in heading_hierarchy:
        raw_text = (heading.get("text") or "").strip()
        if not raw_text:
            continue

        level = _coerce_level(heading.get("level"))
        if keep_levels is not None and level not in keep_levels:
            continue

        text = re.sub(r"\s+", " ", raw_text).strip()
        if not text:
            continue
        if len(text) > max_heading_chars:
            continue
        if _looks_decorative(text):
            continue
        if _FIELD_LABEL_RE.match(text):
            continue

        current_key = (level, text)
        if previous_key == current_key:
            continue

        cleaned.append({"level": level, "text": text})
        previous_key = current_key

    return cleaned


def _coerce_level(value: Any) -> int:
    try:
        level = int(value)
    except Exception:
        level = 1
    return min(max(level, 1), 6)


def _looks_decorative(text: str) -> bool:
    first = text[0]
    if first.isalnum():
        return False
    return ord(first) >= 0x2600
