"""
canonicalization.py - Helpers for stabilizing canonical module grouping.

The key design rule is that only standalone BUSINESS_MODULE sections can seed
canonical modules. All other sections must attach to one of those seeds.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from src.msbc.orchestration.schemas.sections import SectionClassification

logger = logging.getLogger(__name__)


GENERIC_MODULE_KEYS: set[str] = {
    "purpose",
    "overview",
    "introduction",
    "summary",
    "core_concept",
    "most_important_logic",
    "one_line_definition",
    "recommended_one_line_definition",
    "final_insight",
    "ui_recommendation",
    "best_ui_recommendation",
    "recommended",
    "suggested",
    "suggested_additional_fields",
    "best_practice",
    "validation_rules",
    "business_rules",
    "workflow",
    "save_logic",
    "error_handling",
    "mobile_application_logic",
    "barcode_integration",
    "process_configuration",
    "configuration",
    "integration",
    "history",
    "dashboard",
    "listing_screen",
    "filters_section",
    "scan_data_grid",
    "main_screen_structure",
    "export_to_excel",
    "export_print",
    "print_output",
}

GENERIC_MODULE_SUFFIXES: tuple[str, ...] = (
    "_logic",
    "_rules",
    "_workflow",
    "_screen",
    "_grid",
    "_history",
    "_dashboard",
    "_integration",
    "_configuration",
    "_recommendation",
    "_print",
    "_export",
    "_input_section",
    "_listing_screen",
    "_summary_grid",
    "_history_grid",
    "_detail_screen",
)


def normalize_display_name(display_name: str) -> str:
    """
    Clean a display name before slugging or generic-name checks.
    """
    if not display_name:
        return ""

    name = display_name.strip()
    name = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", name)
    name = re.sub(r"\((?:final|draft|v\d+.*?)\)$", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def make_module_key(display_name: str) -> str:
    """
    Convert a display name to a stable snake_case slug.
    """
    name = normalize_display_name(display_name)
    if not name:
        return "module"

    key = name.lower()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return key or "module"


def is_generic_module_name(display_name: str) -> bool:
    """
    Return True when a name looks like a child section, not a real module.
    """
    key = make_module_key(display_name)
    if not key:
        return True
    if key in GENERIC_MODULE_KEYS:
        return True
    if any(key.endswith(suffix) for suffix in GENERIC_MODULE_SUFFIXES):
        return True
    if key.startswith(("add_new_", "edit_", "top_grid_", "final_", "best_", "recommended_")):
        return True
    return False


def build_seed_groups(
    classifications: list[SectionClassification],
) -> dict[str, list[SectionClassification]]:
    """
    Group standalone BUSINESS_MODULE classifications by canonical name.
    """
    groups: dict[str, list[SectionClassification]] = defaultdict(list)
    for classification in classifications:
        name = classification.canonical_module_name or classification.heading
        groups[make_module_key(name)].append(classification)

    logger.debug(
        "build_seed_groups: %d seed classification(s) -> %d group(s): %s",
        len(classifications),
        len(groups),
        list(groups.keys()),
    )
    return dict(groups)


def pick_display_name(classifications: list[SectionClassification]) -> str:
    """
    Choose the best display name for a seed group.
    """
    standalones = [c for c in classifications if c.is_standalone_module]
    candidates = standalones if standalones else classifications
    best = max(candidates, key=lambda c: c.confidence)
    name = normalize_display_name(best.canonical_module_name or best.heading)
    return name or "Unknown Module"


def find_nearest_module_ancestor(
    section_id: str,
    parent_by_section_id: dict[str, str | None],
    standalone_section_ids: set[str],
) -> str | None:
    """
    Walk upward through the section tree and return the nearest standalone module.
    """
    visited: set[str] = set()
    current = section_id
    while current and current not in visited:
        visited.add(current)
        parent_id = parent_by_section_id.get(current)
        if not parent_id:
            return None
        if parent_id in standalone_section_ids:
            return parent_id
        current = parent_id
    return None


def find_similar_module_keys(
    module_key: str,
    other_keys: list[str],
) -> list[str]:
    """
    Return module keys that look suspiciously similar to the target key.
    """
    similar: list[str] = []
    for other in other_keys:
        if other == module_key:
            continue
        if module_key in other or other in module_key:
            similar.append(other)
            continue

        module_tokens = set(module_key.split("_"))
        other_tokens = set(other.split("_"))
        overlap = module_tokens & other_tokens
        if overlap and len(overlap) >= min(len(module_tokens), len(other_tokens)) - 1:
            similar.append(other)

    return similar
