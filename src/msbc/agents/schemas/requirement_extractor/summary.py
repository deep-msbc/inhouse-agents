"""
JSON Schema (Draft 2020-12) for the summary extraction node output.

Shape:
  { "module_summary": { name, purpose, key_entities, key_flows,
                        dependencies, shared_enums,
                        cross_module_validations } }
"""

_DEPENDENCY_ITEM = {
    "type": "object",
    "required": ["module", "reason", "interaction_type"],
    "additionalProperties": False,
    "properties": {
        "module": {"type": "string"},
        "reason": {"type": "string"},
        "interaction_type": {
            "type": "string",
            "enum": ["data", "auth", "event", "api", "navigation", "shared_enum"],
        },
        "data_shared": {"type": "array", "items": {"type": "string"}},
    },
}

_SHARED_ENUM_ITEM = {
    "type": "object",
    "required": ["name", "values"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "values": {"type": "array", "items": {"type": "string"}},
        "used_by": {"type": "array", "items": {"type": "string"}},
    },
}

SUMMARY_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["module_summary"],
    "additionalProperties": False,
    "properties": {
        "module_summary": {
            "type": "object",
            "required": ["name", "purpose", "key_entities", "key_flows", "dependencies"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "purpose": {"type": "string"},
                "key_entities": {"type": "array", "items": {"type": "string"}},
                "key_flows": {"type": "array", "items": {"type": "string"}},
                "dependencies": {
                    "type": "object",
                    "required": ["depends_on", "depended_on_by"],
                    "additionalProperties": False,
                    "properties": {
                        "depends_on":      {"type": "array", "items": _DEPENDENCY_ITEM},
                        "depended_on_by":  {"type": "array", "items": _DEPENDENCY_ITEM},
                        # Some LLM responses nest shared_enums here; accept it.
                        "shared_enums":    {"type": "array", "items": _SHARED_ENUM_ITEM},
                        # LLM sometimes places this inside dependencies instead
                        # of at module_summary level — accept in both positions.
                        "cross_module_validations": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "shared_enums": {"type": "array", "items": _SHARED_ENUM_ITEM},
                "cross_module_validations": {"type": "array", "items": {"type": "string"}},
            },
        }
    },
}
