"""
JSON Schema (Draft 2020-12) for the segmentation node.

CLASSIFICATION_SCHEMA — used by the new LLM classification call.
  The LLM receives a flat heading list and assigns each heading a type:
    MODULE       — a top-level functional area that becomes a module
    SUB_SECTION  — a section within a module, not standalone
    UI           — a UI sub-component (Filter Panel, Grid Structure, etc.)
    IGNORE       — administrative/structural heading (Purpose, Overview, etc.)

SEGMENTATION_SCHEMA — legacy shape kept for compatibility; no longer used
  directly in the LLM call (Python builds the modules list from classifications).
"""

CLASSIFICATION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["classifications"],
    "additionalProperties": False,
    "properties": {
        "classifications": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["heading", "type"],
                "additionalProperties": False,
                "properties": {
                    "heading":     {"type": "string", "minLength": 1},
                    "type":        {"type": "string", "enum": ["MODULE", "SUB_SECTION", "UI", "IGNORE"]},
                    "module_name": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                },
            },
        }
    },
}

SEGMENTATION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["modules"],
    "additionalProperties": False,
    "properties": {
        "modules": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name", "heading", "description"],
                "additionalProperties": True,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "heading": {"type": "string", "minLength": 1},
                    "description": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}
