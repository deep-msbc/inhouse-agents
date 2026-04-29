"""
JSON Schema (Draft 2020-12) for the graph builder node output.

Edge relation types:
  depends_on | calls | triggers | navigates_to | shares_enum | extends

Node types:
  feature | auth | data | integration | utility
"""

_NODE_SCHEMA = {
    "type": "object",
    "required": ["id", "label"],
    "properties": {
        "id":          {"type": "string", "minLength": 1},
        "type":        {"type": ["string", "null"]},
        "label":       {"type": "string"},
        "description": {"type": ["string", "null"]},
        "external_dependencies": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

_EDGE_SCHEMA = {
    "type": "object",
    "required": ["from", "to", "relation"],
    "properties": {
        "from":             {"type": "string"},
        "to":               {"type": "string"},
        "relation":         {"type": "string", "minLength": 1},
        "interaction_type": {"type": ["string", "null"]},
        "data_shared":      {"type": "array", "items": {"type": "string"}},
        "description":      {"type": ["string", "null"]},
    },
}

GRAPH_OUTPUT_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["graph"],
    "additionalProperties": False,
    "properties": {
        "graph": {
            "type": "object",
            "required": ["nodes", "edges"],
            "properties": {
                "nodes": {
                    "type": "array",
                    "minItems": 1,
                    "items": _NODE_SCHEMA,
                },
                "edges": {
                    "type": "array",
                    "items": _EDGE_SCHEMA,
                },
                "entry_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "total_modules": {"type": "integer", "minimum": 1},
                        "mode":         {"type": "string"},
                        "total_edges":  {"type": "integer", "minimum": 0},
                    },
                },
            },
        }
    },
}
