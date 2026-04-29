"""
JSON Schema (Draft 2020-12) for the segmentation node output.

Shape:
  {
    "modules": [
      { "name": str, "heading": str, "level": int, "description": str }
    ]
  }
"""

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
                "required": ["name", "heading", "level", "description"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "heading": {"type": "string", "minLength": 1},
                    "level": {"type": "integer", "minimum": 1, "maximum": 6},
                    "description": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}
