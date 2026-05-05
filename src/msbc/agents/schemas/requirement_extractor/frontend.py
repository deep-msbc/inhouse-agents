"""
JSON Schema (Draft 2020-12) for frontend extraction node output.

Shape:
  {
    "module": {
      "name", "description",
      "screens": [ { name, screen_type, opens_as, purpose, linked_forms, components,
                     title, description, field_groups, actions, validations, behaviors } ],
      "enums":          [ { name, values } ],
      "business_rules": [ str ],
      "workflows":      [ { name, steps, screens_involved } ]
    }
  }

Design intent:
  - Dashboard screens carry their content inside a `components` array.
  - Form screens may carry `field_groups`, `actions`, `validations`, and `behaviors`
    directly on the screen object OR inside a nested form component — both shapes
    are accepted so the LLM is never penalised.
  - Component `type` is validated as a non-empty string only.  The known set of
    types is documented in the prompt; we do not hard-code an enum here because
    the LLM may legitimately produce new or compound component types.
"""

# ── Component ──────────────────────────────────────────────────────────────────
# Each component type (toolbar, grid, form, scan_panel, kpi, tabs, stepper,
# feedback_area, barcode_panel, filter_panel, upload_zone, timeline, dropdown …)
# has a completely different internal shape.  We only require that `type` is a
# non-empty string and leave all other properties open so the LLM is never
# penalised for returning valid component-specific fields.
_COMPONENT_SCHEMA = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "id":   {"type": "string"},
        "type": {"type": "string", "minLength": 1},
    },
    # No additionalProperties constraint — component internals vary widely.
}

# ── Module-level schemas ───────────────────────────────────────────────────────

_ENUM_ITEM_SCHEMA = {
    "type": "object",
    "required": ["name", "values"],
    "additionalProperties": False,
    "properties": {
        "name":   {"type": "string"},
        "values": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
}

_WORKFLOW_SCHEMA = {
    "type": "object",
    "required": ["name", "steps"],
    "additionalProperties": False,
    "properties": {
        "name":             {"type": "string"},
        "steps":            {"type": "array", "items": {"type": "string"}},
        "screens_involved": {"type": "array", "items": {"type": "string"}},
    },
}

# ── Screen ─────────────────────────────────────────────────────────────────────
# Screens come in two shapes:
#   dashboard — content lives inside the `components` array.
#   form      — may carry `field_groups`, `actions`, `validations`, `behaviors`
#               directly on the screen object OR inside a nested form component.
# Both shapes are valid; we do not use additionalProperties: False so that the
# LLM is never penalised for either representation.

_FIELD_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name":             {"type": "string"},
        "label":            {"type": "string"},
        "type":             {"type": "string"},
        "required":         {"type": "boolean"},
        "default_value":    {},
        "placeholder":      {"type": ["string", "null"]},
        "options":          {"type": "array"},
        "validation":       {"type": "array", "items": {"type": "string"}},
        "readonly":         {"type": "boolean"},
        "depends_on":       {"type": ["string", "null"]},
        "visible_when":     {"type": ["string", "null"]},
        "required_when":    {"type": ["string", "null"]},
        "disabled_when":    {"type": ["string", "null"]},
        "computed_formula": {"type": ["string", "null"]},
        "auto_fill_from":   {"type": ["string", "null"]},
        "behavior":         {"type": ["string", "null"]},
    },
}

_FIELD_GROUP_SCHEMA = {
    "type": "object",
    "required": ["group_name", "fields"],
    "properties": {
        "group_name": {"type": "string"},
        "fields":     {"type": "array", "items": _FIELD_SCHEMA},
    },
}

_SCREEN_ACTION_SCHEMA = {
    "type": "object",
    "required": ["label"],
    "properties": {
        "label":         {"type": "string"},
        "type":          {"type": "string"},
        "behavior":      {"type": "string"},
        "disabled_when": {"type": ["string", "null"]},
    },
}

_BEHAVIOR_SCHEMA = {
    "type": "object",
    "properties": {
        "trigger":   {"type": "string"},
        "action":    {"type": "string"},
        "condition": {"type": ["string", "null"]},
    },
}

_SCREEN_SCHEMA = {
    "type": "object",
    "required": ["name", "screen_type"],
    # additionalProperties is intentionally omitted — dashboards and forms carry
    # different top-level keys and the LLM may output either shape.
    "properties": {
        "name":        {"type": "string"},
        "screen_type": {"type": "string"},          # "dashboard" | "form" | any future type
        "opens_as":    {"type": ["string", "null"]},
        "purpose":     {"type": ["string", "null"]},
        "title":       {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "linked_forms": {"type": "array", "items": {"type": "string"}},
        # dashboard shape
        "components":  {"type": "array", "items": _COMPONENT_SCHEMA},
        # form shape — properties may appear at screen level
        "field_groups": {"type": "array", "items": _FIELD_GROUP_SCHEMA},
        "actions":      {"type": "array", "items": _SCREEN_ACTION_SCHEMA},
        "validations":  {"type": "array", "items": {"type": "string"}},
        "behaviors":    {"type": "array", "items": _BEHAVIOR_SCHEMA},
    },
}

# ── Top-level schema ───────────────────────────────────────────────────────────

FRONTEND_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["module"],
    "additionalProperties": False,
    "properties": {
        "module": {
            "type": "object",
            "required": ["name", "screens"],
            "additionalProperties": False,
            "properties": {
                "name":        {"type": "string"},
                "description": {"type": ["string", "null"]},
                "screens": {
                    "type": "array",
                    "items": _SCREEN_SCHEMA,
                    "minItems": 1,
                },
                # Module-level cross-screen data
                "enums": {
                    "type": "array",
                    "items": _ENUM_ITEM_SCHEMA,
                },
                "business_rules": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "workflows": {
                    "type": "array",
                    "items": _WORKFLOW_SCHEMA,
                },
            },
        }
    },
}
