"""
toon_serializer.py  (Frontend Planner Agent)
─────────────────────────────────────────────
Converts the ``extracted_requirements`` JSON (as stored in the
``requirement_extractions`` table) into a compact TOON string for the
Frontend Planner LLM.

TOON — Token-Oriented Object Notation (spec v3.0)
Line-oriented, indentation-based encoding.  Human-readable and lossless.

Public API
──────────
toon_frontend_module(module_dict, *, dep_priority, shared_enums, shared_rules)
    Convert one frontend module dict (from the unified extraction) into TOON.

toon_single_module(module_dict, *, dep_priority, shared_enums, shared_rules)
    Alias kept for internal use by the planner node.

The serializer handles all three extraction modes:
  "frontend" → module.extraction  is FrontendExtraction shape
  "both"     → module.extraction.frontend  is BothFrontendSection shape
It normalises both shapes into the same intermediate dict before encoding.
"""

from __future__ import annotations

import math
import re
from typing import Any

# ─── TOON primitives ──────────────────────────────────────────────────────────

_NEEDS_QUOTE_RE = re.compile(r'[\[\]{}\:\,\\\"\n\r\t]')
_NUMERIC_RE = re.compile(r'^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$', re.IGNORECASE)
_LEADING_ZERO_RE = re.compile(r'^0\d+$')
_RESERVED = {"true", "false", "null"}


def _needs_quotes(value: str, delimiter: str = ",") -> bool:
    if value == "" or value != value.strip():
        return True
    if value in _RESERVED:
        return True
    if _NUMERIC_RE.match(value) or _LEADING_ZERO_RE.match(value):
        return True
    if _NEEDS_QUOTE_RE.search(value):
        return True
    if delimiter in value:
        return True
    if value.startswith("-"):
        return True
    return False


def _escape(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _quote(value: str, delimiter: str = ",") -> str:
    if _needs_quotes(value, delimiter):
        return f'"{_escape(value)}"'
    return value


def _format_number(n: int | float) -> str:
    if isinstance(n, float):
        if math.isnan(n) or math.isinf(n):
            return "null"
        if n == 0.0:
            return "0"
        formatted = f"{n:.17g}"
        if "e" in formatted or "E" in formatted:
            formatted = f"{n:.20f}".rstrip("0").rstrip(".")
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted
    return str(n)


def _quote_key(key: str) -> str:
    if re.match(r'^[A-Za-z_][A-Za-z0-9_.]*$', key):
        return key
    return f'"{_escape(key)}"'


_INDENT = "  "


def _encode_primitive(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return _format_number(val)
    return _quote(str(val))


def _is_all_primitives(lst: list) -> bool:
    return all(isinstance(v, (str, int, float, bool, type(None))) for v in lst)


def _is_tabular(lst: list) -> bool:
    if not lst or not all(isinstance(v, dict) for v in lst):
        return False
    keys = set(lst[0].keys())
    for obj in lst[1:]:
        if set(obj.keys()) != keys:
            return False
    for obj in lst:
        for v in obj.values():
            if not isinstance(v, (str, int, float, bool, type(None))):
                return False
    return True


def _encode_value(val: Any, depth: int) -> list[str]:
    pad = _INDENT * depth
    if val is None:
        return ["null"]
    if isinstance(val, bool):
        return ["true" if val else "false"]
    if isinstance(val, (int, float)):
        return [_format_number(val)]
    if isinstance(val, str):
        return [_quote(val)]
    if isinstance(val, list):
        return _encode_array(val, depth)
    if isinstance(val, dict):
        return _encode_object_fields(val, depth)
    return [_quote(str(val))]


def _encode_array(lst: list, depth: int) -> list[str]:
    if not lst:
        return ["[0]:"]
    if _is_all_primitives(lst):
        parts = [_encode_primitive(v) for v in lst]
        return [f"[{len(lst)}]: {','.join(parts)}"]
    if _is_tabular(lst):
        fields = list(lst[0].keys())
        header = f"[{len(lst)}]{{{','.join(_quote_key(f) for f in fields)}}}:"
        lines = [header]
        row_pad = _INDENT * (depth + 1)
        for obj in lst:
            row = ",".join(_encode_primitive(obj.get(f)) for f in fields)
            lines.append(f"{row_pad}{row}")
        return lines
    # Expanded
    lines: list[str] = [f"[{len(lst)}]:"]
    item_pad = _INDENT * (depth + 1)
    for item in lst:
        if isinstance(item, dict):
            lines.extend(_encode_list_item_object(item, depth + 1))
        else:
            lines.append(f"{item_pad}- {_encode_primitive(item)}")
    return lines


def _encode_list_item_object(obj: dict, depth: int) -> list[str]:
    obj_pad = _INDENT * depth
    inner_pad = _INDENT * (depth + 1)
    lines: list[str] = []
    keys = list(obj.keys())
    if not keys:
        lines.append(f"{obj_pad}-")
        return lines

    first_key = keys[0]
    first_val = obj[first_key]
    if isinstance(first_val, (str, int, float, bool, type(None))):
        lines.append(f"{obj_pad}- {_quote_key(first_key)}: {_encode_primitive(first_val)}")
    elif isinstance(first_val, list) and _is_all_primitives(first_val):
        parts = [_encode_primitive(v) for v in first_val]
        lines.append(f"{obj_pad}- {_quote_key(first_key)}[{len(first_val)}]: {','.join(parts)}")
    else:
        arr_lines = _encode_value(first_val, depth + 1)
        lines.append(f"{obj_pad}- {_quote_key(first_key)}{arr_lines[0]}")
        lines.extend(arr_lines[1:])

    for key in keys[1:]:
        val = obj[key]
        lines.extend(_encode_kv(key, val, depth + 1))

    return lines


def _encode_kv(key: str, val: Any, depth: int) -> list[str]:
    pad = _INDENT * depth
    qk = _quote_key(key)
    if val is None:
        return [f"{pad}{qk}: null"]
    if isinstance(val, bool):
        return [f"{pad}{qk}: {'true' if val else 'false'}"]
    if isinstance(val, (int, float)):
        return [f"{pad}{qk}: {_format_number(val)}"]
    if isinstance(val, str):
        return [f"{pad}{qk}: {_quote(val)}"]
    if isinstance(val, list):
        arr_lines = _encode_array(val, depth)
        return [f"{pad}{qk}{arr_lines[0]}"] + arr_lines[1:]
    if isinstance(val, dict):
        if not val:
            return [f"{pad}{qk}:"]
        lines = [f"{pad}{qk}:"]
        lines.extend(_encode_object_fields(val, depth + 1))
        return lines
    return [f"{pad}{qk}: {_quote(str(val))}"]


def _encode_object_fields(obj: dict, depth: int) -> list[str]:
    lines: list[str] = []
    for k, v in obj.items():
        lines.extend(_encode_kv(k, v, depth))
    return lines


def _to_toon(data: Any) -> str:
    """Encode a Python object to a TOON string."""
    if isinstance(data, dict):
        lines = _encode_object_fields(data, depth=0)
    elif isinstance(data, list):
        lines = _encode_array(data, depth=0)
    else:
        lines = _encode_value(data, depth=0)
    return "\n".join(lines)


# ─── Extraction shape normaliser ──────────────────────────────────────────────

def _normalise_frontend_module(module_dict: dict) -> dict:
    """
    Normalise a unified module dict into a consistent frontend shape.

    Handles three source shapes:
      1. mode='frontend' unified entry:
            { name, order, description, screens, enums, business_rules, workflows }
      2. mode='both' unified entry:
            { name, order, description, frontend: { screens, enums, business_rules, workflows }, backend: {...} }
      3. Raw FrontendModule (from per-module extraction envelope):
            { module: { name, screens, enums, business_rules, workflows } }

    Returns a flat dict:
      { name, description, order, screens, enums, business_rules, workflows }
    """
    # Shape 3: envelope with "module" key
    if "module" in module_dict and isinstance(module_dict["module"], dict):
        inner = module_dict["module"]
        return {
            "name":           inner.get("name", ""),
            "description":    inner.get("description", ""),
            "order":          module_dict.get("order", 1),
            "screens":        inner.get("screens", []),
            "enums":          inner.get("enums", []),
            "business_rules": inner.get("business_rules", []),
            "workflows":      inner.get("workflows", []),
        }

    # Shape 2: mode='both' — frontend section is nested
    if "frontend" in module_dict and isinstance(module_dict.get("frontend"), dict):
        fe = module_dict["frontend"]
        return {
            "name":           module_dict.get("name", ""),
            "description":    module_dict.get("description", ""),
            "order":          module_dict.get("order", 1),
            "screens":        fe.get("screens", []),
            "enums":          fe.get("enums", []),
            "business_rules": fe.get("business_rules", []),
            "workflows":      fe.get("workflows", []),
        }

    # Shape 1: already flat frontend module (mode='frontend')
    return {
        "name":           module_dict.get("name", ""),
        "description":    module_dict.get("description", ""),
        "order":          module_dict.get("order", 1),
        "screens":        module_dict.get("screens", []),
        "enums":          module_dict.get("enums", []),
        "business_rules": module_dict.get("business_rules", []),
        "workflows":      module_dict.get("workflows", []),
    }


# ─── Public API ───────────────────────────────────────────────────────────────

def toon_frontend_module(
    module_dict: dict,
    *,
    dep_priority: int = 1,
    shared_enums: dict | None = None,
    shared_rules: list[str] | None = None,
) -> str:
    """
    Convert one module entry from ``extracted_requirements`` into a TOON string
    suitable for the Frontend Planner LLM.

    Parameters
    ----------
    module_dict:
        One element from ``extracted_requirements.unified.modules`` (or the
        raw list in frontend/both extraction output).
    dep_priority:
        Priority assigned by the dependency graph (1 = build first).
        Injected so the LLM can respect build order when setting module priority.
    shared_enums:
        Global enums dict from ``extracted_requirements.unified.global_enums``.
        Merged into the module's enums list.
    shared_rules:
        Global business rules from ``extracted_requirements.unified.global_business_rules``.
        Appended to the module's business_rules list.

    Returns
    -------
    str
        TOON-encoded string for this module.
    """
    normalised = _normalise_frontend_module(module_dict)

    # Merge shared context
    merged_rules: list[str] = list(normalised["business_rules"])
    if shared_rules:
        for rule in shared_rules:
            if rule not in merged_rules:
                merged_rules.append(rule)

    merged_enums: list[dict] = list(normalised["enums"])
    if shared_enums:
        existing_names = {e.get("name") for e in merged_enums}
        for enum_name, values in shared_enums.items():
            if enum_name not in existing_names:
                merged_enums.append({"name": enum_name, "values": values})

    toon_dict = {
        "name":           normalised["name"],
        "description":    normalised["description"],
        "order":          normalised["order"],
        "dep_priority":   dep_priority,
        "screens":        normalised["screens"],
        "enums":          merged_enums,
        "business_rules": merged_rules,
        "workflows":      normalised["workflows"],
    }

    return _to_toon(toon_dict)


# Alias used by the planner node
toon_single_module = toon_frontend_module
