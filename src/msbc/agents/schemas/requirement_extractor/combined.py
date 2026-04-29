"""
JSON Schema (Draft 2020-12) for combined (mode="both") extraction node output.

Merges the frontend and backend sub-schemas under a single "module" object.
"""

from src.msbc.agents.schemas.requirement_extractor.frontend import (
    _ENUM_ITEM_SCHEMA,
    _SCREEN_SCHEMA,
    _WORKFLOW_SCHEMA as _FE_WORKFLOW_SCHEMA,
)
from src.msbc.agents.schemas.requirement_extractor.backend import (
    _ENDPOINT_SCHEMA,
    _MODEL_SCHEMA,
    _BUSINESS_LOGIC_ITEM,
    _WORKFLOW_SCHEMA as _BE_WORKFLOW_SCHEMA,
)

COMBINED_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["module"],
    "additionalProperties": False,
    "properties": {
        "module": {
            "type": "object",
            "required": ["name", "frontend", "backend"],
            "properties": {
                "name":        {"type": "string"},
                "description": {"type": ["string", "null"]},
                "frontend": {
                    "type": "object",
                    "required": ["screens"],
                    "properties": {
                        "screens": {"type": "array", "items": _SCREEN_SCHEMA, "minItems": 1},
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
                            "items": _FE_WORKFLOW_SCHEMA,
                        },
                    },
                },
                "backend": {
                    "type": "object",
                    "required": ["api_endpoints", "models"],
                    "properties": {
                        "api_endpoints": {"type": "array", "items": _ENDPOINT_SCHEMA},
                        "models":        {"type": "array", "items": _MODEL_SCHEMA},
                        "business_logic":{"type": "array", "items": _BUSINESS_LOGIC_ITEM},
                        "workflows":     {"type": "array", "items": _BE_WORKFLOW_SCHEMA},
                    },
                },
            },
        }
    },
}
