"""
JSON Schema (Draft 2020-12) for the Phase 1 section classification call.

SECTION_CLASSIFICATION_SCHEMA — used by section_classifier_node.
  The LLM receives a JSON array of DocumentSection objects and returns a
  classification for every section, including:
    - section_type  (BUSINESS_MODULE | SCREEN | FORM | ... | UNKNOWN)
    - is_standalone_module
    - canonical_module_name (always required)
    - belongs_to_section_id (null for standalone modules)
    - reason, confidence

CANONICALIZATION_SCHEMA — used by module_canonicalizer_node (low-confidence review).
  The LLM receives provisional module groups and returns the corrected final list.
"""

SECTION_CLASSIFICATION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["section_classifications"],
    "additionalProperties": False,
    "properties": {
        "section_classifications": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "section_id",
                    "heading",
                    "level",
                    "section_type",
                    "is_standalone_module",
                    "canonical_module_name",
                    "reason",
                    "confidence",
                ],
                "additionalProperties": False,
                "properties": {
                    "section_id": {"type": "string", "minLength": 1},
                    "heading": {"type": "string", "minLength": 1},
                    "level": {"type": "integer", "minimum": 1},
                    "section_type": {
                        "type": "string",
                        "enum": [
                            "BUSINESS_MODULE",
                            "SCREEN",
                            "FORM",
                            "GRID",
                            "TOOLBAR",
                            "FILTER_PANEL",
                            "WORKFLOW",
                            "VALIDATION_RULES",
                            "BUSINESS_RULES",
                            "ENUM_DEFINITION",
                            "API_SPEC",
                            "MODEL_SPEC",
                            "INTEGRATION",
                            "EXAMPLE",
                            "NOTE",
                            "UNKNOWN",
                        ],
                    },
                    "is_standalone_module": {"type": "boolean"},
                    "canonical_module_name": {"type": "string", "minLength": 1},
                    "belongs_to_section_id": {"type": ["string", "null"]},
                    "reason": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            },
        }
    },
}


CANONICALIZATION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["canonical_modules"],
    "additionalProperties": False,
    "properties": {
        "canonical_modules": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["module_key", "display_name", "section_ids", "confidence"],
                "additionalProperties": False,
                "properties": {
                    "module_key": {"type": "string", "minLength": 1, "pattern": "^[a-z0-9_]+$"},
                    "display_name": {"type": "string", "minLength": 1},
                    "section_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "merge_reason": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            },
        }
    },
}
