"""
JSON Schema (Draft 2020-12) for backend extraction node output.

Shape:
  { "module": { "name", "description", "api_endpoints", "models",
                "business_logic", "workflows" } }
"""

_PARAM_ITEM = {
    "type": "object",
    "required": ["name", "type"],
    "properties": {
        "name":       {"type": "string"},
        "type":       {"type": "string"},
        "required":   {"type": ["boolean", "null"]},
        "validation": {"type": ["string", "null"]},
        "notes":      {"type": ["string", "null"]},
    },
}

_REQUEST_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "path":  {"type": "array", "items": _PARAM_ITEM},
        "query": {"type": "array", "items": _PARAM_ITEM},
        "body":  {"type": "array", "items": _PARAM_ITEM},
    },
}

_RESPONSE_BODY_SCHEMA = {
    "type": "object",
    "properties": {
        "success_status": {"type": "integer"},
        "shape": {"type": ["string", "null"]},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type"],
                "properties": {
                    "name":  {"type": "string"},
                    "type":  {"type": "string"},
                    "notes": {"type": ["string", "null"]},
                },
            },
        },
    },
}

_ENDPOINT_SCHEMA = {
    "type": "object",
    "required": ["path", "method", "summary"],
    "properties": {
        "path":            {"type": "string"},
        "method":          {"type": "string", "minLength": 1},
        "summary":         {"type": "string"},
        "request_params":  _REQUEST_PARAMS_SCHEMA,
        "response_body":   _RESPONSE_BODY_SCHEMA,
        "authentication":  {"type": ["string", "null"]},
        "authorization":   {"type": ["string", "null"]},
        "validations":     {"type": "array", "items": {"type": "string"}},
        "error_responses": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["status", "condition"],
                "properties": {
                    "status":    {"type": "integer"},
                    "condition": {"type": "string"},
                },
            },
        },
        "notes":           {"type": ["string", "null"]},
    },
}

_FIELD_SCHEMA = {
    "type": "object",
    "required": ["name", "type"],
    "properties": {
        "name":        {"type": "string"},
        "type":        {"type": "string"},
        "required":    {"type": ["boolean", "null"]},
        "unique":      {"type": ["boolean", "null"]},
        "default":     {"type": ["string", "integer", "number", "boolean", "null"]},
        "enum_values": {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
        "max_length":  {"type": ["string", "integer", "null"]},
        "notes":       {"type": ["string", "null"]},
    },
}

_RELATIONSHIP_SCHEMA = {
    "type": "object",
    "required": ["type", "target_model"],
    "properties": {
        "type":         {"type": "string", "minLength": 1},
        "target_model": {"type": "string"},
        "foreign_key":  {"type": ["string", "null"]},
        "description":  {"type": ["string", "null"]},
    },
}

_MODEL_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name":          {"type": "string"},
        "description":   {"type": ["string", "null"]},
        "table_name":    {"type": ["string", "null"]},
        "fields":        {"type": "array", "items": _FIELD_SCHEMA},
        "relationships": {"type": "array", "items": _RELATIONSHIP_SCHEMA},
        "indexes":       {"type": "array", "items": {"type": "string"}},
        "soft_delete":   {"type": ["boolean", "string", "null"]},
    },
}

_BUSINESS_LOGIC_ITEM = {
    "type": "object",
    "required": ["rule"],
    "properties": {
        "rule":              {"type": "string"},
        "trigger":           {"type": ["string", "null"]},
        "affected_entities": {"type": "array", "items": {"type": "string"}},
        "enforcement":       {"type": ["string", "null"]},
    },
}

_WORKFLOW_SCHEMA = {
    "type": "object",
    "required": ["name", "steps"],
    "properties": {
        "name":     {"type": "string"},
        "trigger":  {"type": ["string", "null"]},
        "steps":    {"type": "array", "items": {"type": "string"}},
        "outcome":  {"type": ["string", "null"]},
        "rollback": {"type": ["string", "null"]},
    },
}

BACKEND_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["module"],
    "additionalProperties": False,
    "properties": {
        "module": {
            "type": "object",
            "required": ["name", "api_endpoints", "models"],
            "properties": {
                "name": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "api_endpoints": {"type": "array", "items": _ENDPOINT_SCHEMA},
                "models": {"type": "array", "items": _MODEL_SCHEMA},
                "business_logic": {"type": "array", "items": _BUSINESS_LOGIC_ITEM},
                "workflows": {"type": "array", "items": _WORKFLOW_SCHEMA},
            },
        }
    },
}
