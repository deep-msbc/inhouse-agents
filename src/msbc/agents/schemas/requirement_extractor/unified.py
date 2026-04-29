"""
JSON Schema (Draft 2020-12) for the unification node output.

The extraction object per module is intentionally typed as an open object
because its internal structure varies by mode (frontend / backend / both).
The LLM passes through the already-validated per-module extraction unchanged.
"""

UNIFIED_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["unified"],
    "additionalProperties": False,
    "properties": {
        "unified": {
            "type": "object",
            "required": ["mode", "total_modules", "modules"],
            "additionalProperties": False,
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["frontend", "backend", "both"],
                },
                "total_modules": {"type": "integer", "minimum": 1},
                "modules": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["name", "description", "order", "extraction"],
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "order": {"type": "integer", "minimum": 1},
                            # extraction varies by mode — validated per-mode before unification
                            "extraction": {"type": "object"},
                        },
                    },
                },
                "global_enums": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "global_business_rules": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }
    },
}
