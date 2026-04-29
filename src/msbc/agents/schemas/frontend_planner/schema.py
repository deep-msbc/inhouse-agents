"""
JSON Schema (Draft 2020-12) for the Frontend Planner LLM output.

Shape — the LLM returns a JSON ARRAY, one element per module:
[
  {
    "module_name":      string,
    "description":      string,
    "priority":         integer,
    "similarity_query": string,
    "business_rules":   [string, ...],
    "screens": [
      {
        "screen_name":      string,
        "type":             "dashboard" | "form" | "detail" | "popup",
        "route":            string,
        "opens_as":         "page" | "modal" | "popup",
        "priority":         integer,
        "similarity_query": string,
        "components": [
          {
            "component_name":   string,
            "type":             string,
            "toolkit_mapping":  string,
            "similarity_query": string,
            "actions":    [...],
            "columns":    [...],
            "fields":     [...],
            "filters":    [...],
            "validations": [string, ...],
            "data_hook":  string
          }
        ],
        "user_interactions": [...],
        "data_flow":        { "state": [...], "api_calls": [...] }
      }
    ],
    "shared_components": [...],
    "file_structure": [
      {
        "path":             string,
        "type":             string,
        "description":      string,
        "belongs_to_screen": string,
        "uses_components":  [string, ...],
        "toolkit_imports":  { "@msbc/...": [string, ...] },
        "key_exports":      [string, ...]
      }
    ]
  }
]

Design intent:
  - additionalProperties: True on all objects so the LLM is never penalised for
    returning valid extra fields.
  - Only structural shape is enforced here; value-level checks (e.g. allowed
    field types, belongs_to_screen non-null) are applied by the Pydantic layer.
  - Used by call_llm_with_schema in openai_client.py for schema-validation retry.
"""

from __future__ import annotations

# ── Leaf schemas ──────────────────────────────────────────────────────────────

_ACTION_SCHEMA = {
    "type": "object",
    "required": ["text", "type", "behavior"],
    "additionalProperties": True,
    "properties": {
        "text":            {"type": "string", "minLength": 1},
        "type":            {"type": "string"},
        "behavior":        {"type": "string"},
        "opens_component": {"type": ["string", "null"]},
    },
}

_COLUMN_SCHEMA = {
    "type": "object",
    "required": ["name", "label", "type"],
    "additionalProperties": True,
    "properties": {
        "name":        {"type": "string"},
        "label":       {"type": "string"},
        "type":        {"type": "string"},
        "sortable":    {"type": ["boolean", "string"]},
        "editable":    {"type": ["boolean", "string"]},
        "format":      {"type": ["string", "null"]},
        # LLM may return a dict rule-object or boolean — coerced to string by normalizer
        "color_logic": {},
    },
}

_FIELD_SCHEMA = {
    "type": "object",
    "required": ["name", "label", "type"],
    "additionalProperties": True,
    "properties": {
        "name":          {"type": "string"},
        "label":         {"type": "string"},
        "type":          {"type": "string"},
        "required":      {"type": ["boolean", "string"]},
        # options items may be string or number (enum values) — coerced to str by normalizer
        "options":       {"type": "array", "items": {}},
        "validation":    {"type": "array", "items": {"type": "string"}},
        # LLM may return false (boolean) for these — coerced to null by normalizer
        "visible_when":  {},
        "required_when": {},
        "disabled_when": {},
        # LLM may return false/0/true — coerced to string by normalizer
        "default_value": {},
        "behavior":      {"type": ["string", "null"]},
    },
}

_FILTER_SCHEMA = {
    "type": "object",
    "required": ["name", "label", "type"],
    "additionalProperties": True,
    "properties": {
        "name":          {"type": "string"},
        "label":         {"type": "string"},
        "type":          {"type": "string"},
        "options":       {"type": "array", "items": {}},
        "default_value": {},
        "placeholder":   {"type": ["string", "null"]},
    },
}

_COMPONENT_SCHEMA = {
    "type": "object",
    "required": ["component_name", "type", "toolkit_mapping", "similarity_query"],
    "additionalProperties": True,
    "properties": {
        "component_name":   {"type": "string", "minLength": 1},
        "type":             {"type": "string", "minLength": 1},
        "toolkit_mapping":  {"type": "string", "minLength": 1},
        "similarity_query": {"type": "string", "minLength": 1},
        "actions":          {"type": "array", "items": _ACTION_SCHEMA},
        "columns":          {"type": "array", "items": _COLUMN_SCHEMA},
        "fields":           {"type": "array", "items": _FIELD_SCHEMA},
        "filters":          {"type": "array", "items": _FILTER_SCHEMA},
        "validations":      {"type": "array", "items": {"type": "string"}},
        "data_hook":        {"type": "string"},
    },
}

_USER_INTERACTION_SCHEMA = {
    "type": "object",
    "required": ["action", "flow"],
    "additionalProperties": True,
    "properties": {
        "action": {"type": "string"},
        "flow":   {"type": "array", "items": {"type": "string"}},
    },
}

_STATE_ITEM_SCHEMA = {
    "type": "object",
    "required": ["name", "type"],
    "additionalProperties": True,
    "properties": {
        "name": {"type": "string"},
        "type": {"type": "string"},
    },
}

_API_CALL_SCHEMA = {
    "type": "object",
    "required": ["name", "method"],
    "additionalProperties": True,
    "properties": {
        "name":     {"type": "string"},
        "method":   {"type": "string"},
        "endpoint": {"type": "string"},
        "hook":     {"type": "string"},
    },
}

_DATA_FLOW_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "state":     {"type": "array", "items": _STATE_ITEM_SCHEMA},
        "api_calls": {"type": "array", "items": _API_CALL_SCHEMA},
    },
}

_SCREEN_SCHEMA = {
    "type": "object",
    "required": ["screen_name", "type", "opens_as", "similarity_query", "components"],
    "additionalProperties": True,
    "properties": {
        "screen_name":       {"type": "string", "minLength": 1},
        # No enum — LLM may return valid types like 'barcode_panel', 'list', 'wizard', etc.
        "type":              {"type": "string"},
        # Note: common values are dashboard | form | detail | popup | list | barcode_panel
        "route":             {"type": "string"},
        "opens_as":          {"type": "string"},
        "priority":          {"type": "integer", "minimum": 1},
        "similarity_query":  {"type": "string", "minLength": 1},
        "components":        {"type": "array", "items": _COMPONENT_SCHEMA},
        "user_interactions": {"type": "array", "items": _USER_INTERACTION_SCHEMA},
        "data_flow":         _DATA_FLOW_SCHEMA,
    },
}

_SHARED_COMPONENT_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "additionalProperties": True,
    "properties": {
        "name":             {"type": "string"},
        "toolkit_mapping":  {"type": "string"},
        "used_in_screens":  {"type": "array", "items": {"type": "string"}},
    },
}

_FILE_PLAN_SCHEMA = {
    "type": "object",
    "required": ["path", "type", "description", "belongs_to_screen"],
    "additionalProperties": True,
    "properties": {
        "path":              {"type": "string", "minLength": 1},
        "type":              {"type": "string", "minLength": 1},
        "description":       {"type": "string"},
        "belongs_to_screen": {"type": "string"},
        "uses_components":   {"type": "array", "items": {"type": "string"}},
        "toolkit_imports": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "key_exports":       {"type": "array", "items": {"type": "string"}},
    },
}

# ── Top-level module schema ───────────────────────────────────────────────────

_MODULE_SCHEMA = {
    "type": "object",
    "required": ["module_name", "description", "similarity_query", "screens", "file_structure"],
    "additionalProperties": True,
    "properties": {
        "module_name":       {"type": "string", "minLength": 1},
        "description":       {"type": "string"},
        "priority":          {"type": "integer", "minimum": 1},
        "similarity_query":  {"type": "string", "minLength": 1},
        "business_rules":    {"type": "array", "items": {"type": "string"}},
        "screens":           {"type": "array", "items": _SCREEN_SCHEMA},
        "shared_components": {"type": "array", "items": _SHARED_COMPONENT_SCHEMA},
        "file_structure":    {"type": "array", "items": _FILE_PLAN_SCHEMA},
    },
}

# ── Root schema — exported for use with call_llm_with_schema ─────────────────

PLANNER_OUTPUT_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "array",
    "minItems": 1,
    "items": _MODULE_SCHEMA,
}
