"""
agents/code_generator/spec_normalizer.py
─────────────────────────────────────────
Pure-Python normalizer that translates planner vocabulary into values that
the toolkit / DashboardConfig / JSONFormSchema actually accept.

Called in the `generate_file` node BEFORE the prompt is assembled so the LLM
never sees invalid type names or forbidden key names in the SCREEN SPECIFICATION
section.

Design rules:
  • No LLM calls. No side effects. Pure function — `normalize_screen()` always
    returns a new deep-copied dict; the original is never mutated.
  • Handles both raw LLM output dicts AND model_dump() output from Pydantic
    planner models (ScreenPlan → dict).
  • All look-ups are case-insensitive on the incoming value so minor casing
    differences from the LLM ("Dropdown", "DROPDOWN") are still caught.
  • Gracefully skips non-dict/non-list entries rather than raising.
"""

from __future__ import annotations

import copy
from typing import Any


# ─── Form field type map ──────────────────────────────────────────────────────
# Source of truth: generate_file.yaml § STRICT TYPE NAME ENFORCEMENT
# Valid JSONFormSchema field types:
#   text | email | number | password | textarea | tel |
#   select | radio | checkbox | list | fileUpload | map | date | date-range
_FORM_FIELD_TYPE_MAP: dict[str, str] = {
    # Already-valid pass-throughs (normalise casing only)
    "text":        "text",
    "email":       "email",
    "number":      "number",
    "password":    "password",
    "textarea":    "textarea",
    "tel":         "tel",
    "select":      "select",
    "radio":       "radio",
    "checkbox":    "checkbox",
    "list":        "list",
    "fileupload":  "fileUpload",   # keep camelCase canonical form
    "file_upload": "fileUpload",
    "map":         "map",
    "date":        "date",
    "date-range":  "date-range",
    # Planner aliases → correct values
    "dropdown":    "select",
    "multi_select": "select",
    "multiselect": "select",
    "toggle":      "checkbox",
    "bool":        "checkbox",
    "boolean":     "checkbox",
    "phone":       "tel",
    "integer":     "number",
    "int":         "number",
    "float":       "number",
    "decimal":     "number",
    "date_range":  "date-range",
    "daterange":   "date-range",
    # Generic string aliases
    "string":      "text",
    "str":         "text",
    "name":        "text",
    "label":       "text",
    "input":       "text",
}

# ─── Dashboard filter type map ────────────────────────────────────────────────
# Valid DashboardConfig filter types:
#   date-range | date | select | text | int | bool | phone
_FILTER_TYPE_MAP: dict[str, str] = {
    # Already-valid pass-throughs
    "date-range":  "date-range",
    "date":        "date",
    "select":      "select",
    "text":        "text",
    "int":         "int",
    "bool":        "bool",
    "phone":       "phone",
    # Planner aliases → correct values
    "dropdown":    "select",
    "multi_select": "select",
    "multiselect": "select",
    "date_range":  "date-range",
    "daterange":   "date-range",
    "boolean":     "bool",
    "toggle":      "bool",
    "integer":     "int",
    "float":       "int",
    "number":      "int",
    "string":      "text",
    "str":         "text",
    "input":       "text",
    "tel":         "phone",
}

# ─── Dashboard column key map ─────────────────────────────────────────────────
# DashboardConfig.columnDefs expects: field | headerName (plus sortable, editable, …)
# The planner's ColumnDef schema emits: name | label (those are its canonical keys).
# Any LLM that further uses key/title/id must also be corrected.
#
# Shape: { forbidden_planner_key → correct_dashboardconfig_key }
_COLUMN_KEY_MAP: dict[str, str] = {
    "name":  "field",
    "key":   "field",
    "id":    "field",
    "label": "headerName",
    "title": "headerName",
    "header": "headerName",
}

# ─── API method normalizer ────────────────────────────────────────────────────
# DashboardConfig.api.method and useApiRequest both require lowercase.
# The FrontendPlan ApiCall.method stores uppercase (GET | POST | PUT | DELETE).
_HTTP_METHOD_MAP: dict[str, str] = {
    "GET":    "get",
    "POST":   "post",
    "PUT":    "patch",   # DRF uses PATCH for partial update; map PUT → patch
    "PATCH":  "patch",
    "DELETE": "delete",
}


# ─── Private helpers ──────────────────────────────────────────────────────────

def _normalize_field_type(field: dict[str, Any]) -> None:
    """Normalize a single form FieldDef dict in place."""
    raw: str = field.get("type", "")
    if not isinstance(raw, str):
        return
    field["type"] = _FORM_FIELD_TYPE_MAP.get(raw.lower(), raw)


def _normalize_filter_type(filt: dict[str, Any]) -> None:
    """Normalize a single FilterDef dict in place."""
    raw: str = filt.get("type", "")
    if not isinstance(raw, str):
        return
    filt["type"] = _FILTER_TYPE_MAP.get(raw.lower(), raw)


def _normalize_column_keys(col: dict[str, Any]) -> None:
    """
    Rename forbidden planner keys to DashboardConfig-compatible keys in place.

    The planner's ColumnDef always emits `name` and `label`; any LLM output
    may additionally emit `key`, `title`, or `id`. All are mapped to `field`
    or `headerName` only if the correct key is not already present (avoids
    overwriting a valid `field` value with a wrong `name` value).
    """
    for forbidden, correct in _COLUMN_KEY_MAP.items():
        if forbidden in col and correct not in col:
            col[correct] = col.pop(forbidden)


def _normalize_api_method(method: str) -> str:
    """Return the lowercase DashboardConfig-compatible method string."""
    if not isinstance(method, str):
        return method
    return _HTTP_METHOD_MAP.get(method.upper(), method.lower())


def _normalize_api_calls(data_flow: dict[str, Any]) -> None:
    """Lowercase method on every api_call in data_flow in place."""
    for call in data_flow.get("api_calls", []):
        if isinstance(call, dict) and "method" in call:
            call["method"] = _normalize_api_method(call["method"])


def _normalize_component(component: dict[str, Any]) -> None:
    """Apply all normalizations to a single ComponentPlan dict in place."""
    if not isinstance(component, dict):
        return

    for field in component.get("fields", []):
        if isinstance(field, dict):
            _normalize_field_type(field)

    for filt in component.get("filters", []):
        if isinstance(filt, dict):
            _normalize_filter_type(filt)

    for col in component.get("columns", []):
        if isinstance(col, dict):
            _normalize_column_keys(col)

    # Normalize method on any action that carries an inline api config
    for action in component.get("actions", []):
        if not isinstance(action, dict):
            continue
        api_obj = action.get("api")
        if isinstance(api_obj, dict) and "method" in api_obj:
            api_obj["method"] = _normalize_api_method(api_obj["method"])


# ─── Public API ───────────────────────────────────────────────────────────────

def normalize_screen(screen: dict[str, Any]) -> dict[str, Any]:
    """
    Return a deep-normalized copy of a planner ScreenPlan dict.

    Applied transformations (in order):
      1. components[*].fields[*].type   — planner alias → JSONFormSchema type
      2. components[*].filters[*].type  — planner alias → DashboardConfig filter type
      3. components[*].columns[*] keys  — { name, label, key, title, id } → { field, headerName }
      4. components[*].actions[*].api.method — uppercase → lowercase
      5. data_flow.api_calls[*].method  — uppercase → lowercase

    Parameters
    ----------
    screen:
        Raw screen dict — either the direct LLM output or a model_dump() of
        ScreenPlan. Must not be None.

    Returns
    -------
    dict
        New deep-copied dict with all normalizations applied. The original
        is never mutated.
    """
    if not isinstance(screen, dict):
        return screen  # type: ignore[return-value]

    screen = copy.deepcopy(screen)

    for component in screen.get("components", []):
        _normalize_component(component)

    data_flow = screen.get("data_flow", {})
    if isinstance(data_flow, dict):
        _normalize_api_calls(data_flow)

    return screen
